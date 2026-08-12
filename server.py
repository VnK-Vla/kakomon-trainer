#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email.utils
import gzip
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SOURCE_PDF_DIR = STATIC_DIR / "source-pdfs"
DATA_DIR = Path(os.environ.get("KAKOMON_DATA_DIR", BASE_DIR / "data")).resolve()
DB_PATH = DATA_DIR / "questions.db"
DEFAULT_USER_NAME = "自分"
MAX_USER_NAME_LENGTH = 80
MAX_NOTE_LENGTH = 4000
TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"
SOURCE_PDF_CACHE_SECONDS = 60.0
SOURCE_PDF_CHUNK_SIZE = 1024 * 256
GZIP_JSON_MIN_BYTES = 1024
MAX_JSON_BODY_BYTES = 1024 * 1024
MAX_PRACTICE_SESSION_QUESTIONS = 5000
MAX_PRACTICE_FILTER_TEXT_LENGTH = 200
MAX_PRACTICE_SESSION_TOKEN_LENGTH = 200
PRACTICE_RESULT_MARKS = ("ok", "warn", "wrong", "untried")
PRACTICE_LOCAL_FILTER_KEYS = ("hasImages", "unattempted", "withoutAnswer")

EXAM_SOURCE_DIRS = {
    "放射線診断専門医認定試験": "diagnostic",
    "核医学専門医試験": "nuclear",
    "放射線治療専門医認定試験": "treatment",
}

TREATMENT_SOURCE_FILES = {
    "2016": "20160831.pdf",
    "2017": "20170904_4.pdf",
    "2018": "20180926_4.pdf",
    "2019": "20190904_04.pdf",
    "2020": "chiryo2020.pdf",
    "2021": "chiryo2021.pdf",
    "2022": "chiryo2022.pdf",
    "2023": "chiryo2023.pdf",
    "2024": "chiryo2024.pdf",
    "2025": "kikou_chiryo2025_02.pdf",
}

SOURCE_PDF_CACHE: dict[str, object] = {"expires_at": 0.0, "files": set()}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_user_name(value: object | None) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return DEFAULT_USER_NAME
    return text[:MAX_USER_NAME_LENGTH]


def configured_admin_users() -> set[str]:
    raw = os.environ.get("KAKOMON_ADMIN_USERS", "")
    return {clean_user_name(item).casefold() for item in raw.split(",") if item.strip()}


def normalize_answer(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def answer_letters(value: str | None) -> set[str]:
    text = normalize_answer(value)
    if not text:
        return set()

    direct = re.fullmatch(r"[a-e](?:\s*[,;/、，]\s*[a-e])*", text)
    if direct:
        return set(re.findall(r"[a-e]", text))

    labeled = set()
    for match in re.finditer(r"(?:^|[;\n；])\s*([a-e])\s*[\.)．、，,：:]", text):
        labeled.add(match.group(1))
    if labeled:
        return labeled

    letters = set()
    for match in re.finditer(r"(?<![a-z])([a-e])(?=\s*[\.)．、，:：;；]|$)", text):
        letters.add(match.group(1))
    return letters


def is_correct_answer(user_answer: str, correct_answer: str) -> bool:
    user_letters = answer_letters(user_answer)
    correct_letters = answer_letters(correct_answer)
    if user_letters and correct_letters:
        return user_letters == correct_letters
    return normalize_answer(user_answer) == normalize_answer(correct_answer)


def question_number_snapshot(question: str, explanation: str = "") -> int | None:
    for text in (question, explanation):
        match = re.search(r"問\s*(\d{1,4})", text or "")
        if match:
            return int(match.group(1))
    return None


def source_pdf_filename(exam: str, year: str, explanation: str) -> str:
    source_match = re.search(r"出典:\s*([^/\n]+?\.pdf)\b", explanation or "", re.IGNORECASE)
    if source_match:
        return source_match.group(1).strip()
    if exam == "放射線治療専門医認定試験":
        return TREATMENT_SOURCE_FILES.get(str(year), "")
    if exam in {"放射線診断専門医認定試験", "核医学専門医試験"} and year:
        return f"{year}.pdf"
    return ""


def source_pdf_page(explanation: str) -> int | None:
    page_match = re.search(r"(?:p\.?|page)\s*([0-9]{1,4})", explanation or "", re.IGNORECASE)
    if not page_match:
        return None
    try:
        return int(page_match.group(1))
    except ValueError:
        return None


def available_source_pdfs() -> set[tuple[str, str]]:
    now = time.monotonic()
    cached_files = SOURCE_PDF_CACHE.get("files")
    expires_at = float(SOURCE_PDF_CACHE.get("expires_at") or 0.0)
    if isinstance(cached_files, set) and now < expires_at:
        return cached_files

    files: set[tuple[str, str]] = set()
    if SOURCE_PDF_DIR.exists():
        for path in SOURCE_PDF_DIR.glob("*/*.pdf"):
            if path.is_file():
                files.add((path.parent.name, path.name))
    SOURCE_PDF_CACHE["files"] = files
    SOURCE_PDF_CACHE["expires_at"] = now + SOURCE_PDF_CACHE_SECONDS
    return files


def source_pdf_for_question(row: sqlite3.Row) -> dict | None:
    exam = str(row["exam"] or "")
    year = str(row["year"] or "")
    slug = EXAM_SOURCE_DIRS.get(exam)
    if not slug:
        return None
    filename = source_pdf_filename(exam, year, str(row["explanation"] or ""))
    if not filename:
        return None
    if (slug, filename) not in available_source_pdfs():
        return None

    page = source_pdf_page(str(row["explanation"] or ""))
    url = f"/source-pdfs/{quote(slug)}/{quote(filename)}"
    if page:
        url = f"{url}#page={page}"
    return {
        "label": f"{filename}" + (f" p.{page}" if page else ""),
        "url": url,
        "page": page,
        "filename": filename,
    }


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL,
                choices TEXT NOT NULL DEFAULT '[]',
                images TEXT NOT NULL DEFAULT '[]',
                answer TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_name TEXT NOT NULL DEFAULT '自分',
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS question_notes (
                question_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(question_id, user_name),
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS practice_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                user_name TEXT NOT NULL,
                exam TEXT NOT NULL,
                filters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'completed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(user_name, exam),
                FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS practice_session_items (
                session_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                completed_at TEXT,
                PRIMARY KEY(session_id, question_id),
                UNIQUE(session_id, position),
                FOREIGN KEY(session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                exam TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_name, exam, title),
                FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_set_items (
                question_set_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                PRIMARY KEY(question_set_id, question_id),
                UNIQUE(question_set_id, position),
                FOREIGN KEY(question_set_id) REFERENCES question_sets(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_set_rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_set_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'completed', 'abandoned')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                abandoned_at TEXT,
                UNIQUE(question_set_id, round_number),
                FOREIGN KEY(question_set_id) REFERENCES question_sets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_set_round_items (
                round_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                question_id INTEGER,
                source_question_id INTEGER NOT NULL,
                source_year TEXT NOT NULL DEFAULT '',
                source_category TEXT NOT NULL DEFAULT '',
                source_question_number INTEGER,
                completed_at TEXT,
                attempt_id INTEGER,
                user_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER,
                self_mark TEXT,
                PRIMARY KEY(round_id, source_question_id),
                UNIQUE(round_id, position),
                FOREIGN KEY(round_id) REFERENCES question_set_rounds(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE SET NULL,
                FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS disease_checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                exam TEXT NOT NULL,
                title TEXT NOT NULL,
                source_sha256 TEXT NOT NULL DEFAULT '',
                extraction_criteria TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_name, exam, title),
                FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS disease_checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                disease_name TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                concept_type TEXT NOT NULL DEFAULT 'disease',
                primary_area TEXT NOT NULL DEFAULT '',
                areas_json TEXT NOT NULL DEFAULT '[]',
                curriculum_refs_json TEXT NOT NULL DEFAULT '[]',
                base_included INTEGER NOT NULL DEFAULT 0
                    CHECK(base_included IN (0, 1)),
                review_note TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                note_updated_at TEXT,
                ever_wrong_at TEXT,
                ever_wrong_question_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(checklist_id, position),
                UNIQUE(checklist_id, disease_name),
                FOREIGN KEY(checklist_id) REFERENCES disease_checklists(id) ON DELETE CASCADE,
                FOREIGN KEY(ever_wrong_question_id) REFERENCES questions(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS disease_checklist_item_questions (
                item_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                match_type TEXT NOT NULL
                    CHECK(match_type IN ('correct', 'structured_target')),
                created_at TEXT NOT NULL,
                PRIMARY KEY(item_id, question_id, match_type),
                FOREIGN KEY(item_id) REFERENCES disease_checklist_items(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS disease_check_statuses (
                item_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('ok', 'warn', 'wrong')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES disease_checklist_items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam);
            CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
            CREATE INDEX IF NOT EXISTS idx_attempts_question_id ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at);
            CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);
            CREATE INDEX IF NOT EXISTS idx_question_notes_user_name ON question_notes(user_name);
            CREATE INDEX IF NOT EXISTS idx_practice_sessions_user_exam
                ON practice_sessions(user_name, exam);
            CREATE INDEX IF NOT EXISTS idx_practice_session_items_question_id
                ON practice_session_items(question_id);
            CREATE INDEX IF NOT EXISTS idx_question_sets_user_exam
                ON question_sets(user_name, exam);
            CREATE INDEX IF NOT EXISTS idx_question_set_items_question_id
                ON question_set_items(question_id);
            CREATE INDEX IF NOT EXISTS idx_question_set_rounds_set_number
                ON question_set_rounds(question_set_id, round_number DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_question_set_rounds_one_active
                ON question_set_rounds(question_set_id)
                WHERE status = 'active';
            CREATE INDEX IF NOT EXISTS idx_question_set_round_items_question_id
                ON question_set_round_items(question_id);
            CREATE INDEX IF NOT EXISTS idx_question_set_round_items_attempt_id
                ON question_set_round_items(attempt_id);
            CREATE INDEX IF NOT EXISTS idx_disease_checklists_user_exam
                ON disease_checklists(user_name, exam);
            CREATE INDEX IF NOT EXISTS idx_disease_checklist_items_active
                ON disease_checklist_items(checklist_id, base_included, ever_wrong_at);
            CREATE INDEX IF NOT EXISTS idx_disease_checklist_item_questions_question
                ON disease_checklist_item_questions(question_id, match_type);
            CREATE INDEX IF NOT EXISTS idx_disease_check_statuses_status
                ON disease_check_statuses(status);
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        if "images" not in columns:
            conn.execute("ALTER TABLE questions ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
        attempt_columns = {row["name"] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()}
        if "self_mark" not in attempt_columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN self_mark TEXT NOT NULL DEFAULT ''")
        if "user_name" not in attempt_columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN user_name TEXT NOT NULL DEFAULT '自分'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_user_name ON attempts(user_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_question_user ON attempts(question_id, user_name)")
        disease_item_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(disease_checklist_items)").fetchall()
        }
        if "note_updated_at" not in disease_item_columns:
            conn.execute("ALTER TABLE disease_checklist_items ADD COLUMN note_updated_at TEXT")
        disease_status_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(disease_check_statuses)").fetchall()
        }
        if "user_name" in disease_status_columns:
            conn.executescript(
                """
                CREATE TABLE disease_check_statuses_owner_scoped (
                    item_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('ok', 'warn', 'wrong')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES disease_checklist_items(id) ON DELETE CASCADE
                );
                INSERT INTO disease_check_statuses_owner_scoped (
                    item_id, status, created_at, updated_at
                )
                SELECT s.item_id, s.status, s.created_at, s.updated_at
                FROM disease_check_statuses s
                JOIN disease_checklist_items i ON i.id = s.item_id
                JOIN disease_checklists c ON c.id = i.checklist_id
                WHERE s.user_name = c.user_name;
                DROP TABLE disease_check_statuses;
                ALTER TABLE disease_check_statuses_owner_scoped
                    RENAME TO disease_check_statuses;
                DROP INDEX IF EXISTS idx_disease_check_statuses_user_status;
                CREATE INDEX IF NOT EXISTS idx_disease_check_statuses_status
                    ON disease_check_statuses(status);
                """
            )
        timestamp = now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO users (name, created_at)
            SELECT DISTINCT user_name, ?
            FROM attempts
            WHERE user_name <> ''
            """,
            (timestamp,),
        )


def row_to_question(row: sqlite3.Row) -> dict:
    try:
        choices = json.loads(row["choices"] or "[]")
    except json.JSONDecodeError:
        choices = []
    try:
        images = json.loads(row["images"] or "[]")
    except json.JSONDecodeError:
        images = []

    item = {
        "id": row["id"],
        "exam": row["exam"],
        "year": row["year"],
        "category": row["category"],
        "question": row["question"],
        "choices": choices if isinstance(choices, list) else [],
        "images": images if isinstance(images, list) else [],
        "answer": row["answer"],
        "explanation": row["explanation"],
        "source_pdf": source_pdf_for_question(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

    if "attempts_count" in row.keys():
        item["attempts_count"] = row["attempts_count"] or 0
        item["correct_count"] = row["correct_count"] or 0
        item["graded_count"] = row["graded_count"] or 0
        item["last_attempt_at"] = row["last_attempt_at"]
        item["last_self_mark"] = row["last_self_mark"] or ""

    if "user_note" in row.keys():
        item["user_note"] = row["user_note"] or ""
        item["user_note_updated_at"] = row["user_note_updated_at"]

    return item


def clean_question_payload(payload: dict, partial: bool = False) -> dict:
    fields: dict[str, object] = {}

    for key in ("exam", "year", "category", "question", "answer", "explanation"):
        if key in payload:
            fields[key] = str(payload.get(key) or "").strip()

    if "question" in fields:
        fields["question"] = " ".join(str(fields["question"]).splitlines()).strip()

    if "choices" in payload:
        choices = payload.get("choices")
        if isinstance(choices, str):
            choices = [line.strip() for line in choices.splitlines()]
        if not isinstance(choices, list):
            choices = []
        fields["choices"] = [str(choice).strip() for choice in choices if str(choice).strip()]

    if "images" in payload:
        images = payload.get("images")
        if isinstance(images, str):
            images = [line.strip() for line in images.splitlines()]
        if not isinstance(images, list):
            images = []
        fields["images"] = [str(image).strip() for image in images if str(image).strip()]

    if not partial:
        required = ("question",)
        missing = [key for key in required if not fields.get(key)]
        if missing:
            raise ValueError("問題文は必須です。")

    return fields


def clean_practice_filters(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("開始条件はJSONオブジェクトで指定してください。")

    filters: dict[str, object] = {}
    for key in ("year", "category", "q"):
        raw = value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ValueError(f"開始条件の {key} は文字列で指定してください。")
        cleaned = " ".join(raw.split()).strip()
        if len(cleaned) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
            raise ValueError(f"開始条件の {key} が長すぎます。")
        if cleaned:
            filters[key] = cleaned

    raw_marks = value.get("result_marks")
    if raw_marks is not None:
        if not isinstance(raw_marks, list):
            raise ValueError("開始条件の result_marks は配列で指定してください。")
        marks: set[str] = set()
        for raw_mark in raw_marks:
            if not isinstance(raw_mark, str):
                raise ValueError("開始条件の result_marks に不正な値があります。")
            mark = raw_mark.strip()
            if mark not in PRACTICE_RESULT_MARKS:
                raise ValueError("開始条件の result_marks に不正な値があります。")
            marks.add(mark)
        normalized_marks = [mark for mark in PRACTICE_RESULT_MARKS if mark in marks]
        if normalized_marks:
            filters["result_marks"] = normalized_marks

    raw_local_filter = value.get("local_filter")
    if raw_local_filter is not None:
        if not isinstance(raw_local_filter, dict):
            raise ValueError("開始条件の local_filter はJSONオブジェクトで指定してください。")
        local_filter: dict[str, bool] = {}
        for key in PRACTICE_LOCAL_FILTER_KEYS:
            if key not in raw_local_filter:
                continue
            enabled = raw_local_filter[key]
            if not isinstance(enabled, bool):
                raise ValueError(f"開始条件の local_filter.{key} は真偽値で指定してください。")
            if enabled:
                local_filter[key] = True
        if local_filter:
            filters["local_filter"] = local_filter

    return filters


class AppHandler(BaseHTTPRequestHandler):
    server_version = "KakomonTrainer/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"status": "ok"})
        elif parsed.path == "/api/session":
            self.handle_session()
        elif parsed.path == "/api/questions":
            self.handle_list_questions(parsed.query)
        elif parsed.path == "/api/stats":
            self.handle_stats(parsed.query)
        elif parsed.path == "/api/study-summary":
            self.handle_study_summary(parsed.query)
        elif parsed.path == "/api/practice-session":
            self.handle_get_practice_session(parsed.query)
        elif parsed.path == "/api/question-sets":
            self.handle_list_question_sets(parsed.query)
        elif parsed.path.startswith("/api/question-sets/"):
            self.route_get_question_set(parsed.path, parsed.query)
        elif parsed.path == "/api/disease-checklists":
            self.handle_list_disease_checklists(parsed.query)
        elif parsed.path.startswith("/api/disease-checklists/"):
            self.route_get_disease_checklist(parsed.path, parsed.query)
        elif parsed.path == "/api/export":
            self.handle_export()
        elif parsed.path == "/api/attempts":
            self.handle_attempts(parsed.query)
        elif parsed.path == "/api/users":
            self.handle_list_users()
        elif parsed.path.startswith("/api/"):
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        else:
            self.serve_static(parsed.path)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/questions":
            self.handle_create_question()
        elif parsed.path == "/api/attempts":
            self.handle_create_attempt()
        elif parsed.path == "/api/practice-session":
            self.handle_create_practice_session()
        elif parsed.path.startswith("/api/question-sets/"):
            self.route_post_question_set(parsed.path, parsed.query)
        elif parsed.path == "/api/import":
            self.handle_import()
        elif parsed.path == "/api/users":
            self.handle_create_user()
        elif parsed.path.startswith("/api/notes/"):
            question_id = self.parse_id(parsed.path, "/api/notes/")
            if question_id is None:
                self.send_json({"error": "Invalid question id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_save_note(question_id)
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/questions/"):
            question_id = self.parse_id(parsed.path, "/api/questions/")
            if question_id is None:
                self.send_json({"error": "Invalid question id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_update_question(question_id)
        elif parsed.path.startswith("/api/attempts/"):
            attempt_id = self.parse_id(parsed.path, "/api/attempts/")
            if attempt_id is None:
                self.send_json({"error": "Invalid attempt id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_update_attempt(attempt_id)
        elif parsed.path.startswith("/api/disease-checklists/"):
            self.route_put_disease_checklist(parsed.path)
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/questions/"):
            question_id = self.parse_id(parsed.path, "/api/questions/")
            if question_id is None:
                self.send_json({"error": "Invalid question id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_delete_question(question_id)
        elif parsed.path == "/api/practice-session":
            self.handle_delete_practice_session(parsed.query)
        elif parsed.path.startswith("/api/question-sets/"):
            self.route_delete_question_set(parsed.path, parsed.query)
        elif parsed.path == "/api/attempts":
            self.handle_delete_attempts(parsed.query)
        elif parsed.path.startswith("/api/attempts/"):
            attempt_id = self.parse_id(parsed.path, "/api/attempts/")
            if attempt_id is None:
                self.send_json({"error": "Invalid attempt id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_delete_attempt(attempt_id)
        elif parsed.path.startswith("/api/users/"):
            user_id = self.parse_id(parsed.path, "/api/users/")
            if user_id is None:
                self.send_json({"error": "Invalid user id"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_delete_user(user_id)
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def parse_id(self, path: str, prefix: str) -> int | None:
        raw = path.removeprefix(prefix).strip("/")
        try:
            return int(raw)
        except ValueError:
            return None

    def route_get_question_set(self, path: str, query: str) -> None:
        active_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds/active", path)
        if active_match:
            self.handle_get_active_question_set_round(int(active_match.group(1)), query)
            return

        round_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds/(\d+)", path)
        if round_match:
            self.handle_get_question_set_round(
                int(round_match.group(1)),
                int(round_match.group(2)),
                query,
            )
            return

        rounds_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds", path)
        if rounds_match:
            self.handle_list_question_set_rounds(int(rounds_match.group(1)), query)
            return

        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def route_post_question_set(self, path: str, query: str) -> None:
        restart_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds/restart", path)
        if restart_match:
            self.handle_restart_question_set_round(int(restart_match.group(1)), query)
            return

        abandon_match = re.fullmatch(
            r"/api/question-sets/(\d+)/rounds/(\d+)/abandon",
            path,
        )
        if abandon_match:
            self.handle_abandon_question_set_round(
                int(abandon_match.group(1)),
                int(abandon_match.group(2)),
                query,
            )
            return

        rounds_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds", path)
        if rounds_match:
            self.handle_start_question_set_round(int(rounds_match.group(1)), query)
            return

        self.discard_request_body()
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def route_delete_question_set(self, path: str, query: str) -> None:
        round_match = re.fullmatch(r"/api/question-sets/(\d+)/rounds/(\d+)", path)
        if round_match:
            self.handle_delete_question_set_round(
                int(round_match.group(1)),
                int(round_match.group(2)),
                query,
            )
            return

        set_match = re.fullmatch(r"/api/question-sets/(\d+)", path)
        if set_match:
            self.handle_delete_question_set(int(set_match.group(1)), query)
            return

        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def route_get_disease_checklist(self, path: str, query: str) -> None:
        checklist_match = re.fullmatch(r"/api/disease-checklists/(\d+)", path)
        if checklist_match:
            self.handle_get_disease_checklist(int(checklist_match.group(1)), query)
            return

        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def route_put_disease_checklist(self, path: str) -> None:
        item_match = re.fullmatch(
            r"/api/disease-checklists/(\d+)/items/(\d+)",
            path,
        )
        if item_match:
            self.handle_update_disease_check_status(
                int(item_match.group(1)),
                int(item_match.group(2)),
            )
            return

        self.discard_request_body()
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def request_content_length(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def read_json(self) -> dict | list:
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            # CSRF対策: フォーム/text-plain経由のクロスサイトPOSTを拒否する
            self.discard_request_body()
            raise ValueError("Content-Type は application/json を指定してください。")
        length = self.request_content_length()
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError("リクエストボディが大きすぎます。")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("JSONの形式を確認してください。") from exc

    def discard_request_body(self) -> None:
        remaining = self.request_content_length()
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, SOURCE_PDF_CHUNK_SIZE))
            if not chunk:
                break
            remaining -= len(chunk)

    def accepts_gzip(self) -> bool:
        header = self.headers.get("Accept-Encoding", "")
        return any(item.strip().split(";", 1)[0].lower() == "gzip" for item in header.split(","))

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        use_gzip = len(body) >= GZIP_JSON_MIN_BYTES and self.accepts_gzip()
        response_body = gzip.compress(body, compresslevel=5) if use_gzip else body
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(response_body)

    def tailscale_user(self) -> str:
        login = self.headers.get(TAILSCALE_LOGIN_HEADER)
        if login and self.trust_tailscale_user_header():
            return clean_user_name(login)
        return ""

    def trust_tailscale_user_header(self) -> bool:
        client_host = str(self.client_address[0])
        bind_host = str(self.server.server_address[0])
        client_is_loopback = client_host == "::1" or client_host.startswith("127.")
        bind_is_loopback = bind_host in {"::1", "localhost"} or bind_host.startswith("127.")
        return client_is_loopback and bind_is_loopback

    def can_manage_users(self) -> bool:
        tailscale_user = self.tailscale_user()
        if not tailscale_user:
            return False
        return tailscale_user.casefold() in configured_admin_users()

    def can_edit_questions(self) -> bool:
        return self.can_manage_users()

    def require_user_management(self) -> bool:
        if self.can_manage_users():
            return True
        self.discard_request_body()
        self.send_json({"error": "ユーザー管理は管理者として許可されたTailscaleアカウントのみ使用できます。"}, HTTPStatus.FORBIDDEN)
        return False

    def require_question_edit(self) -> bool:
        if self.can_edit_questions():
            return True
        self.discard_request_body()
        self.send_json({"error": "問題編集は管理者として許可されたTailscaleアカウントのみ使用できます。"}, HTTPStatus.FORBIDDEN)
        return False

    def require_disease_checklist_access(self) -> bool:
        if self.can_manage_users():
            return True
        # リストの存在や所有者を推測できないよう、未認可時は常に404にそろえる。
        self.discard_request_body()
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        return False

    def effective_user_name(self, params: dict | None = None, payload: dict | None = None) -> str:
        tailscale_user = self.tailscale_user()
        if tailscale_user:
            return tailscale_user
        if payload and "user_name" in payload:
            return clean_user_name(payload.get("user_name"))
        if params:
            return clean_user_name(params.get("user", [""])[0])
        return DEFAULT_USER_NAME

    def can_modify_attempt(self, owner_name: str, requested_user_name: str) -> bool:
        if self.can_manage_users():
            return True
        return clean_user_name(owner_name).casefold() == clean_user_name(requested_user_name).casefold()

    def ensure_user(self, user_name: str) -> None:
        cleaned = clean_user_name(user_name)
        if not cleaned:
            return
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (cleaned, now_iso()),
            )

    def handle_session(self) -> None:
        tailscale_user = self.tailscale_user()
        if tailscale_user:
            self.ensure_user(tailscale_user)
            self.send_json(
                {
                    "mode": "tailscale",
                    "user_name": tailscale_user,
                    "can_switch_user": False,
                    "can_manage_users": self.can_manage_users(),
                    "can_edit_questions": self.can_edit_questions(),
                }
            )
            return

        self.send_json(
            {
                "mode": "direct",
                "user_name": DEFAULT_USER_NAME,
                "can_switch_user": True,
                "can_manage_users": False,
                "can_edit_questions": False,
            }
        )

    def practice_session_payload(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        items = conn.execute(
            """
            SELECT question_id, completed_at
            FROM practice_session_items
            WHERE session_id = ?
            ORDER BY position
            """,
            (row["id"],),
        ).fetchall()
        question_ids = [int(item["question_id"]) for item in items]
        completed_question_ids = [
            int(item["question_id"])
            for item in items
            if item["completed_at"] is not None
        ]
        total = len(question_ids)
        completed = len(completed_question_ids)
        remaining = total - completed

        status = str(row["status"] or "active")
        completed_at = row["completed_at"]
        updated_at = row["updated_at"]
        if remaining == 0 and (status != "completed" or not completed_at):
            timestamp = now_iso()
            completed_at = completed_at or timestamp
            updated_at = timestamp
            status = "completed"
            conn.execute(
                """
                UPDATE practice_sessions
                SET status = 'completed', updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (updated_at, completed_at, row["id"]),
            )

        try:
            filters = json.loads(row["filters"] or "{}")
        except (TypeError, json.JSONDecodeError):
            filters = {}
        if not isinstance(filters, dict):
            filters = {}

        return {
            "token": row["token"],
            "user_name": row["user_name"],
            "exam": row["exam"],
            "status": status,
            "filters": filters,
            "question_ids": question_ids,
            "completed_question_ids": completed_question_ids,
            "total": total,
            "completed": completed,
            "remaining": remaining,
            "created_at": row["created_at"],
            "updated_at": updated_at,
            "completed_at": completed_at,
        }

    def practice_session_for_user_exam(
        self,
        conn: sqlite3.Connection,
        user_name: str,
        exam: str,
    ) -> dict | None:
        row = conn.execute(
            """
            SELECT *
            FROM practice_sessions
            WHERE user_name = ? AND exam = ?
            """,
            (user_name, exam),
        ).fetchone()
        return self.practice_session_payload(conn, row) if row is not None else None

    def handle_get_practice_session(self, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        exam = " ".join((params.get("exam", [""])[0] or "").split()).strip()
        if not exam:
            self.send_json({"error": "試験を指定してください。"}, HTTPStatus.BAD_REQUEST)
            return
        if len(exam) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
            self.send_json({"error": "試験名が長すぎます。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            practice_session = self.practice_session_for_user_exam(conn, user_name, exam)

        self.send_json({"practice_session": practice_session})

    def handle_create_practice_session(self) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")

            user_name = self.effective_user_name(payload=payload)
            raw_exam = payload.get("exam")
            if not isinstance(raw_exam, str):
                raise ValueError("試験を指定してください。")
            exam = " ".join(raw_exam.split()).strip()
            if not exam:
                raise ValueError("試験を指定してください。")
            if len(exam) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
                raise ValueError("試験名が長すぎます。")

            filters = clean_practice_filters(payload.get("filters"))
            raw_question_ids = payload.get("question_ids")
            if not isinstance(raw_question_ids, list):
                raise ValueError("問題IDは配列で指定してください。")
            if not raw_question_ids:
                raise ValueError("一周する問題を1問以上指定してください。")
            if len(raw_question_ids) > MAX_PRACTICE_SESSION_QUESTIONS:
                raise ValueError(
                    f"一周に指定できる問題は{MAX_PRACTICE_SESSION_QUESTIONS}問までです。"
                )

            question_ids: list[int] = []
            seen_question_ids: set[int] = set()
            for value in raw_question_ids:
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError("問題IDは正の整数で指定してください。")
                if value in seen_question_ids:
                    raise ValueError("問題IDを重複して指定することはできません。")
                seen_question_ids.add(value)
                question_ids.append(value)
        except (TypeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        timestamp = now_iso()
        token = secrets.token_urlsafe(32)
        with db() as conn:
            found_question_ids: set[int] = set()
            for start in range(0, len(question_ids), 900):
                chunk = question_ids[start : start + 900]
                placeholders = ", ".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT id
                    FROM questions
                    WHERE exam = ? AND id IN ({placeholders})
                    """,
                    [exam, *chunk],
                ).fetchall()
                found_question_ids.update(int(row["id"]) for row in rows)
            if found_question_ids != seen_question_ids:
                self.send_json(
                    {"error": "指定した試験に属さない問題IDが含まれています。"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, timestamp),
            )
            conn.execute(
                "DELETE FROM practice_sessions WHERE user_name = ? AND exam = ?",
                (user_name, exam),
            )
            cur = conn.execute(
                """
                INSERT INTO practice_sessions (
                    token, user_name, exam, filters, status,
                    created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                """,
                (
                    token,
                    user_name,
                    exam,
                    json.dumps(filters, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            session_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO practice_session_items (
                    session_id, position, question_id, completed_at
                )
                VALUES (?, ?, ?, NULL)
                """,
                [
                    (session_id, position, question_id)
                    for position, question_id in enumerate(question_ids)
                ],
            )
            row = conn.execute(
                "SELECT * FROM practice_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            practice_session = self.practice_session_payload(conn, row)

        self.send_json(
            {"practice_session": practice_session},
            HTTPStatus.CREATED,
        )

    def handle_delete_practice_session(self, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        exam = " ".join((params.get("exam", [""])[0] or "").split()).strip()
        if not exam:
            self.send_json({"error": "試験を指定してください。"}, HTTPStatus.BAD_REQUEST)
            return
        if len(exam) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
            self.send_json({"error": "試験名が長すぎます。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            cur = conn.execute(
                "DELETE FROM practice_sessions WHERE user_name = ? AND exam = ?",
                (user_name, exam),
            )
            deleted = cur.rowcount

        self.send_json(
            {
                "ok": True,
                "deleted": deleted,
                "user_name": user_name,
                "exam": exam,
                "practice_session": None,
            }
        )

    def question_set_for_user(
        self,
        conn: sqlite3.Connection,
        question_set_id: int,
        user_name: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM question_sets
            WHERE id = ? AND user_name = ?
            """,
            (question_set_id, user_name),
        ).fetchone()

    def question_set_round_summary(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict:
        aggregate = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END), 0)
                    AS completed,
                COALESCE(SUM(CASE
                    WHEN question_id IS NOT NULL AND completed_at IS NULL THEN 1 ELSE 0
                END), 0) AS remaining,
                COALESCE(SUM(CASE WHEN question_id IS NULL THEN 1 ELSE 0 END), 0)
                    AS unavailable,
                COALESCE(SUM(CASE WHEN is_correct IN (0, 1) THEN 1 ELSE 0 END), 0)
                    AS graded,
                COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0)
                    AS correct,
                COALESCE(SUM(CASE WHEN self_mark = 'ok' THEN 1 ELSE 0 END), 0) AS mark_ok,
                COALESCE(SUM(CASE WHEN self_mark = 'warn' THEN 1 ELSE 0 END), 0) AS mark_warn,
                COALESCE(SUM(CASE WHEN self_mark = 'wrong' THEN 1 ELSE 0 END), 0) AS mark_wrong
            FROM question_set_round_items
            WHERE round_id = ?
            """,
            (row["id"],),
        ).fetchone()

        status = str(row["status"])
        updated_at = row["updated_at"]
        completed_at = row["completed_at"]
        if status == "active" and int(aggregate["remaining"] or 0) == 0:
            timestamp = now_iso()
            cur = conn.execute(
                """
                UPDATE question_set_rounds
                SET status = 'completed', updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (timestamp, timestamp, row["id"]),
            )
            if cur.rowcount:
                conn.execute(
                    "UPDATE question_sets SET updated_at = ? WHERE id = ?",
                    (timestamp, row["question_set_id"]),
                )
            current = conn.execute(
                """
                SELECT status, updated_at, completed_at
                FROM question_set_rounds
                WHERE id = ?
                """,
                (row["id"],),
            ).fetchone()
            status = str(current["status"])
            updated_at = current["updated_at"]
            completed_at = current["completed_at"]

        graded = int(aggregate["graded"] or 0)
        correct = int(aggregate["correct"] or 0)
        summary = {
            "total": int(aggregate["total"] or 0),
            "completed": int(aggregate["completed"] or 0),
            "remaining": int(aggregate["remaining"] or 0),
            "unavailable": int(aggregate["unavailable"] or 0),
            "graded": graded,
            "correct": correct,
            "rate": round(correct * 100 / graded, 1) if graded else 0,
            "self_marks": {
                "ok": int(aggregate["mark_ok"] or 0),
                "warn": int(aggregate["mark_warn"] or 0),
                "wrong": int(aggregate["mark_wrong"] or 0),
            },
        }
        payload = {
            "id": int(row["id"]),
            "question_set_id": int(row["question_set_id"]),
            "round_number": int(row["round_number"]),
            "token": row["token"],
            "status": status,
            "summary": summary,
            "created_at": row["created_at"],
            "updated_at": updated_at,
            "completed_at": completed_at,
            "abandoned_at": row["abandoned_at"],
        }
        payload.update(summary)
        return payload

    def question_set_round_active_payload(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict:
        payload = self.question_set_round_summary(conn, row)
        items = conn.execute(
            """
            SELECT question_id, completed_at
            FROM question_set_round_items
            WHERE round_id = ?
            ORDER BY position
            """,
            (row["id"],),
        ).fetchall()
        payload["question_ids"] = [
            int(item["question_id"])
            for item in items
            if item["question_id"] is not None
        ]
        payload["completed_question_ids"] = [
            int(item["question_id"])
            for item in items
            if item["question_id"] is not None and item["completed_at"] is not None
        ]
        next_item = next(
            (
                item
                for item in items
                if item["question_id"] is not None and item["completed_at"] is None
            ),
            None,
        )
        payload["next_question_id"] = (
            int(next_item["question_id"]) if next_item is not None else None
        )
        return payload

    def create_question_set_round(
        self,
        conn: sqlite3.Connection,
        question_set: sqlite3.Row,
        timestamp: str,
    ) -> sqlite3.Row:
        questions = conn.execute(
            """
            SELECT q.id, q.year, q.category, q.question, q.explanation
            FROM question_set_items i
            JOIN questions q ON q.id = i.question_id
            WHERE i.question_set_id = ?
            ORDER BY i.position
            """,
            (question_set["id"],),
        ).fetchall()
        if not questions:
            raise ValueError("この問題セットには利用できる問題がありません。")

        shuffled_questions = list(questions)
        secrets.SystemRandom().shuffle(shuffled_questions)
        previous_order = [
            int(item["source_question_id"])
            for item in conn.execute(
                """
                SELECT i.source_question_id
                FROM question_set_round_items i
                JOIN question_set_rounds r ON r.id = i.round_id
                WHERE r.id = (
                    SELECT id
                    FROM question_set_rounds
                    WHERE question_set_id = ?
                    ORDER BY round_number DESC
                    LIMIT 1
                )
                ORDER BY i.position
                """,
                (question_set["id"],),
            ).fetchall()
        ]
        shuffled_ids = [int(question["id"]) for question in shuffled_questions]
        if len(shuffled_questions) > 1 and shuffled_ids == previous_order:
            shuffled_questions = shuffled_questions[1:] + shuffled_questions[:1]
        round_number = int(
            conn.execute(
                """
                SELECT COALESCE(MAX(round_number), 0) + 1 AS next_number
                FROM question_set_rounds
                WHERE question_set_id = ?
                """,
                (question_set["id"],),
            ).fetchone()["next_number"]
        )
        cur = conn.execute(
            """
            INSERT INTO question_set_rounds (
                question_set_id, round_number, token, status,
                created_at, updated_at, completed_at, abandoned_at
            )
            VALUES (?, ?, ?, 'active', ?, ?, NULL, NULL)
            """,
            (
                question_set["id"],
                round_number,
                secrets.token_urlsafe(32),
                timestamp,
                timestamp,
            ),
        )
        round_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO question_set_round_items (
                round_id, position, question_id, source_question_id,
                source_year, source_category, source_question_number,
                completed_at, attempt_id, user_answer, correct_answer,
                is_correct, self_mark
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            [
                (
                    round_id,
                    position,
                    int(question["id"]),
                    int(question["id"]),
                    str(question["year"] or ""),
                    str(question["category"] or ""),
                    question_number_snapshot(
                        str(question["question"] or ""),
                        str(question["explanation"] or ""),
                    ),
                )
                for position, question in enumerate(shuffled_questions)
            ],
        )
        conn.execute(
            "UPDATE question_sets SET updated_at = ? WHERE id = ?",
            (timestamp, question_set["id"]),
        )
        return conn.execute(
            "SELECT * FROM question_set_rounds WHERE id = ?",
            (round_id,),
        ).fetchone()

    def handle_list_question_sets(self, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        exam = " ".join((params.get("exam", [""])[0] or "").split()).strip()
        if not exam:
            self.send_json({"error": "試験を指定してください。"}, HTTPStatus.BAD_REQUEST)
            return
        if len(exam) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
            self.send_json({"error": "試験名が長すぎます。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            set_rows = conn.execute(
                """
                SELECT *
                FROM question_sets
                WHERE user_name = ? AND exam = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_name, exam),
            ).fetchall()
            question_sets = []
            for set_row in set_rows:
                total = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM question_set_items
                        WHERE question_set_id = ?
                        """,
                        (set_row["id"],),
                    ).fetchone()["total"]
                )
                rounds_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM question_set_rounds
                        WHERE question_set_id = ?
                        """,
                        (set_row["id"],),
                    ).fetchone()["total"]
                )
                active_row = conn.execute(
                    """
                    SELECT * FROM question_set_rounds
                    WHERE question_set_id = ? AND status = 'active'
                    """,
                    (set_row["id"],),
                ).fetchone()
                active_round = (
                    self.question_set_round_summary(conn, active_row)
                    if active_row is not None
                    else None
                )
                if active_round is not None and active_round["status"] != "active":
                    active_round = None
                latest_row = conn.execute(
                    """
                    SELECT * FROM question_set_rounds
                    WHERE question_set_id = ?
                    ORDER BY round_number DESC
                    LIMIT 1
                    """,
                    (set_row["id"],),
                ).fetchone()
                latest_round = (
                    self.question_set_round_summary(conn, latest_row)
                    if latest_row is not None
                    else None
                )
                question_sets.append(
                    {
                        "id": int(set_row["id"]),
                        "user_name": set_row["user_name"],
                        "exam": set_row["exam"],
                        "title": set_row["title"],
                        "total": total,
                        "rounds_count": rounds_count,
                        "active_round": active_round,
                        "latest_round": latest_round,
                        "created_at": set_row["created_at"],
                        "updated_at": set_row["updated_at"],
                    }
                )

        self.send_json({"question_sets": question_sets, "total": len(question_sets)})

    def handle_start_question_set_round(self, question_set_id: int, query: str) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            user_name = self.effective_user_name(
                params=parse_qs(query),
                payload=payload,
            )
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        created = False
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                question_set = self.question_set_for_user(conn, question_set_id, user_name)
                if question_set is None:
                    self.send_json({"error": "問題セットが見つかりません。"}, HTTPStatus.NOT_FOUND)
                    return
                active_row = conn.execute(
                    """
                    SELECT * FROM question_set_rounds
                    WHERE question_set_id = ? AND status = 'active'
                    """,
                    (question_set_id,),
                ).fetchone()
                if active_row is not None:
                    active_round = self.question_set_round_active_payload(conn, active_row)
                    if active_round["status"] == "active":
                        round_payload = active_round
                    else:
                        active_row = None
                if active_row is None:
                    round_row = self.create_question_set_round(conn, question_set, now_iso())
                    round_payload = self.question_set_round_active_payload(conn, round_row)
                    created = True
        except sqlite3.IntegrityError:
            self.send_json(
                {"error": "問題セットの周回を開始できませんでした。もう一度お試しください。"},
                HTTPStatus.CONFLICT,
            )
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return

        self.send_json(
            {"round": round_payload},
            HTTPStatus.CREATED if created else HTTPStatus.OK,
        )

    def handle_get_active_question_set_round(self, question_set_id: int, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            question_set = self.question_set_for_user(conn, question_set_id, user_name)
            if question_set is None:
                self.send_json({"error": "問題セットが見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            row = conn.execute(
                """
                SELECT * FROM question_set_rounds
                WHERE question_set_id = ? AND status = 'active'
                """,
                (question_set_id,),
            ).fetchone()
            round_payload = (
                self.question_set_round_active_payload(conn, row)
                if row is not None
                else None
            )
            if round_payload is not None and round_payload["status"] != "active":
                round_payload = None

        self.send_json({"round": round_payload})

    def handle_restart_question_set_round(self, question_set_id: int, query: str) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            user_name = self.effective_user_name(
                params=parse_qs(query),
                payload=payload,
            )
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                question_set = self.question_set_for_user(conn, question_set_id, user_name)
                if question_set is None:
                    self.send_json({"error": "問題セットが見つかりません。"}, HTTPStatus.NOT_FOUND)
                    return
                available = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM question_set_items i
                        JOIN questions q ON q.id = i.question_id
                        WHERE i.question_set_id = ?
                        """,
                        (question_set_id,),
                    ).fetchone()["total"]
                )
                if not available:
                    raise ValueError("この問題セットには利用できる問題がありません。")
                timestamp = now_iso()
                conn.execute(
                    """
                    UPDATE question_set_rounds
                    SET status = 'abandoned', updated_at = ?, abandoned_at = ?
                    WHERE question_set_id = ? AND status = 'active'
                    """,
                    (timestamp, timestamp, question_set_id),
                )
                round_row = self.create_question_set_round(conn, question_set, timestamp)
                round_payload = self.question_set_round_active_payload(conn, round_row)
        except sqlite3.IntegrityError:
            self.send_json(
                {"error": "問題セットの周回を開始できませんでした。もう一度お試しください。"},
                HTTPStatus.CONFLICT,
            )
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return

        self.send_json({"round": round_payload}, HTTPStatus.CREATED)

    def handle_abandon_question_set_round(
        self,
        question_set_id: int,
        round_id: int,
        query: str,
    ) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            user_name = self.effective_user_name(
                params=parse_qs(query),
                payload=payload,
            )
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT r.*
                FROM question_set_rounds r
                JOIN question_sets s ON s.id = r.question_set_id
                WHERE r.id = ? AND r.question_set_id = ? AND s.user_name = ?
                """,
                (round_id, question_set_id, user_name),
            ).fetchone()
            if row is None:
                self.send_json({"error": "周回履歴が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            if row["status"] != "active":
                self.send_json({"error": "進行中の周回ではありません。"}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE question_set_rounds
                SET status = 'abandoned', updated_at = ?, abandoned_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, round_id),
            )
            conn.execute(
                "UPDATE question_sets SET updated_at = ? WHERE id = ?",
                (timestamp, question_set_id),
            )
            row = conn.execute(
                "SELECT * FROM question_set_rounds WHERE id = ?",
                (round_id,),
            ).fetchone()
            round_payload = self.question_set_round_summary(conn, row)

        self.send_json({"round": round_payload})

    def handle_list_question_set_rounds(self, question_set_id: int, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        try:
            limit = min(max(int(params.get("limit", ["20"])[0]), 1), 20)
            offset = max(int(params.get("offset", ["0"])[0]), 0)
        except ValueError:
            self.send_json({"error": "ページ指定が正しくありません。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            question_set = self.question_set_for_user(conn, question_set_id, user_name)
            if question_set is None:
                self.send_json({"error": "問題セットが見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            total = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM question_set_rounds
                    WHERE question_set_id = ?
                    """,
                    (question_set_id,),
                ).fetchone()["total"]
            )
            rows = conn.execute(
                """
                SELECT *
                FROM question_set_rounds
                WHERE question_set_id = ?
                ORDER BY round_number DESC
                LIMIT ? OFFSET ?
                """,
                (question_set_id, limit, offset),
            ).fetchall()
            rounds = [self.question_set_round_summary(conn, row) for row in rows]

        self.send_json(
            {
                "rounds": rounds,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(rounds) < total,
            }
        )

    def handle_get_question_set_round(
        self,
        question_set_id: int,
        round_id: int,
        query: str,
    ) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        try:
            limit = min(max(int(params.get("limit", ["100"])[0]), 1), 100)
            offset = max(int(params.get("offset", ["0"])[0]), 0)
        except ValueError:
            self.send_json({"error": "ページ指定が正しくありません。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            row = conn.execute(
                """
                SELECT r.*
                FROM question_set_rounds r
                JOIN question_sets s ON s.id = r.question_set_id
                WHERE r.id = ? AND r.question_set_id = ? AND s.user_name = ?
                """,
                (round_id, question_set_id, user_name),
            ).fetchone()
            if row is None:
                self.send_json({"error": "周回履歴が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            total = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM question_set_round_items
                    WHERE round_id = ?
                    """,
                    (round_id,),
                ).fetchone()["total"]
            )
            item_rows = conn.execute(
                """
                SELECT *
                FROM question_set_round_items
                WHERE round_id = ?
                ORDER BY position
                LIMIT ? OFFSET ?
                """,
                (round_id, limit, offset),
            ).fetchall()
            items = [
                {
                    "position": int(item["position"]) + 1,
                    "question_id": (
                        int(item["question_id"])
                        if item["question_id"] is not None
                        else None
                    ),
                    "source_question_id": int(item["source_question_id"]),
                    "year": item["source_year"],
                    "category": item["source_category"],
                    "question_number": item["source_question_number"],
                    "available": item["question_id"] is not None,
                    "completed_at": item["completed_at"],
                    "attempt_id": item["attempt_id"],
                    "user_answer": item["user_answer"],
                    "correct_answer": item["correct_answer"],
                    "is_correct": item["is_correct"],
                    "self_mark": item["self_mark"],
                }
                for item in item_rows
            ]
            round_payload = self.question_set_round_summary(conn, row)
            round_payload["items"] = items

        self.send_json(
            {
                "round": round_payload,
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(items) < total,
            }
        )

    def handle_delete_question_set_round(
        self,
        question_set_id: int,
        round_id: int,
        query: str,
    ) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            row = conn.execute(
                """
                SELECT r.status
                FROM question_set_rounds r
                JOIN question_sets s ON s.id = r.question_set_id
                WHERE r.id = ? AND r.question_set_id = ? AND s.user_name = ?
                """,
                (round_id, question_set_id, user_name),
            ).fetchone()
            if row is None:
                self.send_json({"error": "周回履歴が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            if row["status"] == "active":
                self.send_json(
                    {"error": "進行中の周回は削除できません。先に中断してください。"},
                    HTTPStatus.CONFLICT,
                )
                return
            conn.execute("DELETE FROM question_set_rounds WHERE id = ?", (round_id,))
            conn.execute(
                "UPDATE question_sets SET updated_at = ? WHERE id = ?",
                (now_iso(), question_set_id),
            )

        self.send_json({"ok": True, "round_id": round_id})

    def handle_delete_question_set(self, question_set_id: int, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            cur = conn.execute(
                "DELETE FROM question_sets WHERE id = ? AND user_name = ?",
                (question_set_id, user_name),
            )
            if cur.rowcount == 0:
                self.send_json({"error": "問題セットが見つかりません。"}, HTTPStatus.NOT_FOUND)
                return

        self.send_json({"ok": True, "question_set_id": question_set_id})

    @staticmethod
    def parse_json_list(value: object) -> list:
        try:
            parsed = json.loads(str(value or "[]"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def disease_checklist_summary(
        self,
        conn: sqlite3.Connection,
        checklist: sqlite3.Row,
        _user_name: str,
    ) -> dict:
        counts = conn.execute(
            """
            SELECT
                COUNT(*) AS item_count,
                COALESCE(SUM(CASE WHEN s.status IS NULL THEN 1 ELSE 0 END), 0)
                    AS unreviewed,
                COALESCE(SUM(CASE WHEN s.status = 'ok' THEN 1 ELSE 0 END), 0) AS ok,
                COALESCE(SUM(CASE WHEN s.status = 'warn' THEN 1 ELSE 0 END), 0) AS warn,
                COALESCE(SUM(CASE WHEN s.status = 'wrong' THEN 1 ELSE 0 END), 0) AS wrong,
                COALESCE(SUM(CASE WHEN i.base_included = 1 THEN 1 ELSE 0 END), 0)
                    AS base_item_count,
                COALESCE(SUM(CASE WHEN i.ever_wrong_at IS NOT NULL THEN 1 ELSE 0 END), 0)
                    AS ever_wrong_count,
                COALESCE(SUM(CASE
                    WHEN i.base_included = 0 AND i.ever_wrong_at IS NOT NULL THEN 1 ELSE 0
                END), 0) AS added_by_wrong_count
            FROM disease_checklist_items i
            LEFT JOIN disease_check_statuses s ON s.item_id = i.id
            WHERE i.checklist_id = ?
              AND (i.base_included = 1 OR i.ever_wrong_at IS NOT NULL)
            """,
            (checklist["id"],),
        ).fetchone()
        definition_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM disease_checklist_items
                WHERE checklist_id = ?
                """,
                (checklist["id"],),
            ).fetchone()["total"]
        )
        status_counts = {
            "unreviewed": int(counts["unreviewed"] or 0),
            "ok": int(counts["ok"] or 0),
            "warn": int(counts["warn"] or 0),
            "wrong": int(counts["wrong"] or 0),
        }
        return {
            "id": int(checklist["id"]),
            "exam": checklist["exam"],
            "title": checklist["title"],
            "name": checklist["title"],
            "item_count": int(counts["item_count"] or 0),
            "definition_count": definition_count,
            "base_item_count": int(counts["base_item_count"] or 0),
            "ever_wrong_count": int(counts["ever_wrong_count"] or 0),
            "added_by_wrong_count": int(counts["added_by_wrong_count"] or 0),
            "status_counts": status_counts,
            "source_sha256": checklist["source_sha256"],
            "extraction_criteria": checklist["extraction_criteria"],
            "created_at": checklist["created_at"],
            "updated_at": checklist["updated_at"],
        }

    def disease_checklist_item_payload(self, row: sqlite3.Row) -> dict:
        aliases = self.parse_json_list(row["aliases_json"])
        areas = self.parse_json_list(row["areas_json"])
        curriculum_refs = self.parse_json_list(row["curriculum_refs_json"])
        additional_sources = self.parse_json_list(row["sources_json"])
        status = row["status"] if "status" in row.keys() else None
        first_reviewed_at = (
            row["status_created_at"] if "status_created_at" in row.keys() else None
        )
        status_updated_at = (
            row["status_updated_at"] if "status_updated_at" in row.keys() else None
        )
        base_included = bool(row["base_included"])
        ever_wrong = row["ever_wrong_at"] is not None
        return {
            "id": int(row["id"]),
            "position": int(row["position"]),
            "disease_name": row["disease_name"],
            "aliases": aliases,
            "concept_type": row["concept_type"],
            "primary_area": row["primary_area"],
            "primary_region": row["primary_area"],
            "areas": areas,
            "hierarchy": curriculum_refs,
            "curriculum_refs": curriculum_refs,
            "review_note": row["review_note"],
            "note": row["review_note"],
            "note_updated_at": row["note_updated_at"],
            "sources": additional_sources,
            "additional_sources": additional_sources,
            "base_included": base_included,
            "ever_wrong": ever_wrong,
            "ever_wrong_at": row["ever_wrong_at"],
            "ever_wrong_question_id": row["ever_wrong_question_id"],
            "added_by_wrong": not base_included and ever_wrong,
            "status": status,
            "first_reviewed_at": first_reviewed_at,
            "status_updated_at": status_updated_at,
            "reviewed_at": status_updated_at,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def disease_checklist_for_user(
        self,
        conn: sqlite3.Connection,
        checklist_id: int,
        user_name: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM disease_checklists
            WHERE id = ? AND user_name = ?
            """,
            (checklist_id, user_name),
        ).fetchone()

    def disease_checklist_item_for_user(
        self,
        conn: sqlite3.Connection,
        checklist_id: int,
        item_id: int,
        user_name: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT
                i.*,
                s.status,
                s.created_at AS status_created_at,
                s.updated_at AS status_updated_at
            FROM disease_checklist_items i
            JOIN disease_checklists c ON c.id = i.checklist_id
            LEFT JOIN disease_check_statuses s
                ON s.item_id = i.id
            WHERE c.id = ?
              AND i.id = ?
              AND c.user_name = ?
              AND (i.base_included = 1 OR i.ever_wrong_at IS NOT NULL)
            """,
            (checklist_id, item_id, user_name),
        ).fetchone()

    def handle_list_disease_checklists(self, query: str) -> None:
        if not self.require_disease_checklist_access():
            return
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        exam = " ".join((params.get("exam", [""])[0] or "").split()).strip()
        if not exam:
            self.send_json({"error": "試験を指定してください。"}, HTTPStatus.BAD_REQUEST)
            return
        if len(exam) > MAX_PRACTICE_FILTER_TEXT_LENGTH:
            self.send_json({"error": "試験名が長すぎます。"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM disease_checklists
                WHERE user_name = ? AND exam = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_name, exam),
            ).fetchall()
            checklists = [
                self.disease_checklist_summary(conn, row, user_name)
                for row in rows
            ]

        self.send_json({"checklists": checklists, "total": len(checklists)})

    def handle_get_disease_checklist(self, checklist_id: int, query: str) -> None:
        if not self.require_disease_checklist_access():
            return
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            checklist = self.disease_checklist_for_user(conn, checklist_id, user_name)
            if checklist is None:
                self.send_json({"error": "疾患確認リストが見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            rows = conn.execute(
                """
                SELECT
                    i.*,
                    s.status,
                    s.created_at AS status_created_at,
                    s.updated_at AS status_updated_at
                FROM disease_checklist_items i
                LEFT JOIN disease_check_statuses s ON s.item_id = i.id
                WHERE i.checklist_id = ?
                  AND (i.base_included = 1 OR i.ever_wrong_at IS NOT NULL)
                ORDER BY i.position, i.id
                """,
                (checklist_id,),
            ).fetchall()
            checklist_payload = self.disease_checklist_summary(
                conn,
                checklist,
                user_name,
            )
            checklist_payload["items"] = [
                self.disease_checklist_item_payload(row) for row in rows
            ]

        self.send_json({"checklist": checklist_payload})

    def handle_update_disease_check_status(
        self,
        checklist_id: int,
        item_id: int,
    ) -> None:
        if not self.require_disease_checklist_access():
            return
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            user_name = self.effective_user_name(payload=payload)
            status = str(payload.get("status") or "").strip()
            if status not in {"ok", "warn", "wrong"}:
                raise ValueError("評価は○、△、×から選択してください。")
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        timestamp = now_iso()
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            checklist = self.disease_checklist_for_user(conn, checklist_id, user_name)
            item = self.disease_checklist_item_for_user(
                conn,
                checklist_id,
                item_id,
                user_name,
            )
            if checklist is None or item is None:
                self.send_json({"error": "疾患確認項目が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            conn.execute(
                """
                INSERT INTO disease_check_statuses (
                    item_id, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (item_id, status, timestamp, timestamp),
            )
            conn.execute(
                "UPDATE disease_checklists SET updated_at = ? WHERE id = ?",
                (timestamp, checklist_id),
            )
            checklist = self.disease_checklist_for_user(conn, checklist_id, user_name)
            item = self.disease_checklist_item_for_user(
                conn,
                checklist_id,
                item_id,
                user_name,
            )
            checklist_payload = self.disease_checklist_summary(
                conn,
                checklist,
                user_name,
            )
            item_payload = self.disease_checklist_item_payload(item)

        self.send_json({"item": item_payload, "checklist": checklist_payload})

    def serve_static(self, raw_path: str) -> None:
        path = unquote(raw_path)
        if path in ("", "/"):
            target = STATIC_DIR / "index.html"
        else:
            target = (STATIC_DIR / path.lstrip("/")).resolve()

        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        file_stat = target.stat()
        file_size = file_stat.st_size
        etag = f'"{int(file_stat.st_mtime):x}-{file_size:x}"'
        last_modified = self.date_time_string(int(file_stat.st_mtime))
        cache_control = self.static_cache_control(path, content_type)

        range_header = self.headers.get("Range", "")
        range_info = self.parse_byte_range(range_header, file_size) if range_header else None
        if range_header and range_info is None:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # 条件付きGET: 内容が変わっていなければ本文を送らず 304 で返す(モバイルの再取得帯域を節約)。
        # Range リクエスト時は部分取得の再検証を避けるため通常配信にフォールバックする。
        if not range_header and self.static_not_modified(etag, file_stat.st_mtime):
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            self.end_headers()
            return

        if range_info:
            start, end = range_info
            content_length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        else:
            start = 0
            content_length = file_size
            self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified)
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        if content_type == "text/html":
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'",
            )
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command == "HEAD":
            return

        with target.open("rb") as handle:
            handle.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = handle.read(min(SOURCE_PDF_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def static_cache_control(self, path: str, content_type: str) -> str:
        # PDF は既存どおり短期の private キャッシュ。
        if path.startswith("/source-pdfs/"):
            return "private, max-age=3600"
        # ?v= のキャッシュバスター付きで要求された JS/CSS 等は、内容が変われば URL も
        # 変わるので長期 immutable キャッシュにして再取得自体を無くす。
        if "v" in parse_qs(urlparse(self.path).query):
            return "public, max-age=31536000, immutable"
        # index.html はバスター無しで参照されるため毎回 ETag で再検証させる
        # (更新した ?v= を取りこぼさないため。中身が同じなら 304 で軽く返る)。
        if content_type == "text/html":
            return "no-cache"
        # その他(バスター無しの画像など)は1日キャッシュしつつ再検証可能にする。
        return "public, max-age=86400"

    def static_not_modified(self, etag: str, mtime: float) -> bool:
        inm = self.headers.get("If-None-Match")
        if inm is not None:
            # If-None-Match があれば(RFC 7232)それを優先。弱い検証子の W/ は外して比較。
            candidates = {tag.strip().removeprefix("W/") for tag in inm.split(",")}
            return etag in candidates or "*" in candidates
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                parsed = email.utils.parsedate_to_datetime(ims)
            except (TypeError, ValueError):
                return False
            if parsed is not None:
                return int(mtime) <= int(parsed.timestamp())
        return False

    def parse_byte_range(self, header: str, file_size: int) -> tuple[int, int] | None:
        if not header.startswith("bytes=") or "," in header:
            return None
        raw_start, _, raw_end = header.removeprefix("bytes=").partition("-")
        try:
            if raw_start:
                start = int(raw_start)
                end = int(raw_end) if raw_end else file_size - 1
            elif raw_end:
                suffix_length = int(raw_end)
                if suffix_length <= 0:
                    return None
                start = max(0, file_size - suffix_length)
                end = file_size - 1
            else:
                return None
        except ValueError:
            return None
        if start < 0 or end < start or start >= file_size:
            return None
        return start, min(end, file_size - 1)

    def handle_list_questions(self, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params)
        filters = []
        args: list[str] = []

        for field in ("exam", "year", "category"):
            value = (params.get(field, [""])[0] or "").strip()
            if value:
                filters.append(f"q.{field} = ?")
                args.append(value)

        keyword = (params.get("q", [""])[0] or "").strip()
        if keyword:
            filters.append("(q.question LIKE ? OR q.answer LIKE ? OR q.explanation LIKE ?)")
            like = f"%{keyword}%"
            args.extend([like, like, like])

        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT
                q.*,
                COUNT(a.id) AS attempts_count,
                COALESCE(SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct_count,
                COALESCE(SUM(CASE WHEN a.is_correct IN (0, 1) THEN 1 ELSE 0 END), 0) AS graded_count,
                MAX(a.created_at) AS last_attempt_at,
                COALESCE((
                    SELECT a2.self_mark
                    FROM attempts a2
                    WHERE a2.question_id = q.id AND a2.user_name = ?
                    ORDER BY a2.created_at DESC, a2.id DESC
                    LIMIT 1
                ), '') AS last_self_mark,
                COALESCE(n.note, '') AS user_note,
                n.updated_at AS user_note_updated_at
                FROM questions q
                LEFT JOIN attempts a ON a.question_id = q.id AND a.user_name = ?
                LEFT JOIN question_notes n ON n.question_id = q.id AND n.user_name = ?
                {where}
                GROUP BY q.id
                ORDER BY
                    q.year DESC,
                    q.id ASC
                """,
                [user_name, user_name, user_name, *args],
            ).fetchall()

        self.send_json({"questions": [row_to_question(row) for row in rows]})

    def handle_create_question(self) -> None:
        self.discard_request_body()
        self.send_json({"error": "ブラウザ上での問題作成は無効です。"}, HTTPStatus.FORBIDDEN)

    def handle_update_question(self, question_id: int) -> None:
        if not self.require_question_edit():
            return
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            fields = clean_question_payload(payload, partial=True)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        allowed = ("exam", "year", "category", "question", "choices", "images", "answer", "explanation")
        updates = []
        args: list[object] = []
        for key in allowed:
            if key not in fields:
                continue
            updates.append(f"{key} = ?")
            value = fields[key]
            if key in ("choices", "images"):
                value = json.dumps(value, ensure_ascii=False)
            args.append(value)

        if not updates:
            self.send_json({"error": "更新する項目がありません。"}, HTTPStatus.BAD_REQUEST)
            return

        updates.append("updated_at = ?")
        args.append(now_iso())
        args.append(question_id)

        with db() as conn:
            existing = conn.execute(
                "SELECT exam FROM questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if existing is None:
                self.send_json({"error": "問題が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            if "exam" in fields and fields["exam"] != existing["exam"]:
                linked_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM disease_checklist_item_questions
                        WHERE question_id = ?
                        """,
                        (question_id,),
                    ).fetchone()["total"]
                )
                if linked_count:
                    self.send_json(
                        {"error": "疾患確認の監査対象になっている問題は試験を変更できません。"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
            conn.execute(
                f"UPDATE questions SET {', '.join(updates)} WHERE id = ?",
                args,
            )
            row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()

        self.send_json({"question": row_to_question(row)})

    def handle_delete_question(self, question_id: int) -> None:
        if not self.require_question_edit():
            return
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if row is None:
                self.send_json({"error": "問題が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            disease_reference_count = int(
                conn.execute(
                    """
                    SELECT
                        (SELECT COUNT(*)
                         FROM disease_checklist_item_questions
                         WHERE question_id = ?)
                      + (SELECT COUNT(*)
                         FROM disease_checklist_items
                         WHERE ever_wrong_question_id = ?) AS total
                    """,
                    (question_id, question_id),
                ).fetchone()["total"]
            )
            if disease_reference_count:
                self.send_json(
                    {"error": "疾患確認の監査根拠に使われている問題は削除できません。"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        self.send_json({"ok": True})

    def handle_save_note(self, question_id: int) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSON object is required.")
            user_name = self.effective_user_name(payload=payload)
            note = str(payload.get("note") or "").strip()[:MAX_NOTE_LENGTH]
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        timestamp = now_iso()
        with db() as conn:
            row = conn.execute("SELECT id FROM questions WHERE id = ?", (question_id,)).fetchone()
            if row is None:
                self.send_json({"error": "Question not found."}, HTTPStatus.NOT_FOUND)
                return

            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, timestamp),
            )
            if note:
                cur = conn.execute(
                    """
                    UPDATE question_notes
                    SET note = ?, updated_at = ?
                    WHERE question_id = ? AND user_name = ?
                    """,
                    (note, timestamp, question_id, user_name),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        """
                        INSERT INTO question_notes (question_id, user_name, note, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (question_id, user_name, note, timestamp),
                    )
            else:
                conn.execute(
                    "DELETE FROM question_notes WHERE question_id = ? AND user_name = ?",
                    (question_id, user_name),
                )

        self.send_json(
            {
                "ok": True,
                "question_id": question_id,
                "user_name": user_name,
                "note": note,
                "updated_at": timestamp if note else None,
            }
        )

    def attempt_rows_for_question(
        self,
        conn: sqlite3.Connection,
        question_id: int,
        user_name: str = DEFAULT_USER_NAME,
        limit: int = 30,
    ) -> list[dict]:
        rows = conn.execute(
            """
            SELECT
                a.id,
                a.question_id,
                a.user_name,
                a.user_answer,
                a.is_correct,
                a.self_mark,
                a.created_at
            FROM attempts a
            WHERE a.question_id = ? AND a.user_name = ?
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ?
            """,
            (question_id, user_name, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def activate_disease_checklist_items_for_wrong_attempt(
        self,
        conn: sqlite3.Connection,
        user_name: str,
        question_id: int,
        timestamp: str,
    ) -> int:
        checklist_rows = conn.execute(
            """
            SELECT DISTINCT c.id
            FROM disease_checklist_item_questions iq
            JOIN disease_checklist_items i ON i.id = iq.item_id
            JOIN disease_checklists c ON c.id = i.checklist_id
            JOIN questions q ON q.id = iq.question_id AND q.exam = c.exam
            WHERE iq.question_id = ?
              AND iq.match_type IN ('correct', 'structured_target')
              AND c.user_name = ?
              AND i.ever_wrong_at IS NULL
            """,
            (question_id, user_name),
        ).fetchall()
        checklist_ids = [int(row["id"]) for row in checklist_rows]
        if not checklist_ids:
            return 0

        cur = conn.execute(
            """
            UPDATE disease_checklist_items
            SET ever_wrong_at = ?, ever_wrong_question_id = ?, updated_at = ?
            WHERE ever_wrong_at IS NULL
              AND id IN (
                  SELECT iq.item_id
                  FROM disease_checklist_item_questions iq
                  JOIN disease_checklist_items linked_item ON linked_item.id = iq.item_id
                  JOIN disease_checklists c ON c.id = linked_item.checklist_id
                  JOIN questions q ON q.id = iq.question_id AND q.exam = c.exam
                  WHERE iq.question_id = ?
                    AND iq.match_type IN ('correct', 'structured_target')
                    AND c.user_name = ?
              )
            """,
            (timestamp, question_id, timestamp, question_id, user_name),
        )
        if cur.rowcount:
            placeholders = ", ".join("?" for _ in checklist_ids)
            conn.execute(
                f"""
                UPDATE disease_checklists
                SET updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [timestamp, *checklist_ids],
            )
        return max(0, int(cur.rowcount))

    def handle_create_attempt(self) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            question_id = int(payload.get("question_id", 0))
            user_name = self.effective_user_name(payload=payload)
            user_answer = str(payload.get("user_answer") or "").strip()
            self_mark = str(payload.get("self_mark") or "warn").strip()
            raw_practice_session_token = payload.get("practice_session_token")
            if raw_practice_session_token is not None and not isinstance(
                raw_practice_session_token, str
            ):
                raise ValueError("一周トークンの形式が正しくありません。")
            practice_session_token = str(raw_practice_session_token or "").strip()
            raw_question_set_round_token = payload.get("question_set_round_token")
            if raw_question_set_round_token is not None and not isinstance(
                raw_question_set_round_token, str
            ):
                raise ValueError("問題セット周回トークンの形式が正しくありません。")
            question_set_round_token = str(raw_question_set_round_token or "").strip()
            if question_id <= 0:
                raise ValueError("問題を選択してください。")
            if not user_answer:
                raise ValueError("解答を入力してください。")
            if self_mark not in {"ok", "warn", "wrong"}:
                raise ValueError("評価は○、△、×から選択してください。")
            if len(practice_session_token) > MAX_PRACTICE_SESSION_TOKEN_LENGTH:
                raise ValueError("一周トークンが長すぎます。")
            if len(question_set_round_token) > MAX_PRACTICE_SESSION_TOKEN_LENGTH:
                raise ValueError("問題セット周回トークンが長すぎます。")
            if practice_session_token and question_set_round_token:
                raise ValueError("クイック演習と問題セットの周回トークンは同時に指定できません。")
        except (TypeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
            if row is None:
                self.send_json({"error": "問題が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return

            has_answer = bool(str(row["answer"] or "").strip())
            correct = is_correct_answer(user_answer, row["answer"]) if has_answer else None
            timestamp = now_iso()
            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, timestamp),
            )
            cur = conn.execute(
                """
                INSERT INTO attempts (question_id, user_name, user_answer, is_correct, self_mark, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    user_name,
                    user_answer,
                    1 if correct is True else 0 if correct is False else -1,
                    self_mark,
                    timestamp,
                ),
            )
            attempt_id = cur.lastrowid
            disease_checklist_items_activated = 0
            if correct is False:
                disease_checklist_items_activated = (
                    self.activate_disease_checklist_items_for_wrong_attempt(
                        conn,
                        user_name,
                        question_id,
                        timestamp,
                    )
                )

            practice_session = None
            practice_session_stale = False
            if practice_session_token:
                session_item = conn.execute(
                    """
                    SELECT
                        s.*,
                        i.completed_at AS item_completed_at
                    FROM practice_sessions s
                    JOIN practice_session_items i ON i.session_id = s.id
                    WHERE
                        s.token = ?
                        AND s.user_name = ?
                        AND i.question_id = ?
                    """,
                    (practice_session_token, user_name, question_id),
                ).fetchone()
                if session_item is None:
                    practice_session_stale = True
                else:
                    if session_item["item_completed_at"] is None:
                        conn.execute(
                            """
                            UPDATE practice_session_items
                            SET completed_at = ?
                            WHERE
                                session_id = ?
                                AND question_id = ?
                                AND completed_at IS NULL
                            """,
                            (timestamp, session_item["id"], question_id),
                        )
                        conn.execute(
                            """
                            UPDATE practice_sessions
                            SET updated_at = ?
                            WHERE id = ?
                            """,
                            (timestamp, session_item["id"]),
                        )
                    session_row = conn.execute(
                        "SELECT * FROM practice_sessions WHERE id = ?",
                        (session_item["id"],),
                    ).fetchone()
                    practice_session = self.practice_session_payload(conn, session_row)

            question_set_round = None
            question_set_round_stale = False
            if question_set_round_token:
                round_item = conn.execute(
                    """
                    SELECT
                        r.*,
                        i.completed_at AS item_completed_at
                    FROM question_set_rounds r
                    JOIN question_sets s ON s.id = r.question_set_id
                    JOIN question_set_round_items i ON i.round_id = r.id
                    WHERE
                        r.token = ?
                        AND r.status = 'active'
                        AND s.user_name = ?
                        AND i.question_id = ?
                    """,
                    (question_set_round_token, user_name, question_id),
                ).fetchone()
                if round_item is None:
                    question_set_round_stale = True
                else:
                    if round_item["item_completed_at"] is None:
                        conn.execute(
                            """
                            UPDATE question_set_round_items
                            SET
                                completed_at = ?,
                                attempt_id = ?,
                                user_answer = ?,
                                correct_answer = ?,
                                is_correct = ?,
                                self_mark = ?
                            WHERE
                                round_id = ?
                                AND question_id = ?
                                AND completed_at IS NULL
                            """,
                            (
                                timestamp,
                                attempt_id,
                                user_answer,
                                row["answer"],
                                1 if correct is True else 0 if correct is False else -1,
                                self_mark,
                                round_item["id"],
                                question_id,
                            ),
                        )
                        conn.execute(
                            """
                            UPDATE question_set_rounds
                            SET updated_at = ?
                            WHERE id = ?
                            """,
                            (timestamp, round_item["id"]),
                        )
                        conn.execute(
                            "UPDATE question_sets SET updated_at = ? WHERE id = ?",
                            (timestamp, round_item["question_set_id"]),
                        )
                    round_row = conn.execute(
                        "SELECT * FROM question_set_rounds WHERE id = ?",
                        (round_item["id"],),
                    ).fetchone()
                    question_set_round = self.question_set_round_active_payload(
                        conn,
                        round_row,
                    )

            attempts = self.attempt_rows_for_question(conn, question_id, user_name)

        self.send_json(
            {
                "attempt_id": attempt_id,
                "user_name": user_name,
                "self_mark": self_mark,
                "graded": has_answer,
                "correct": correct,
                "correct_answer": row["answer"],
                "explanation": row["explanation"],
                "attempts": attempts,
                "practice_session": practice_session,
                "practice_session_stale": practice_session_stale,
                "question_set_round": question_set_round,
                "question_set_round_stale": question_set_round_stale,
                "disease_checklist_items_activated": disease_checklist_items_activated,
            }
        )

    def handle_update_attempt(self, attempt_id: int) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            self_mark = str(payload.get("self_mark") or "").strip()
            user_name = self.effective_user_name(payload=payload)
            if self_mark not in {"ok", "warn", "wrong"}:
                raise ValueError("評価は○、△、×から選択してください。")
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            row = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if row is None:
                self.send_json({"error": "解答履歴が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            if not self.can_modify_attempt(row["user_name"], user_name):
                self.send_json({"error": "This attempt belongs to another user."}, HTTPStatus.FORBIDDEN)
                return
            conn.execute("UPDATE attempts SET self_mark = ? WHERE id = ?", (self_mark, attempt_id))
            conn.execute(
                """
                UPDATE question_set_round_items
                SET self_mark = ?
                WHERE attempt_id = ?
                """,
                (self_mark, attempt_id),
            )
            attempts = self.attempt_rows_for_question(conn, row["question_id"], row["user_name"])

        self.send_json({"attempt_id": attempt_id, "user_name": row["user_name"], "self_mark": self_mark, "attempts": attempts})

    def handle_delete_attempt(self, attempt_id: int) -> None:
        params = parse_qs(urlparse(self.path).query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            row = conn.execute("SELECT question_id, user_name FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            if row is None:
                self.send_json({"error": "解答履歴が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            if not self.can_modify_attempt(row["user_name"], user_name):
                self.send_json({"error": "This attempt belongs to another user."}, HTTPStatus.FORBIDDEN)
                return
            conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))

        self.send_json({"ok": True, "attempt_id": attempt_id, "question_id": row["question_id"], "user_name": row["user_name"]})

    def handle_delete_attempts(self, query: str) -> None:
        params = parse_qs(query)
        user_name = self.effective_user_name(params=params)
        with db() as conn:
            cur = conn.execute("DELETE FROM attempts WHERE user_name = ?", (user_name,))
            deleted = cur.rowcount
            session_cur = conn.execute(
                "DELETE FROM practice_sessions WHERE user_name = ?",
                (user_name,),
            )
            practice_sessions_deleted = session_cur.rowcount
            question_set_rounds_deleted = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM question_set_rounds r
                    JOIN question_sets s ON s.id = r.question_set_id
                    WHERE s.user_name = ?
                    """,
                    (user_name,),
                ).fetchone()["total"]
            )
            conn.execute(
                """
                DELETE FROM question_set_rounds
                WHERE question_set_id IN (
                    SELECT id FROM question_sets WHERE user_name = ?
                )
                """,
                (user_name,),
            )

        self.send_json(
            {
                "ok": True,
                "deleted": deleted,
                "practice_sessions_deleted": practice_sessions_deleted,
                "question_set_rounds_deleted": question_set_rounds_deleted,
                "user_name": user_name,
            }
        )

    def user_rows(self, conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute(
            """
            SELECT
                u.id,
                u.name,
                u.created_at,
                COUNT(a.id) AS attempts_count,
                COUNT(DISTINCT a.question_id) AS questions_count,
                MAX(a.created_at) AS last_attempt_at
            FROM users u
            LEFT JOIN attempts a ON a.user_name = u.name
            GROUP BY u.id
            ORDER BY
                CASE WHEN u.name = ? THEN 0 ELSE 1 END,
                u.name COLLATE NOCASE
            """,
            (DEFAULT_USER_NAME,),
        ).fetchall()
        return [dict(row) for row in rows]

    def handle_list_users(self) -> None:
        if not self.require_user_management():
            return
        with db() as conn:
            rows = self.user_rows(conn)
        self.send_json({"users": rows})

    def handle_create_user(self) -> None:
        if not self.require_user_management():
            return
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            raw_name = payload.get("name")
            if not str(raw_name or "").strip():
                raise ValueError("ユーザー名を入力してください。")
            user_name = clean_user_name(raw_name)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, now_iso()),
            )
            rows = self.user_rows(conn)

        self.send_json({"user_name": user_name, "users": rows}, HTTPStatus.CREATED)

    def handle_delete_user(self, user_id: int) -> None:
        if not self.require_user_management():
            return
        with db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                self.send_json({"error": "ユーザーが見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            attempts_count = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = ?",
                (row["name"],),
            ).fetchone()["total"]
            question_sets_count = conn.execute(
                "SELECT COUNT(*) AS total FROM question_sets WHERE user_name = ?",
                (row["name"],),
            ).fetchone()["total"]
            disease_checklists_count = conn.execute(
                "SELECT COUNT(*) AS total FROM disease_checklists WHERE user_name = ?",
                (row["name"],),
            ).fetchone()["total"]
            if attempts_count or question_sets_count or disease_checklists_count:
                self.send_json(
                    {
                        "error": (
                            "履歴、問題セット、または疾患確認リストがあるユーザーは"
                            "削除できません。"
                        )
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            rows = self.user_rows(conn)

        self.send_json({"ok": True, "user_id": user_id, "users": rows})

    def handle_stats(self, query: str = "") -> None:
        params = parse_qs(query)
        exam = (params.get("exam", [""])[0] or "").strip()
        user_name = self.effective_user_name(params)
        question_filter = "WHERE exam = ?" if exam else ""
        question_args: list[str] = [exam] if exam else []
        attempt_filters = ["a.user_name = ?"]
        attempt_args: list[str] = [user_name]
        if exam:
            attempt_filters.append("q.exam = ?")
            attempt_args.append(exam)
        attempt_filter = f"WHERE {' AND '.join(attempt_filters)}"

        with db() as conn:
            q_total = conn.execute(
                f"SELECT COUNT(*) AS total FROM questions {question_filter}",
                question_args,
            ).fetchone()["total"]
            attempts = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct,
                    COALESCE(SUM(CASE WHEN is_correct IN (0, 1) THEN 1 ELSE 0 END), 0) AS graded
                FROM attempts a
                JOIN questions q ON q.id = a.question_id
                {attempt_filter}
                """,
                attempt_args,
            ).fetchone()
            attempted_questions = conn.execute(
                f"""
                SELECT COUNT(DISTINCT a.question_id) AS total
                FROM attempts a
                JOIN questions q ON q.id = a.question_id
                {attempt_filter}
                """,
                attempt_args,
            ).fetchone()["total"]
            exams = [
                row["exam"]
                for row in conn.execute(
                    "SELECT DISTINCT exam FROM questions WHERE exam <> '' ORDER BY exam"
                ).fetchall()
            ]
            years = [
                row["year"]
                for row in conn.execute(
                    f"SELECT DISTINCT year FROM questions WHERE year <> '' {'AND exam = ?' if exam else ''} ORDER BY year DESC",
                    question_args,
                ).fetchall()
            ]
            categories = [
                row["category"]
                for row in conn.execute(
                    f"SELECT DISTINCT category FROM questions WHERE category <> '' {'AND exam = ?' if exam else ''} ORDER BY category",
                    question_args,
                ).fetchall()
            ]

        total_attempts = attempts["total"] or 0
        graded_attempts = attempts["graded"] or 0
        correct_attempts = attempts["correct"] or 0
        rate = round(correct_attempts * 100 / graded_attempts, 1) if graded_attempts else 0
        self.send_json(
            {
                "questions": q_total,
                "attempts": total_attempts,
                "graded_attempts": graded_attempts,
                "attempted_questions": attempted_questions,
                "correct": correct_attempts,
                "rate": rate,
                "exams": exams,
                "years": years,
                "categories": categories,
            }
        )

    def handle_study_summary(self, query: str = "") -> None:
        params = parse_qs(query)
        exam = (params.get("exam", [""])[0] or "").strip()
        user_name = self.effective_user_name(params)
        filters = []
        args: list[str] = [user_name]
        if exam:
            filters.append("q.exam = ?")
            args.append(exam)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        def make_rows(rows: list[sqlite3.Row], label_field: str) -> list[dict]:
            items = []
            for row in rows:
                total = int(row["total"] or 0)
                ok = int(row["ok"] or 0)
                warn = int(row["warn"] or 0)
                wrong = int(row["wrong"] or 0)
                untried = int(row["untried"] or 0)
                attempted = ok + warn + wrong
                items.append(
                    {
                        "label": row[label_field],
                        "total": total,
                        "attempted": attempted,
                        "ok": ok,
                        "warn": warn,
                        "wrong": wrong,
                        "untried": untried,
                        "remaining": untried,
                        "percent": round(attempted * 100 / total) if total else 0,
                    }
                )
            return items

        summary_select = """
            COUNT(*) AS total,
            SUM(CASE WHEN latest.question_id IS NULL THEN 1 ELSE 0 END) AS untried,
            SUM(CASE WHEN latest.question_id IS NOT NULL AND latest.self_mark = 'ok' THEN 1 ELSE 0 END) AS ok,
            SUM(CASE WHEN latest.question_id IS NOT NULL AND latest.self_mark = 'wrong' THEN 1 ELSE 0 END) AS wrong,
            SUM(CASE WHEN latest.question_id IS NOT NULL AND latest.self_mark NOT IN ('ok', 'wrong') THEN 1 ELSE 0 END) AS warn
        """
        latest_cte = """
            WITH latest AS (
                SELECT question_id, COALESCE(self_mark, '') AS self_mark
                FROM (
                    SELECT
                        question_id,
                        self_mark,
                        ROW_NUMBER() OVER (
                            PARTITION BY question_id
                            ORDER BY created_at DESC, id DESC
                        ) AS row_number
                    FROM attempts
                    WHERE user_name = ?
                )
                WHERE row_number = 1
            )
        """
        with db() as conn:
            category_rows = conn.execute(
                f"""
                {latest_cte}
                SELECT q.category AS category, {summary_select}
                FROM questions q
                LEFT JOIN latest ON latest.question_id = q.id
                {where}
                {"AND" if where else "WHERE"} q.category <> ''
                GROUP BY q.category
                ORDER BY q.category
                """,
                args,
            ).fetchall()
            year_rows = conn.execute(
                f"""
                {latest_cte}
                SELECT q.year AS year, {summary_select}
                FROM questions q
                LEFT JOIN latest ON latest.question_id = q.id
                {where}
                {"AND" if where else "WHERE"} q.year <> ''
                GROUP BY q.year
                ORDER BY q.year DESC
                """,
                args,
            ).fetchall()

        self.send_json(
            {
                "category": make_rows(category_rows, "category"),
                "year": make_rows(year_rows, "year"),
            }
        )

    def handle_attempts(self, query: str) -> None:
        params = parse_qs(query)
        try:
            limit = min(max(int(params.get("limit", ["50"])[0]), 1), 200)
        except ValueError:
            limit = 50
        try:
            question_id = int(params.get("question_id", ["0"])[0])
        except ValueError:
            question_id = 0
        exam = (params.get("exam", [""])[0] or "").strip()
        user_name = self.effective_user_name(params)

        filters = ["a.user_name = ?"]
        args: list[object] = [user_name]
        if question_id > 0:
            filters.append("a.question_id = ?")
            args.append(question_id)
        if exam:
            filters.append("q.exam = ?")
            args.append(exam)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        args.append(limit)

        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    a.id,
                    a.question_id,
                    a.user_name,
                    a.user_answer,
                    a.is_correct,
                    a.self_mark,
                    a.created_at,
                    q.exam,
                    q.year,
                    q.category,
                    q.question,
                    q.answer
                FROM attempts a
                JOIN questions q ON q.id = a.question_id
                {where}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?
                """,
                args,
            ).fetchall()

        self.send_json({"attempts": [dict(row) for row in rows]})

    def handle_export(self) -> None:
        with db() as conn:
            rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()

        self.send_json({"questions": [row_to_question(row) for row in rows]})

    def handle_import(self) -> None:
        self.discard_request_body()
        self.send_json({"error": "ブラウザ上でのJSON取込は無効です。"}, HTTPStatus.FORBIDDEN)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser-based past exam trainer")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8081, help="Bind port")
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Serving Kakomon Trainer at http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
