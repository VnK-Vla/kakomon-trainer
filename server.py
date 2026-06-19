#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("KAKOMON_DATA_DIR", BASE_DIR / "data")).resolve()
DB_PATH = DATA_DIR / "questions.db"
DEFAULT_USER_NAME = "自分"
MAX_USER_NAME_LENGTH = 80
MAX_NOTE_LENGTH = 4000
TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"


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

            CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam);
            CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
            CREATE INDEX IF NOT EXISTS idx_attempts_question_id ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at);
            CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);
            CREATE INDEX IF NOT EXISTS idx_question_notes_user_name ON question_notes(user_name);
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


class AppHandler(BaseHTTPRequestHandler):
    server_version = "KakomonTrainer/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/session":
            self.handle_session()
        elif parsed.path == "/api/questions":
            self.handle_list_questions(parsed.query)
        elif parsed.path == "/api/stats":
            self.handle_stats(parsed.query)
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/questions":
            self.handle_create_question()
        elif parsed.path == "/api/attempts":
            self.handle_create_attempt()
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

    def read_json(self) -> dict | list:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("JSONの形式を確認してください。") from exc

    def discard_request_body(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 0:
            self.rfile.read(length)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            cur = conn.execute(
                f"UPDATE questions SET {', '.join(updates)} WHERE id = ?",
                args,
            )
            if cur.rowcount == 0:
                self.send_json({"error": "問題が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
            row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()

        self.send_json({"question": row_to_question(row)})

    def handle_delete_question(self, question_id: int) -> None:
        if not self.require_question_edit():
            return
        with db() as conn:
            cur = conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            if cur.rowcount == 0:
                self.send_json({"error": "問題が見つかりません。"}, HTTPStatus.NOT_FOUND)
                return
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

    def handle_create_attempt(self) -> None:
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("JSONオブジェクトを送信してください。")
            question_id = int(payload.get("question_id", 0))
            user_name = self.effective_user_name(payload=payload)
            user_answer = str(payload.get("user_answer") or "").strip()
            self_mark = str(payload.get("self_mark") or "warn").strip()
            if question_id <= 0:
                raise ValueError("問題を選択してください。")
            if not user_answer:
                raise ValueError("解答を入力してください。")
            if self_mark not in {"ok", "warn", "wrong"}:
                raise ValueError("評価は○、△、×から選択してください。")
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

        self.send_json({"ok": True, "deleted": deleted, "user_name": user_name})

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
            if attempts_count:
                self.send_json({"error": "履歴があるユーザーは削除できません。"}, HTTPStatus.BAD_REQUEST)
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
