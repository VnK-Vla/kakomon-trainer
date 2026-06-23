#!/usr/bin/env python3
"""既存の核医学専門医試験の設問を新しい 10 分野へ再分類する。

nuclear_classifier.classify で全設問を分類し直し、questions テーブルの
category 列を更新する。実行前に DB をバックアップする。分類は設問本文
（question 列。先頭の「問N」は無害なため除去せずそのまま用いる）に基づく。

使い方:
    python3 tools/reclassify_nuclear.py            # 再分類を実行
    python3 tools/reclassify_nuclear.py --dry-run  # 件数の確認のみ（更新しない）
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nuclear_classifier import classify, NUCLEAR_CATEGORIES

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
EXAM_NAME = "核医学専門医試験"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = APP_DIR / "backups" / f"before-nuclear-reclassify-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def print_distribution(title: str, counts: Counter) -> None:
    print(title)
    for category in NUCLEAR_CATEGORIES:
        print(f"  {counts.get(category, 0):>4}  {category}")
    extras = sorted(set(counts) - set(NUCLEAR_CATEGORIES))
    for category in extras:
        print(f"  {counts.get(category, 0):>4}  [旧] {category}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify nuclear medicine exam questions into the 10 official domains.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true", help="Show the before/after distribution without updating the database.")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 1

    with sqlite3.connect(args.db) as conn:
        rows = conn.execute(
            "SELECT id, category, question FROM questions WHERE exam = ?",
            (EXAM_NAME,),
        ).fetchall()

        before = Counter(category for _, category, _ in rows)
        updates: list[tuple[str, str, int]] = []
        after = Counter()
        changed = 0
        for question_id, current, question in rows:
            new_category = classify(question)
            after[new_category] += 1
            if new_category != current:
                changed += 1
            updates.append((new_category, now_iso(), question_id))

        print(f"対象: {len(rows)} 問（{EXAM_NAME}）")
        print_distribution("\n=== 変更前 ===", before)
        print_distribution("\n=== 変更後 ===", after)
        print(f"\n変更される設問数: {changed} / {len(rows)}")

        if args.dry_run:
            print("\n--dry-run のため DB は更新しません。")
            return 0

        backup = backup_db(args.db)
        if backup:
            print(f"\nbackup: {backup}")

        conn.executemany(
            "UPDATE questions SET category = ?, updated_at = ? WHERE id = ?",
            updates,
        )
        conn.commit()
        print(f"updated: {len(updates)} 問の分野を更新しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
