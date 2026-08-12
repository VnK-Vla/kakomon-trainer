import contextlib
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import manage_disease_checklists


EXAM = manage_disease_checklists.EXPECTED_EXAM
OTHER_EXAM = "核医学専門医試験"


class ManageDiseaseChecklistsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "questions.db"
        self.db_path.parent.mkdir()
        self.backup_root = self.root / "backups"
        self.manifest_path = self.root / "manifest.json"
        self.review_path = self.root / "review.tsv"
        self.create_schema()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                ("alice", "2026-08-01T00:00:00+00:00"),
            )
            conn.executemany(
                "INSERT INTO questions (id, exam, year, category) VALUES (?, ?, ?, ?)",
                [
                    (1, EXAM, "2025", "中枢神経"),
                    (2, EXAM, "2024", "呼吸器・縦隔"),
                    (3, OTHER_EXAM, "2025", "核医学"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO attempts (
                    id, user_name, question_id, is_correct, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (1, "alice", 1, 0, "2026-08-03T00:00:00+00:00"),
                    (2, "alice", 1, 1, "2026-08-04T00:00:00+00:00"),
                    (3, "alice", 1, 0, "2026-08-02T00:00:00+00:00"),
                ],
            )
        self.payload = self.valid_payload()
        self.write_manifest()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE users (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY,
                    exam TEXT NOT NULL,
                    year TEXT NOT NULL,
                    category TEXT NOT NULL
                );
                CREATE TABLE attempts (
                    id INTEGER PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    question_id INTEGER NOT NULL,
                    is_correct INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_name) REFERENCES users(name),
                    FOREIGN KEY(question_id) REFERENCES questions(id)
                );
                CREATE TABLE disease_checklists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    exam TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    extraction_criteria TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_name, exam, title),
                    FOREIGN KEY(user_name) REFERENCES users(name) ON DELETE CASCADE
                );
                CREATE TABLE disease_checklist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checklist_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    disease_name TEXT NOT NULL,
                    aliases_json TEXT NOT NULL,
                    concept_type TEXT NOT NULL,
                    primary_area TEXT NOT NULL,
                    areas_json TEXT NOT NULL,
                    curriculum_refs_json TEXT NOT NULL,
                    base_included INTEGER NOT NULL CHECK(base_included IN (0, 1)),
                    review_note TEXT NOT NULL DEFAULT '',
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    note_updated_at TEXT,
                    ever_wrong_at TEXT,
                    ever_wrong_question_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(checklist_id, position),
                    UNIQUE(checklist_id, disease_name),
                    FOREIGN KEY(checklist_id) REFERENCES disease_checklists(id) ON DELETE CASCADE,
                    FOREIGN KEY(ever_wrong_question_id) REFERENCES questions(id) ON DELETE RESTRICT
                );
                CREATE TABLE disease_checklist_item_questions (
                    item_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    match_type TEXT NOT NULL CHECK(match_type IN ('correct', 'structured_target')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, question_id, match_type),
                    FOREIGN KEY(item_id) REFERENCES disease_checklist_items(id) ON DELETE CASCADE,
                    FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE RESTRICT
                );
                CREATE TABLE disease_check_statuses (
                    item_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('ok', 'warn', 'wrong')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES disease_checklist_items(id) ON DELETE CASCADE
                );
                """
            )

    def valid_payload(self):
        items = []
        for index in range(manage_disease_checklists.EXPECTED_ITEM_COUNT):
            included = index < manage_disease_checklists.EXPECTED_BASE_INCLUDED
            links = []
            if index == 0:
                links = [{"question_id": 1, "match_type": "structured_target"}]
            elif not included:
                links = [{"question_id": 2, "match_type": "correct"}]
            items.append(
                {
                    "disease_name": f"疾患{index:03d}",
                    "aliases": [f"別名{index:03d}"],
                    "concept_type": "disease",
                    "primary_area": "中枢神経",
                    "areas": ["中枢神経"],
                    "curriculum_refs": [
                        {
                            "no": index + 1,
                            "chapter": "画像診断学・IVR(各領域)",
                            "major": "各論",
                            "middle": "中枢神経",
                            "small": f"疾患{index:03d}",
                        }
                    ],
                    "base_included": included,
                    "question_links": links,
                }
            )
        return {
            "title": "診断専門医 未正答疾患チェック",
            "exam": EXAM,
            "source_sha256": manage_disease_checklists.EXPECTED_SOURCE_SHA256,
            "extraction_criteria": "登録正答肢に出現する疾患を基本一覧から除外する。",
            "items": items,
        }

    def write_manifest(self):
        self.manifest_path.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )

    def create(self, *, dry_run=False):
        return manage_disease_checklists.create_disease_checklist(
            self.manifest_path,
            user_name="alice",
            db_path=self.db_path,
            dry_run=dry_run,
            backup_root=self.backup_root,
        )

    def test_dry_run_validates_audited_counts_without_writing_or_leaking_owner(self):
        result = self.create(dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["item_count"], 790)
        self.assertEqual(result["base_included_count"], 621)
        self.assertEqual(result["hidden_count"], 169)
        self.assertEqual(result["correct_link_count"], 169)
        self.assertEqual(result["structured_target_link_count"], 1)
        self.assertEqual(result["ever_wrong_activation_count"], 1)
        self.assertNotIn("user", result)
        self.assertFalse(self.backup_root.exists())
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM disease_checklists").fetchone()[0],
                0,
            )

    def test_cli_dry_run_outputs_json_without_owner_name(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = manage_disease_checklists.main(
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
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("alice", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["item_count"], 790)

    def test_create_backs_up_then_inserts_all_rows_and_first_wrong_is_sticky(self):
        result = self.create()

        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        with sqlite3.connect(backup) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM disease_checklists").fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        with sqlite3.connect(self.db_path) as conn:
            checklist = conn.execute(
                "SELECT user_name, source_sha256 FROM disease_checklists"
            ).fetchone()
            counts = (
                conn.execute("SELECT COUNT(*) FROM disease_checklist_items").fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM disease_checklist_item_questions"
                ).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM disease_check_statuses").fetchone()[0],
            )
            first = conn.execute(
                """
                SELECT ever_wrong_at, ever_wrong_question_id
                FROM disease_checklist_items WHERE position=0
                """
            ).fetchone()
        self.assertEqual(checklist[0], "alice")
        self.assertEqual(checklist[1], manage_disease_checklists.EXPECTED_SOURCE_SHA256)
        self.assertEqual(counts, (790, 170, 0))
        self.assertEqual(first, ("2026-08-02T00:00:00+00:00", 1))

    def test_duplicate_title_and_manifest_shape_errors_are_rejected(self):
        self.create()
        with self.assertRaisesRegex(
            manage_disease_checklists.DiseaseChecklistError, "同名"
        ):
            self.create(dry_run=True)

        cases = []
        payload = self.valid_payload()
        payload["unexpected"] = True
        cases.append((payload, "未対応のキー"))
        payload = self.valid_payload()
        payload["source_sha256"] = "0" * 64
        cases.append((payload, "source_sha256"))
        payload = self.valid_payload()
        payload["items"].pop()
        cases.append((payload, "790"))
        for payload, pattern in cases:
            with self.subTest(pattern=pattern):
                self.payload = payload
                self.write_manifest()
                with self.assertRaisesRegex(
                    manage_disease_checklists.DiseaseChecklistError, pattern
                ):
                    manage_disease_checklists.load_manifest(self.manifest_path)

    def test_duplicate_entities_links_and_hidden_rules_are_rejected(self):
        cases = []
        payload = self.valid_payload()
        payload["items"][1]["disease_name"] = payload["items"][0]["disease_name"]
        cases.append((payload, "disease_nameに重複"))
        payload = self.valid_payload()
        payload["items"][0]["aliases"] = ["同じ", " 同じ "]
        cases.append((payload, "aliases.*重複"))
        payload = self.valid_payload()
        payload["items"][0]["question_links"].append(
            {"question_id": 1, "match_type": "structured_target"}
        )
        cases.append((payload, "question_idに重複"))
        payload = self.valid_payload()
        payload["items"][0]["question_links"] = [
            {"question_id": 1, "match_type": "correct"}
        ]
        cases.append((payload, "base_included=true"))
        payload = self.valid_payload()
        payload["items"][621]["question_links"] = []
        cases.append((payload, "correct link"))
        for payload, pattern in cases:
            with self.subTest(pattern=pattern):
                self.payload = payload
                self.write_manifest()
                with self.assertRaisesRegex(
                    manage_disease_checklists.DiseaseChecklistError, pattern
                ):
                    manage_disease_checklists.load_manifest(self.manifest_path)

    def test_hidden_item_can_keep_structured_target_link_beside_correct_link(self):
        hidden = self.payload["items"][621]
        hidden["question_links"].append(
            {"question_id": 1, "match_type": "structured_target"}
        )
        self.write_manifest()

        manifest = manage_disease_checklists.load_manifest(self.manifest_path)

        self.assertFalse(manifest["items"][621]["base_included"])
        self.assertEqual(
            manifest["items"][621]["question_links"],
            [
                {"question_id": 2, "match_type": "correct"},
                {"question_id": 1, "match_type": "structured_target"},
            ],
        )

    def test_missing_and_wrong_exam_question_ids_are_rejected(self):
        cases = [(99, "存在しない問題ID"), (3, "指定examに属さない問題ID")]
        for question_id, pattern in cases:
            with self.subTest(question_id=question_id):
                self.payload = self.valid_payload()
                self.payload["items"][0]["question_links"] = [
                    {"question_id": question_id, "match_type": "structured_target"}
                ]
                self.write_manifest()
                with self.assertRaisesRegex(
                    manage_disease_checklists.DiseaseChecklistError, pattern
                ):
                    self.create(dry_run=True)
        self.assertFalse(self.backup_root.exists())

    def test_failed_item_insert_rolls_back_all_creation(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TRIGGER reject_second_disease_item
                BEFORE INSERT ON disease_checklist_items
                WHEN NEW.position = 1
                BEGIN
                    SELECT RAISE(ABORT, 'test failure');
                END;
                """
            )
        with self.assertRaisesRegex(
            manage_disease_checklists.DiseaseChecklistError, "ロールバック"
        ):
            self.create()
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM disease_checklists").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM disease_checklist_items").fetchone()[0],
                0,
            )
        self.assertEqual(
            len(list(self.backup_root.glob("before-disease-checklist-*/questions.db"))),
            1,
        )

    def test_export_review_is_owner_scoped_and_import_notes_round_trips(self):
        checklist_id = self.create()["checklist_id"]
        with sqlite3.connect(self.db_path) as conn:
            item_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM disease_checklist_items ORDER BY position LIMIT 3"
                )
            ]
            conn.executemany(
                """
                INSERT INTO disease_check_statuses (
                    item_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (item_ids[0], "wrong", "2026-08-07", "2026-08-07"),
                    (item_ids[1], "warn", "2026-08-07", "2026-08-07"),
                    (item_ids[2], "ok", "2026-08-07", "2026-08-07"),
                ],
            )

        result = manage_disease_checklists.export_review(
            checklist_id=checklist_id,
            user_name="alice",
            output_path=self.review_path,
            db_path=self.db_path,
        )
        self.assertEqual(result["exported_count"], 2)
        self.assertEqual(result["missing_note_count"], 2)
        with self.review_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual({row["status"] for row in rows}, {"wrong", "warn"})
        rows[0]["review_note"] = "特徴を再確認する"
        rows[0]["sources"] = "https://example.org/guideline"
        rows[1]["review_note"] = "鑑別を復習する"
        rows[1]["sources"] = "https://example.org/review"
        with self.review_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=manage_disease_checklists.REVIEW_TSV_FIELDS,
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows(rows)

        dry_run = manage_disease_checklists.import_notes(
            self.review_path,
            checklist_id=checklist_id,
            user_name="alice",
            db_path=self.db_path,
            dry_run=True,
            backup_root=self.backup_root,
        )
        self.assertEqual(dry_run["update_count"], 2)
        backups_before = len(list(self.backup_root.glob("*/questions.db")))
        result = manage_disease_checklists.import_notes(
            self.review_path,
            checklist_id=checklist_id,
            user_name="alice",
            db_path=self.db_path,
            backup_root=self.backup_root,
        )
        self.assertEqual(result["update_count"], 2)
        self.assertEqual(
            len(list(self.backup_root.glob("*/questions.db"))), backups_before + 1
        )
        with sqlite3.connect(self.db_path) as conn:
            imported = conn.execute(
                """
                SELECT review_note, sources_json, note_updated_at
                FROM disease_checklist_items WHERE id=?
                """,
                (int(rows[0]["item_id"]),),
            ).fetchone()
        self.assertEqual(imported[0], "特徴を再確認する")
        self.assertEqual(json.loads(imported[1]), ["https://example.org/guideline"])
        self.assertIsNotNone(imported[2])

        with self.assertRaisesRegex(
            manage_disease_checklists.DiseaseChecklistError, "見つかりません"
        ):
            manage_disease_checklists.export_review(
                checklist_id=checklist_id,
                user_name="bob",
                output_path=self.root / "bob.tsv",
                db_path=self.db_path,
            )

    def test_export_review_does_not_infer_status_from_ever_wrong(self):
        checklist_id = self.create()["checklist_id"]

        result = manage_disease_checklists.export_review(
            checklist_id=checklist_id,
            user_name="alice",
            output_path=self.review_path,
            db_path=self.db_path,
        )

        self.assertEqual(result["exported_count"], 0)
        with self.review_path.open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle, delimiter="\t")), [])

    def test_import_notes_rejects_html_and_non_https_sources(self):
        checklist_id = self.create()["checklist_id"]
        with sqlite3.connect(self.db_path) as conn:
            item_id = conn.execute(
                "SELECT id FROM disease_checklist_items WHERE position=0"
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO disease_check_statuses (
                    item_id, status, created_at, updated_at
                ) VALUES (?, 'wrong', '2026-08-07', '2026-08-07')
                """,
                (item_id,),
            )
        manage_disease_checklists.export_review(
            checklist_id=checklist_id,
            user_name="alice",
            output_path=self.review_path,
            db_path=self.db_path,
        )
        with self.review_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        cases = [("<b>危険</b>", "https://example.org", "プレーンテキスト"), ("復習", "http://example.org", "HTTPS")]
        for note, source, pattern in cases:
            with self.subTest(pattern=pattern):
                row = dict(rows[0])
                row["review_note"] = note
                row["sources"] = source
                with self.review_path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=manage_disease_checklists.REVIEW_TSV_FIELDS,
                        delimiter="\t",
                    )
                    writer.writeheader()
                    writer.writerow(row)
                with self.assertRaisesRegex(
                    manage_disease_checklists.DiseaseChecklistError, pattern
                ):
                    manage_disease_checklists.import_notes(
                        self.review_path,
                        checklist_id=checklist_id,
                        user_name="alice",
                        db_path=self.db_path,
                        dry_run=True,
                        backup_root=self.backup_root,
                    )

    def test_private_export_rejects_repository_paths(self):
        with self.assertRaisesRegex(
            manage_disease_checklists.DiseaseChecklistError, "リポジトリ内"
        ):
            manage_disease_checklists._private_path(
                manage_disease_checklists.APP_DIR / "review.tsv"
            )

    def test_sync_links_only_adds_and_activates_historical_wrong(self):
        checklist_id = self.create()["checklist_id"]
        self.payload["items"][1]["question_links"] = [
            {"question_id": 1, "match_type": "structured_target"}
        ]
        self.write_manifest()

        dry_run = manage_disease_checklists.sync_links(
            self.manifest_path,
            user_name="alice",
            db_path=self.db_path,
            dry_run=True,
            backup_root=self.backup_root,
        )
        self.assertEqual(dry_run["add_link_count"], 1)
        self.assertFalse(dry_run["changed"])
        result = manage_disease_checklists.sync_links(
            self.manifest_path,
            user_name="alice",
            db_path=self.db_path,
            backup_root=self.backup_root,
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["add_link_count"], 1)
        self.assertEqual(result["new_ever_wrong_activation_count"], 1)
        with sqlite3.connect(self.db_path) as conn:
            item = conn.execute(
                """
                SELECT ever_wrong_at, ever_wrong_question_id
                FROM disease_checklist_items
                WHERE checklist_id=? AND position=1
                """,
                (checklist_id,),
            ).fetchone()
            links = conn.execute(
                "SELECT COUNT(*) FROM disease_checklist_item_questions"
            ).fetchone()[0]
        self.assertEqual(item, ("2026-08-02T00:00:00+00:00", 1))
        self.assertEqual(links, 171)

    def test_missing_schema_fails_without_initializing_or_backing_up(self):
        incomplete = self.root / "incomplete.db"
        with sqlite3.connect(incomplete) as conn:
            conn.execute("CREATE TABLE users (name TEXT PRIMARY KEY)")
        with self.assertRaisesRegex(
            manage_disease_checklists.DiseaseChecklistError, "再起動"
        ):
            manage_disease_checklists.create_disease_checklist(
                self.manifest_path,
                user_name="alice",
                db_path=incomplete,
                backup_root=self.backup_root,
            )
        self.assertFalse(self.backup_root.exists())


if __name__ == "__main__":
    unittest.main()
