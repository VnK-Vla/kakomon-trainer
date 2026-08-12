import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import server


DIAGNOSTIC_EXAM = "放射線診断専門医認定試験"
NUCLEAR_EXAM = "核医学専門医試験"


class QuietAppHandler(server.AppHandler):
    def log_message(self, _format, *args):
        return


class QuestionSetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "questions.db"
        server.init_db()

        self.diagnostic_questions = [
            self.insert_question(DIAGNOSTIC_EXAM, "2025", "中枢神経", 1, "a"),
            self.insert_question(DIAGNOSTIC_EXAM, "2024", "胸部", 2, "b"),
            self.insert_question(DIAGNOSTIC_EXAM, "2023", "腹部", 3, "c"),
        ]
        self.nuclear_question = self.insert_question(
            NUCLEAR_EXAM,
            "2025",
            "核医学総論",
            1,
            "d",
        )
        self.alice_set = self.insert_question_set(
            "alice",
            DIAGNOSTIC_EXAM,
            "Alice 診断セット",
            self.diagnostic_questions[:2],
        )
        self.bob_set = self.insert_question_set(
            "bob",
            DIAGNOSTIC_EXAM,
            "Bob 診断セット",
            self.diagnostic_questions[1:],
        )

        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietAppHandler)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.http_thread.join(timeout=5)
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def insert_question(self, exam, year, category, number, answer):
        timestamp = server.now_iso()
        with server.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO questions (
                    exam, year, category, question, choices, images,
                    answer, explanation, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)
                """,
                (
                    exam,
                    year,
                    category,
                    f"問{number}\nテスト問題{number}",
                    json.dumps(["a", "b", "c", "d", "e"], ensure_ascii=False),
                    answer,
                    f"出典: {year}.pdf / 問{number}",
                    timestamp,
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def insert_question_set(self, user_name, exam, title, question_ids):
        timestamp = server.now_iso()
        with server.db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)",
                (user_name, timestamp),
            )
            cursor = conn.execute(
                """
                INSERT INTO question_sets (
                    user_name, exam, title, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_name, exam, title, timestamp, timestamp),
            )
            question_set_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO question_set_items (question_set_id, position, question_id)
                VALUES (?, ?, ?)
                """,
                [
                    (question_set_id, position, question_id)
                    for position, question_id in enumerate(question_ids)
                ],
            )
            return question_set_id

    def request_json(
        self,
        method,
        path,
        payload=None,
        content_type="application/json",
        extra_headers=None,
    ):
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(body))
        if extra_headers:
            headers.update(extra_headers)

        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.httpd.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return response.status, parsed

    def user_query(self, user_name="alice", **values):
        return urlencode({"user": user_name, **values})

    def start_round(self, question_set_id=None, user_name="alice"):
        if question_set_id is None:
            question_set_id = self.alice_set
        query = self.user_query(user_name)
        return self.request_json(
            "POST",
            f"/api/question-sets/{question_set_id}/rounds?{query}",
            {},
        )

    def abandon_round(self, question_set_id, round_id, user_name="alice"):
        query = self.user_query(user_name)
        return self.request_json(
            "POST",
            f"/api/question-sets/{question_set_id}/rounds/{round_id}/abandon?{query}",
            {},
        )

    def create_attempt(
        self,
        question_id,
        token,
        *,
        user_name="alice",
        user_answer="a",
        self_mark="warn",
        practice_session_token=None,
    ):
        payload = {
            "question_id": question_id,
            "user_name": user_name,
            "user_answer": user_answer,
            "self_mark": self_mark,
            "question_set_round_token": token,
        }
        if practice_session_token is not None:
            payload["practice_session_token"] = practice_session_token
        return self.request_json("POST", "/api/attempts", payload)

    def get_round_detail(self, question_set_id, round_id, user_name="alice", **page):
        query = self.user_query(user_name, **page)
        return self.request_json(
            "GET",
            f"/api/question-sets/{question_set_id}/rounds/{round_id}?{query}",
        )

    def test_schema_is_idempotent_and_round_snapshots_survive_source_deletes(self):
        server.init_db()
        server.init_db()
        with server.db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            foreign_keys = conn.execute(
                "PRAGMA foreign_key_list(question_set_round_items)"
            ).fetchall()
            indexes = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            ).fetchall()

        self.assertTrue(
            {
                "question_sets",
                "question_set_items",
                "question_set_rounds",
                "question_set_round_items",
            }.issubset(tables)
        )
        self.assertTrue(
            any(
                row["table"] == "questions"
                and row["from"] == "question_id"
                and row["on_delete"].upper() == "SET NULL"
                for row in foreign_keys
            )
        )
        self.assertTrue(
            any(
                "WHERE status = 'active'" in row["sql"]
                for row in indexes
            )
        )

    def test_list_start_resume_and_owner_isolation(self):
        status, _ = self.request_json(
            "GET",
            f"/api/question-sets?{self.user_query('alice')}",
        )
        self.assertEqual(status, 400)
        query = self.user_query("alice", exam=DIAGNOSTIC_EXAM)
        status, payload = self.request_json("GET", f"/api/question-sets?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        listed = payload["question_sets"][0]
        self.assertEqual(listed["id"], self.alice_set)
        self.assertEqual(listed["total"], 2)
        self.assertEqual(listed["rounds_count"], 0)
        self.assertIsNone(listed["active_round"])

        status, created_payload = self.start_round()
        self.assertEqual(status, 201)
        created = created_payload["round"]
        self.assertEqual(created["status"], "active")
        self.assertEqual(created["round_number"], 1)
        self.assertEqual(set(created["question_ids"]), set(self.diagnostic_questions[:2]))
        self.assertEqual(created["completed_question_ids"], [])
        self.assertIn(created["next_question_id"], created["question_ids"])

        status, resumed_payload = self.start_round()
        self.assertEqual(status, 200)
        self.assertEqual(resumed_payload["round"]["token"], created["token"])

        active_query = self.user_query("alice")
        status, active_payload = self.request_json(
            "GET",
            f"/api/question-sets/{self.alice_set}/rounds/active?{active_query}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(active_payload["round"]["token"], created["token"])

        for method, path, request_payload in (
            (
                "GET",
                f"/api/question-sets/{self.alice_set}/rounds/active?{self.user_query('bob')}",
                None,
            ),
            (
                "POST",
                f"/api/question-sets/{self.alice_set}/rounds?{self.user_query('bob')}",
                {},
            ),
            (
                "DELETE",
                f"/api/question-sets/{self.alice_set}?{self.user_query('bob')}",
                None,
            ),
        ):
            with self.subTest(method=method):
                status, _ = self.request_json(method, path, request_payload)
                self.assertEqual(status, 404)

    def test_round_mutations_require_json_content_type(self):
        query = self.user_query("alice")
        status, payload = self.request_json(
            "POST",
            f"/api/question-sets/{self.alice_set}/rounds?{query}",
            {},
            content_type="text/plain",
        )
        self.assertEqual(status, 400)
        self.assertIn("Content-Type", payload["error"])
        with server.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS total FROM question_set_rounds"
            ).fetchone()["total"]
        self.assertEqual(count, 0)

        _, started_payload = self.start_round()
        active = started_payload["round"]
        for path in (
            f"/api/question-sets/{self.alice_set}/rounds/restart?{query}",
            f"/api/question-sets/{self.alice_set}/rounds/{active['id']}/abandon?{query}",
        ):
            with self.subTest(path=path):
                status, payload = self.request_json(
                    "POST",
                    path,
                    {},
                    content_type="text/plain",
                )
                self.assertEqual(status, 400)
                self.assertIn("Content-Type", payload["error"])
        with server.db() as conn:
            status = conn.execute(
                "SELECT status FROM question_set_rounds WHERE id = ?",
                (active["id"],),
            ).fetchone()["status"]
        self.assertEqual(status, "active")

    def test_every_id_endpoint_hides_another_owners_set_and_round(self):
        _, payload = self.start_round()
        round_id = payload["round"]["id"]
        query = self.user_query("bob")
        cases = (
            ("GET", f"/api/question-sets/{self.alice_set}/rounds?{query}", None),
            (
                "GET",
                f"/api/question-sets/{self.alice_set}/rounds/{round_id}?{query}",
                None,
            ),
            (
                "POST",
                f"/api/question-sets/{self.alice_set}/rounds/restart?{query}",
                {},
            ),
            (
                "POST",
                f"/api/question-sets/{self.alice_set}/rounds/{round_id}/abandon?{query}",
                {},
            ),
            (
                "DELETE",
                f"/api/question-sets/{self.alice_set}/rounds/{round_id}?{query}",
                None,
            ),
        )
        for method, path, request_payload in cases:
            with self.subTest(method=method, path=path):
                status, _ = self.request_json(method, path, request_payload)
                self.assertEqual(status, 404)

    def test_concurrent_starts_create_only_one_active_round(self):
        barrier = threading.Barrier(3)
        results = []

        def start():
            barrier.wait()
            results.append(self.start_round())

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(sorted(status for status, _ in results), [200, 201])
        self.assertEqual(len({payload["round"]["token"] for _, payload in results}), 1)
        with server.db() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM question_set_rounds
                WHERE question_set_id = ?
                GROUP BY status
                """,
                (self.alice_set,),
            ).fetchall()
        self.assertEqual([(row["status"], row["total"]) for row in rows], [("active", 1)])

    def test_attempts_complete_round_and_snapshot_results_and_self_mark_updates(self):
        _, start_payload = self.start_round()
        active = start_payload["round"]
        first_id, second_id = active["question_ids"]

        status, first_payload = self.create_attempt(
            first_id,
            active["token"],
            user_answer="e",
            self_mark="wrong",
        )
        self.assertEqual(status, 200)
        self.assertFalse(first_payload["question_set_round_stale"])
        self.assertEqual(first_payload["question_set_round"]["summary"]["completed"], 1)
        first_attempt_id = first_payload["attempt_id"]

        correct_answer = {
            self.diagnostic_questions[0]: "a",
            self.diagnostic_questions[1]: "b",
        }[second_id]
        status, second_payload = self.create_attempt(
            second_id,
            active["token"],
            user_answer=correct_answer,
            self_mark="ok",
        )
        self.assertEqual(status, 200)
        completed = second_payload["question_set_round"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["summary"]["completed"], 2)
        self.assertEqual(completed["summary"]["remaining"], 0)
        self.assertEqual(completed["summary"]["graded"], 2)
        self.assertEqual(completed["summary"]["correct"], 1)
        self.assertEqual(completed["summary"]["rate"], 50.0)
        self.assertEqual(completed["summary"]["self_marks"], {"ok": 1, "warn": 0, "wrong": 1})
        self.assertEqual(completed["completed"], completed["summary"]["completed"])
        self.assertEqual(completed["self_marks"], completed["summary"]["self_marks"])

        status, _ = self.request_json(
            "PUT",
            f"/api/attempts/{first_attempt_id}",
            {"user_name": "alice", "self_mark": "warn"},
        )
        self.assertEqual(status, 200)
        status, detail_payload = self.get_round_detail(self.alice_set, active["id"])
        self.assertEqual(status, 200)
        detail = detail_payload["round"]
        self.assertEqual(detail["summary"]["self_marks"], {"ok": 1, "warn": 1, "wrong": 0})
        first_item = next(item for item in detail["items"] if item["attempt_id"] == first_attempt_id)
        self.assertEqual(first_item["user_answer"], "e")
        self.assertEqual(first_item["is_correct"], 0)
        self.assertEqual(first_item["self_mark"], "warn")
        self.assertIsNotNone(first_item["question_number"])

    def test_restart_abandons_old_round_and_stale_token_only_saves_attempt(self):
        _, first_payload = self.start_round()
        first = first_payload["round"]
        answered_id = first["question_ids"][0]
        self.create_attempt(answered_id, first["token"], user_answer="e")

        query = self.user_query("alice")
        status, restarted_payload = self.request_json(
            "POST",
            f"/api/question-sets/{self.alice_set}/rounds/restart?{query}",
            {},
        )
        self.assertEqual(status, 201)
        restarted = restarted_payload["round"]
        self.assertEqual(restarted["round_number"], 2)
        self.assertNotEqual(restarted["token"], first["token"])
        self.assertNotEqual(restarted["question_ids"], first["question_ids"])

        status, stale_payload = self.create_attempt(
            answered_id,
            first["token"],
            user_answer="a",
        )
        self.assertEqual(status, 200)
        self.assertTrue(stale_payload["question_set_round_stale"])
        self.assertIsNone(stale_payload["question_set_round"])

        status, history_payload = self.request_json(
            "GET",
            f"/api/question-sets/{self.alice_set}/rounds?{query}",
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["round_number"] for item in history_payload["rounds"]], [2, 1])
        self.assertEqual(history_payload["rounds"][1]["status"], "abandoned")
        self.assertEqual(history_payload["rounds"][1]["summary"]["completed"], 1)
        status, page_payload = self.request_json(
            "GET",
            f"/api/question-sets/{self.alice_set}/rounds?{query}&limit=1&offset=1",
        )
        self.assertEqual(status, 200)
        self.assertEqual(page_payload["total"], 2)
        self.assertEqual(page_payload["limit"], 1)
        self.assertEqual([item["round_number"] for item in page_payload["rounds"]], [1])
        with server.db() as conn:
            attempts = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = 'alice'"
            ).fetchone()["total"]
        self.assertEqual(attempts, 2)

    def test_abandon_delete_round_and_set_leave_attempts_intact(self):
        _, payload = self.start_round()
        active = payload["round"]
        status, attempt_payload = self.create_attempt(
            active["question_ids"][0],
            active["token"],
        )
        self.assertEqual(status, 200)
        attempt_id = attempt_payload["attempt_id"]
        query = self.user_query("alice")

        status, _ = self.request_json(
            "DELETE",
            f"/api/question-sets/{self.alice_set}/rounds/{active['id']}?{query}",
        )
        self.assertEqual(status, 409)

        status, abandoned_payload = self.abandon_round(self.alice_set, active["id"])
        self.assertEqual(status, 200)
        self.assertEqual(abandoned_payload["round"]["status"], "abandoned")
        status, _ = self.request_json(
            "DELETE",
            f"/api/question-sets/{self.alice_set}/rounds/{active['id']}?{query}",
        )
        self.assertEqual(status, 200)
        with server.db() as conn:
            self.assertIsNotNone(
                conn.execute("SELECT id FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
            )

        _, second_payload = self.start_round()
        status, _ = self.request_json(
            "DELETE",
            f"/api/question-sets/{self.alice_set}?{query}",
        )
        self.assertEqual(status, 200)
        with server.db() as conn:
            attempts = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = 'alice'"
            ).fetchone()["total"]
            rounds = conn.execute(
                "SELECT COUNT(*) AS total FROM question_set_rounds WHERE question_set_id = ?",
                (self.alice_set,),
            ).fetchone()["total"]
        self.assertEqual(attempts, 1)
        self.assertEqual(rounds, 0)
        self.assertEqual(second_payload["round"]["round_number"], 1)

    def test_round_snapshot_survives_question_and_attempt_deletion(self):
        _, payload = self.start_round()
        active = payload["round"]
        answered_id = active["question_ids"][0]
        _, attempt_payload = self.create_attempt(
            answered_id,
            active["token"],
            user_answer="e",
            self_mark="wrong",
        )
        attempt_id = attempt_payload["attempt_id"]

        status, _ = self.request_json(
            "DELETE",
            f"/api/attempts/{attempt_id}?{self.user_query('alice')}",
        )
        self.assertEqual(status, 200)
        with server.db() as conn:
            conn.execute("DELETE FROM questions WHERE id = ?", (answered_id,))

        status, detail_payload = self.get_round_detail(
            self.alice_set,
            active["id"],
            limit=1,
            offset=0,
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail_payload["limit"], 1)
        self.assertTrue(detail_payload["has_more"])
        self.assertEqual(len(detail_payload["items"]), 1)
        status, all_detail_payload = self.get_round_detail(self.alice_set, active["id"])
        self.assertEqual(status, 200)
        unavailable_item = next(
            item
            for item in all_detail_payload["round"]["items"]
            if item["source_question_id"] == answered_id
        )
        self.assertFalse(unavailable_item["available"])
        self.assertIsNone(unavailable_item["question_id"])
        self.assertIsNone(unavailable_item["attempt_id"])
        self.assertEqual(unavailable_item["user_answer"], "e")
        self.assertEqual(unavailable_item["is_correct"], 0)
        self.assertEqual(unavailable_item["self_mark"], "wrong")
        self.assertTrue(unavailable_item["year"])
        self.assertTrue(unavailable_item["category"])
        self.assertEqual(all_detail_payload["round"]["summary"]["unavailable"], 1)

    def test_round_and_item_pagination_boundaries_are_20_and_100(self):
        timestamp = server.now_iso()
        latest_round_id = None
        with server.db() as conn:
            for round_number in range(1, 22):
                cursor = conn.execute(
                    """
                    INSERT INTO question_set_rounds (
                        question_set_id, round_number, token, status,
                        created_at, updated_at, completed_at, abandoned_at
                    )
                    VALUES (?, ?, ?, 'abandoned', ?, ?, NULL, ?)
                    """,
                    (
                        self.alice_set,
                        round_number,
                        f"manual-token-{round_number}",
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                latest_round_id = int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO question_set_round_items (
                        round_id, position, question_id, source_question_id,
                        source_year, source_category, source_question_number
                    )
                    VALUES (?, 0, ?, ?, '2025', '中枢神経', 1)
                    """,
                    (
                        latest_round_id,
                        self.diagnostic_questions[0],
                        self.diagnostic_questions[0],
                    ),
                )
            conn.executemany(
                """
                INSERT INTO question_set_round_items (
                    round_id, position, question_id, source_question_id,
                    source_year, source_category, source_question_number
                )
                VALUES (?, ?, NULL, ?, '2025', '削除済み', ?)
                """,
                [
                    (latest_round_id, position, 10000 + position, position + 1)
                    for position in range(1, 101)
                ],
            )

        query = self.user_query("alice")
        status, first_page = self.request_json(
            "GET",
            f"/api/question-sets/{self.alice_set}/rounds?{query}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(first_page["limit"], 20)
        self.assertEqual(first_page["total"], 21)
        self.assertEqual(len(first_page["rounds"]), 20)
        self.assertTrue(first_page["has_more"])
        status, second_page = self.request_json(
            "GET",
            f"/api/question-sets/{self.alice_set}/rounds?{query}&offset=20",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(second_page["rounds"]), 1)
        self.assertFalse(second_page["has_more"])

        status, first_items = self.get_round_detail(
            self.alice_set,
            latest_round_id,
        )
        self.assertEqual(status, 200)
        self.assertEqual(first_items["limit"], 100)
        self.assertEqual(first_items["total"], 101)
        self.assertEqual(len(first_items["items"]), 100)
        self.assertTrue(first_items["has_more"])
        status, last_item = self.get_round_detail(
            self.alice_set,
            latest_round_id,
            offset=100,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(last_item["items"]), 1)
        self.assertEqual(last_item["items"][0]["position"], 101)
        self.assertFalse(last_item["has_more"])

    def test_overlapping_sets_keep_progress_isolated_and_tokens_are_exclusive(self):
        overlap_set = self.insert_question_set(
            "alice",
            DIAGNOSTIC_EXAM,
            "重複セット",
            [self.diagnostic_questions[0]],
        )
        _, first_payload = self.start_round()
        _, overlap_payload = self.start_round(overlap_set)
        first = first_payload["round"]
        overlap = overlap_payload["round"]

        _, attempt_payload = self.create_attempt(
            self.diagnostic_questions[0],
            first["token"],
        )
        self.assertEqual(attempt_payload["question_set_round"]["summary"]["completed"], 1)
        status, overlap_active = self.request_json(
            "GET",
            f"/api/question-sets/{overlap_set}/rounds/active?{self.user_query('alice')}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(overlap_active["round"]["summary"]["completed"], 0)

        status, quick_payload = self.request_json(
            "POST",
            "/api/practice-session",
            {
                "user_name": "alice",
                "exam": DIAGNOSTIC_EXAM,
                "question_ids": [self.diagnostic_questions[0]],
                "filters": {},
            },
        )
        self.assertEqual(status, 201)
        before_count = None
        with server.db() as conn:
            before_count = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = 'alice'"
            ).fetchone()["total"]
        status, rejected = self.create_attempt(
            self.diagnostic_questions[0],
            overlap["token"],
            practice_session_token=quick_payload["practice_session"]["token"],
        )
        self.assertEqual(status, 400)
        self.assertIn("error", rejected)
        with server.db() as conn:
            after_count = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = 'alice'"
            ).fetchone()["total"]
        self.assertEqual(after_count, before_count)

    def test_clear_attempts_deletes_only_owner_rounds_and_keeps_set_definitions(self):
        _, alice_payload = self.start_round()
        _, bob_payload = self.start_round(self.bob_set, "bob")
        self.create_attempt(alice_payload["round"]["question_ids"][0], alice_payload["round"]["token"])
        self.create_attempt(
            bob_payload["round"]["question_ids"][0],
            bob_payload["round"]["token"],
            user_name="bob",
        )

        status, payload = self.request_json(
            "DELETE",
            f"/api/attempts?{self.user_query('alice')}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["question_set_rounds_deleted"], 1)
        with server.db() as conn:
            alice_sets = conn.execute(
                "SELECT COUNT(*) AS total FROM question_sets WHERE user_name = 'alice'"
            ).fetchone()["total"]
            alice_items = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM question_set_items i
                JOIN question_sets s ON s.id = i.question_set_id
                WHERE s.user_name = 'alice'
                """
            ).fetchone()["total"]
            alice_rounds = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM question_set_rounds r
                JOIN question_sets s ON s.id = r.question_set_id
                WHERE s.user_name = 'alice'
                """
            ).fetchone()["total"]
            bob_rounds = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM question_set_rounds r
                JOIN question_sets s ON s.id = r.question_set_id
                WHERE s.user_name = 'bob'
                """
            ).fetchone()["total"]
        self.assertEqual(alice_sets, 1)
        self.assertEqual(alice_items, 2)
        self.assertEqual(alice_rounds, 0)
        self.assertEqual(bob_rounds, 1)

    def test_user_with_a_question_set_cannot_be_deleted(self):
        with server.db() as conn:
            alice_id = conn.execute(
                "SELECT id FROM users WHERE name = 'alice'"
            ).fetchone()["id"]

        with mock.patch.dict(server.os.environ, {"KAKOMON_ADMIN_USERS": "admin@example.com"}):
            status, payload = self.request_json(
                "DELETE",
                f"/api/users/{alice_id}",
                extra_headers={server.TAILSCALE_LOGIN_HEADER: "admin@example.com"},
            )

        self.assertEqual(status, 400)
        self.assertIn("問題セット", payload["error"])
        with server.db() as conn:
            self.assertIsNotNone(
                conn.execute("SELECT id FROM users WHERE id = ?", (alice_id,)).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
