#!/usr/bin/env python3
"""Create an owner-private named set together with authored questions."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from tools import manage_question_sets
except ModuleNotFoundError:  # Direct execution: python3 tools/manage_private_question_sets.py
    import manage_question_sets  # type: ignore[no-redef]


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_BACKUP_ROOT = APP_DIR / "backups"
EXPECTED_MANIFEST_KEYS = {"title", "exam", "questions"}
EXPECTED_QUESTION_KEYS = {
    "year",
    "category",
    "question",
    "choices",
    "answer",
    "explanation",
}
MAX_QUESTIONS = 200
MAX_TEXT_LENGTH = 20_000
MAX_CHOICE_LENGTH = 2_000
ANSWER_RE = re.compile(r"^[a-j]$")

REQUIRED_SCHEMA = {
    "questions": {
        "id",
        "exam",
        "year",
        "category",
        "question",
        "choices",
        "images",
        "answer",
        "explanation",
        "created_at",
        "updated_at",
    },
    "users": {"name"},
    "private_question_owners": {"question_id", "user_name", "created_at"},
    "question_sets": {"id", "user_name", "exam", "title", "created_at", "updated_at"},
    "question_set_items": {"question_set_id", "position", "question_id"},
}


class PrivateQuestionSetError(RuntimeError):
    """An expected validation or creation error."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PrivateQuestionSetError(f"manifestに重複したキーがあります: {key}")
        result[key] = value
    return result


def private_manifest_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    app_dir = APP_DIR.resolve()
    if resolved == app_dir or app_dir in resolved.parents:
        raise PrivateQuestionSetError("個人問題のmanifestはリポジトリ外に置いてください。")
    if not resolved.is_file():
        raise PrivateQuestionSetError(f"manifestが見つかりません: {resolved}")
    return resolved


def _clean_short_text(value: Any, field: str, maximum: int = 80) -> str:
    if not isinstance(value, str):
        raise PrivateQuestionSetError(f"{field}は文字列にしてください。")
    cleaned = " ".join(value.split()).strip()
    if not 1 <= len(cleaned) <= maximum:
        raise PrivateQuestionSetError(f"{field}は1〜{maximum}文字にしてください。")
    return cleaned


def _clean_long_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise PrivateQuestionSetError(f"{field}は文字列にしてください。")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= MAX_TEXT_LENGTH:
        raise PrivateQuestionSetError(
            f"{field}は1〜{MAX_TEXT_LENGTH}文字にしてください。"
        )
    return cleaned


def _normalize_question(value: Any, position: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrivateQuestionSetError(f"questions[{position}]はオブジェクトにしてください。")
    keys = set(value)
    unknown = sorted(keys - EXPECTED_QUESTION_KEYS)
    missing = sorted(EXPECTED_QUESTION_KEYS - keys)
    if unknown:
        raise PrivateQuestionSetError(
            f"questions[{position}]に未対応のキーがあります: " + ", ".join(unknown)
        )
    if missing:
        raise PrivateQuestionSetError(
            f"questions[{position}]に必須キーがありません: " + ", ".join(missing)
        )

    choices = value["choices"]
    if not isinstance(choices, list) or not 2 <= len(choices) <= 10:
        raise PrivateQuestionSetError(
            f"questions[{position}].choicesは2〜10個の配列にしてください。"
        )
    normalized_choices: list[str] = []
    for choice_position, choice in enumerate(choices):
        if not isinstance(choice, str):
            raise PrivateQuestionSetError(
                f"questions[{position}].choices[{choice_position}]は文字列にしてください。"
            )
        cleaned_choice = choice.strip()
        expected_prefix = f"{chr(ord('a') + choice_position)}."
        if not cleaned_choice.startswith(expected_prefix):
            raise PrivateQuestionSetError(
                f"questions[{position}].choices[{choice_position}]は"
                f"「{expected_prefix}」で始めてください。"
            )
        if len(cleaned_choice) > MAX_CHOICE_LENGTH:
            raise PrivateQuestionSetError(
                f"questions[{position}].choices[{choice_position}]が長すぎます。"
            )
        normalized_choices.append(cleaned_choice)
    if len(set(normalized_choices)) != len(normalized_choices):
        raise PrivateQuestionSetError(f"questions[{position}].choicesに重複があります。")

    answer = value["answer"]
    if not isinstance(answer, str) or not ANSWER_RE.fullmatch(answer):
        raise PrivateQuestionSetError(
            f"questions[{position}].answerは単一の小文字選択肢記号にしてください。"
        )
    if ord(answer) - ord("a") >= len(normalized_choices):
        raise PrivateQuestionSetError(
            f"questions[{position}].answerに対応する選択肢がありません。"
        )

    return {
        "year": _clean_short_text(value["year"], f"questions[{position}].year"),
        "category": _clean_short_text(
            value["category"], f"questions[{position}].category"
        ),
        "question": _clean_long_text(
            value["question"], f"questions[{position}].question"
        ),
        "choices": normalized_choices,
        "answer": answer,
        "explanation": _clean_long_text(
            value["explanation"], f"questions[{position}].explanation"
        ),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    path = private_manifest_path(path)
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except PrivateQuestionSetError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateQuestionSetError("manifestはUTF-8の正しいJSONにしてください。") from exc
    if not isinstance(payload, dict):
        raise PrivateQuestionSetError("manifestの最上位はオブジェクトにしてください。")

    keys = set(payload)
    unknown = sorted(keys - EXPECTED_MANIFEST_KEYS)
    missing = sorted(EXPECTED_MANIFEST_KEYS - keys)
    if unknown:
        raise PrivateQuestionSetError(
            "manifestに未対応のキーがあります: " + ", ".join(unknown)
        )
    if missing:
        raise PrivateQuestionSetError(
            "manifestに必須キーがありません: " + ", ".join(missing)
        )

    raw_questions = payload["questions"]
    if not isinstance(raw_questions, list) or not 1 <= len(raw_questions) <= MAX_QUESTIONS:
        raise PrivateQuestionSetError(f"questionsは1〜{MAX_QUESTIONS}件にしてください。")
    questions = [
        _normalize_question(question, position)
        for position, question in enumerate(raw_questions)
    ]
    question_texts = [question["question"] for question in questions]
    if len(set(question_texts)) != len(question_texts):
        raise PrivateQuestionSetError("questions内に同一の問題文があります。")

    return {
        "title": _clean_short_text(payload["title"], "title"),
        "exam": _clean_short_text(payload["exam"], "exam"),
        "questions": questions,
    }


def require_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(set(REQUIRED_SCHEMA) - tables)
    missing_columns: list[str] = []
    for table, expected in REQUIRED_SCHEMA.items():
        if table not in tables:
            continue
        actual = {
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        missing_columns.extend(
            f"{table}.{column}" for column in sorted(expected - actual)
        )
    if missing_tables or missing_columns:
        details = missing_tables + missing_columns
        raise PrivateQuestionSetError(
            "個人問題用スキーマが未導入です。新しいserver.pyで初期化してください。"
            f" ({', '.join(details)})"
        )


def open_read_only(db_path: Path) -> sqlite3.Connection:
    try:
        conn = manage_question_sets.open_read_only(db_path)
    except manage_question_sets.QuestionSetError as exc:
        raise PrivateQuestionSetError(str(exc)) from exc
    return conn


def inspect_request(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    user_name: str,
) -> dict[str, Any]:
    require_schema(conn)
    if conn.execute("SELECT 1 FROM users WHERE name = ?", (user_name,)).fetchone() is None:
        raise PrivateQuestionSetError("指定ユーザーはusersテーブルに存在しません。")
    if conn.execute(
        "SELECT 1 FROM question_sets WHERE user_name = ? AND exam = ? AND title = ?",
        (user_name, manifest["exam"], manifest["title"]),
    ).fetchone() is not None:
        raise PrivateQuestionSetError("同じユーザー・試験に同名の問題セットがあります。")
    if conn.execute(
        """
        SELECT 1
        FROM questions q
        WHERE q.exam = ?
          AND NOT EXISTS (
              SELECT 1 FROM private_question_owners p WHERE p.question_id = q.id
          )
        LIMIT 1
        """,
        (manifest["exam"],),
    ).fetchone() is None:
        raise PrivateQuestionSetError("指定examに公開問題が存在しません。")

    questions = manifest["questions"]
    return {
        "owner_verified": True,
        "title": manifest["title"],
        "exam": manifest["exam"],
        "question_count": len(questions),
        "single_answer_count": sum(
            1 for question in questions if ANSWER_RE.fullmatch(question["answer"])
        ),
        "breakdown": {
            "year": dict(sorted(Counter(q["year"] for q in questions).items())),
            "category": dict(
                sorted(Counter(q["category"] for q in questions).items())
            ),
        },
    }


def create_private_question_set(
    manifest_path: Path,
    *,
    user_name: str,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    normalized_user = user_name.strip()
    if not normalized_user:
        raise PrivateQuestionSetError("--userには既存ユーザー名を指定してください。")
    manifest = load_manifest(manifest_path)
    db_path = db_path.resolve()

    conn = open_read_only(db_path)
    try:
        summary = inspect_request(conn, manifest, normalized_user)
    finally:
        conn.close()
    if dry_run:
        return {"ok": True, "dry_run": True, **summary}

    try:
        backup_path = manage_question_sets.backup_database(
            db_path,
            backup_root=backup_root,
        )
    except manage_question_sets.QuestionSetError as exc:
        raise PrivateQuestionSetError(str(exc)) from exc

    conn = None
    try:
        conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=rw",
            uri=True,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        summary = inspect_request(conn, manifest, normalized_user)
        timestamp = manage_question_sets.now_iso()
        question_ids: list[int] = []
        for question in manifest["questions"]:
            cursor = conn.execute(
                """
                INSERT INTO questions (
                    exam, year, category, question, choices, images,
                    answer, explanation, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)
                """,
                (
                    manifest["exam"],
                    question["year"],
                    question["category"],
                    question["question"],
                    json.dumps(question["choices"], ensure_ascii=False),
                    question["answer"],
                    question["explanation"],
                    timestamp,
                    timestamp,
                ),
            )
            question_id = int(cursor.lastrowid)
            question_ids.append(question_id)
            conn.execute(
                """
                INSERT INTO private_question_owners (question_id, user_name, created_at)
                VALUES (?, ?, ?)
                """,
                (question_id, normalized_user, timestamp),
            )

        set_cursor = conn.execute(
            """
            INSERT INTO question_sets (
                user_name, exam, title, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_user,
                manifest["exam"],
                manifest["title"],
                timestamp,
                timestamp,
            ),
        )
        question_set_id = int(set_cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO question_set_items (question_set_id, position, question_id)
            VALUES (?, ?, ?)
            """,
            [
                (question_set_id, position, question_id)
                for position, question_id in enumerate(question_ids)
            ],
        )
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise PrivateQuestionSetError("外部キー整合性を確認できませんでした。")
        conn.commit()
    except PrivateQuestionSetError:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise PrivateQuestionSetError(
            "個人問題セットの登録に失敗し、変更をロールバックしました。"
        ) from exc
    finally:
        if conn is not None:
            conn.close()

    return {
        "ok": True,
        "dry_run": False,
        "question_set_id": question_set_id,
        "backup": str(backup_path),
        **summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="新作問題を所有者専用の問題セットとして登録します。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="manifestから作成")
    create_parser.add_argument("manifest", type=Path)
    create_parser.add_argument("--user", required=True)
    create_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    create_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = create_private_question_set(
            args.manifest,
            user_name=args.user,
            db_path=args.db,
            dry_run=args.dry_run,
        )
    except PrivateQuestionSetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
