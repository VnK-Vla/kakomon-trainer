#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from field_classifier import classify_question, extract_question_number


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"


def classify_db(db_path: Path, dry_run: bool = False) -> Counter[str]:
    counts: Counter[str] = Counter()
    updates: list[tuple[str, int]] = []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, year, question, explanation FROM questions ORDER BY id").fetchall()
        for row in rows:
            question_number = extract_question_number(row["question"], row["explanation"])
            field = classify_question(row["question"], row["year"], question_number)
            counts[field] += 1
            updates.append((field, row["id"]))

        if not dry_run:
            conn.executemany("UPDATE questions SET category = ? WHERE id = ?", updates)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify imported questions into practice fields")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to questions.db")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without updating the DB")
    args = parser.parse_args()

    counts = classify_db(Path(args.db).resolve(), args.dry_run)
    for field, count in counts.most_common():
        print(f"{field}: {count}")


if __name__ == "__main__":
    main()
