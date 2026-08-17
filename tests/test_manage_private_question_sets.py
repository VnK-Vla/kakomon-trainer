import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import server
from tools import manage_private_question_sets


DIAGNOSTIC_EXAM = "放射線診断専門医認定試験"


class ManagePrivateQuestionSetsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "questions.db"
        self.db_path.parent.mkdir()
        self.manifest_path = self.root / "private-set.json"
        self.backup_root = self.root / "backups"
        self.original_db_path = server.DB_PATH
        server.DB_PATH = self.db_path
        server.init_db()
        timestamp = server.now_iso()
        with server.db() as conn:
            conn.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                ("alice", timestamp),
            )
            conn.execute(
                """
                INSERT INTO questions (
                    exam, year, category, question, choices, images,
                    answer, explanation, created_at, updated_at
                )
                VALUES (?, '2025', '胸部', '公開問題', '[\"a. 正しい\", \"b. 誤り\"]',
                        '[]', 'a', '公開解説', ?, ?)
                """,
                (DIAGNOSTIC_EXAM, timestamp, timestamp),
            )

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def write_manifest(self, **question_overrides):
        question = {
            "year": "自作",
            "category": "多臓器疾患",
            "question": "問1\n脳・腎・肺の病変を認める。最も考えられる疾患はどれか。",
            "choices": ["a. 疾患甲", "b. 疾患乙", "c. 疾患丙"],
            "answer": "b",
            "explanation": "正解は疾患乙。三臓器の組み合わせが決め手。",
        }
        question.update(question_overrides)
        self.manifest_path.write_text(
            json.dumps(
                {
                    "title": "多臓器疾患17問",
                    "exam": DIAGNOSTIC_EXAM,
                    "questions": [question],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def create(self, *, dry_run=False):
        return manage_private_question_sets.create_private_question_set(
            self.manifest_path,
            user_name="alice",
            db_path=self.db_path,
            dry_run=dry_run,
            backup_root=self.backup_root,
        )

    def test_dry_run_validates_without_writing_or_disclosing_owner(self):
        self.write_manifest()

        result = self.create(dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertTrue(result["owner_verified"])
        self.assertNotIn("user", result)
        self.assertEqual(result["question_count"], 1)
        self.assertEqual(result["single_answer_count"], 1)
        self.assertFalse(self.backup_root.exists())
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question_sets").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM private_question_owners").fetchone()[0],
                0,
            )

    def test_create_backs_up_and_inserts_questions_owners_and_set_atomically(self):
        self.write_manifest()

        result = self.create()

        self.assertTrue(Path(result["backup"]).is_file())
        with sqlite3.connect(self.db_path) as conn:
            private_row = conn.execute(
                """
                SELECT q.question, q.answer, p.user_name
                FROM questions q
                JOIN private_question_owners p ON p.question_id = q.id
                """
            ).fetchone()
            set_row = conn.execute(
                "SELECT user_name, exam, title FROM question_sets"
            ).fetchone()
            item_count = conn.execute(
                "SELECT COUNT(*) FROM question_set_items"
            ).fetchone()[0]
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        self.assertIn("脳・腎・肺", private_row[0])
        self.assertEqual(private_row[1:], ("b", "alice"))
        self.assertEqual(set_row, ("alice", DIAGNOSTIC_EXAM, "多臓器疾患17問"))
        self.assertEqual(item_count, 1)
        self.assertEqual(foreign_key_errors, [])

    def test_invalid_or_multiple_answer_is_rejected(self):
        self.write_manifest(answer="a,b")

        with self.assertRaisesRegex(
            manage_private_question_sets.PrivateQuestionSetError,
            "単一",
        ):
            self.create(dry_run=True)

    def test_manifest_inside_repository_is_rejected(self):
        with self.assertRaisesRegex(
            manage_private_question_sets.PrivateQuestionSetError,
            "リポジトリ外",
        ):
            manage_private_question_sets.private_manifest_path(
                manage_private_question_sets.APP_DIR / "private.json"
            )


if __name__ == "__main__":
    unittest.main()
