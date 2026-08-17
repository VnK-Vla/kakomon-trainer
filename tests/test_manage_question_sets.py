import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import backup_to_google_drive
from tools import manage_question_sets


DIAGNOSTIC_EXAM = "放射線診断専門医認定試験"
NUCLEAR_EXAM = "核医学専門医試験"


class ManageQuestionSetsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "questions.db"
        self.db_path.parent.mkdir()
        self.backup_root = self.root / "backups"
        self.manifest_path = self.root / "manifest.json"
        self.create_schema()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                ("alice", "2026-08-06T00:00:00+00:00"),
            )
            conn.executemany(
                """
                INSERT INTO questions (id, exam, year, category)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (1, DIAGNOSTIC_EXAM, "2025", "中枢神経"),
                    (2, DIAGNOSTIC_EXAM, "2024", "胸部"),
                    (3, DIAGNOSTIC_EXAM, "2025", "中枢神経"),
                    (4, NUCLEAR_EXAM, "2025", "核医学総論"),
                ],
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY,
                    exam TEXT NOT NULL,
                    year TEXT NOT NULL,
                    category TEXT NOT NULL
                );

                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE private_question_owners (
                    question_id INTEGER PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE RESTRICT
                );

                CREATE TABLE question_sets (
                    id INTEGER PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    exam TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_name, exam, title),
                    FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE CASCADE
                );

                CREATE TABLE question_set_items (
                    question_set_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    PRIMARY KEY(question_set_id, question_id),
                    UNIQUE(question_set_id, position),
                    FOREIGN KEY(question_set_id) REFERENCES question_sets(id) ON DELETE CASCADE,
                    FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
                );
                """
            )

    def write_manifest(self, **overrides):
        payload = {
            "title": "MRI・CT 要確認セット",
            "exam": DIAGNOSTIC_EXAM,
            "question_ids": [1, 2, 3],
        }
        payload.update(overrides)
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def create(self, *, dry_run=False):
        return manage_question_sets.create_question_set(
            self.manifest_path,
            user_name="alice",
            db_path=self.db_path,
            dry_run=dry_run,
            backup_root=self.backup_root,
        )

    def test_dry_run_reports_breakdown_without_writing_or_backing_up(self):
        self.write_manifest(title="  MRI・CT 要確認セット  ")

        result = self.create(dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["title"], "MRI・CT 要確認セット")
        self.assertEqual(result["question_count"], 3)
        self.assertEqual(result["breakdown"]["year"], {"2024": 1, "2025": 2})
        self.assertEqual(result["breakdown"]["category"], {"中枢神経": 2, "胸部": 1})
        self.assertFalse(self.backup_root.exists())
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0], 0)

    def test_cli_create_dry_run_syntax_outputs_json(self):
        self.write_manifest(question_ids=[1, 2])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = manage_question_sets.main(
                [
                    "create",
                    str(self.manifest_path),
                    "--user",
                    "alice",
                    "--db",
                    str(self.db_path),
                    "--dry-run",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["question_count"], 2)
        self.assertFalse(self.backup_root.exists())

    def test_create_inserts_set_and_items_after_safe_backup(self):
        self.write_manifest(question_ids=[3, 1, 2])

        result = self.create()

        backup_path = Path(result["backup"])
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.name, "questions.db")
        self.assertTrue(backup_path.parent.name.startswith("before-question-set-"))

        with sqlite3.connect(backup_path) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0], 0)
        with sqlite3.connect(self.db_path) as conn:
            created = conn.execute(
                "SELECT user_name, exam, title FROM question_sets"
            ).fetchone()
            items = conn.execute(
                "SELECT position, question_id FROM question_set_items ORDER BY position"
            ).fetchall()
        self.assertEqual(created, ("alice", DIAGNOSTIC_EXAM, "MRI・CT 要確認セット"))
        self.assertEqual(items, [(0, 3), (1, 1), (2, 2)])

    def test_duplicate_title_and_duplicate_ids_are_rejected(self):
        self.write_manifest()
        self.create()

        self.write_manifest(question_ids=[1])
        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "同名"):
            self.create(dry_run=True)

        self.write_manifest(title="別セット", question_ids=[1, 1])
        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "重複"):
            self.create(dry_run=True)

    def test_missing_and_mixed_exam_question_ids_are_rejected(self):
        cases = [
            ([1, 99], "存在しない問題ID"),
            ([1, 4], "指定examに属さない問題ID"),
        ]
        for question_ids, error_pattern in cases:
            with self.subTest(question_ids=question_ids):
                self.write_manifest(question_ids=question_ids)
                with self.assertRaisesRegex(manage_question_sets.QuestionSetError, error_pattern):
                    self.create(dry_run=True)

        self.assertFalse(self.backup_root.exists())

    def test_private_question_can_only_be_selected_by_its_owner(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                ("bob", "2026-08-06T00:00:00+00:00"),
            )
            conn.execute(
                """
                INSERT INTO private_question_owners (question_id, user_name, created_at)
                VALUES (?, ?, ?)
                """,
                (3, "bob", "2026-08-06T00:00:00+00:00"),
            )
        self.write_manifest(question_ids=[1, 3])

        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "別ユーザー"):
            self.create(dry_run=True)

    def test_failed_item_insert_rolls_back_the_entire_creation(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TRIGGER reject_second_question_set_item
                BEFORE INSERT ON question_set_items
                WHEN NEW.position = 1
                BEGIN
                    SELECT RAISE(ABORT, 'test failure');
                END;
                """
            )
        self.write_manifest(question_ids=[1, 2])

        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "ロールバック"):
            self.create()

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_set_items").fetchone()[0], 0)
        backups = list(self.backup_root.glob("before-question-set-*/questions.db"))
        self.assertEqual(len(backups), 1)

    def test_unknown_manifest_key_is_rejected(self):
        self.write_manifest(extra="not allowed")

        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "未対応のキー"):
            self.create(dry_run=True)

        self.assertFalse(self.backup_root.exists())

    def test_missing_schema_fails_without_initializing_or_backing_up(self):
        incomplete_db = self.root / "incomplete.db"
        with sqlite3.connect(incomplete_db) as conn:
            conn.execute("CREATE TABLE users (name TEXT PRIMARY KEY)")
        self.write_manifest()

        with self.assertRaisesRegex(manage_question_sets.QuestionSetError, "再起動"):
            manage_question_sets.create_question_set(
                self.manifest_path,
                user_name="alice",
                db_path=incomplete_db,
                backup_root=self.backup_root,
            )

        with sqlite3.connect(incomplete_db) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertEqual(tables, {"users"})
        self.assertFalse(self.backup_root.exists())

    def test_backup_manifest_counts_include_progress_and_question_set_tables(self):
        counts = backup_to_google_drive.db_counts(self.db_path)

        self.assertEqual(counts["question_sets"], 0)
        self.assertEqual(counts["question_set_items"], 0)
        for table in (
            "question_set_rounds",
            "question_set_round_items",
            "practice_sessions",
            "practice_session_items",
        ):
            self.assertIn(table, counts)


if __name__ == "__main__":
    unittest.main()
