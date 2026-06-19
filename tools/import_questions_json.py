#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def backup_db(db_path: Path, label: str) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = APP_DIR / "backups" / f"before-{label}-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def load_questions(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        questions = payload.get("questions", [])
    elif isinstance(payload, list):
        questions = payload
    else:
        questions = []
    if not isinstance(questions, list):
        raise ValueError("JSONには questions の配列が必要です。")
    return [item for item in questions if isinstance(item, dict)]


def import_questions(db_path: Path, questions: list[dict], replace_years: bool, backup_label: str) -> tuple[int, int, Path | None]:
    timestamp = now_iso()
    inserted = 0
    skipped = 0
    backup = backup_db(db_path, backup_label)

    with sqlite3.connect(db_path) as conn:
        if replace_years:
            targets = sorted({(str(item.get("exam", "")), str(item.get("year", ""))) for item in questions})
            for exam, year in targets:
                if exam and year:
                    conn.execute("DELETE FROM questions WHERE exam = ? AND year = ?", (exam, year))

        for item in questions:
            exam = str(item.get("exam", "")).strip()
            year = str(item.get("year", "")).strip()
            category = str(item.get("category", "")).strip()
            question = str(item.get("question", "")).strip()
            if not exam or not year or not question:
                skipped += 1
                continue
            exists = conn.execute(
                "SELECT 1 FROM questions WHERE exam = ? AND year = ? AND question = ? LIMIT 1",
                (exam, year, question),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO questions
                    (exam, year, category, question, choices, images, answer, explanation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exam,
                    year,
                    category,
                    question,
                    json.dumps(item.get("choices", []), ensure_ascii=False),
                    json.dumps(item.get("images", []), ensure_ascii=False),
                    str(item.get("answer", "")),
                    str(item.get("explanation", "")),
                    timestamp,
                    timestamp,
                ),
            )
            inserted += 1
        conn.commit()

    return inserted, skipped, backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Kakomon Trainer questions from JSON.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--replace-year", action="store_true")
    parser.add_argument("--backup-label", default="json-import")
    args = parser.parse_args()

    questions = load_questions(args.json_path)
    inserted, skipped, backup = import_questions(args.db.resolve(), questions, args.replace_year, args.backup_label)
    if backup:
        print(f"backup: {backup}")
    print(f"DB: {args.db.resolve()}")
    print(f"Inserted: {inserted}, skipped: {skipped}, total loaded: {len(questions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
