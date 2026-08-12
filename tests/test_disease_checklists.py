import http.client
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import server
from scripts import backup_to_google_drive


DIAGNOSTIC_EXAM = "放射線診断専門医認定試験"


class QuietAppHandler(server.AppHandler):
    def log_message(self, _format, *args):
        return


class DiseaseChecklistApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "questions.db"
        self.admin_env = mock.patch.dict(os.environ, {"KAKOMON_ADMIN_USERS": "alice"})
        self.admin_env.start()
        server.init_db()

        self.question_one = self.insert_question(1, "a")
        self.question_two = self.insert_question(2, "b")
        self.alice_checklist = self.insert_checklist("alice", "未出題疾患")
        self.base_item = self.insert_item(
            self.alice_checklist,
            0,
            "基礎対象疾患",
            base_included=True,
        )
        self.conditional_item = self.insert_item(
            self.alice_checklist,
            1,
            "誤答時追加疾患",
            base_included=False,
        )
        self.hidden_item = self.insert_item(
            self.alice_checklist,
            2,
            "未発動疾患",
            base_included=False,
        )
        self.unlinked_item = self.insert_item(
            self.alice_checklist,
            3,
            "常時表示疾患",
            base_included=True,
        )
        self.link_item(self.base_item, self.question_one, "correct")
        self.link_item(self.conditional_item, self.question_one, "structured_target")
        self.link_item(self.hidden_item, self.question_two, "correct")

        self.bob_checklist = self.insert_checklist("bob", "Bob疾患")
        self.bob_item = self.insert_item(
            self.bob_checklist,
            0,
            "Bob専用疾患",
            base_included=True,
        )
        self.link_item(self.bob_item, self.question_one, "correct")

        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietAppHandler)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.http_thread.join(timeout=5)
        server.DB_PATH = self.original_db_path
        self.admin_env.stop()
        self.temp_dir.cleanup()

    def insert_question(self, number, answer, *, exam=DIAGNOSTIC_EXAM):
        timestamp = "2026-08-07T00:00:00+00:00"
        with server.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO questions (
                    exam, year, category, question, choices, images,
                    answer, explanation, created_at, updated_at
                )
                VALUES (?, '2025', '中枢神経', ?, ?, '[]', ?, '', ?, ?)
                """,
                (
                    exam,
                    f"問{number}\nテスト問題{number}",
                    json.dumps(["選択肢a", "選択肢b", "選択肢c"], ensure_ascii=False),
                    answer,
                    timestamp,
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def insert_checklist(self, user_name, title):
        timestamp = "2026-08-07T00:00:00+00:00"
        with server.db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, timestamp),
            )
            cursor = conn.execute(
                """
                INSERT INTO disease_checklists (
                    user_name, exam, title, source_sha256, extraction_criteria,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'test-sha', 'correct-choice exclusion', ?, ?)
                """,
                (user_name, DIAGNOSTIC_EXAM, title, timestamp, timestamp),
            )
            return int(cursor.lastrowid)

    def insert_item(self, checklist_id, position, disease_name, *, base_included):
        timestamp = "2026-08-07T00:00:00+00:00"
        refs = [
            {
                "no": position + 1,
                "chapter": "画像診断学・IVR(各領域)",
                "major": "各論（中枢神経）",
                "middle": "テスト分類",
                "small": disease_name,
            }
        ]
        with server.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO disease_checklist_items (
                    checklist_id, position, disease_name, aliases_json,
                    concept_type, primary_area, areas_json, curriculum_refs_json,
                    base_included, review_note, sources_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'disease', '中枢神経', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checklist_id,
                    position,
                    disease_name,
                    json.dumps([f"{disease_name}別名"], ensure_ascii=False),
                    json.dumps(["中枢神経", "テスト分類"], ensure_ascii=False),
                    json.dumps(refs, ensure_ascii=False),
                    1 if base_included else 0,
                    "確認メモ",
                    json.dumps([{"label": "抽出根拠"}], ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def link_item(self, item_id, question_id, match_type):
        with server.db() as conn:
            conn.execute(
                """
                INSERT INTO disease_checklist_item_questions (
                    item_id, question_id, match_type, created_at
                )
                VALUES (?, ?, ?, '2026-08-07T00:00:00+00:00')
                """,
                (item_id, question_id, match_type),
            )

    def request_json(
        self,
        method,
        path,
        payload=None,
        *,
        content_type="application/json",
        headers=None,
        authenticated=True,
    ):
        body = None
        request_headers = dict(headers or {})
        if authenticated:
            request_headers.setdefault(server.TAILSCALE_LOGIN_HEADER, "alice")
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = content_type
            request_headers["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.httpd.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return response.status, parsed

    @staticmethod
    def query(user_name="alice", **values):
        return urlencode({"user": user_name, **values})

    def put_status(
        self,
        item_id,
        status,
        *,
        checklist_id=None,
        user_name="alice",
        content_type="application/json",
    ):
        target_checklist = checklist_id or self.alice_checklist
        return self.request_json(
            "PUT",
            f"/api/disease-checklists/{target_checklist}/items/{item_id}",
            {"user_name": user_name, "status": status},
            content_type=content_type,
        )

    def create_attempt(self, question_id, user_answer, *, self_mark="warn"):
        return self.request_json(
            "POST",
            "/api/attempts",
            {
                "question_id": question_id,
                "user_name": "alice",
                "user_answer": user_answer,
                "self_mark": self_mark,
            },
        )

    def test_schema_is_idempotent_and_protects_sticky_audit_evidence(self):
        server.init_db()
        server.init_db()
        with server.db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "disease_checklists",
                    "disease_checklist_items",
                    "disease_checklist_item_questions",
                    "disease_check_statuses",
                }.issubset(tables)
            )
            foreign_keys = conn.execute(
                "PRAGMA foreign_key_list(disease_checklist_items)"
            ).fetchall()
            self.assertTrue(
                any(
                    row["from"] == "ever_wrong_question_id"
                    and row["table"] == "questions"
                    and row["on_delete"].upper() == "RESTRICT"
                    for row in foreign_keys
                )
            )
            status_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(disease_check_statuses)"
                ).fetchall()
            }
            self.assertNotIn("user_name", status_columns)
            self.assertIn("note_updated_at", {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(disease_checklist_items)"
                ).fetchall()
            })
            conn.execute(
                """
                UPDATE disease_checklist_items
                SET ever_wrong_at = '2026-08-07T01:00:00+00:00',
                    ever_wrong_question_id = ?
                WHERE id = ?
                """,
                (self.question_one, self.conditional_item),
            )

        status, payload = self.request_json(
            "DELETE",
            f"/api/questions/{self.question_one}",
        )
        self.assertEqual(status, 400)
        self.assertIn("監査根拠", payload["error"])
        with server.db() as conn:
            activated = conn.execute(
                """
                SELECT ever_wrong_at, ever_wrong_question_id
                FROM disease_checklist_items WHERE id = ?
                """,
                (self.conditional_item,),
            ).fetchone()
            linked = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM disease_checklist_item_questions WHERE question_id = ?
                """,
                (self.question_one,),
            ).fetchone()["total"]
        self.assertIsNotNone(activated["ever_wrong_at"])
        self.assertEqual(activated["ever_wrong_question_id"], self.question_one)
        self.assertGreater(linked, 0)

    def test_list_and_detail_return_only_owner_active_items(self):
        status, payload = self.request_json(
            "GET",
            f"/api/disease-checklists?{self.query(exam=DIAGNOSTIC_EXAM)}",
            authenticated=False,
        )
        self.assertEqual(status, 404)
        status, payload = self.request_json(
            "GET",
            f"/api/disease-checklists?{self.query(exam=DIAGNOSTIC_EXAM)}",
            headers={server.TAILSCALE_LOGIN_HEADER: "bob"},
        )
        self.assertEqual(status, 404)
        status, _ = self.request_json(
            "GET",
            f"/api/disease-checklists/{self.alice_checklist}",
            authenticated=False,
        )
        self.assertEqual(status, 404)
        status, payload = self.request_json("GET", "/api/disease-checklists?user=alice")
        self.assertEqual(status, 400)

        status, payload = self.request_json(
            "GET",
            f"/api/disease-checklists?{self.query('bob', exam=DIAGNOSTIC_EXAM)}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        summary = payload["checklists"][0]
        self.assertEqual(summary["id"], self.alice_checklist)
        self.assertEqual(summary["item_count"], 2)
        self.assertEqual(summary["definition_count"], 4)
        self.assertEqual(summary["base_item_count"], 2)
        self.assertEqual(summary["ever_wrong_count"], 0)
        self.assertEqual(summary["added_by_wrong_count"], 0)
        self.assertEqual(
            summary["status_counts"],
            {"unreviewed": 2, "ok": 0, "warn": 0, "wrong": 0},
        )

        status, detail = self.request_json(
            "GET",
            f"/api/disease-checklists/{self.alice_checklist}?{self.query()}",
        )
        self.assertEqual(status, 200)
        items = detail["checklist"]["items"]
        self.assertEqual(
            [item["id"] for item in items],
            [self.base_item, self.unlinked_item],
        )
        first = items[0]
        self.assertEqual(first["primary_region"], "中枢神経")
        self.assertEqual(first["hierarchy"][0]["no"], 1)
        self.assertEqual(first["sources"], [{"label": "抽出根拠"}])
        self.assertIsNone(first["status"])
        self.assertIsNone(first["first_reviewed_at"])

        status, _ = self.request_json(
            "GET",
            f"/api/disease-checklists/{self.alice_checklist}?{self.query('bob')}",
        )
        self.assertEqual(status, 200)
        status, _ = self.request_json(
            "GET",
            f"/api/disease-checklists/{self.alice_checklist}?{self.query()}",
            headers={server.TAILSCALE_LOGIN_HEADER: "bob"},
        )
        self.assertEqual(status, 404)

    def test_put_status_validates_visibility_owner_and_content_type(self):
        target = f"/api/disease-checklists/{self.alice_checklist}/items/{self.base_item}"
        status, _ = self.request_json(
            "PUT",
            target,
            {"status": "ok"},
            authenticated=False,
        )
        self.assertEqual(status, 404)
        status, _ = self.request_json(
            "PUT",
            target,
            {"status": "ok"},
            headers={server.TAILSCALE_LOGIN_HEADER: "bob"},
        )
        self.assertEqual(status, 404)
        status, payload = self.put_status(
            self.base_item,
            "ok",
            content_type="text/plain",
        )
        self.assertEqual(status, 400)
        self.assertIn("Content-Type", payload["error"])
        status, _ = self.put_status(self.base_item, "maybe")
        self.assertEqual(status, 400)
        status, _ = self.put_status(self.hidden_item, "ok")
        self.assertEqual(status, 404)
        status, _ = self.put_status(
            self.bob_item,
            "ok",
            checklist_id=self.bob_checklist,
            user_name="alice",
        )
        self.assertEqual(status, 404)

        with mock.patch.object(server, "now_iso", return_value="2026-08-07T01:00:00+00:00"):
            status, first_payload = self.put_status(
                self.base_item,
                "ok",
                user_name="bob",
            )
        self.assertEqual(status, 200)
        first_item = first_payload["item"]
        self.assertEqual(first_item["status"], "ok")
        self.assertEqual(first_item["first_reviewed_at"], "2026-08-07T01:00:00+00:00")
        self.assertEqual(first_item["status_updated_at"], "2026-08-07T01:00:00+00:00")
        self.assertEqual(
            first_payload["checklist"]["status_counts"],
            {"unreviewed": 1, "ok": 1, "warn": 0, "wrong": 0},
        )

        with mock.patch.object(server, "now_iso", return_value="2026-08-07T02:00:00+00:00"):
            status, second_payload = self.put_status(self.base_item, "warn")
        self.assertEqual(status, 200)
        second_item = second_payload["item"]
        self.assertEqual(second_item["status"], "warn")
        self.assertEqual(second_item["first_reviewed_at"], "2026-08-07T01:00:00+00:00")
        self.assertEqual(second_item["status_updated_at"], "2026-08-07T02:00:00+00:00")

    def test_server_computed_wrong_answer_stickily_activates_only_owner_links(self):
        with mock.patch.object(server, "now_iso", return_value="2026-08-07T03:00:00+00:00"):
            status, wrong_payload = self.create_attempt(
                self.question_one,
                "b",
                self_mark="ok",
            )
        self.assertEqual(status, 200)
        self.assertFalse(wrong_payload["correct"])
        self.assertEqual(wrong_payload["disease_checklist_items_activated"], 2)
        wrong_attempt_id = wrong_payload["attempt_id"]

        with server.db() as conn:
            rows = {
                int(row["id"]): row
                for row in conn.execute(
                    """
                    SELECT id, ever_wrong_at, ever_wrong_question_id
                    FROM disease_checklist_items
                    WHERE id IN (?, ?, ?, ?)
                    """,
                    (
                        self.base_item,
                        self.conditional_item,
                        self.hidden_item,
                        self.bob_item,
                    ),
                ).fetchall()
            }
        self.assertEqual(rows[self.base_item]["ever_wrong_question_id"], self.question_one)
        self.assertEqual(
            rows[self.conditional_item]["ever_wrong_question_id"],
            self.question_one,
        )
        self.assertIsNone(rows[self.hidden_item]["ever_wrong_at"])
        self.assertIsNone(rows[self.bob_item]["ever_wrong_at"])

        status, detail = self.request_json(
            "GET",
            f"/api/disease-checklists/{self.alice_checklist}?{self.query()}",
        )
        self.assertEqual(status, 200)
        conditional = next(
            item
            for item in detail["checklist"]["items"]
            if item["id"] == self.conditional_item
        )
        self.assertTrue(conditional["ever_wrong"])
        self.assertTrue(conditional["added_by_wrong"])
        self.assertEqual(detail["checklist"]["item_count"], 3)
        self.assertEqual(detail["checklist"]["base_item_count"], 2)
        self.assertEqual(detail["checklist"]["ever_wrong_count"], 2)
        self.assertEqual(detail["checklist"]["added_by_wrong_count"], 1)

        with mock.patch.object(server, "now_iso", return_value="2026-08-07T04:00:00+00:00"):
            status, correct_payload = self.create_attempt(
                self.question_one,
                "a",
                self_mark="wrong",
            )
        self.assertEqual(status, 200)
        self.assertTrue(correct_payload["correct"])
        self.assertEqual(correct_payload["disease_checklist_items_activated"], 0)
        with server.db() as conn:
            sticky = conn.execute(
                """
                SELECT ever_wrong_at, ever_wrong_question_id
                FROM disease_checklist_items WHERE id = ?
                """,
                (self.conditional_item,),
            ).fetchone()
        self.assertEqual(sticky["ever_wrong_at"], "2026-08-07T03:00:00+00:00")
        self.assertEqual(sticky["ever_wrong_question_id"], self.question_one)

        status, _ = self.request_json(
            "DELETE",
            f"/api/attempts/{wrong_attempt_id}?{self.query()}",
        )
        self.assertEqual(status, 200)
        status, correct_only = self.create_attempt(
            self.question_two,
            "b",
            self_mark="wrong",
        )
        self.assertEqual(status, 200)
        self.assertTrue(correct_only["correct"])
        with server.db() as conn:
            hidden = conn.execute(
                "SELECT ever_wrong_at FROM disease_checklist_items WHERE id = ?",
                (self.hidden_item,),
            ).fetchone()
        self.assertIsNone(hidden["ever_wrong_at"])

        other_exam_question = self.insert_question(
            3,
            "a",
            exam="核医学専門医試験",
        )
        cross_exam_item = self.insert_item(
            self.alice_checklist,
            4,
            "別試験誤リンク疾患",
            base_included=False,
        )
        self.link_item(cross_exam_item, other_exam_question, "correct")
        status, cross_exam_attempt = self.create_attempt(
            other_exam_question,
            "b",
            self_mark="wrong",
        )
        self.assertEqual(status, 200)
        self.assertFalse(cross_exam_attempt["correct"])
        self.assertEqual(cross_exam_attempt["disease_checklist_items_activated"], 0)
        with server.db() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT ever_wrong_at FROM disease_checklist_items WHERE id = ?",
                    (cross_exam_item,),
                ).fetchone()["ever_wrong_at"]
            )

        status, _ = self.put_status(self.conditional_item, "wrong")
        self.assertEqual(status, 200)
        status, clear_payload = self.request_json(
            "DELETE",
            f"/api/attempts?{self.query()}",
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(clear_payload["deleted"], 1)
        with server.db() as conn:
            sticky = conn.execute(
                """
                SELECT ever_wrong_at FROM disease_checklist_items WHERE id = ?
                """,
                (self.conditional_item,),
            ).fetchone()
            saved_status = conn.execute(
                """
                SELECT status FROM disease_check_statuses
                WHERE item_id = ?
                """,
                (self.conditional_item,),
            ).fetchone()
        self.assertIsNotNone(sticky["ever_wrong_at"])
        self.assertEqual(saved_status["status"], "wrong")

    def test_user_with_checklist_cannot_be_deleted_and_backup_counts_include_tables(self):
        with server.db() as conn:
            alice_id = int(
                conn.execute("SELECT id FROM users WHERE name = 'alice'").fetchone()["id"]
            )
        status, payload = self.request_json(
            "DELETE",
            f"/api/users/{alice_id}",
        )
        self.assertEqual(status, 400)
        self.assertIn("疾患確認リスト", payload["error"])
        with server.db() as conn:
            self.assertIsNotNone(
                conn.execute("SELECT id FROM users WHERE id = ?", (alice_id,)).fetchone()
            )

        counts = backup_to_google_drive.db_counts(server.DB_PATH)
        self.assertEqual(counts["disease_checklists"], 2)
        self.assertEqual(counts["disease_checklist_items"], 5)
        self.assertEqual(counts["disease_checklist_item_questions"], 4)
        self.assertEqual(counts["disease_check_statuses"], 0)


if __name__ == "__main__":
    unittest.main()
