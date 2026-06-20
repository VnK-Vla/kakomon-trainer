#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


APP_DIR = Path(os.environ.get("KAKOMON_APP_DIR", Path(__file__).resolve().parents[1])).resolve()
STAGING_DIR = Path(os.environ.get("KAKOMON_BACKUP_STAGING", APP_DIR / "backup-staging")).resolve()
REMOTE = os.environ.get("KAKOMON_BACKUP_REMOTE", "gdrive:kakomon-trainer-backup")
DAILY_KEEP = int(os.environ.get("KAKOMON_BACKUP_DAILY_KEEP", "30"))
FULL_KEEP = int(os.environ.get("KAKOMON_BACKUP_FULL_KEEP", "8"))


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def now_stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def copy_path(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def db_counts(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        for table in ("questions", "attempts", "users", "question_notes"):
            try:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                counts[table] = -1
    finally:
        conn.close()
    return counts


def count_tree(path: Path) -> dict[str, int]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def write_manifest(root: Path, mode: str, archive_name: str, db_path: Path) -> None:
    manifest = {
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "archive": archive_name,
        "app_dir": str(APP_DIR),
        "db_counts": db_counts(db_path),
        "source_sizes": {
            "data": count_tree(APP_DIR / "data"),
            "imports": count_tree(APP_DIR / "imports"),
            "source_pdfs": count_tree(APP_DIR / "static" / "source-pdfs"),
            "media": count_tree(APP_DIR / "static" / "media"),
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def build_archive(mode: str) -> Path:
    if mode not in {"daily", "full"}:
        raise ValueError("mode must be daily or full")

    timestamp = now_stamp()
    archive_dir = STAGING_DIR / mode
    tmp_parent = STAGING_DIR / "tmp"
    archive_dir.mkdir(parents=True, exist_ok=True)
    tmp_parent.mkdir(parents=True, exist_ok=True)
    archive_name = f"kakomon-{mode}-{timestamp}.tar.gz"
    archive_path = archive_dir / archive_name

    with tempfile.TemporaryDirectory(prefix=f"{mode}-", dir=tmp_parent) as tmp_name:
        payload = Path(tmp_name) / "kakomon-trainer"
        snapshot_sqlite(APP_DIR / "data" / "questions.db", payload / "data" / "questions.db")

        for rel in (
            "data/imported_questions.json",
            "imports",
            "server.py",
            "README.md",
            "static/index.html",
            "static/app.js",
            "static/app.css",
            "tools",
        ):
            copy_path(APP_DIR / rel, payload / rel)

        if mode == "full":
            for rel in ("static/media", "static/source-pdfs"):
                copy_path(APP_DIR / rel, payload / rel)

        write_manifest(payload, mode, archive_name, payload / "data" / "questions.db")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(payload, arcname="kakomon-trainer")

    print(f"created {archive_path} {archive_path.stat().st_size} bytes sha256={sha256(archive_path)}")
    return archive_path


def prune_local(mode: str, keep: int) -> None:
    archive_dir = STAGING_DIR / mode
    archives = sorted(archive_dir.glob(f"kakomon-{mode}-*.tar.gz"), reverse=True)
    for old in archives[keep:]:
        old.unlink(missing_ok=True)
        print(f"removed local old backup {old}")


def rclone_available() -> bool:
    return shutil.which("rclone") is not None


def rclone_remote_ready(remote: str) -> bool:
    if not rclone_available():
        return False
    result = run(["rclone", "lsd", remote], check=False)
    if result.returncode == 0:
        return True
    sys.stderr.write(result.stderr)
    return False


def upload_archive(archive: Path, mode: str, remote: str, dry_run: bool) -> None:
    remote_dir = f"{remote.rstrip('/')}/{mode}"
    cmd = ["rclone", "copy", str(archive), remote_dir, "--checksum", "--create-empty-src-dirs"]
    if dry_run:
        cmd.append("--dry-run")
    print("upload " + " ".join(cmd))
    result = run(cmd, check=False)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def prune_remote(mode: str, remote: str, keep: int, dry_run: bool) -> None:
    remote_dir = f"{remote.rstrip('/')}/{mode}"
    result = run(["rclone", "lsf", remote_dir, "--files-only"], check=False)
    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        return
    names = sorted(
        [line.strip() for line in result.stdout.splitlines() if line.strip().startswith(f"kakomon-{mode}-")],
        reverse=True,
    )
    for name in names[keep:]:
        target = f"{remote_dir}/{name}"
        cmd = ["rclone", "deletefile", target]
        if dry_run:
            cmd.append("--dry-run")
        result = run(cmd, check=False)
        if result.returncode == 0:
            print(f"removed remote old backup {target}")
        elif result.stderr:
            sys.stderr.write(result.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up kakomon-trainer to Google Drive via rclone.")
    parser.add_argument("mode", choices=["daily", "full"], help="daily backs up data/imports; full also includes PDFs/images")
    parser.add_argument("--remote", default=REMOTE, help="rclone remote path, e.g. gdrive:kakomon-trainer-backup")
    parser.add_argument("--no-upload", action="store_true", help="create the archive locally without uploading")
    parser.add_argument("--dry-run", action="store_true", help="pass --dry-run to rclone upload and cleanup")
    args = parser.parse_args()

    keep = DAILY_KEEP if args.mode == "daily" else FULL_KEEP
    archive = build_archive(args.mode)
    prune_local(args.mode, keep)

    if args.no_upload:
        print("upload skipped by --no-upload")
        return 0

    if not rclone_available():
        print("rclone is not installed. Install and configure rclone first.", file=sys.stderr)
        return 2
    if not rclone_remote_ready(args.remote):
        print(f"rclone remote is not ready: {args.remote}", file=sys.stderr)
        return 2

    upload_archive(archive, args.mode, args.remote, args.dry_run)
    prune_remote(args.mode, args.remote, keep, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
