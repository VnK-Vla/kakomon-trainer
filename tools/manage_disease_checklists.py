#!/usr/bin/env python3
"""Safely create and maintain an owner-private disease knowledge checklist."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_BACKUP_ROOT = APP_DIR / "backups"

EXPECTED_EXAM = "放射線診断専門医認定試験"
EXPECTED_SOURCE_SHA256 = (
    "7eb8f540e36557a950dbbc9199efe956c4dcd99aa47221df39c4b6dc2f8e1d52"
)
EXPECTED_ITEM_COUNT = 790
EXPECTED_BASE_INCLUDED = 621
EXPECTED_HIDDEN = 169

MANIFEST_KEYS = {
    "title",
    "exam",
    "source_sha256",
    "extraction_criteria",
    "items",
}
ITEM_KEYS = {
    "disease_name",
    "aliases",
    "concept_type",
    "primary_area",
    "areas",
    "curriculum_refs",
    "base_included",
    "question_links",
}
LINK_KEYS = {"question_id", "match_type"}
CURRICULUM_REF_KEYS = {"no", "chapter", "major", "middle", "small"}
CONCEPT_TYPES = {
    "disease",
    "tumor",
    "congenital_anomaly",
    "trauma",
    "pathological_condition",
}
MATCH_TYPES = {"correct", "structured_target"}
REVIEW_STATUSES = {"warn", "wrong"}
REVIEW_TSV_FIELDS = [
    "item_id",
    "disease_name",
    "status",
    "primary_area",
    "curriculum_refs",
    "ever_wrong_at",
    "ever_wrong_question_id",
    "review_note",
    "sources",
]

MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_TEXT = 4_000
QUERY_CHUNK_SIZE = 400

REQUIRED_SCHEMA = {
    "questions": {"id", "exam"},
    "users": {"name"},
    "attempts": {"id", "user_name", "question_id", "is_correct", "created_at"},
    "disease_checklists": {
        "id",
        "user_name",
        "exam",
        "title",
        "source_sha256",
        "extraction_criteria",
        "created_at",
        "updated_at",
    },
    "disease_checklist_items": {
        "id",
        "checklist_id",
        "position",
        "disease_name",
        "aliases_json",
        "concept_type",
        "primary_area",
        "areas_json",
        "curriculum_refs_json",
        "base_included",
        "review_note",
        "sources_json",
        "ever_wrong_at",
        "ever_wrong_question_id",
        "note_updated_at",
        "created_at",
        "updated_at",
    },
    "disease_checklist_item_questions": {
        "item_id",
        "question_id",
        "match_type",
        "created_at",
    },
    "disease_check_statuses": {
        "item_id",
        "status",
        "created_at",
        "updated_at",
    },
}


class DiseaseChecklistError(RuntimeError):
    """An expected, user-facing validation or persistence error."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiseaseChecklistError(f"JSONに重複したキーがあります: {key}")
        result[key] = value
    return result


def _identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("囊", "嚢").replace("剝", "剥")
    return re.sub(r"[\s　]+", "", value)


def _plain_text(
    value: Any,
    label: str,
    *,
    max_length: int = MAX_TEXT,
    allow_empty: bool = False,
    trim: bool = False,
) -> str:
    if not isinstance(value, str):
        raise DiseaseChecklistError(f"{label}は文字列にしてください。")
    normalized = value.strip() if trim else value
    if not allow_empty and not normalized:
        raise DiseaseChecklistError(f"{label}は空にできません。")
    if len(normalized) > max_length:
        raise DiseaseChecklistError(f"{label}は{max_length}文字以内にしてください。")
    if any(ord(char) < 32 and char not in {"\t", "\n", "\r"} for char in normalized):
        raise DiseaseChecklistError(f"{label}に制御文字を含めないでください。")
    return normalized


def _strict_object(
    value: Any,
    *,
    label: str,
    expected_keys: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DiseaseChecklistError(f"{label}はJSONオブジェクトにしてください。")
    keys = set(value)
    unknown = sorted(keys - expected_keys)
    missing = sorted(expected_keys - keys)
    if unknown:
        raise DiseaseChecklistError(
            f"{label}に未対応のキーがあります: {', '.join(unknown)}"
        )
    if missing:
        raise DiseaseChecklistError(
            f"{label}に必須キーがありません: {', '.join(missing)}"
        )
    return value


def _string_list(
    value: Any,
    *,
    label: str,
    allow_empty: bool,
    max_items: int,
) -> list[str]:
    if not isinstance(value, list):
        raise DiseaseChecklistError(f"{label}は文字列の配列にしてください。")
    if not allow_empty and not value:
        raise DiseaseChecklistError(f"{label}は空にできません。")
    if len(value) > max_items:
        raise DiseaseChecklistError(f"{label}は{max_items}件以内にしてください。")
    result: list[str] = []
    identities: set[str] = set()
    for index, raw in enumerate(value):
        item = _plain_text(raw, f"{label}[{index}]", max_length=300, trim=True)
        key = _identity(item)
        if key in identities:
            raise DiseaseChecklistError(f"{label}に重複があります: {item}")
        identities.add(key)
        result.append(item)
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    path = _private_path(path, must_exist=True)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise DiseaseChecklistError("manifestが大きすぎます。")
        raw = path.read_text(encoding="utf-8")
    except DiseaseChecklistError:
        raise
    except OSError as exc:
        raise DiseaseChecklistError(f"manifestを読めません: {path}") from exc
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except DiseaseChecklistError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DiseaseChecklistError("manifestはUTF-8の正しいJSONにしてください。") from exc

    payload = _strict_object(
        payload,
        label="manifest",
        expected_keys=MANIFEST_KEYS,
    )
    title = _plain_text(payload["title"], "title", max_length=80, trim=True)
    exam = _plain_text(payload["exam"], "exam", max_length=100)
    if exam != exam.strip():
        raise DiseaseChecklistError("examの前後に空白を含めないでください。")
    if exam != EXPECTED_EXAM:
        raise DiseaseChecklistError(
            f"examは今回の監査対象と一致しません: {EXPECTED_EXAM}"
        )
    source_sha256 = _plain_text(
        payload["source_sha256"],
        "source_sha256",
        max_length=64,
    )
    if source_sha256 != EXPECTED_SOURCE_SHA256:
        raise DiseaseChecklistError("source_sha256が今回の添付ファイルと一致しません。")
    extraction_criteria = _plain_text(
        payload["extraction_criteria"],
        "extraction_criteria",
        max_length=5_000,
        trim=True,
    )

    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise DiseaseChecklistError("itemsは配列にしてください。")
    if len(raw_items) != EXPECTED_ITEM_COUNT:
        raise DiseaseChecklistError(
            f"itemsは監査済みの{EXPECTED_ITEM_COUNT}件にしてください。"
        )

    items: list[dict[str, Any]] = []
    disease_keys: set[str] = set()
    included_count = 0
    for position, raw_item in enumerate(raw_items):
        item = _strict_object(
            raw_item,
            label=f"items[{position}]",
            expected_keys=ITEM_KEYS,
        )
        disease_name = _plain_text(
            item["disease_name"],
            f"items[{position}].disease_name",
            max_length=200,
            trim=True,
        )
        disease_key = _identity(disease_name)
        if disease_key in disease_keys:
            raise DiseaseChecklistError(f"disease_nameに重複があります: {disease_name}")
        disease_keys.add(disease_key)

        aliases = _string_list(
            item["aliases"],
            label=f"items[{position}].aliases",
            allow_empty=True,
            max_items=100,
        )
        if disease_key in {_identity(alias) for alias in aliases}:
            raise DiseaseChecklistError(
                f"aliasesにdisease_name自身を含めないでください: {disease_name}"
            )
        concept_type = _plain_text(
            item["concept_type"],
            f"items[{position}].concept_type",
            max_length=40,
        )
        if concept_type not in CONCEPT_TYPES:
            raise DiseaseChecklistError(
                f"未対応のconcept_typeです: {concept_type}"
            )
        primary_area = _plain_text(
            item["primary_area"],
            f"items[{position}].primary_area",
            max_length=100,
            trim=True,
        )
        areas = _string_list(
            item["areas"],
            label=f"items[{position}].areas",
            allow_empty=False,
            max_items=20,
        )
        if _identity(primary_area) not in {_identity(area) for area in areas}:
            raise DiseaseChecklistError(
                f"primary_areaをareasにも含めてください: {disease_name}"
            )
        raw_refs = item["curriculum_refs"]
        if not isinstance(raw_refs, list) or not raw_refs:
            raise DiseaseChecklistError(
                f"items[{position}].curriculum_refsは空でない配列にしてください。"
            )
        if len(raw_refs) > 100:
            raise DiseaseChecklistError(f"curriculum_refsが多すぎます: {disease_name}")
        refs: list[dict[str, Any]] = []
        seen_ref_numbers: set[int] = set()
        for ref_index, raw_ref in enumerate(raw_refs):
            ref = _strict_object(
                raw_ref,
                label=f"items[{position}].curriculum_refs[{ref_index}]",
                expected_keys=CURRICULUM_REF_KEYS,
            )
            number = ref["no"]
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number <= 0
                or number in seen_ref_numbers
            ):
                raise DiseaseChecklistError(
                    f"curriculum_refsのnoに重複または不正値があります: {disease_name}"
                )
            seen_ref_numbers.add(number)
            chapter = _plain_text(
                ref["chapter"],
                f"curriculum_refs[{ref_index}].chapter",
                max_length=300,
                trim=True,
            )
            hierarchy = {}
            for key in ("major", "middle", "small"):
                hierarchy[key] = _plain_text(
                    ref[key],
                    f"curriculum_refs[{ref_index}].{key}",
                    max_length=500,
                    allow_empty=True,
                    trim=True,
                )
            refs.append({"no": number, "chapter": chapter, **hierarchy})

        base_included = item["base_included"]
        if not isinstance(base_included, bool):
            raise DiseaseChecklistError(
                f"items[{position}].base_includedは真偽値にしてください。"
            )
        included_count += int(base_included)

        raw_links = item["question_links"]
        if not isinstance(raw_links, list):
            raise DiseaseChecklistError(
                f"items[{position}].question_linksは配列にしてください。"
            )
        links: list[dict[str, Any]] = []
        seen_question_ids: set[int] = set()
        for link_index, raw_link in enumerate(raw_links):
            link = _strict_object(
                raw_link,
                label=f"items[{position}].question_links[{link_index}]",
                expected_keys=LINK_KEYS,
            )
            question_id = link["question_id"]
            if (
                not isinstance(question_id, int)
                or isinstance(question_id, bool)
                or question_id <= 0
            ):
                raise DiseaseChecklistError("question_idは正の整数にしてください。")
            if question_id in seen_question_ids:
                raise DiseaseChecklistError(
                    f"同一疾患のquestion_idに重複があります: {disease_name}/{question_id}"
                )
            seen_question_ids.add(question_id)
            match_type = _plain_text(
                link["match_type"],
                f"question_links[{link_index}].match_type",
                max_length=30,
            )
            if match_type not in MATCH_TYPES:
                raise DiseaseChecklistError(f"未対応のmatch_typeです: {match_type}")
            links.append({"question_id": question_id, "match_type": match_type})

        correct_links = [link for link in links if link["match_type"] == "correct"]
        if base_included and correct_links:
            raise DiseaseChecklistError(
                f"base_included=trueの項目にcorrect linkがあります: {disease_name}"
            )
        if not base_included:
            if not correct_links:
                raise DiseaseChecklistError(
                    f"非表示項目には除外根拠のcorrect linkが必要です: {disease_name}"
                )

        items.append(
            {
                "disease_name": disease_name,
                "aliases": aliases,
                "concept_type": concept_type,
                "primary_area": primary_area,
                "areas": areas,
                "curriculum_refs": refs,
                "base_included": base_included,
                "question_links": links,
            }
        )

    hidden_count = len(items) - included_count
    if included_count != EXPECTED_BASE_INCLUDED or hidden_count != EXPECTED_HIDDEN:
        raise DiseaseChecklistError(
            "base_includedの内訳が監査値と一致しません: "
            f"採用{included_count}件/除外{hidden_count}件"
        )
    return {
        "title": title,
        "exam": exam,
        "source_sha256": source_sha256,
        "extraction_criteria": extraction_criteria,
        "items": items,
    }


def open_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise DiseaseChecklistError(f"DBが見つかりません: {db_path}")
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DiseaseChecklistError(f"DBを読み取り専用で開けません: {db_path}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    return conn


def require_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = sorted(set(REQUIRED_SCHEMA) - tables)
    missing_columns: list[str] = []
    for table, expected in REQUIRED_SCHEMA.items():
        if table not in tables:
            continue
        actual = {
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        missing_columns.extend(
            f"{table}.{column}" for column in sorted(expected - actual)
        )
    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append("不足テーブル: " + ", ".join(missing_tables))
        if missing_columns:
            details.append("不足列: " + ", ".join(missing_columns))
        raise DiseaseChecklistError(
            "疾患チェック用スキーマがまだ導入されていません。"
            "新しいserver.pyでアプリを再起動してから再実行してください。"
            f" ({'; '.join(details)})"
        )


def _chunks(values: list[int]) -> Iterable[list[int]]:
    for start in range(0, len(values), QUERY_CHUNK_SIZE):
        yield values[start : start + QUERY_CHUNK_SIZE]


def _fetch_questions(
    conn: sqlite3.Connection,
    question_ids: set[int],
) -> dict[int, sqlite3.Row]:
    rows: dict[int, sqlite3.Row] = {}
    ordered = sorted(question_ids)
    for chunk in _chunks(ordered):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT id, exam FROM questions WHERE id IN ({placeholders})",
            chunk,
        ):
            rows[int(row["id"])] = row
    return rows


def _first_wrong_by_position(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    user_name: str,
) -> dict[int, tuple[str, int, int]]:
    positions_by_question: dict[int, list[int]] = {}
    for position, item in enumerate(manifest["items"]):
        for link in item["question_links"]:
            positions_by_question.setdefault(link["question_id"], []).append(position)
    earliest: dict[int, tuple[str, int, int]] = {}
    for chunk in _chunks(sorted(positions_by_question)):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT id, question_id, created_at
            FROM attempts
            WHERE user_name = ? AND is_correct = 0
              AND question_id IN ({placeholders})
            ORDER BY created_at, id
            """,
            (user_name, *chunk),
        ).fetchall()
        for row in rows:
            qid = int(row["question_id"])
            candidate = (str(row["created_at"]), int(row["id"]), qid)
            for position in positions_by_question[qid]:
                current = earliest.get(position)
                if current is None or candidate[:2] < current[:2]:
                    earliest[position] = candidate
    return earliest


def inspect_create_request(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    user_name: str,
) -> dict[str, Any]:
    require_schema(conn)
    if conn.execute("SELECT 1 FROM users WHERE name=?", (user_name,)).fetchone() is None:
        raise DiseaseChecklistError("指定ユーザーはusersテーブルに存在しません。")
    duplicate = conn.execute(
        """
        SELECT 1 FROM disease_checklists
        WHERE user_name=? AND exam=? AND title=?
        """,
        (user_name, manifest["exam"], manifest["title"]),
    ).fetchone()
    if duplicate is not None:
        raise DiseaseChecklistError("同じ所有者・試験に同名チェックリストがあります。")

    if conn.execute(
        "SELECT 1 FROM questions WHERE exam=? LIMIT 1", (manifest["exam"],)
    ).fetchone() is None:
        raise DiseaseChecklistError("manifestのexamに対応する問題がありません。")
    question_ids = {
        link["question_id"]
        for item in manifest["items"]
        for link in item["question_links"]
    }
    question_rows = _fetch_questions(conn, question_ids)
    missing = sorted(question_ids - set(question_rows))
    if missing:
        raise DiseaseChecklistError(
            "存在しない問題IDがあります: " + ", ".join(map(str, missing[:20]))
        )
    wrong_exam = sorted(
        qid for qid, row in question_rows.items() if row["exam"] != manifest["exam"]
    )
    if wrong_exam:
        raise DiseaseChecklistError(
            "指定examに属さない問題IDがあります: "
            + ", ".join(map(str, wrong_exam[:20]))
        )

    first_wrong = _first_wrong_by_position(conn, manifest, user_name)
    concept_counts = Counter(item["concept_type"] for item in manifest["items"])
    area_counts = Counter(item["primary_area"] for item in manifest["items"])
    included = sum(item["base_included"] for item in manifest["items"])
    links = sum(len(item["question_links"]) for item in manifest["items"])
    correct_links = sum(
        link["match_type"] == "correct"
        for item in manifest["items"]
        for link in item["question_links"]
    )
    return {
        "title": manifest["title"],
        "exam": manifest["exam"],
        "source_sha256": manifest["source_sha256"],
        "item_count": len(manifest["items"]),
        "base_included_count": included,
        "hidden_count": len(manifest["items"]) - included,
        "question_link_count": links,
        "correct_link_count": correct_links,
        "structured_target_link_count": links - correct_links,
        "ever_wrong_activation_count": len(first_wrong),
        "effective_included_count": sum(
            item["base_included"] or position in first_wrong
            for position, item in enumerate(manifest["items"])
        ),
        "breakdown": {
            "concept_type": dict(sorted(concept_counts.items())),
            "primary_area": dict(sorted(area_counts.items())),
        },
        "_first_wrong": first_wrong,
    }


def _allocate_backup_dir(backup_root: Path, timestamp: str) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    base = f"before-disease-checklist-{timestamp}"
    for sequence in range(1_000):
        suffix = "" if sequence == 0 else f"-{sequence:02d}"
        candidate = backup_root / f"{base}{suffix}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise DiseaseChecklistError("バックアップ保存先を確保できませんでした。")


def backup_database(
    db_path: Path,
    *,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    timestamp: str | None = None,
) -> Path:
    try:
        backup_dir = _allocate_backup_dir(backup_root, timestamp or now_stamp())
    except OSError as exc:
        raise DiseaseChecklistError("バックアップ保存先を作成できませんでした。") from exc
    target = backup_dir / "questions.db"
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = open_read_only(db_path)
        destination = sqlite3.connect(target)
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]).lower() != "ok":
            raise DiseaseChecklistError("バックアップの整合性を確認できませんでした。")
    except Exception as exc:
        if destination is not None:
            destination.close()
            destination = None
        if source is not None:
            source.close()
            source = None
        target.unlink(missing_ok=True)
        try:
            backup_dir.rmdir()
        except OSError:
            pass
        if isinstance(exc, DiseaseChecklistError):
            raise
        raise DiseaseChecklistError("DBバックアップを作成できませんでした。") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    return target


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _public_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def create_disease_checklist(
    manifest_path: Path,
    *,
    user_name: str,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    normalized_user = user_name.strip()
    if not normalized_user:
        raise DiseaseChecklistError("--userには既存ユーザー名を指定してください。")
    manifest = load_manifest(manifest_path)
    db_path = db_path.resolve()
    try:
        conn = open_read_only(db_path)
        try:
            summary = inspect_create_request(conn, manifest, normalized_user)
        finally:
            conn.close()
    except DiseaseChecklistError:
        raise
    except sqlite3.Error as exc:
        raise DiseaseChecklistError("DBの内容を検証できませんでした。") from exc
    if dry_run:
        return {"ok": True, "dry_run": True, **_public_summary(summary)}

    backup_path = backup_database(db_path, backup_root=backup_root)
    conn = None
    try:
        conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=rw",
            uri=True,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        summary = inspect_create_request(conn, manifest, normalized_user)
        first_wrong = summary["_first_wrong"]
        timestamp = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO disease_checklists (
                user_name, exam, title, source_sha256, extraction_criteria,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_user,
                manifest["exam"],
                manifest["title"],
                manifest["source_sha256"],
                manifest["extraction_criteria"],
                timestamp,
                timestamp,
            ),
        )
        checklist_id = int(cursor.lastrowid)
        item_ids: dict[int, int] = {}
        for position, item in enumerate(manifest["items"]):
            wrong = first_wrong.get(position)
            item_cursor = conn.execute(
                """
                INSERT INTO disease_checklist_items (
                    checklist_id, position, disease_name, aliases_json,
                    concept_type, primary_area, areas_json, curriculum_refs_json,
                    base_included, review_note, sources_json,
                    ever_wrong_at, ever_wrong_question_id, note_updated_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '[]', ?, ?, NULL, ?, ?)
                """,
                (
                    checklist_id,
                    position,
                    item["disease_name"],
                    _json(item["aliases"]),
                    item["concept_type"],
                    item["primary_area"],
                    _json(item["areas"]),
                    _json(item["curriculum_refs"]),
                    int(item["base_included"]),
                    wrong[0] if wrong else None,
                    wrong[2] if wrong else None,
                    timestamp,
                    timestamp,
                ),
            )
            item_ids[position] = int(item_cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO disease_checklist_item_questions (
                item_id, question_id, match_type, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (item_ids[position], link["question_id"], link["match_type"], timestamp)
                for position, item in enumerate(manifest["items"])
                for link in item["question_links"]
            ],
        )
        conn.commit()
    except DiseaseChecklistError:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise DiseaseChecklistError(
            "疾患チェックリストの登録に失敗しました。変更はロールバックしました。"
        ) from exc
    finally:
        if conn is not None:
            conn.close()
    return {
        "ok": True,
        "dry_run": False,
        "checklist_id": checklist_id,
        "backup": str(backup_path),
        **_public_summary(summary),
    }


def _owned_checklist(
    conn: sqlite3.Connection,
    checklist_id: int,
    user_name: str,
) -> sqlite3.Row:
    require_schema(conn)
    row = conn.execute(
        """
        SELECT * FROM disease_checklists
        WHERE id=? AND user_name=?
        """,
        (checklist_id, user_name),
    ).fetchone()
    if row is None:
        raise DiseaseChecklistError("指定チェックリストが見つかりません。")
    return row


def _effective_status(row: sqlite3.Row) -> str:
    return str(row["status"] or "")


def _private_path(path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.resolve()
    if resolved == APP_DIR or APP_DIR in resolved.parents:
        raise DiseaseChecklistError("非公開TSVをリポジトリ内には置けません。")
    if must_exist and not resolved.is_file():
        raise DiseaseChecklistError(f"ファイルが見つかりません: {resolved}")
    return resolved


def _decode_sources(value: str, *, label: str) -> list[str]:
    try:
        sources = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise DiseaseChecklistError(f"{label}のsources_jsonが不正です。") from exc
    if not isinstance(sources, list) or any(not isinstance(url, str) for url in sources):
        raise DiseaseChecklistError(f"{label}のsources_jsonが不正です。")
    return sources


def export_review(
    *,
    checklist_id: int,
    user_name: str,
    output_path: Path,
    db_path: Path = DEFAULT_DB,
) -> dict[str, Any]:
    output_path = _private_path(output_path)
    conn = open_read_only(db_path)
    try:
        checklist = _owned_checklist(conn, checklist_id, user_name.strip())
        rows = conn.execute(
            """
            SELECT i.id, i.disease_name, i.primary_area,
                   i.curriculum_refs_json, i.review_note, i.sources_json,
                   i.ever_wrong_at, i.ever_wrong_question_id, s.status
            FROM disease_checklist_items i
            LEFT JOIN disease_check_statuses s ON s.item_id=i.id
            WHERE i.checklist_id=?
            ORDER BY i.position
            """,
            (checklist_id,),
        ).fetchall()
        exported: list[dict[str, str]] = []
        missing_notes = 0
        for row in rows:
            status = _effective_status(row)
            if status not in REVIEW_STATUSES:
                continue
            note = str(row["review_note"] or "")
            sources = _decode_sources(str(row["sources_json"]), label=str(row["id"]))
            if note.strip() and sources:
                continue
            missing_notes += 1
            exported.append(
                {
                    "item_id": str(row["id"]),
                    "disease_name": str(row["disease_name"]),
                    "status": status,
                    "primary_area": str(row["primary_area"]),
                    "curriculum_refs": str(row["curriculum_refs_json"]),
                    "ever_wrong_at": str(row["ever_wrong_at"] or ""),
                    "ever_wrong_question_id": str(
                        row["ever_wrong_question_id"] or ""
                    ),
                    "review_note": note,
                    "sources": " | ".join(sources),
                }
            )
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as handle:
            temp_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=REVIEW_TSV_FIELDS, delimiter="\t")
            writer.writeheader()
            writer.writerows(exported)
        os.replace(temp_name, output_path)
    except OSError as exc:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
        raise DiseaseChecklistError("レビューTSVを書き出せませんでした。") from exc
    return {
        "ok": True,
        "checklist_id": int(checklist["id"]),
        "title": str(checklist["title"]),
        "exported_count": len(exported),
        "missing_note_count": missing_notes,
        "output": str(output_path),
    }


def _https_sources(raw: str, label: str) -> list[str]:
    sources = [part.strip() for part in raw.split("|") if part.strip()]
    if len(sources) > 20 or len(set(sources)) != len(sources):
        raise DiseaseChecklistError(f"{label}のsourcesに重複または件数超過があります。")
    for url in sources:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise DiseaseChecklistError(f"sourcesはHTTPS URLだけにしてください: {url}")
    return sources


def _review_import_rows(path: Path) -> list[dict[str, Any]]:
    path = _private_path(path, must_exist=True)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames is None or reader.fieldnames != REVIEW_TSV_FIELDS:
                raise DiseaseChecklistError(
                    "レビューTSVの列はexport-reviewの指定列をそのまま使用してください。"
                )
            raw_rows = list(reader)
    except DiseaseChecklistError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise DiseaseChecklistError("レビューTSVを読めませんでした。") from exc
    if not raw_rows:
        raise DiseaseChecklistError("レビューTSVに更新行がありません。")
    rows = []
    seen_ids: set[int] = set()
    for index, raw in enumerate(raw_rows, start=2):
        try:
            item_id = int(raw["item_id"])
        except (TypeError, ValueError) as exc:
            raise DiseaseChecklistError(f"TSV {index}行目のitem_idが不正です。") from exc
        if item_id <= 0 or item_id in seen_ids:
            raise DiseaseChecklistError(f"TSVのitem_idに重複または不正値があります: {item_id}")
        seen_ids.add(item_id)
        disease_name = _plain_text(
            raw["disease_name"], f"TSV {index}行目 disease_name", max_length=200
        )
        status = _plain_text(raw["status"], f"TSV {index}行目 status", max_length=10)
        if status not in REVIEW_STATUSES:
            raise DiseaseChecklistError("import-notesはwarn/wrong行だけを受け付けます。")
        primary_area = _plain_text(
            raw["primary_area"],
            f"TSV {index}行目 primary_area",
            max_length=100,
        )
        try:
            curriculum_refs = json.loads(raw["curriculum_refs"])
        except json.JSONDecodeError as exc:
            raise DiseaseChecklistError(
                f"TSV {index}行目のcurriculum_refsが不正です。"
            ) from exc
        if not isinstance(curriculum_refs, list) or any(
            not isinstance(ref, dict) or set(ref) != CURRICULUM_REF_KEYS
            for ref in curriculum_refs
        ):
            raise DiseaseChecklistError(
                f"TSV {index}行目のcurriculum_refsが不正です。"
            )
        ever_wrong_at = _plain_text(
            raw["ever_wrong_at"],
            f"TSV {index}行目 ever_wrong_at",
            max_length=100,
            allow_empty=True,
        )
        raw_wrong_question = raw["ever_wrong_question_id"].strip()
        if raw_wrong_question:
            try:
                ever_wrong_question_id = int(raw_wrong_question)
            except ValueError as exc:
                raise DiseaseChecklistError(
                    f"TSV {index}行目のever_wrong_question_idが不正です。"
                ) from exc
            if ever_wrong_question_id <= 0:
                raise DiseaseChecklistError(
                    f"TSV {index}行目のever_wrong_question_idが不正です。"
                )
        else:
            ever_wrong_question_id = None
        note = _plain_text(
            raw["review_note"],
            f"TSV {index}行目 review_note",
            allow_empty=True,
            max_length=MAX_TEXT,
        )
        if "<" in note or ">" in note or "\t" in note or "\n" in note or "\r" in note:
            raise DiseaseChecklistError("review_noteは改行やHTMLを含まないプレーンテキストにしてください。")
        sources = _https_sources(raw["sources"], f"TSV {index}行目")
        if not note.strip() or not sources:
            raise DiseaseChecklistError(
                f"TSV {index}行目はreview_noteとHTTPS sourcesの両方を入力してください。"
            )
        rows.append(
            {
                "item_id": item_id,
                "disease_name": disease_name,
                "status": status,
                "primary_area": primary_area,
                "curriculum_refs": curriculum_refs,
                "ever_wrong_at": ever_wrong_at,
                "ever_wrong_question_id": ever_wrong_question_id,
                "review_note": note,
                "sources": sources,
            }
        )
    return rows


def _inspect_note_import(
    conn: sqlite3.Connection,
    *,
    checklist_id: int,
    user_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    checklist = _owned_checklist(conn, checklist_id, user_name)
    ids = [row["item_id"] for row in rows]
    found: dict[int, sqlite3.Row] = {}
    for chunk in _chunks(ids):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            SELECT i.id, i.disease_name, i.primary_area,
                   i.curriculum_refs_json, i.ever_wrong_at,
                   i.ever_wrong_question_id, s.status
            FROM disease_checklist_items i
            LEFT JOIN disease_check_statuses s ON s.item_id=i.id
            WHERE i.checklist_id=? AND i.id IN ({placeholders})
            """,
            (checklist_id, *chunk),
        ):
            found[int(row["id"])] = row
    missing = sorted(set(ids) - set(found))
    if missing:
        raise DiseaseChecklistError(
            "指定チェックリストに属さないitem_idがあります: "
            + ", ".join(map(str, missing))
        )
    for requested in rows:
        current = found[requested["item_id"]]
        if current["disease_name"] != requested["disease_name"]:
            raise DiseaseChecklistError(
                f"item_idとdisease_nameが一致しません: {requested['item_id']}"
            )
        if current["primary_area"] != requested["primary_area"]:
            raise DiseaseChecklistError(
                f"item_idとprimary_areaが一致しません: {requested['item_id']}"
            )
        if str(current["curriculum_refs_json"]) != _json(
            requested["curriculum_refs"]
        ):
            raise DiseaseChecklistError(
                f"item_idとcurriculum_refsが一致しません: {requested['item_id']}"
            )
        if str(current["ever_wrong_at"] or "") != requested["ever_wrong_at"]:
            raise DiseaseChecklistError(
                f"ever_wrong状態がTSV出力後に変わっています: {requested['disease_name']}"
            )
        if current["ever_wrong_question_id"] != requested["ever_wrong_question_id"]:
            raise DiseaseChecklistError(
                f"ever_wrong状態がTSV出力後に変わっています: {requested['disease_name']}"
            )
        if _effective_status(current) != requested["status"]:
            raise DiseaseChecklistError(
                f"レビュー状態がTSV出力後に変わっています: {requested['disease_name']}"
            )
    return {
        "checklist_id": int(checklist["id"]),
        "title": str(checklist["title"]),
        "update_count": len(rows),
        "source_url_count": sum(len(row["sources"]) for row in rows),
    }


def import_notes(
    tsv_path: Path,
    *,
    checklist_id: int,
    user_name: str,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    rows = _review_import_rows(tsv_path)
    db_path = db_path.resolve()
    conn = open_read_only(db_path)
    try:
        summary = _inspect_note_import(
            conn,
            checklist_id=checklist_id,
            user_name=user_name.strip(),
            rows=rows,
        )
    finally:
        conn.close()
    if dry_run:
        return {"ok": True, "dry_run": True, **summary}
    backup_path = backup_database(db_path, backup_root=backup_root)
    conn = None
    try:
        conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=rw", uri=True, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        summary = _inspect_note_import(
            conn,
            checklist_id=checklist_id,
            user_name=user_name.strip(),
            rows=rows,
        )
        timestamp = now_iso()
        conn.executemany(
            """
            UPDATE disease_checklist_items
            SET review_note=?, sources_json=?, note_updated_at=?, updated_at=?
            WHERE id=? AND checklist_id=?
            """,
            [
                (
                    row["review_note"],
                    _json(row["sources"]),
                    timestamp,
                    timestamp,
                    row["item_id"],
                    checklist_id,
                )
                for row in rows
            ],
        )
        conn.execute(
            "UPDATE disease_checklists SET updated_at=? WHERE id=?",
            (timestamp, checklist_id),
        )
        conn.commit()
    except DiseaseChecklistError:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise DiseaseChecklistError(
            "ノートの取り込みに失敗しました。変更はロールバックしました。"
        ) from exc
    finally:
        if conn is not None:
            conn.close()
    return {"ok": True, "dry_run": False, "backup": str(backup_path), **summary}


def _inspect_sync(
    conn: sqlite3.Connection,
    *,
    manifest: dict[str, Any],
    user_name: str,
) -> dict[str, Any]:
    require_schema(conn)
    checklist = conn.execute(
        """
        SELECT * FROM disease_checklists
        WHERE user_name=? AND exam=? AND title=?
        """,
        (user_name, manifest["exam"], manifest["title"]),
    ).fetchone()
    if checklist is None:
        raise DiseaseChecklistError("同期対象のチェックリストが見つかりません。")
    if checklist["source_sha256"] != manifest["source_sha256"]:
        raise DiseaseChecklistError("既存チェックリストのsource_sha256が一致しません。")
    existing_items = conn.execute(
        """
        SELECT id, disease_name, base_included
        FROM disease_checklist_items WHERE checklist_id=?
        """,
        (checklist["id"],),
    ).fetchall()
    by_name = {str(row["disease_name"]): row for row in existing_items}
    manifest_names = {item["disease_name"] for item in manifest["items"]}
    if set(by_name) != manifest_names:
        raise DiseaseChecklistError("manifestと既存項目の疾患集合が一致しません。")
    for item in manifest["items"]:
        if bool(by_name[item["disease_name"]]["base_included"]) != item["base_included"]:
            raise DiseaseChecklistError(
                f"base_includedが既存項目と一致しません: {item['disease_name']}"
            )
    question_ids = {
        link["question_id"]
        for item in manifest["items"]
        for link in item["question_links"]
    }
    questions = _fetch_questions(conn, question_ids)
    if set(questions) != question_ids:
        raise DiseaseChecklistError("存在しない問題IDがあります。")
    if any(row["exam"] != manifest["exam"] for row in questions.values()):
        raise DiseaseChecklistError("指定examに属さない問題IDがあります。")
    desired = {
        (int(by_name[item["disease_name"]]["id"]), link["question_id"], link["match_type"])
        for item in manifest["items"]
        for link in item["question_links"]
    }
    existing = {
        (int(row["item_id"]), int(row["question_id"]), str(row["match_type"]))
        for row in conn.execute(
            """
            SELECT q.item_id, q.question_id, q.match_type
            FROM disease_checklist_item_questions q
            JOIN disease_checklist_items i ON i.id=q.item_id
            WHERE i.checklist_id=?
            """,
            (checklist["id"],),
        )
    }
    additions = sorted(desired - existing)
    return {
        "checklist_id": int(checklist["id"]),
        "title": str(checklist["title"]),
        "existing_link_count": len(existing),
        "desired_link_count": len(desired),
        "add_link_count": len(additions),
        "_additions": additions,
    }


def _activate_existing_wrong(
    conn: sqlite3.Connection,
    *,
    checklist_id: int,
    user_name: str,
    timestamp: str,
) -> int:
    rows = conn.execute(
        """
        SELECT i.id AS item_id, a.question_id, a.created_at, a.id AS attempt_id
        FROM disease_checklist_items i
        JOIN disease_checklist_item_questions q ON q.item_id=i.id
        JOIN attempts a ON a.question_id=q.question_id
        WHERE i.checklist_id=? AND i.ever_wrong_at IS NULL
          AND a.user_name=? AND a.is_correct=0
        ORDER BY a.created_at, a.id
        """,
        (checklist_id, user_name),
    ).fetchall()
    first: dict[int, sqlite3.Row] = {}
    for row in rows:
        first.setdefault(int(row["item_id"]), row)
    conn.executemany(
        """
        UPDATE disease_checklist_items
        SET ever_wrong_at=?, ever_wrong_question_id=?, updated_at=?
        WHERE id=? AND ever_wrong_at IS NULL
        """,
        [
            (row["created_at"], row["question_id"], timestamp, item_id)
            for item_id, row in first.items()
        ],
    )
    return len(first)


def sync_links(
    manifest_path: Path,
    *,
    user_name: str,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    normalized_user = user_name.strip()
    db_path = db_path.resolve()
    conn = open_read_only(db_path)
    try:
        summary = _inspect_sync(conn, manifest=manifest, user_name=normalized_user)
    finally:
        conn.close()
    if dry_run or summary["add_link_count"] == 0:
        return {
            "ok": True,
            "dry_run": dry_run,
            "changed": False,
            **_public_summary(summary),
        }
    backup_path = backup_database(db_path, backup_root=backup_root)
    conn = None
    try:
        conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=rw", uri=True, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        summary = _inspect_sync(conn, manifest=manifest, user_name=normalized_user)
        timestamp = now_iso()
        conn.executemany(
            """
            INSERT INTO disease_checklist_item_questions (
                item_id, question_id, match_type, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            [(*addition, timestamp) for addition in summary["_additions"]],
        )
        activated = _activate_existing_wrong(
            conn,
            checklist_id=summary["checklist_id"],
            user_name=normalized_user,
            timestamp=timestamp,
        )
        conn.execute(
            "UPDATE disease_checklists SET updated_at=? WHERE id=?",
            (timestamp, summary["checklist_id"]),
        )
        conn.commit()
    except DiseaseChecklistError:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise DiseaseChecklistError(
            "リンク同期に失敗しました。変更はロールバックしました。"
        ) from exc
    finally:
        if conn is not None:
            conn.close()
    return {
        "ok": True,
        "dry_run": False,
        "changed": True,
        "backup": str(backup_path),
        "new_ever_wrong_activation_count": activated,
        **_public_summary(summary),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="所有者専用の疾患知識チェックリストを安全に管理します。"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="監査済みmanifestから新規作成")
    create.add_argument("manifest", type=Path)
    create.add_argument("--user", required=True)
    create.add_argument("--db", type=Path, default=DEFAULT_DB)
    create.add_argument("--dry-run", action="store_true")

    export = commands.add_parser("export-review", help="warn/wrongを非公開TSVへ出力")
    export.add_argument("--checklist-id", type=int, required=True)
    export.add_argument("--user", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--db", type=Path, default=DEFAULT_DB)

    notes = commands.add_parser("import-notes", help="レビューTSVからノートを更新")
    notes.add_argument("tsv", type=Path)
    notes.add_argument("--checklist-id", type=int, required=True)
    notes.add_argument("--user", required=True)
    notes.add_argument("--db", type=Path, default=DEFAULT_DB)
    notes.add_argument("--dry-run", action="store_true")

    sync = commands.add_parser("sync-links", help="manifestのリンクだけを追加同期")
    sync.add_argument("manifest", type=Path)
    sync.add_argument("--user", required=True)
    sync.add_argument("--db", type=Path, default=DEFAULT_DB)
    sync.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_disease_checklist(
                args.manifest,
                user_name=args.user,
                db_path=args.db,
                dry_run=args.dry_run,
            )
        elif args.command == "export-review":
            result = export_review(
                checklist_id=args.checklist_id,
                user_name=args.user,
                output_path=args.output,
                db_path=args.db,
            )
        elif args.command == "import-notes":
            result = import_notes(
                args.tsv,
                checklist_id=args.checklist_id,
                user_name=args.user,
                db_path=args.db,
                dry_run=args.dry_run,
            )
        elif args.command == "sync-links":
            result = sync_links(
                args.manifest,
                user_name=args.user,
                db_path=args.db,
                dry_run=args.dry_run,
            )
        else:
            raise DiseaseChecklistError(f"未対応の操作です: {args.command}")
    except DiseaseChecklistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
