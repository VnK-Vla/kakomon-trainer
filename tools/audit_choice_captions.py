#!/usr/bin/env python3
"""選択肢への図キャプション/版面要素(News Letter バナー等)混入を DB から監査する。

PDF 再取込などで混入が再発していないかを確認するための検査ツール。何も書き換え
ない。検出があれば終了コード 1 を返すので、取込後のチェックにそのまま使える。

使い方:
    python3 tools/audit_choice_captions.py [--db data/questions.db]

判定:
  * 高精度規則(句点後の付加テキスト・フッター/バナー)にヒットした選択肢
  * 過去に修正済みの問題(choice_caption_guard.KNOWN_FIXED_IDS)で、規則に
    再ヒットしたものは「回帰」として強調表示する
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from choice_caption_guard import KNOWN_FIXED_IDS, find_contaminated  # noqa: E402

DEFAULT_DB = Path(os.environ.get("KAKOMON_DATA_DIR", "data")) / "questions.db"


def load_questions(db_path: Path):
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("SELECT id, exam, year, choices, images FROM questions")
        rows = []
        meta = {}
        for qid, exam, year, choices, images in cur.fetchall():
            ch = json.loads(choices) if choices else []
            im = json.loads(images) if images else []
            rows.append((qid, ch, im))
            meta[qid] = (exam, year)
        return rows, meta
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        print(f"DB が見つかりません: {db_path}", file=sys.stderr)
        return 2

    rows, meta = load_questions(db_path)
    hits = find_contaminated(rows)

    if not hits:
        print(f"OK: 選択肢へのキャプション/版面要素の混入は検出されませんでした ({db_path})")
        return 0

    print(f"混入候補 {len(hits)} 件 ({db_path}):\n")
    letters = "abcde"
    regressions = 0
    for qid, idx, choice, tail in hits:
        exam, year = meta.get(qid, ("?", "?"))
        letter = letters[idx] if idx < len(letters) else str(idx)
        mark = ""
        if qid in KNOWN_FIXED_IDS:
            mark = "  << 修正済み問題での再混入(回帰)"
            regressions += 1
        print(f"  問題ID {qid} [{exam} {year}] 選択肢 {letter}{mark}")
        print(f"    現在値 : {choice!r}")
        print(f"    疑い箇所: {tail!r}")
    if regressions:
        print(f"\n!! 修正済み問題での再混入が {regressions} 件あります(再取込で上書きされた可能性)。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
