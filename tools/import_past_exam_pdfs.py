#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from field_classifier import classify_question


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_EXAM = "放射線診断専門医認定試験"

QUESTION_START_RE = re.compile(r"(?m)^\s*(\d{1,3})\s*$")
CHOICE_START_RE = re.compile(r"(?m)^\s*([a-e])[\.)．、，:：]?\s+")
PAGE_MARK_RE = re.compile(r"[―-]\s*\d{1,3}\s*[―-]")
RADIONUCLIDE_MASS_NUMBERS = {11, 13, 15, 18, 67, 68, 81, 99, 111, 123, 125, 131, 133, 201}
CAPTION_START_RE = re.compile(
    r"^(?:"
    r"T1|T2|FLAIR|CT|MRI|PET|MIP|HRCT|ADC|VR|"
    r"単純|造影|脂肪|横断|冠状|矢状|前面|後面|短軸|水平|垂直|"
    r"門脈|平衡|動脈|肝細胞|画像|病変部|透視|血管|後前像|左側面像|"
    r"矢状断像|横断像|冠状断像|前面像|後面像|融合画像|レノグラム|赤は"
    r")"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require_pypdf():
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        print("pypdf が見つかりません。先に `python -m pip install pypdf` を実行してください。", file=sys.stderr)
        raise SystemExit(2)
    return PdfReader


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
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions(exam);
            CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
            CREATE INDEX IF NOT EXISTS idx_attempts_question_id ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created_at ON attempts(created_at);
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        if "images" not in columns:
            conn.execute("ALTER TABLE questions ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")


def expand_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            paths.extend(Path(item) for item in matches)
        else:
            paths.append(Path(pattern))
    return sorted({path.resolve() for path in paths}, key=lambda item: item.name)


def read_pdf_pages(pdf_path: Path) -> list[str]:
    PdfReader = require_pypdf()
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def require_crop_tools():
    try:
        import pdfplumber  # type: ignore
        import pypdfium2 as pdfium  # type: ignore
    except ImportError as exc:
        print("PDFの図切り抜きには pdfplumber と pypdfium2 が必要です。", file=sys.stderr)
        raise SystemExit(2) from exc

    return pdfplumber, pdfium


def object_bbox(item: dict) -> tuple[float, float, float, float] | None:
    try:
        x0 = float(item["x0"])
        top = float(item["top"])
        x1 = float(item["x1"])
        bottom = float(item["bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    if x1 <= x0 or bottom <= top:
        return None
    return x0, top, x1, bottom


def union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def horizontal_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return horizontal_overlap(a, b) > 0 and max(a[1], b[1]) < min(a[3], b[3])


def find_question_positions(pdf_path: Path, max_question_number: int = 200) -> dict[int, dict[str, float | int]]:
    pdfplumber, _ = require_crop_tools()
    positions: dict[int, dict[str, float | int]] = {}
    page_heights: dict[int, float] = {}
    expected = 1

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            page_heights[page_index] = float(page.height)
            words = page.extract_words() or []
            candidates = []
            for word in words:
                text = unicodedata.normalize("NFKC", str(word.get("text", ""))).strip()
                if not re.fullmatch(r"\d{1,3}", text):
                    continue
                if float(word.get("x0", 999)) > 95:
                    continue
                candidates.append((float(word["top"]), int(text), word))

            for _, number, word in sorted(candidates, key=lambda item: item[0]):
                if number != expected:
                    continue
                positions[number] = {
                    "page": page_index,
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                    "page_height": float(page.height),
                    "page_width": float(page.width),
                }
                expected += 1
                if expected > max_question_number:
                    break
            if expected > max_question_number:
                break

    for number, position in positions.items():
        next_position = positions.get(number + 1)
        same_page = next_position and next_position["page"] == position["page"]
        if same_page:
            position["end_top"] = max(float(position["bottom"]) + 12, float(next_position["top"]) - 8)
        else:
            position["end_top"] = page_heights.get(int(position["page"]), float(position["page_height"])) - 28

    return positions


def caption_boxes_below_images(page, image_boxes: list[tuple[float, float, float, float]], span_bottom: float) -> list[tuple[float, float, float, float]]:
    words = page.extract_words() or []
    boxes: list[tuple[float, float, float, float]] = []
    for word in words:
        word_box = object_bbox(word)
        if word_box is None:
            continue
        for image_box in image_boxes:
            if word_box[1] < image_box[3] - 2:
                continue
            if word_box[1] > min(span_bottom, image_box[3] + 36):
                continue
            if horizontal_overlap(word_box, (image_box[0] - 24, image_box[1], image_box[2] + 24, image_box[3])) <= 0:
                continue
            boxes.append(word_box)
            break
    return boxes


def nearby_vector_words(page, visual_box: tuple[float, float, float, float], span_top: float, span_bottom: float) -> list[tuple[float, float, float, float]]:
    expanded = (
        max(0, visual_box[0] - 32),
        max(span_top, visual_box[1] - 42),
        min(float(page.width), visual_box[2] + 32),
        min(span_bottom, visual_box[3] + 36),
    )
    boxes: list[tuple[float, float, float, float]] = []
    for word in page.extract_words() or []:
        word_box = object_bbox(word)
        if word_box is None:
            continue
        if word_box[1] < span_top or word_box[3] > span_bottom:
            continue
        if bbox_intersects(word_box, expanded):
            boxes.append(word_box)
    return boxes


def question_visual_bbox(page, position: dict[str, float | int]) -> tuple[float, float, float, float] | None:
    span_top = float(position["top"])
    span_bottom = float(position["end_top"])
    image_boxes = []
    for image in page.images:
        box = object_bbox(image)
        if box is None:
            continue
        center_y = (box[1] + box[3]) / 2
        if span_top <= center_y <= span_bottom:
            image_boxes.append(box)

    if image_boxes:
        boxes = image_boxes + caption_boxes_below_images(page, image_boxes, span_bottom)
        visual_box = union_bbox(boxes)
    else:
        shape_boxes: list[tuple[float, float, float, float]] = []
        for collection_name in ("rects", "lines", "curves"):
            for item in getattr(page, collection_name):
                box = object_bbox(item)
                if box is None:
                    continue
                width = box[2] - box[0]
                height = box[3] - box[1]
                center_y = (box[1] + box[3]) / 2
                if box[0] < 95:
                    continue
                if not (span_top <= center_y <= span_bottom):
                    continue
                if width < 16 and height < 16:
                    continue
                shape_boxes.append(box)
        initial_box = union_bbox(shape_boxes)
        if initial_box is None:
            return None
        visual_box = union_bbox(shape_boxes + nearby_vector_words(page, initial_box, span_top, span_bottom))

    if visual_box is None:
        return None

    margin = 8
    x0 = max(0.0, visual_box[0] - margin)
    top = max(span_top, visual_box[1] - margin)
    x1 = min(float(page.width), visual_box[2] + margin)
    bottom = min(span_bottom, visual_box[3] + margin)
    if x1 - x0 < 32 or bottom - top < 32:
        return None
    return x0, top, x1, bottom


def render_question_media(
    pdf_path: Path,
    media_dir: Path,
    year: str,
    image_url_prefix: str,
    dpi: int,
    positions: dict[int, dict[str, float | int]],
) -> dict[int, str]:
    pdfplumber, pdfium = require_crop_tools()
    target_dir = media_dir / year
    target_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    mapping: dict[int, str] = {}

    page_to_questions: dict[int, list[int]] = {}
    for number, position in positions.items():
        page_to_questions.setdefault(int(position["page"]), []).append(number)

    pdf_doc = pdfium.PdfDocument(str(pdf_path))
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, question_numbers in page_to_questions.items():
            if page_number < 1 or page_number > len(pdf.pages):
                continue
            plumber_page = pdf.pages[page_number - 1]
            pdfium_page = pdf_doc[page_number - 1]
            bitmap = pdfium_page.render(scale=scale)
            page_image = bitmap.to_pil().convert("RGB")
            for question_number in question_numbers:
                visual_box = question_visual_bbox(plumber_page, positions[question_number])
                if visual_box is None:
                    continue
                crop_box = tuple(max(0, int(round(value * scale))) for value in visual_box)
                crop_box = (
                    max(0, crop_box[0]),
                    max(0, crop_box[1]),
                    min(page_image.width, crop_box[2]),
                    min(page_image.height, crop_box[3]),
                )
                if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                    continue
                image_path = target_dir / f"q-{question_number:03d}.png"
                page_image.crop(crop_box).save(image_path, optimize=True)
                mapping[question_number] = f"{image_url_prefix.rstrip('/')}/{year}/{image_path.name}"

    return mapping


def render_pages(pdf_path: Path, media_dir: Path, year: str, image_url_prefix: str, dpi: int) -> dict[int, str]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        runtime_bin = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "bin" / "pdftoppm.exe"
        if runtime_bin.exists():
            pdftoppm = str(runtime_bin)
    if not pdftoppm:
        try:
            import pypdfium2 as pdfium  # type: ignore
        except ImportError:
            print(f"PDFページ画像化ツールが見つからないため画像レンダリングをスキップします: {pdf_path.name}", file=sys.stderr)
            return {}

        target_dir = media_dir / year
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf = pdfium.PdfDocument(str(pdf_path))
        scale = dpi / 72
        mapping: dict[int, str] = {}
        for index in range(len(pdf)):
            page_number = index + 1
            image_path = target_dir / f"page-{page_number:03d}.png"
            page = pdf[index]
            bitmap = page.render(scale=scale)
            bitmap.to_pil().save(image_path)
            mapping[page_number] = f"{image_url_prefix.rstrip('/')}/{year}/{image_path.name}"
        return mapping

    target_dir = media_dir / year
    target_dir.mkdir(parents=True, exist_ok=True)
    prefix = target_dir / "page"
    subprocess.run(
        [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    mapping: dict[int, str] = {}
    for image_path in sorted(target_dir.glob("page-*.png")):
        match = re.search(r"page-(\d+)\.png$", image_path.name)
        if not match:
            continue
        page_number = int(match.group(1))
        mapping[page_number] = f"{image_url_prefix.rstrip('/')}/{year}/{image_path.name}"
    return mapping


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u0002", "-").replace("\r\n", "\n").replace("\r", "\n")
    text = PAGE_MARK_RE.sub("\n", text)
    text = re.sub(r"\[page \d+\]", "\n", text)
    text = re.sub(r"(?<=日本医学放射線学会)(?=\d{1,3}\s)", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def compact_lines(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def previous_nonempty_line(text: str, position: int) -> str:
    before = text[:position].rstrip()
    if not before:
        return ""
    return before.rsplit("\n", 1)[-1].strip()


def is_question_start_candidate(text: str, match: re.Match[str]) -> bool:
    previous = previous_nonempty_line(text, match.start())
    number = int(match.group(1))
    if number in RADIONUCLIDE_MASS_NUMBERS and re.fullmatch(r"[a-e][\.)．、，:：]?", previous):
        return False
    return True


def looks_like_caption(line: str) -> bool:
    return bool(CAPTION_START_RE.search(line.strip()))


def split_last_choice_and_tail(block: str) -> tuple[str, str]:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return "", ""

    choice_lines = [lines[0]]
    tail_lines: list[str] = []
    for line in lines[1:]:
        if tail_lines:
            tail_lines.append(line)
            continue
        if looks_like_caption(line):
            tail_lines.append(line)
            continue
        if choice_lines[-1].endswith(("。", ".", "?", "？")):
            tail_lines.append(line)
            continue
        choice_lines.append(line)

    return " ".join(choice_lines), "\n".join(tail_lines)


def parse_choices(segment: str) -> tuple[str, list[str], str]:
    matches = list(CHOICE_START_RE.finditer(segment))
    if len(matches) < 2:
        return segment.strip(), [], ""

    stem = segment[: matches[0].start()].strip()
    choices: list[str] = []
    tail = ""

    for index, match in enumerate(matches):
        label = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
        block = segment[start:end].strip()
        if index + 1 == len(matches):
            choice_text, tail = split_last_choice_and_tail(block)
        else:
            choice_text = " ".join(line.strip() for line in block.splitlines() if line.strip())
        choices.append(f"{label}. {choice_text or '画像参照'}")

    return stem, choices, tail.strip()


def parse_questions(
    pdf_path: Path,
    exam: str,
    category: str,
    media_dir: Path | None = None,
    image_url_prefix: str = "/media",
    render_images: bool = False,
    dpi: int = 120,
) -> list[dict]:
    year_match = re.search(r"(20\d{2})", pdf_path.stem)
    year = year_match.group(1) if year_match else pdf_path.stem
    pages = read_pdf_pages(pdf_path)
    positions = find_question_positions(pdf_path)
    question_images = (
        render_question_media(pdf_path, media_dir, year, image_url_prefix, dpi, positions)
        if render_images and media_dir
        else {}
    )
    text_parts = []
    for page_index, page_text in enumerate(pages, start=1):
        text_parts.append(f"\n\n[[PAGE:{page_index}]]\n{page_text}")
    text = compact_lines(clean_text("\n".join(text_parts)))

    starts = []
    expected_number = 1
    for match in QUESTION_START_RE.finditer(text):
        if not is_question_start_candidate(text, match):
            continue
        number = int(match.group(1))
        if number == expected_number:
            starts.append(match)
            expected_number += 1
        elif number > 200:
            continue
    questions: list[dict] = []
    for index, start in enumerate(starts):
        number = int(start.group(1))
        if number < 1 or number > 200:
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        segment = re.sub(r"\[\[PAGE:\d+\]\]", "\n", text[start.end() : end]).strip()
        stem, choices, tail = parse_choices(segment)
        if len(choices) < 2:
            continue

        page_marker = list(re.finditer(r"\[\[PAGE:(\d+)\]\]", text[: start.start()]))
        page_number = int(positions.get(number, {}).get("page") or (page_marker[-1].group(1) if page_marker else 0)) or None
        images = [question_images[number]] if number in question_images else []

        question_text = f"問{number}\n{stem}"
        field = category if category and category != "過去問" else classify_question(question_text, year, number)

        questions.append(
            {
                "exam": exam,
                "year": year,
                "category": field,
                "question": question_text.strip(),
                "choices": choices,
                "images": images,
                "answer": "",
                "explanation": f"出典: {pdf_path.name} / 問{number}" + (f" / p.{page_number}" if page_number else ""),
                "source_file": pdf_path.name,
                "source_question_number": number,
                "source_page": page_number,
            }
        )

    return questions


def import_questions(db_path: Path, questions: list[dict], replace_years: bool) -> tuple[int, int]:
    init_db(db_path)
    timestamp = now_iso()
    inserted = 0
    skipped = 0

    with sqlite3.connect(db_path) as conn:
        if replace_years:
            targets = sorted({(item["exam"], item["year"]) for item in questions})
            for exam, year in targets:
                conn.execute("DELETE FROM questions WHERE exam = ? AND year = ?", (exam, year))

        for item in questions:
            exists = conn.execute(
                "SELECT 1 FROM questions WHERE exam = ? AND year = ? AND question = ? LIMIT 1",
                (item["exam"], item["year"], item["question"]),
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
                    item["exam"],
                    item["year"],
                    item["category"],
                    item["question"],
                    json.dumps(item["choices"], ensure_ascii=False),
                    json.dumps(item.get("images", []), ensure_ascii=False),
                    item.get("answer", ""),
                    item.get("explanation", ""),
                    timestamp,
                    timestamp,
                ),
            )
            inserted += 1

    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Import past-exam PDFs into Kakomon Trainer")
    parser.add_argument("pdfs", nargs="+", help="PDF paths or glob patterns")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--exam", default=DEFAULT_EXAM, help="Exam name")
    parser.add_argument("--category", default="過去問", help="Category name")
    parser.add_argument("--replace-year", action="store_true", help="Delete existing questions for imported years first")
    parser.add_argument("--json", dest="json_path", help="Also write extracted questions to this JSON file")
    parser.add_argument("--render-images", action="store_true", help="Render PDF pages to PNG and attach page images to questions")
    parser.add_argument("--media-dir", default=str(APP_DIR / "static" / "media"), help="Output directory for rendered page images")
    parser.add_argument("--image-url-prefix", default="/media", help="URL prefix for rendered images")
    parser.add_argument("--dpi", type=int, default=120, help="DPI for page rendering")
    args = parser.parse_args()

    pdf_paths = expand_paths(args.pdfs)
    missing = [path for path in pdf_paths if not path.exists()]
    if missing:
        for path in missing:
            print(f"PDFが見つかりません: {path}", file=sys.stderr)
        raise SystemExit(1)

    all_questions: list[dict] = []
    for pdf_path in pdf_paths:
        questions = parse_questions(
            pdf_path,
            args.exam,
            args.category,
            media_dir=Path(args.media_dir).resolve(),
            image_url_prefix=args.image_url_prefix,
            render_images=args.render_images,
            dpi=args.dpi,
        )
        print(f"{pdf_path.name}: {len(questions)} questions")
        all_questions.extend(questions)

    if args.json_path:
        json_path = Path(args.json_path).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"questions": all_questions}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {json_path}")

    inserted, skipped = import_questions(Path(args.db).resolve(), all_questions, args.replace_year)
    print(f"DB: {Path(args.db).resolve()}")
    print(f"Inserted: {inserted}, skipped: {skipped}, total extracted: {len(all_questions)}")


if __name__ == "__main__":
    main()
