#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_PDF_DIR = APP_DIR / "static" / "source-pdfs" / "nuclear"
DEFAULT_MEDIA_ROOT = APP_DIR / "static" / "media" / "nuclear"
EXAM_NAME = "核医学専門医試験"

NUMBER_TOKEN_RE = re.compile(r"^0?([1-9]\d?)(?:[-‐‑‒–—ー−]\d+)?$")
NO_TOKEN_RE = re.compile(r"^No\.?\s*([1-9]\d?)(?:[-‐‑‒–—ー−]\d+)?$", re.IGNORECASE)
IMAGE_CUE_RE = re.compile(r"別紙|画像|図|写真|呈示|示す")
MEDIA_PAGE_RE = re.compile(r"-p(\d+)-(\d+)\.png$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True)
class Label:
    number: int
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class QuestionRow:
    question_id: int
    year: str
    number: int
    question: str
    images: list[str]


@dataclass
class Repair:
    question: QuestionRow
    page: int
    region: tuple[float, float, float, float]
    url: str


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    return text.replace("\u00a0", " ").replace("\u3000", " ").strip()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_commands() -> None:
    missing = [name for name in ("pdfinfo", "pdftotext", "pdftoppm") if not shutil.which(name)]
    if missing:
        raise RuntimeError(f"必要なコマンドが見つかりません: {', '.join(missing)}")


def run_text(args: list[str]) -> str:
    result = subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout


def page_count(pdf_path: Path) -> int:
    output = run_text(["pdfinfo", str(pdf_path)])
    match = re.search(r"Pages:\s+(\d+)", output)
    if not match:
        raise ValueError(f"PDFページ数を読めません: {pdf_path}")
    return int(match.group(1))


def parse_question_number(question: str) -> int | None:
    match = re.search(r"問\s*(\d{1,2})", question or "")
    return int(match.group(1)) if match else None


def load_questions(db_path: Path) -> list[QuestionRow]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, year, question, images
            FROM questions
            WHERE exam = ?
            ORDER BY year, id
            """,
            (EXAM_NAME,),
        ).fetchall()

    questions: list[QuestionRow] = []
    for row in rows:
        number = parse_question_number(row["question"])
        if number is None:
            continue
        try:
            images = json.loads(row["images"] or "[]")
        except json.JSONDecodeError:
            images = []
        questions.append(
            QuestionRow(
                question_id=int(row["id"]),
                year=str(row["year"]),
                number=number,
                question=str(row["question"] or ""),
                images=[str(item) for item in images if str(item).strip()],
            )
        )
    return questions


def existing_media_pages(media_root: Path, year: str) -> set[int]:
    pages: set[int] = set()
    year_dir = media_root / year
    if not year_dir.exists():
        return pages
    for path in year_dir.glob("q-*-p*-*.png"):
        match = MEDIA_PAGE_RE.search(path.name)
        if match:
            pages.add(int(match.group(1)))
    return pages


def image_pages(images: list[str]) -> set[int]:
    pages: set[int] = set()
    for image in images:
        match = MEDIA_PAGE_RE.search(Path(image).name)
        if match:
            pages.add(int(match.group(1)))
    return pages


def read_page_words(pdf_path: Path, page: int) -> tuple[list[Word], float, float]:
    xml = run_text(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", str(pdf_path), "-"])
    root = ET.fromstring(xml)
    namespace = {"x": "http://www.w3.org/1999/xhtml"}
    page_el = root.find(".//x:page", namespace)
    if page_el is None:
        return [], 0.0, 0.0
    width = float(page_el.attrib["width"])
    height = float(page_el.attrib["height"])
    words: list[Word] = []
    for word_el in page_el.findall(".//x:word", namespace):
        words.append(
            Word(
                text=normalize("".join(word_el.itertext())),
                x0=float(word_el.attrib["xMin"]),
                top=float(word_el.attrib["yMin"]),
                x1=float(word_el.attrib["xMax"]),
                bottom=float(word_el.attrib["yMax"]),
            )
        )
    words.sort(key=lambda item: (item.top, item.x0))
    return words, width, height


def label_from_no_word(words: list[Word], index: int) -> Label | None:
    base = words[index]
    for word in words[index + 1 : index + 8]:
        if word.top - base.top > 90:
            break
        match = NUMBER_TOKEN_RE.match(word.text)
        if not match:
            continue
        same_line = abs(word.top - base.top) <= 14 and -5 <= word.x0 - base.x1 < 90
        stacked = abs(word.x0 - base.x0) < 35 and 0 < word.top - base.top < 80
        if same_line or stacked:
            return Label(
                number=int(match.group(1)),
                x0=min(base.x0, word.x0),
                top=min(base.top, word.top),
                x1=max(base.x1, word.x1),
                bottom=max(base.bottom, word.bottom),
            )
    return None


def detect_labels(pdf_path: Path, page: int) -> tuple[list[Label], float, float]:
    words, width, height = read_page_words(pdf_path, page)
    labels: list[Label] = []
    for index, word in enumerate(words):
        if word.top < 8 or word.top > height - 70:
            continue
        no_match = NO_TOKEN_RE.match(word.text)
        if no_match:
            labels.append(Label(int(no_match.group(1)), word.x0, word.top, word.x1, word.bottom))
            continue
        if word.text.lower() in {"no", "no."}:
            label = label_from_no_word(words, index)
            if label:
                labels.append(label)
            continue
        number_match = NUMBER_TOKEN_RE.match(word.text)
        if not number_match:
            continue
        number = int(number_match.group(1))
        if number < 20 or number > 60:
            continue
        if word.height < 18 or word.x0 > 220:
            continue
        labels.append(Label(number, word.x0, word.top, word.x1, word.bottom))

    labels.sort(key=lambda item: (item.number, item.top, item.x0))
    deduped: list[Label] = []
    for label in labels:
        if any(
            kept.number == label.number and abs(kept.top - label.top) < 35 and abs(kept.x0 - label.x0) < 90
            for kept in deduped
        ):
            continue
        deduped.append(label)
    return sorted(deduped, key=lambda item: (item.top, item.x0, item.number)), width, height


def crop_regions_for_page(
    width: float,
    height: float,
    labels: list[Label],
) -> dict[int, tuple[float, float, float, float]]:
    groups: dict[int, list[Label]] = {}
    for label in labels:
        groups.setdefault(label.number, []).append(label)
    if not groups:
        return {}

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
            q_labels = groups[number]
            min_x = min(label.x0 for label in q_labels)
            max_x = max(label.x1 for label in q_labels)
            if len(row) == 1 or max_x - min_x > width * 0.35:
                x_ranges[number] = (0, width)
                continue
            previous_mid = (q_centers[row[pos - 1]] + q_centers[number]) / 2 if pos > 0 else 0
            next_mid = (q_centers[number] + q_centers[row[pos + 1]]) / 2 if pos + 1 < len(row) else width
            x_ranges[number] = (max(0, previous_mid - 8), min(width, next_mid + 8))

    regions: dict[int, tuple[float, float, float, float]] = {}
    for number in groups:
        x0, x1 = x_ranges[number]
        top = max(0, min(label.top for label in groups[number]) - 18)
        below: list[float] = []
        for other_number, other_top in q_tops.items():
            if other_number == number or other_top <= top + 55:
                continue
            other_x0, other_x1 = x_ranges[other_number]
            if max(x0, other_x0) < min(x1, other_x1):
                below.append(other_top)
        bottom = min(below) - 8 if below else height - 28
        if bottom - top >= 40:
            regions[number] = (x0, top, x1, min(height, bottom))
    return regions


def collect_repairs(
    db_path: Path,
    pdf_dir: Path,
    media_root: Path,
) -> list[Repair]:
    questions = load_questions(db_path)
    by_year_number = {(question.year, question.number): question for question in questions}
    repairs: list[Repair] = []

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        year = pdf_path.stem
        year_questions = [question for question in questions if question.year == year]
        if not year_questions:
            continue
        first_media_page = min(existing_media_pages(media_root, year), default=1)
        page_labels: dict[int, list[Label]] = {}
        page_sizes: dict[int, tuple[float, float]] = {}
        label_pages_by_number: dict[int, set[int]] = {}
        for page in range(first_media_page, page_count(pdf_path) + 1):
            labels, width, height = detect_labels(pdf_path, page)
            if not labels:
                continue
            page_labels[page] = labels
            page_sizes[page] = (width, height)
            for label in labels:
                if (year, label.number) in by_year_number:
                    label_pages_by_number.setdefault(label.number, set()).add(page)

        for number, pages in sorted(label_pages_by_number.items()):
            question = by_year_number[(year, number)]
            existing_pages = image_pages(question.images)
            missing_pages = sorted(pages - existing_pages)
            if not missing_pages:
                continue
            if question.images and len(existing_pages) < len(pages):
                should_repair = True
            else:
                should_repair = not question.images and bool(IMAGE_CUE_RE.search(question.question))
            if not should_repair:
                continue
            for page in missing_pages:
                width, height = page_sizes[page]
                regions = crop_regions_for_page(width, height, page_labels[page])
                region = regions.get(number)
                if not region:
                    continue
                filename = f"q-{number:03d}-p{page:02d}-1.png"
                repairs.append(
                    Repair(
                        question=question,
                        page=page,
                        region=region,
                        url=f"/media/nuclear/{year}/{filename}",
                    )
                )
    return repairs


def render_page(pdf_path: Path, page: int, dpi: int, tmpdir: Path) -> Image.Image:
    prefix = tmpdir / f"page-{page:03d}"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(dpi),
            "-png",
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Image.open(prefix.with_suffix(".png")).convert("RGB")


def save_crop(pdf_path: Path, repair: Repair, media_root: Path, dpi: int, tmpdir: Path) -> Path:
    image = render_page(pdf_path, repair.page, dpi, tmpdir)
    labels, width, height = detect_labels(pdf_path, repair.page)
    del labels
    scale_x = image.width / width
    scale_y = image.height / height
    x0, top, x1, bottom = repair.region
    box = (
        max(0, int(x0 * scale_x)),
        max(0, int(top * scale_y)),
        min(image.width, int(x1 * scale_x)),
        min(image.height, int(bottom * scale_y)),
    )
    if box[2] - box[0] < 40 or box[3] - box[1] < 40:
        raise ValueError(f"切り出し範囲が小さすぎます: {repair.url}")
    target = media_root / repair.question.year / Path(repair.url).name
    target.parent.mkdir(parents=True, exist_ok=True)
    image.crop(box).save(target, optimize=True)
    return target


def sort_image_urls(urls: list[str]) -> list[str]:
    def key(url: str) -> tuple[int, int, str]:
        match = MEDIA_PAGE_RE.search(Path(url).name)
        if not match:
            return (9999, 9999, url)
        return (int(match.group(1)), int(match.group(2)), url)

    return sorted(dict.fromkeys(urls), key=key)


def backup_db(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = APP_DIR / "backups" / f"before-nuclear-image-repair-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def apply_repairs(db_path: Path, pdf_dir: Path, media_root: Path, repairs: list[Repair], dpi: int) -> list[dict]:
    by_pdf = {path.stem: path for path in pdf_dir.glob("*.pdf")}
    generated: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nuclear-image-repair-") as tmp:
        tmpdir = Path(tmp)
        for repair in repairs:
            pdf_path = by_pdf[repair.question.year]
            target = save_crop(pdf_path, repair, media_root, dpi, tmpdir)
            generated.append(
                {
                    "id": repair.question.question_id,
                    "year": repair.question.year,
                    "number": repair.question.number,
                    "page": repair.page,
                    "url": repair.url,
                    "file": str(target),
                }
            )

    timestamp = now_iso()
    by_question: dict[int, list[str]] = {}
    for repair in repairs:
        by_question.setdefault(repair.question.question_id, [])
        by_question[repair.question.question_id].append(repair.url)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for question_id, new_urls in by_question.items():
            row = conn.execute("SELECT images FROM questions WHERE id = ?", (question_id,)).fetchone()
            if row is None:
                continue
            try:
                current = json.loads(row["images"] or "[]")
            except json.JSONDecodeError:
                current = []
            images = sort_image_urls([str(item) for item in current if str(item).strip()] + new_urls)
            conn.execute(
                "UPDATE questions SET images = ?, updated_at = ? WHERE id = ?",
                (json.dumps(images, ensure_ascii=False), timestamp, question_id),
            )
        conn.commit()
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair missing nuclear medicine question images from source PDFs.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--dry-run", action="store_true", help="Show missing images without writing files or DB changes.")
    args = parser.parse_args()

    ensure_commands()
    if not args.db.exists():
        raise FileNotFoundError(f"DBが見つかりません: {args.db}")
    if not args.pdf_dir.exists():
        raise FileNotFoundError(f"PDFフォルダが見つかりません: {args.pdf_dir}")

    repairs = collect_repairs(args.db, args.pdf_dir, args.media_root)
    report = [
        {
            "id": repair.question.question_id,
            "year": repair.question.year,
            "number": repair.question.number,
            "page": repair.page,
            "url": repair.url,
        }
        for repair in repairs
    ]
    print(json.dumps({"repairs": report, "count": len(report)}, ensure_ascii=False, indent=2))
    if args.dry_run or not repairs:
        if args.dry_run:
            print("--dry-run のため変更しません。")
        return 0

    backup = backup_db(args.db)
    if backup:
        print(f"backup: {backup}")
    generated = apply_repairs(args.db, args.pdf_dir, args.media_root, repairs, args.dpi)
    print(json.dumps({"generated": generated, "count": len(generated)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
