#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def normalize_question_text(text: str) -> str:
    return " ".join(str(text or "").splitlines()).strip()


def backup_db(db_path: Path) -> Path:
    backup_dir = APP_DIR / "backups" / f"before-question-newline-normalize-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def normalize_db(db_path: Path, no_backup: bool = False) -> None:
    changed = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, question FROM questions ORDER BY id").fetchall()
        updates = []
        for row in rows:
            current = row["question"] or ""
            normalized = normalize_question_text(current)
            if normalized != current:
                updates.append((normalized, now_iso(), row["id"]))

        backup = None
        if updates and not no_backup:
            backup = backup_db(db_path)

        if updates:
            conn.executemany(
                "UPDATE questions SET question = ?, updated_at = ? WHERE id = ?",
                updates,
            )
            conn.commit()
            changed = len(updates)

    if backup:
        print(f"backup: {backup}")
    print(f"normalized: {changed} questions")


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove manual line breaks from question text.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    normalize_db(args.db, args.no_backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
