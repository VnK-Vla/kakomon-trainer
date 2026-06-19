#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_PDF_DIR = Path("work") / "nuclear_pdfs"
DEFAULT_MEDIA_ROOT = APP_DIR / "static" / "media" / "nuclear"
EXAM_NAME = "核医学専門医試験"

QSTART_RE = re.compile(r"^\s*0?([1-9]\d?)[.．]\s*(.*)$")
CHOICE_RE = re.compile(r"^\s*([a-e])[\).．]\s*(.*)$")
NO_RE = re.compile(r"No\.?\s*([1-9]\d?)(?:[-‐‑‒–—ー−]\d+)?", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"^0?([1-9]\d?)(?:[-‐‑‒–—ー−]\d+)?$")
FIGURE_NUMBER_RE = re.compile(r"^図\s*([2-6]\d)$")


@dataclass
class Question:
    year: str
    number: int
    stem: str
    choices: list[str]
    category: str
    images: list[str]


@dataclass
class Label:
    number: int
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = text.replace("ᵐ", "m")
    return text


def clean_text(text: str) -> str:
    text = normalize(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:、。，．)])", r"\1", text)
    text = re.sub(r"([\(（])\s+", r"\1", text)
    text = re.sub(r"([ぁ-んァ-ン一-龥])\s+([ぁ-んァ-ン一-龥])", r"\1\2", text)
    text = text.replace("1 つ", "1つ").replace("2 つ", "2つ")
    return text


def visible_words(page, *, include_footer: bool = False) -> list[dict]:
    width = float(page.width)
    height = float(page.height)
    words = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        x_tolerance=1,
        y_tolerance=3,
    ) or []
    kept: list[dict] = []
    for word in words:
        x0 = float(word["x0"])
        x1 = float(word["x1"])
        top = float(word["top"])
        if x0 < -1 or x1 > width + 1:
            continue
        if top < 35:
            continue
        if not include_footer and top > height - 50:
            continue
        item = dict(word)
        item["text"] = normalize(item.get("text", ""))
        kept.append(item)
    kept.sort(key=lambda item: (float(item["top"]), float(item["x0"])))
    return kept


def group_lines(words: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None
    for word in words:
        top = float(word["top"])
        if current_top is None or abs(top - current_top) <= tolerance:
            current.append(word)
            current_top = top if current_top is None else (current_top * (len(current) - 1) + top) / len(current)
            continue
        lines.append(current)
        current = [word]
        current_top = top
    if current:
        lines.append(current)
    for line in lines:
        line.sort(key=lambda item: float(item["x0"]))
    return lines


def line_to_text(line: list[dict]) -> str:
    text = ""
    previous_x1: float | None = None
    for word in line:
        chunk = normalize(word["text"])
        x0 = float(word["x0"])
        x1 = float(word["x1"])
        if previous_x1 is not None and x0 - previous_x1 > 2.4:
            text += " "
        text += chunk
        previous_x1 = x1
    text = re.sub(r"\s+", " ", text).strip()
    return text


def visible_page_lines(page) -> list[str]:
    lines: list[str] = []
    for line in group_lines(visible_words(page)):
        text = line_to_text(line)
        if not text:
            continue
        if re.fullmatch(r"-?\s*\d{1,2}\s*-?", text):
            continue
        if "核医学専門医試験問題の領域" in text:
            continue
        lines.append(text)
    return lines


def find_question_page_span(pdf) -> tuple[int, int]:
    start_page: int | None = None
    end_page: int | None = None
    for index, page in enumerate(pdf.pages, start=1):
        if index < 3:
            continue
        lines = visible_page_lines(page)
        numbers: list[int] = []
        for line in lines:
            match = QSTART_RE.match(line)
            if match:
                numbers.append(int(match.group(1)))
        has_choices = any(CHOICE_RE.match(line) for line in lines)
        if start_page is None and 1 in numbers and has_choices:
            start_page = index
        if start_page is not None and 60 in numbers:
            end_page = index
            break
    if start_page is None or end_page is None:
        raise ValueError("本文のページ範囲を特定できませんでした。")
    return start_page, end_page


def split_choices(parts: list[str]) -> tuple[str, list[str]]:
    stem_parts: list[str] = []
    choices: list[str] = []
    current_choice: str | None = None
    for raw in parts:
        line = clean_text(raw)
        if not line:
            continue
        match = CHOICE_RE.match(line)
        if match:
            if current_choice:
                choices.append(clean_text(current_choice))
            current_choice = f"{match.group(1)}. {match.group(2).strip()}"
            continue
        if current_choice:
            current_choice += " " + line
        else:
            stem_parts.append(line)
    if current_choice:
        choices.append(clean_text(current_choice))
    return clean_text(" ".join(stem_parts)), choices


def classify_question(stem: str, choices: list[str]) -> str:
    text = stem + " " + " ".join(choices)
    rules = [
        ("脳神経", ["脳", "認知症", "アルツハイマー", "MIBG", "DAT", "IMP", "ECD", "てんかん", "パーキンソン"]),
        ("循環器", ["心筋", "心臓", "冠", "虚血", "狭心症", "BMIPP", "Tl", "QGS", "心不全", "アミロイドーシス"]),
        ("腫瘍・炎症", ["FDG", "PET", "腫瘍", "癌", "がん", "リンパ腫", "転移", "炎症", "サルコイドーシス"]),
        ("内分泌・内用療法", ["甲状腺", "副甲状腺", "131I", "223Ra", "177Lu", "90Y", "治療", "退出基準"]),
        ("骨・腎・消化器", ["骨", "腎", "肝", "胆", "肺血流", "唾液腺", "胃粘膜", "GSA", "DTPA", "MAG3"]),
        ("基礎・安全管理", ["壊変", "半減期", "放射能", "被ばく", "線量", "法", "医療法", "品質管理", "コリメータ", "SPECT", "PET装置"]),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "核医学総合"


def parse_questions(pdf_path: Path) -> tuple[list[Question], int]:
    year = pdf_path.stem
    with pdfplumber.open(str(pdf_path)) as pdf:
        start_page, end_page = find_question_page_span(pdf)
        lines: list[str] = []
        for page_index in range(start_page, end_page + 1):
            lines.extend(visible_page_lines(pdf.pages[page_index - 1]))

    expected = 1
    current_number: int | None = None
    current_parts: list[str] = []
    parsed: list[Question] = []

    def flush() -> None:
        if current_number is None:
            return
        stem, choices = split_choices(current_parts)
        if len(choices) != 5:
            raise ValueError(f"{year} 問{current_number}: 選択肢が5個ではありません ({len(choices)}個)。")
        parsed.append(
            Question(
                year=year,
                number=current_number,
                stem=stem,
                choices=choices,
                category=classify_question(stem, choices),
                images=[],
            )
        )

    for line in lines:
        match = QSTART_RE.match(line)
        if match and int(match.group(1)) == expected:
            flush()
            current_number = expected
            current_parts = [match.group(2).strip()]
            expected += 1
            continue
        if current_number is not None:
            current_parts.append(line)
    flush()

    numbers = [item.number for item in parsed]
    if numbers != list(range(1, 61)):
        raise ValueError(f"{year}: 60問の連番として読めませんでした: {numbers}")
    return parsed, end_page


def bbox_for_words(words: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(float(word["x0"]) for word in words),
        min(float(word["top"]) for word in words),
        max(float(word["x1"]) for word in words),
        max(float(word["bottom"]) for word in words),
    )


def label_from_no_word(words: list[dict], index: int) -> Label | None:
    base = words[index]
    candidates = [base]
    base_top = float(base["top"])
    base_x0 = float(base["x0"])
    for word in words[index + 1 : index + 8]:
        top = float(word["top"])
        if top - base_top > 48:
            break
        if abs(float(word["x0"]) - base_x0) > 120 and abs(top - base_top) > 8:
            continue
        candidates.append(word)
        joined = " ".join(normalize(item["text"]) for item in candidates)
        compact = "".join(normalize(item["text"]) for item in candidates)
        match = NO_RE.search(joined) or NO_RE.search(compact)
        if match:
            x0, top0, x1, bottom = bbox_for_words(candidates)
            return Label(int(match.group(1)), x0, top0, x1, bottom)
    return None


def detect_labels(page, valid_numbers: set[int]) -> list[Label]:
    words = visible_words(page, include_footer=False)
    page_height = float(page.height)
    labels: list[Label] = []
    for index, word in enumerate(words):
        top = float(word["top"])
        bottom = float(word["bottom"])
        if top > page_height - 110:
            continue
        text = normalize(word["text"]).strip()
        no_match = NO_RE.search(text)
        if no_match:
            labels.append(
                Label(
                    int(no_match.group(1)),
                    float(word["x0"]),
                    float(word["top"]),
                    float(word["x1"]),
                    float(word["bottom"]),
                )
            )
            continue
        if text.lower().startswith("no"):
            label = label_from_no_word(words, index)
            if label:
                labels.append(label)
            continue
        figure_number_match = FIGURE_NUMBER_RE.match(text)
        if figure_number_match and bottom - top >= 13:
            number = int(figure_number_match.group(1))
            if number in valid_numbers:
                labels.append(
                    Label(
                        number,
                        float(word["x0"]),
                        float(word["top"]),
                        float(word["x1"]),
                        float(word["bottom"]),
                    )
                )
            continue
        number_match = NUMBER_TOKEN_RE.match(text)
        if not number_match:
            continue
        number = int(number_match.group(1))
        if number not in valid_numbers or number < 20:
            continue
        if bottom - top < 13:
            continue
        previous = words[index - 1] if index else None
        if previous and abs(float(previous["top"]) - float(word["top"])) <= 8:
            previous_text = normalize(previous["text"])
            if previous_text.lower().startswith("no"):
                continue
            if previous_text.startswith(("図", "Figure", "Fig")):
                continue
        if top < 80 and float(word["x0"]) > 120:
            continue
        labels.append(
            Label(
                number,
                float(word["x0"]),
                float(word["top"]),
                float(word["x1"]),
                float(word["bottom"]),
            )
        )

    filtered = [label for label in labels if label.number in valid_numbers]
    filtered.sort(key=lambda item: (item.number, item.top, item.x0))
    deduped: list[Label] = []
    for label in filtered:
        duplicate = False
        for kept in deduped:
            if kept.number != label.number:
                continue
            if abs(kept.top - label.top) < 16 and abs(kept.x0 - label.x0) < 80:
                duplicate = True
                break
        if not duplicate:
            deduped.append(label)
    return sorted(deduped, key=lambda item: (item.top, item.x0, item.number))


def row_groups(labels: list[Label]) -> list[list[Label]]:
    rows: list[list[Label]] = []
    for label in sorted(labels, key=lambda item: item.top):
        for row in rows:
            if abs(min(item.top for item in row) - label.top) <= 70:
                row.append(label)
                break
        else:
            rows.append([label])
    for row in rows:
        row.sort(key=lambda item: item.cx)
    return rows


def crop_regions_for_page(page, labels: list[Label]) -> dict[int, list[tuple[float, float, float, float]]]:
    width = float(page.width)
    height = float(page.height)
    groups: dict[int, list[Label]] = {}
    for label in labels:
        groups.setdefault(label.number, []).append(label)

    q_tops = {number: min(label.top for label in q_labels) for number, q_labels in groups.items()}
    q_centers = {number: sum(label.cx for label in q_labels) / len(q_labels) for number, q_labels in groups.items()}
    q_rows: list[list[int]] = []
    for number, top in sorted(q_tops.items(), key=lambda item: item[1]):
        for row in q_rows:
            if abs(min(q_tops[item] for item in row) - top) <= 70:
                row.append(number)
                break
        else:
            q_rows.append([number])

    x_ranges: dict[int, tuple[float, float]] = {}
    for row in q_rows:
        row.sort(key=lambda item: q_centers[item])
        for pos, number in enumerate(row):
            labels_for_number = groups[number]
            min_x = min(label.x0 for label in labels_for_number)
            max_x = max(label.x1 for label in labels_for_number)
            if len(row) == 1 or max_x - min_x > width * 0.35:
                x_ranges[number] = (0, width)
                continue
            previous_mid = (q_centers[row[pos - 1]] + q_centers[number]) / 2 if pos > 0 else 0
            next_mid = (q_centers[number] + q_centers[row[pos + 1]]) / 2 if pos + 1 < len(row) else width
            x_ranges[number] = (max(0, previous_mid - 8), min(width, next_mid + 8))

    regions: dict[int, list[tuple[float, float, float, float]]] = {}
    for number, q_labels in groups.items():
        x0, x1 = x_ranges[number]
        top = max(0, min(label.top for label in q_labels) - 18)
        below: list[float] = []
        for other_number, other_top in q_tops.items():
            if other_number == number or other_top <= top + 55:
                continue
            other_x0, other_x1 = x_ranges[other_number]
            if max(x0, other_x0) < min(x1, other_x1):
                below.append(other_top)
        bottom = min(below) - 8 if below else height - 32
        if bottom - top >= 40:
            regions.setdefault(number, []).append((x0, top, x1, min(height, bottom)))
    return regions


def save_crop(
    rendered: Image.Image,
    region: tuple[float, float, float, float],
    scale: float,
    target: Path,
) -> None:
    x0, top, x1, bottom = region
    box = (
        max(0, int(x0 * scale)),
        max(0, int(top * scale)),
        min(rendered.width, int(x1 * scale)),
        min(rendered.height, int(bottom * scale)),
    )
    if box[2] - box[0] < 40 or box[3] - box[1] < 40:
        return
    cropped = rendered.crop(box)
    target.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(target, optimize=True)


def extract_images(
    pdf_path: Path,
    year: str,
    question_end_page: int,
    media_root: Path,
    valid_numbers: set[int],
    scale: float = 2.0,
) -> dict[int, list[str]]:
    image_urls: dict[int, list[str]] = {}
    pdf_render = pdfium.PdfDocument(str(pdf_path))
    media_year = media_root / year
    if media_year.exists():
        shutil.rmtree(media_year)
    media_year.mkdir(parents=True, exist_ok=True)

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index in range(question_end_page + 1, len(pdf.pages) + 1):
            page = pdf.pages[page_index - 1]
            if not page.images:
                continue
            labels = detect_labels(page, valid_numbers)
            if not labels:
                continue
            regions = crop_regions_for_page(page, labels)
            if not regions:
                continue
            rendered = pdf_render[page_index - 1].render(scale=scale).to_pil()
            for number, number_regions in sorted(regions.items()):
                for region_index, region in enumerate(number_regions, start=1):
                    target = media_year / f"q-{number:03d}-p{page_index:02d}-{region_index}.png"
                    save_crop(rendered, region, scale, target)
                    if target.exists():
                        image_urls.setdefault(number, []).append(f"/media/nuclear/{year}/{target.name}")
    return image_urls


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
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
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                self_mark TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );
            """
        )
        question_columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        if "images" not in question_columns:
            conn.execute("ALTER TABLE questions ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
        attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()}
        if "self_mark" not in attempt_columns:
            conn.execute("ALTER TABLE attempts ADD COLUMN self_mark TEXT NOT NULL DEFAULT ''")
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam);
            CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
            CREATE INDEX IF NOT EXISTS idx_attempts_question_id ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at);
            """
        )


def backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = APP_DIR / "backups" / f"before-nuclear-import-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def import_questions(db_path: Path, questions: list[Question], replace: bool) -> None:
    init_db(db_path)
    timestamp = now_iso()
    with sqlite3.connect(db_path) as conn:
        if replace:
            question_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM questions WHERE exam = ?",
                    (EXAM_NAME,),
                ).fetchall()
            ]
            if question_ids:
                placeholders = ",".join("?" for _ in question_ids)
                conn.execute(f"DELETE FROM attempts WHERE question_id IN ({placeholders})", question_ids)
                conn.execute(f"DELETE FROM questions WHERE id IN ({placeholders})", question_ids)
        for item in questions:
            conn.execute(
                """
                INSERT INTO questions
                    (exam, year, category, question, choices, images, answer, explanation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    EXAM_NAME,
                    item.year,
                    item.category,
                    f"問{item.number}\n{item.stem}",
                    json.dumps(item.choices, ensure_ascii=False),
                    json.dumps(item.images, ensure_ascii=False),
                    "",
                    "",
                    timestamp,
                    timestamp,
                ),
            )


def collect_pdfs(pdf_dir: Path) -> list[Path]:
    paths = sorted(pdf_dir.glob("*.pdf"), key=lambda item: item.name)
    if not paths:
        raise FileNotFoundError(f"PDFが見つかりません: {pdf_dir}")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Import nuclear medicine specialist past exam PDFs.")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--replace", action="store_true", help="Replace existing nuclear medicine questions.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and crop images without changing the database.")
    args = parser.parse_args()

    pdf_paths = collect_pdfs(args.pdf_dir)
    all_questions: list[Question] = []
    report: list[dict] = []
    for pdf_path in pdf_paths:
        questions, end_page = parse_questions(pdf_path)
        images = extract_images(
            pdf_path,
            pdf_path.stem,
            end_page,
            args.media_root,
            {item.number for item in questions},
        )
        for question in questions:
            question.images = images.get(question.number, [])
        all_questions.extend(questions)
        report.append(
            {
                "year": pdf_path.stem,
                "questions": len(questions),
                "image_questions": sum(1 for item in questions if item.images),
                "images": sum(len(item.images) for item in questions),
                "last_question_page": end_page,
            }
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    backup = backup_db(args.db)
    if backup:
        print(f"backup: {backup}")
    import_questions(args.db, all_questions, replace=args.replace)
    print(f"imported: {len(all_questions)} questions into {args.db}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
