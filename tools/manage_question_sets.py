#!/usr/bin/env python3
"""Create owner-scoped named question sets from a small JSON manifest."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = APP_DIR / "data" / "questions.db"
DEFAULT_BACKUP_ROOT = APP_DIR / "backups"
EXPECTED_MANIFEST_KEYS = {"title", "exam", "question_ids"}
MAX_QUESTION_IDS = 5_000
QUERY_CHUNK_SIZE = 500

REQUIRED_SCHEMA = {
    "questions": {"id", "exam", "year", "category"},
    "users": {"name"},
    "private_question_owners": {"question_id", "user_name"},
    "question_sets": {"id", "user_name", "exam", "title", "created_at", "updated_at"},
    "question_set_items": {"question_set_id", "position", "question_id"},
}


class QuestionSetError(RuntimeError):
    """An expected, user-facing validation or creation error."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QuestionSetError(f"manifestに重複したキーがあります: {key}")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuestionSetError(f"manifestを読めません: {path}") from exc

    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except QuestionSetError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise QuestionSetError("manifestはUTF-8の正しいJSONにしてください。") from exc

    if not isinstance(payload, dict):
        raise QuestionSetError("manifestの最上位はJSONオブジェクトにしてください。")

    keys = set(payload)
    unknown = sorted(keys - EXPECTED_MANIFEST_KEYS)
    missing = sorted(EXPECTED_MANIFEST_KEYS - keys)
    if unknown:
        raise QuestionSetError("manifestに未対応のキーがあります: " + ", ".join(unknown))
    if missing:
        raise QuestionSetError("manifestに必須キーがありません: " + ", ".join(missing))

    title_value = payload["title"]
    if not isinstance(title_value, str):
        raise QuestionSetError("titleは文字列にしてください。")
    title = title_value.strip()
    if not 1 <= len(title) <= 80:
        raise QuestionSetError("titleは前後の空白を除いて1〜80文字にしてください。")

    exam = payload["exam"]
    if not isinstance(exam, str) or not exam:
        raise QuestionSetError("examは空でない文字列にしてください。")
    if exam != exam.strip():
        raise QuestionSetError("examの前後に空白を含めないでください。")

    question_ids = payload["question_ids"]
    if not isinstance(question_ids, list):
        raise QuestionSetError("question_idsは配列にしてください。")
    if not 1 <= len(question_ids) <= MAX_QUESTION_IDS:
        raise QuestionSetError(f"question_idsは1〜{MAX_QUESTION_IDS}件にしてください。")
    if any(
        not isinstance(question_id, int)
        or isinstance(question_id, bool)
        or question_id <= 0
        for question_id in question_ids
    ):
        raise QuestionSetError("question_idsは正の整数だけにしてください。")
    if len(set(question_ids)) != len(question_ids):
        raise QuestionSetError("question_idsに重複があります。")

    return {"title": title, "exam": exam, "question_ids": question_ids}


def open_read_only(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise QuestionSetError(f"DBが見つかりません: {db_path}")
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise QuestionSetError(f"DBを読み取り専用で開けません: {db_path}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    return conn


def require_schema(conn: sqlite3.Connection) -> None:
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    tables = {str(row["name"]) for row in table_rows}
    missing_tables = sorted(set(REQUIRED_SCHEMA) - tables)
    missing_columns: list[str] = []
    for table, expected_columns in REQUIRED_SCHEMA.items():
        if table not in tables:
            continue
        actual_columns = {
            str(row["name"])
            for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        for column in sorted(expected_columns - actual_columns):
            missing_columns.append(f"{table}.{column}")

    if missing_tables or missing_columns:
        details: list[str] = []
        if missing_tables:
            details.append("不足テーブル: " + ", ".join(missing_tables))
        if missing_columns:
            details.append("不足列: " + ", ".join(missing_columns))
        raise QuestionSetError(
            "問題セット用スキーマがまだ導入されていません。"
            "新しいserver.pyでアプリを再起動してから再実行してください。"
            f" ({'; '.join(details)})"
        )


def _fetch_question_rows(
    conn: sqlite3.Connection,
    question_ids: list[int],
) -> dict[int, sqlite3.Row]:
    rows_by_id: dict[int, sqlite3.Row] = {}
    for start in range(0, len(question_ids), QUERY_CHUNK_SIZE):
        chunk = question_ids[start : start + QUERY_CHUNK_SIZE]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT q.id, q.exam, q.year, q.category, p.user_name AS private_owner
            FROM questions q
            LEFT JOIN private_question_owners p ON p.question_id = q.id
            WHERE q.id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        rows_by_id.update({int(row["id"]): row for row in rows})
    return rows_by_id


def _format_id_sample(ids: list[int]) -> str:
    shown = ", ".join(str(question_id) for question_id in ids[:20])
    if len(ids) > 20:
        shown += f", ...（ほか{len(ids) - 20}件）"
    return shown


def inspect_request(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    user_name: str,
) -> dict[str, Any]:
    require_schema(conn)

    user_exists = conn.execute(
        "SELECT 1 FROM users WHERE name = ? LIMIT 1",
        (user_name,),
    ).fetchone()
    if user_exists is None:
        raise QuestionSetError("指定ユーザーはusersテーブルに存在しません。")

    duplicate_title = conn.execute(
        """
        SELECT 1
        FROM question_sets
        WHERE user_name = ? AND exam = ? AND title = ?
        LIMIT 1
        """,
        (user_name, manifest["exam"], manifest["title"]),
    ).fetchone()
    if duplicate_title is not None:
        raise QuestionSetError("同じユーザー・試験に同名の問題セットが既にあります。")

    question_ids = manifest["question_ids"]
    rows_by_id = _fetch_question_rows(conn, question_ids)
    missing_ids = [question_id for question_id in question_ids if question_id not in rows_by_id]
    if missing_ids:
        raise QuestionSetError(
            "存在しない問題IDがあります: " + _format_id_sample(missing_ids)
        )

    wrong_exam_ids = [
        question_id
        for question_id in question_ids
        if str(rows_by_id[question_id]["exam"]) != manifest["exam"]
    ]
    if wrong_exam_ids:
        raise QuestionSetError(
            "指定examに属さない問題IDがあります: " + _format_id_sample(wrong_exam_ids)
        )

    other_owner_ids = [
        question_id
        for question_id in question_ids
        if rows_by_id[question_id]["private_owner"] is not None
        and str(rows_by_id[question_id]["private_owner"]) != user_name
    ]
    if other_owner_ids:
        raise QuestionSetError(
            "別ユーザーの個人問題が含まれています: "
            + _format_id_sample(other_owner_ids)
        )

    year_counts = Counter(
        str(rows_by_id[question_id]["year"] or "") for question_id in question_ids
    )
    category_counts = Counter(
        str(rows_by_id[question_id]["category"] or "") for question_id in question_ids
    )
    return {
        "user": user_name,
        "title": manifest["title"],
        "exam": manifest["exam"],
        "question_count": len(question_ids),
        "breakdown": {
            "year": dict(sorted(year_counts.items())),
            "category": dict(sorted(category_counts.items())),
        },
    }


def _allocate_backup_dir(backup_root: Path, timestamp: str) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    base_name = f"before-question-set-{timestamp}"
    for sequence in range(1_000):
        suffix = "" if sequence == 0 else f"-{sequence:02d}"
        candidate = backup_root / f"{base_name}{suffix}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise QuestionSetError("バックアップ保存先を確保できませんでした。")


def backup_database(
    db_path: Path,
    *,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    timestamp: str | None = None,
) -> Path:
    try:
        backup_dir = _allocate_backup_dir(backup_root, timestamp or now_stamp())
    except OSError as exc:
        raise QuestionSetError("バックアップ保存先を作成できませんでした。") from exc
    target = backup_dir / "questions.db"
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = open_read_only(db_path)
        destination = sqlite3.connect(target)
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]).lower() != "ok":
            raise QuestionSetError("作成したDBバックアップの整合性を確認できませんでした。")
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
        if isinstance(exc, QuestionSetError):
            raise
        raise QuestionSetError("DBバックアップを作成できませんでした。") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    return target


def create_question_set(
    manifest_path: Path,
    *,
    user_name: str,
    db_path: Path = DEFAULT_DB,
    dry_run: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    normalized_user = user_name.strip()
    if not normalized_user:
        raise QuestionSetError("--userには空でない既存ユーザー名を指定してください。")

    manifest = load_manifest(manifest_path)
    db_path = db_path.resolve()
    try:
        conn = open_read_only(db_path)
        try:
            summary = inspect_request(conn, manifest, normalized_user)
        finally:
            conn.close()
    except QuestionSetError:
        raise
    except sqlite3.Error as exc:
        raise QuestionSetError("DBの内容を検証できませんでした。") from exc

    if dry_run:
        return {"ok": True, "dry_run": True, **summary}

    backup_path = backup_database(db_path, backup_root=backup_root)

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=rw",
            uri=True,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        # Revalidate after taking the snapshot and obtaining the write lock.
        summary = inspect_request(conn, manifest, normalized_user)
        timestamp = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO question_sets (
                user_name, exam, title, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_user,
                manifest["exam"],
                manifest["title"],
                timestamp,
                timestamp,
            ),
        )
        question_set_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO question_set_items (question_set_id, position, question_id)
            VALUES (?, ?, ?)
            """,
            [
                (question_set_id, position, question_id)
                for position, question_id in enumerate(manifest["question_ids"])
            ],
        )
        conn.commit()
    except QuestionSetError:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise QuestionSetError(
            "問題セットの登録に失敗しました。DBへの変更はロールバックしました。"
        ) from exc
    finally:
        if conn is not None:
            conn.close()

    return {
        "ok": True,
        "dry_run": False,
        "question_set_id": question_set_id,
        "backup": str(backup_path),
        **summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="既存問題IDから所有者専用の名前付き問題セットを作成します。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="manifestから問題セットを作成")
    create_parser.add_argument("manifest", type=Path, help="title/exam/question_idsを含むJSON")
    create_parser.add_argument("--user", required=True, help="usersテーブルに存在する所有者名")
    create_parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="questions.dbのパス")
    create_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="検証と内訳表示だけを行い、バックアップ・DB更新はしない",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_question_set(
                args.manifest,
                user_name=args.user,
                db_path=args.db,
                dry_run=args.dry_run,
            )
        else:  # argparse currently prevents this branch.
            raise QuestionSetError(f"未対応の操作です: {args.command}")
    except QuestionSetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
