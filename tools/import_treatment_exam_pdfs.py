#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from pdfminer.cmapdb import CMapDB


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_MEDIA_ROOT = APP_DIR / "static" / "media" / "treatment"
EXAM_NAME = "放射線治療専門医認定試験"

QSTART_RE = re.compile(r"^\s*0?([1-9]\d?|100)[.．\s]+(.+)$")
CHOICE_RE = re.compile(r"^\s*([a-e])[\).．]?\s*(.*)$")
YEAR_RE = re.compile(r"(20\d{2})")
GREEK_SYMBOLS = {"α", "β", "γ"}
LATIN_CONFUSION_CHARS = {"き": "u", "が": "t", "か": "s", "お": "r"}
ADOBE_JAPAN1_MAP = None


@dataclass
class Line:
    page: int
    text: str
    x0: float
    top: float
    bottom: float
    page_width: float
    page_height: float


@dataclass
class ParsedQuestion:
    year: str
    number: int
    stem: str
    choices: list[str]
    category: str
    images: list[str]
    source_file: str
    source_page: int


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    return value


def clean_text(text: str) -> str:
    value = normalize(text)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+([,.;:、。，．)])", r"\1", value)
    value = re.sub(r"([\(（])\s+", r"\1", value)
    value = re.sub(r"([ぁ-んァ-ン一-龥])\s+([ぁ-んァ-ン一-龥])", r"\1\2", value)
    value = value.replace("1 つ", "1つ").replace("2 つ", "2つ")
    return value


def adobe_japan1_unichr(cid: int) -> str | None:
    global ADOBE_JAPAN1_MAP
    if ADOBE_JAPAN1_MAP is None:
        ADOBE_JAPAN1_MAP = CMapDB.get_unicode_map("Adobe-Japan1", vertical=False)
    try:
        return ADOBE_JAPAN1_MAP.get_unichr(cid)
    except Exception:
        return None


def nearby_nonspace(text: str, index: int, step: int) -> str:
    cursor = index + step
    while 0 <= cursor < len(text):
        if not text[cursor].isspace():
            return text[cursor]
        cursor += step
    return ""


def should_keep_greek_symbol(text: str, index: int, char: str) -> bool:
    if char not in GREEK_SYMBOLS:
        return False
    previous = nearby_nonspace(text, index, -1)
    following = nearby_nonspace(text, index, 1)
    return following in {"線", "/", "値", "比", "崩", "放"} or previous in {"/", "-", "（", "("}


def repair_adobe_japan1_text(text: str) -> str:
    def replace_cid(match: re.Match[str]) -> str:
        return adobe_japan1_unichr(int(match.group(1))) or match.group(0)

    value = re.sub(r"\(cid:(\d+)\)", replace_cid, str(text))
    repaired: list[str] = []
    for index, char in enumerate(value):
        codepoint = ord(char)
        if should_keep_greek_symbol(value, index, char):
            repaired.append(char)
            continue
        mapped = None
        if (0x02A0 <= codepoint <= 0x04FF) or (0x0A00 <= codepoint <= 0x0FFF) or (0x1D00 <= codepoint <= 0x1DFF):
            mapped = adobe_japan1_unichr(codepoint)
        repaired.append(mapped or char)
    return "".join(repaired)


def repair_latin_confusion_text(text: str) -> str:
    chars = list(text)
    for index, char in enumerate(chars):
        replacement = LATIN_CONFUSION_CHARS.get(char)
        if replacement is None:
            continue
        previous = chars[index - 1] if index > 0 else ""
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if re.match(r"[A-Za-z0-9-]", previous) or re.match(r"[A-Za-z0-9-]", following):
            chars[index] = replacement
    return "".join(chars)


def repair_2016_text(text: str) -> str:
    value = repair_adobe_japan1_text(text)
    value = repair_latin_confusion_text(value)
    value = value.replace("\x8cû", "")
    return clean_text(value)


def is_2016_question_number_word(text: object) -> bool:
    value = normalize(repair_adobe_japan1_text(str(text)))
    return bool(re.fullmatch(r"[0-9０-９]{1,3}", value))


def is_2016_image_caption_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return len(compact) < 80 and bool(re.match(r"^[IⅠ|l]*[（(]?画像\d", compact))


def year_from_path(path: Path) -> str:
    match = YEAR_RE.search(path.name)
    if not match:
        raise ValueError(f"年度をファイル名から読めません: {path.name}")
    return match.group(1)


def visible_words(page) -> list[dict]:
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
        if top < 35 or top > height - 45:
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
    return re.sub(r"\s+", " ", text).strip()


def page_lines(page, page_number: int) -> list[Line]:
    rows: list[Line] = []
    for line in group_lines(visible_words(page)):
        text = line_to_text(line)
        if not text:
            continue
        if re.fullmatch(r"[―ー-]?\s*\d{1,3}\s*[―ー-]?", text):
            continue
        rows.append(
            Line(
                page=page_number,
                text=text,
                x0=min(float(item["x0"]) for item in line),
                top=min(float(item["top"]) for item in line),
                bottom=max(float(item["bottom"]) for item in line),
                page_width=float(page.width),
                page_height=float(page.height),
            )
        )
    return rows


def extract_lines(pdf_path: Path) -> list[Line]:
    rows: list[Line] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            rows.extend(page_lines(page, page_number))
    return rows


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


def nearby_words(page, visual_box: tuple[float, float, float, float], span_top: float, span_bottom: float) -> list[tuple[float, float, float, float]]:
    expanded = (
        max(0, visual_box[0] - 28),
        max(span_top, visual_box[1] - 32),
        min(float(page.width), visual_box[2] + 28),
        min(span_bottom, visual_box[3] + 32),
    )
    boxes: list[tuple[float, float, float, float]] = []
    for word in page.extract_words() or []:
        box = object_bbox(word)
        if box is None:
            continue
        if box[1] < span_top or box[3] > span_bottom:
            continue
        if bbox_intersects(box, expanded):
            boxes.append(box)
    return boxes


def visual_bbox(page, span_top: float, span_bottom: float) -> tuple[float, float, float, float] | None:
    image_boxes: list[tuple[float, float, float, float]] = []
    for image in page.images:
        box = object_bbox(image)
        if box is None:
            continue
        center_y = (box[1] + box[3]) / 2
        if span_top <= center_y <= span_bottom and box[2] - box[0] > 20 and box[3] - box[1] > 20:
            image_boxes.append(box)
    if image_boxes:
        boxes = image_boxes
        initial = union_bbox(boxes)
    else:
        boxes = []
        for collection_name in ("rects", "lines", "curves"):
            for item in getattr(page, collection_name):
                box = object_bbox(item)
                if box is None:
                    continue
                width = box[2] - box[0]
                height = box[3] - box[1]
                center_y = (box[1] + box[3]) / 2
                if not (span_top <= center_y <= span_bottom):
                    continue
                if width < 18 and height < 18:
                    continue
                if box[0] < 40:
                    continue
                boxes.append(box)
        initial = union_bbox(boxes)
        if initial is None:
            return None
        boxes.extend(nearby_words(page, initial, span_top, span_bottom))

    visual = union_bbox(boxes)
    if visual is None:
        return None
    margin = 8
    x0 = max(0.0, visual[0] - margin)
    top = max(span_top, visual[1] - margin)
    x1 = min(float(page.width), visual[2] + margin)
    bottom = min(span_bottom, visual[3] + margin)
    if x1 - x0 < 32 or bottom - top < 28:
        return None
    return x0, top, x1, bottom


def render_question_crops(
    pdf_path: Path,
    year: str,
    media_root: Path,
    image_url_prefix: str,
    spans: dict[int, list[tuple[int, float, float]]],
    *,
    full_question: bool,
    dpi: int,
) -> dict[int, list[str]]:
    media_year = media_root / year
    if media_year.exists():
        shutil.rmtree(media_year)
    media_year.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    pdf_doc = pdfium.PdfDocument(str(pdf_path))
    mapping: dict[int, list[str]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for number, page_spans in spans.items():
            for page_number, span_top, span_bottom in page_spans:
                if page_number < 1 or page_number > len(pdf.pages):
                    continue
                page = pdf.pages[page_number - 1]
                if full_question:
                    box = (
                        45.0,
                        max(35.0, span_top - 6),
                        float(page.width) - 32.0,
                        min(float(page.height) - 45.0, span_bottom - 6),
                    )
                else:
                    box = visual_bbox(page, span_top, span_bottom)
                    if box is None:
                        continue
                pdf_page = pdf_doc[page_number - 1]
                image = pdf_page.render(scale=scale).to_pil().convert("RGB")
                crop = (
                    max(0, int(round(box[0] * scale))),
                    max(0, int(round(box[1] * scale))),
                    min(image.width, int(round(box[2] * scale))),
                    min(image.height, int(round(box[3] * scale))),
                )
                if crop[2] <= crop[0] or crop[3] <= crop[1]:
                    continue
                target = media_year / f"q-{number:03d}-p{page_number:02d}.png"
                image.crop(crop).save(target, optimize=True)
                mapping.setdefault(number, []).append(f"{image_url_prefix.rstrip('/')}/{year}/{target.name}")
    return mapping


def classify_treatment(stem: str, choices: list[str]) -> str:
    text = stem + " " + " ".join(choices)
    rules = [
        ("治療計画・照射技術", ["IMRT", "VMAT", "IGRT", "PTV", "CTV", "OAR", "DVH", "DIR", "FFF", "MLC", "リニアック", "定位", "治療計画", "照射野", "線量分布", "小線源"]),
        ("基礎・物理", ["半減期", "放射能", "吸収線量", "照射線量", "電子線", "陽子線", "重粒子", "中性子", "Bragg", "PDD", "線量計", "電離箱", "ファントム", "フルエンス"]),
        ("生物・薬剤", ["細胞", "DNA", "LQ", "α/β", "再酸素化", "再増殖", "放射線感受性", "分子標的", "薬剤", "免疫", "温熱"]),
        ("安全管理・QA", ["QA", "QC", "品質", "安全", "被ばく", "防護", "医療法", "リスク", "ペースメーカ", "事故", "投与線量の確認"]),
        ("中枢神経・頭頸部", ["脳", "神経膠腫", "髄芽腫", "頭頸部", "喉頭", "上咽頭", "中咽頭", "口腔", "舌", "耳下腺", "甲状腺眼症"]),
        ("胸部・乳腺", ["肺癌", "肺がん", "食道癌", "食道がん", "乳癌", "乳がん", "縦隔", "胸部", "小細胞肺", "非小細胞肺"]),
        ("消化器", ["胃癌", "胃がん", "肝細胞", "肝癌", "膵癌", "膵がん", "胆道", "直腸", "大腸", "肛門", "腹部"]),
        ("泌尿器・婦人科", ["前立腺", "膀胱", "腎", "子宮", "頸癌", "頸がん", "体癌", "卵巣", "腟", "外陰"]),
        ("血液・小児・骨軟部", ["リンパ腫", "白血病", "小児", "神経芽腫", "腎芽腫", "横紋筋肉腫", "Ewing", "ユーイング", "骨肉腫", "軟部肉腫", "骨転移"]),
        ("緩和・良性疾患", ["緩和", "疼痛", "骨転移", "脊椎転移", "ケロイド", "良性", "血管腫"]),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "放射線治療総合"


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


def spans_from_starts(starts: list[tuple[int, Line]]) -> dict[int, list[tuple[int, float, float]]]:
    spans: dict[int, list[tuple[int, float, float]]] = {}
    for index, (number, line) in enumerate(starts):
        next_line = starts[index + 1][1] if index + 1 < len(starts) else None
        if next_line and next_line.page == line.page:
            spans[number] = [(line.page, line.top, max(line.bottom + 16, next_line.top - 8))]
        elif next_line:
            page_spans: list[tuple[int, float, float]] = [(line.page, line.top, line.page_height - 45)]
            for page_number in range(line.page + 1, next_line.page):
                page_spans.append((page_number, 35.0, line.page_height - 45))
            page_spans.append((next_line.page, 35.0, max(45.0, next_line.top - 8)))
            spans[number] = page_spans
        else:
            spans[number] = [(line.page, line.top, line.page_height - 45)]
    return spans


def parse_regular_pdf(pdf_path: Path, media_root: Path, image_url_prefix: str, dpi: int) -> list[ParsedQuestion]:
    year = year_from_path(pdf_path)
    lines = extract_lines(pdf_path)
    starts: list[tuple[int, int, Line, str]] = []
    expected = 1
    for index, line in enumerate(lines):
        match = QSTART_RE.match(line.text)
        if not match:
            continue
        number = int(match.group(1))
        if number != expected:
            continue
        starts.append((number, index, line, match.group(2).strip()))
        expected += 1

    if not starts:
        raise ValueError(f"問題番号を抽出できません: {pdf_path.name}")

    crop_spans = spans_from_starts([(number, line) for number, _, line, _ in starts])
    image_map = render_question_crops(
        pdf_path,
        year,
        media_root,
        image_url_prefix,
        crop_spans,
        full_question=False,
        dpi=dpi,
    )

    parsed: list[ParsedQuestion] = []
    for start_index, (number, line_index, line, first_text) in enumerate(starts):
        next_line_index = starts[start_index + 1][1] if start_index + 1 < len(starts) else len(lines)
        parts = [first_text]
        parts.extend(item.text for item in lines[line_index + 1 : next_line_index])
        stem, choices = split_choices(parts)
        if len(choices) != 5:
            raise ValueError(f"{pdf_path.name} 問{number}: 選択肢が5個ではありません ({len(choices)}個)")
        parsed.append(
            ParsedQuestion(
                year=year,
                number=number,
                stem=stem,
                choices=choices,
                category=classify_treatment(stem, choices),
                images=image_map.get(number, []),
                source_file=pdf_path.name,
                source_page=line.page,
            )
        )
    return parsed


def parse_2016_pdf(pdf_path: Path, media_root: Path, image_url_prefix: str, dpi: int) -> list[ParsedQuestion]:
    year = year_from_path(pdf_path)
    starts: list[tuple[int, Line]] = []
    all_lines = extract_lines(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        number = 1
        for page_number, page in enumerate(pdf.pages, start=1):
            if page_number == 1:
                continue
            for word in page.extract_words(use_text_flow=False, keep_blank_chars=False, x_tolerance=1, y_tolerance=3) or []:
                x0 = float(word["x0"])
                top = float(word["top"])
                if 60 < x0 < 70 and 35 < top < float(page.height) - 45 and is_2016_question_number_word(word.get("text", "")):
                    starts.append(
                        (
                            number,
                            Line(
                                page=page_number,
                                text=str(word.get("text", "")),
                                x0=x0,
                                top=top,
                                bottom=float(word["bottom"]),
                                page_width=float(page.width),
                                page_height=float(page.height),
                            ),
                        )
                    )
                    number += 1
    if len(starts) != 66:
        raise ValueError(f"2016年PDFは66問として検出される想定です。実際: {len(starts)}問")

    crop_spans = spans_from_starts(starts)
    image_map = render_question_crops(
        pdf_path,
        year,
        media_root,
        image_url_prefix,
        crop_spans,
        full_question=False,
        dpi=dpi,
    )

    parsed: list[ParsedQuestion] = []
    for index, (number, line) in enumerate(starts):
        next_line = starts[index + 1][1] if index + 1 < len(starts) else None
        span_texts = []
        for item in all_lines:
            if item.page < line.page:
                continue
            if next_line and item.page > next_line.page:
                continue
            if item.page == line.page and item.top < line.top - 1:
                continue
            if next_line and item.page == next_line.page and item.top >= next_line.top - 1:
                continue
            text = repair_2016_text(item.text)
            if not text or text == "口" or is_2016_image_caption_line(text):
                continue
            span_texts.append(text)
        if span_texts:
            span_texts[0] = re.sub(r"^[0-9０-９]{1,3}\s+", "", span_texts[0]).strip()
        span_text = " ".join(span_texts)
        stem, choices = split_choices(span_texts)
        if len(choices) != 5:
            raise ValueError(f"{pdf_path.name} 問{number}: 選択肢が5個ではありません ({len(choices)}個)")
        parsed.append(
            ParsedQuestion(
                year=year,
                number=number,
                stem=stem,
                choices=choices,
                category=classify_treatment(span_text, choices),
                images=image_map.get(number, []),
                source_file=pdf_path.name,
                source_page=line.page,
            )
        )
    return parsed


def parse_pdf(pdf_path: Path, media_root: Path, image_url_prefix: str, dpi: int) -> list[ParsedQuestion]:
    year = year_from_path(pdf_path)
    if year == "2016":
        return parse_2016_pdf(pdf_path, media_root, image_url_prefix, dpi)
    return parse_regular_pdf(pdf_path, media_root, image_url_prefix, dpi)


def questions_to_payload(questions: list[ParsedQuestion], exam: str) -> list[dict]:
    payload: list[dict] = []
    for item in questions:
        payload.append(
            {
                "exam": exam,
                "year": item.year,
                "category": item.category,
                "question": f"問{item.number} {item.stem}".strip(),
                "choices": item.choices,
                "images": item.images,
                "answer": "",
                "explanation": f"出典: {item.source_file} / 問{item.number} / p.{item.source_page}",
            }
        )
    return payload


def backup_db(db_path: Path, label: str) -> Path:
    backup_dir = APP_DIR / "backups" / f"before-{label}-{now_stamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / db_path.name
    shutil.copy2(db_path, target)
    return target


def import_questions(db_path: Path, questions: list[dict], replace_years: bool, backup_label: str = "treatment-import") -> tuple[int, int, Path | None]:
    timestamp = now_iso()
    inserted = 0
    skipped = 0
    backup = backup_db(db_path, backup_label) if db_path.exists() else None
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
                    json.dumps(item["images"], ensure_ascii=False),
                    item.get("answer", ""),
                    item.get("explanation", ""),
                    timestamp,
                    timestamp,
                ),
            )
            inserted += 1
        conn.commit()
    return inserted, skipped, backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Import radiation oncology specialist past exam PDFs.")
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--exam", default=EXAM_NAME)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--image-url-prefix", default="/media/treatment")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--replace-year", action="store_true")
    parser.add_argument("--no-db", action="store_true")
    args = parser.parse_args()

    all_items: list[dict] = []
    for pdf_path in args.pdfs:
        parsed = parse_pdf(pdf_path.resolve(), args.media_root.resolve(), args.image_url_prefix, args.dpi)
        payload = questions_to_payload(parsed, args.exam)
        all_items.extend(payload)
        image_count = sum(len(item["images"]) for item in payload)
        print(f"{pdf_path.name}: {len(payload)} questions, {image_count} images")

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps({"questions": all_items}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {args.json_path.resolve()}")

    if not args.no_db:
        inserted, skipped, backup = import_questions(args.db.resolve(), all_items, args.replace_year)
        if backup:
            print(f"backup: {backup}")
        print(f"DB: {args.db.resolve()}")
        print(f"Inserted: {inserted}, skipped: {skipped}, total extracted: {len(all_items)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
