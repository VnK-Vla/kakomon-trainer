#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_YEAR = "2020"
DEFAULT_EXAM = "放射線診断専門医認定試験"


@dataclass
class AnswerEntry:
    number: int
    answer: str
    topic: str
    point: str
    uncertainty: str
    detail: str = ""


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def normalize_answer(answer: str) -> str:
    return re.sub(r"\s+", "", answer.strip())


def parse_detailed_explanations(text: str) -> dict[int, str]:
    details: dict[int, str] = {}
    in_details = False
    current_number: int | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_number, current_lines
        if current_number is not None:
            detail = "\n".join(current_lines).strip()
            if detail:
                details[current_number] = detail
        current_number = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## 詳細長め解説"):
            in_details = True
            continue
        if not in_details:
            continue
        if line.startswith("## "):
            flush()
            break

        heading = re.match(r"^###\s*(?:問\s*)?(\d{1,3})(?:番)?\s*$", line.strip())
        if heading:
            flush()
            current_number = int(heading.group(1))
            continue
        if current_number is not None:
            current_lines.append(line)

    flush()
    return details


def parse_answers(path: Path) -> dict[int, AnswerEntry]:
    text = path.read_text(encoding="utf-8")
    details = parse_detailed_explanations(text)
    entries: dict[int, AnswerEntry] = {}
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## 解答一覧"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = split_markdown_row(line)
        if len(cells) < 5 or cells[0] in {"問", "---:"} or set(cells[0]) <= {"-", ":"}:
            continue
        try:
            number = int(cells[0])
        except ValueError:
            continue
        entries[number] = AnswerEntry(
            number=number,
            answer=normalize_answer(cells[1]),
            topic=cells[2],
            point=cells[3],
            uncertainty=cells[4],
            detail=details.get(number, ""),
        )
    return entries


def question_number(question: str) -> int | None:
    match = re.search(r"問\s*(\d{1,3})", question or "")
    return int(match.group(1)) if match else None


def explanation_for(entry: AnswerEntry) -> str:
    if entry.detail:
        lines = []
        if entry.topic:
            lines.append(f"診断名・テーマ: {entry.topic}")
        lines.append(entry.detail)
        if entry.uncertainty and "疑義" not in entry.detail:
            lines.append(f"疑義: {entry.uncertainty}")
        return "\n\n".join(lines)

    lines = []
    if entry.topic:
        lines.append(f"診断名・テーマ: {entry.topic}")
    if entry.point:
        lines.append(f"要点: {entry.point}")
    if entry.uncertainty:
        lines.append(f"疑義: {entry.uncertainty}")
    return "\n".join(lines)


def backup_db(db_path: Path) -> Path:
    backup_dir = APP_DIR / "backups" / f"before-radiology-2020-answers-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def import_answers(db_path: Path, answers_path: Path, exam: str, year: str, no_backup: bool = False) -> None:
    entries = parse_answers(answers_path)
    if len(entries) != 64:
        raise ValueError(f"解答一覧は64問である必要があります。実際: {len(entries)}問")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, question FROM questions WHERE exam = ? AND year = ? ORDER BY id",
            (exam, year),
        ).fetchall()
        question_by_number = {}
        for row in rows:
            number = question_number(row["question"])
            if number is not None:
                question_by_number[number] = row

        missing_questions = sorted(set(entries) - set(question_by_number))
        missing_answers = sorted(set(question_by_number) - set(entries))
        if len(question_by_number) != 64 or missing_questions or missing_answers:
            raise ValueError(
                f"DBと解答の問題番号が一致しません。"
                f"DB={len(question_by_number)}問 missing_questions={missing_questions} missing_answers={missing_answers}"
            )

        backup = None if no_backup else backup_db(db_path)
        timestamp = now_iso()
        for number, entry in entries.items():
            conn.execute(
                """
                UPDATE questions
                SET answer = ?, explanation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    entry.answer,
                    explanation_for(entry),
                    timestamp,
                    question_by_number[number]["id"],
                ),
            )
        conn.commit()

    if backup:
        print(f"backup: {backup}")
    print(f"updated: {len(entries)} answers for {exam} {year}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import 2020 radiology answer summary.")
    parser.add_argument("answers", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--exam", default=DEFAULT_EXAM)
    parser.add_argument("--year", default=DEFAULT_YEAR)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    import_answers(args.db, args.answers, args.exam, args.year, args.no_backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
