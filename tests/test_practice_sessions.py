import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

import server


DIAGNOSTIC_EXAM = "放射線診断専門医認定試験"
NUCLEAR_EXAM = "核医学専門医試験"


class QuietAppHandler(server.AppHandler):
    def log_message(self, _format, *args):
        return


class PracticeSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "questions.db"
        server.init_db()

        self.diagnostic_questions = [
            self.insert_question(DIAGNOSTIC_EXAM, "2025", "中枢神経", "診断問題1", "a"),
            self.insert_question(DIAGNOSTIC_EXAM, "2024", "胸部", "診断問題2", "b"),
            self.insert_question(DIAGNOSTIC_EXAM, "2023", "腹部", "診断問題3", "c"),
        ]
        self.nuclear_question = self.insert_question(
            NUCLEAR_EXAM,
            "2025",
            "核医学総論",
            "核医学問題1",
            "d",
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

    def insert_question(self, exam, year, category, question, answer):
        timestamp = server.now_iso()
        with server.db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO questions (
                    exam,
                    year,
                    category,
                    question,
                    choices,
                    images,
                    answer,
                    explanation,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exam,
                    year,
                    category,
                    question,
                    json.dumps(["a", "b", "c", "d", "e"], ensure_ascii=False),
                    "[]",
                    answer,
                    "",
                    timestamp,
                    timestamp,
                ),
            )
            return cursor.lastrowid

    def request_json(self, method, path, payload=None):
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))

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

    def create_session(
        self,
        *,
        user_name="alice",
        exam=DIAGNOSTIC_EXAM,
        question_ids=None,
        filters=None,
    ):
        if question_ids is None:
            question_ids = list(self.diagnostic_questions)
        if filters is None:
            filters = {}
        return self.request_json(
            "POST",
            "/api/practice-session",
            {
                "user_name": user_name,
                "exam": exam,
                "filters": filters,
                "question_ids": question_ids,
            },
        )

    def get_session(self, user_name="alice", exam=DIAGNOSTIC_EXAM):
        query = urlencode({"user": user_name, "exam": exam})
        return self.request_json("GET", f"/api/practice-session?{query}")

    def delete_session(self, user_name="alice", exam=DIAGNOSTIC_EXAM):
        query = urlencode({"user": user_name, "exam": exam})
        return self.request_json("DELETE", f"/api/practice-session?{query}")

    def create_attempt(
        self,
        question_id,
        *,
        user_name="alice",
        user_answer="a",
        self_mark="wrong",
        practice_session_token=None,
    ):
        payload = {
            "question_id": question_id,
            "user_name": user_name,
            "user_answer": user_answer,
            "self_mark": self_mark,
        }
        if practice_session_token is not None:
            payload["practice_session_token"] = practice_session_token
        return self.request_json("POST", "/api/attempts", payload)

    def assert_session_counts(
        self,
        practice_session,
        *,
        total,
        completed,
        remaining,
        status,
    ):
        self.assertEqual(practice_session["total"], total)
        self.assertEqual(practice_session["completed"], completed)
        self.assertEqual(practice_session["remaining"], remaining)
        self.assertEqual(practice_session["status"], status)

    def test_init_db_is_idempotent_and_creates_practice_session_schema(self):
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
                "PRAGMA foreign_key_list(practice_session_items)"
            ).fetchall()

        self.assertIn("practice_sessions", tables)
        self.assertIn("practice_session_items", tables)
        self.assertTrue(
            any(
                row["table"] == "practice_sessions"
                and row["on_delete"].upper() == "CASCADE"
                for row in foreign_keys
            )
        )
        self.assertTrue(
            any(
                row["table"] == "questions"
                and row["on_delete"].upper() == "CASCADE"
                for row in foreign_keys
            )
        )

    def test_create_and_get_preserve_question_order_and_normalize_filters(self):
        question_ids = [
            self.diagnostic_questions[2],
            self.diagnostic_questions[0],
            self.diagnostic_questions[1],
        ]
        submitted_filters = {
            "year": "2025",
            "category": "中枢神経",
            "q": "神経",
            "result_marks": ["wrong", "warn"],
            "local_filter": {
                "hasImages": True,
                "unattempted": False,
                "withoutAnswer": True,
            },
        }
        normalized_filters = {
            "year": "2025",
            "category": "中枢神経",
            "q": "神経",
            "result_marks": ["warn", "wrong"],
            "local_filter": {
                "hasImages": True,
                "withoutAnswer": True,
            },
        }

        status, payload = self.create_session(
            question_ids=question_ids,
            filters={**submitted_filters, "ignored": "value"},
        )

        self.assertIn(status, (200, 201))
        created = payload["practice_session"]
        self.assertEqual(created["user_name"], "alice")
        self.assertEqual(created["exam"], DIAGNOSTIC_EXAM)
        self.assertEqual(created["question_ids"], question_ids)
        self.assertEqual(created["completed_question_ids"], [])
        self.assertEqual(created["filters"], normalized_filters)
        self.assertTrue(created["token"])
        self.assert_session_counts(
            created,
            total=3,
            completed=0,
            remaining=3,
            status="active",
        )

        status, payload = self.get_session()

        self.assertEqual(status, 200)
        fetched = payload["practice_session"]
        self.assertEqual(fetched["token"], created["token"])
        self.assertEqual(fetched["question_ids"], question_ids)
        self.assertEqual(fetched["completed_question_ids"], [])
        self.assertEqual(fetched["filters"], normalized_filters)

    def test_sessions_are_isolated_by_user_and_exam(self):
        status, diagnostic_alice_payload = self.create_session(
            user_name="alice",
            exam=DIAGNOSTIC_EXAM,
            question_ids=self.diagnostic_questions[:2],
        )
        self.assertIn(status, (200, 201))
        status, nuclear_alice_payload = self.create_session(
            user_name="alice",
            exam=NUCLEAR_EXAM,
            question_ids=[self.nuclear_question],
        )
        self.assertIn(status, (200, 201))
        status, diagnostic_bob_payload = self.create_session(
            user_name="bob",
            exam=DIAGNOSTIC_EXAM,
            question_ids=[self.diagnostic_questions[2]],
        )
        self.assertIn(status, (200, 201))

        expected_tokens = {
            ("alice", DIAGNOSTIC_EXAM): diagnostic_alice_payload["practice_session"][
                "token"
            ],
            ("alice", NUCLEAR_EXAM): nuclear_alice_payload["practice_session"]["token"],
            ("bob", DIAGNOSTIC_EXAM): diagnostic_bob_payload["practice_session"]["token"],
        }
        for (user_name, exam), expected_token in expected_tokens.items():
            with self.subTest(user_name=user_name, exam=exam):
                status, payload = self.get_session(user_name, exam)
                self.assertEqual(status, 200)
                self.assertEqual(
                    payload["practice_session"]["token"],
                    expected_token,
                )

        status, payload = self.get_session("bob", NUCLEAR_EXAM)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["practice_session"])

    def test_replacement_invalidates_the_old_token(self):
        _, first_payload = self.create_session(
            question_ids=self.diagnostic_questions[:2]
        )
        first_token = first_payload["practice_session"]["token"]

        _, replacement_payload = self.create_session(
            question_ids=self.diagnostic_questions[1:]
        )
        replacement = replacement_payload["practice_session"]

        self.assertNotEqual(replacement["token"], first_token)
        status, fetched_payload = self.get_session()
        self.assertEqual(status, 200)
        self.assertEqual(
            fetched_payload["practice_session"]["token"],
            replacement["token"],
        )
        self.assertEqual(
            fetched_payload["practice_session"]["question_ids"],
            self.diagnostic_questions[1:],
        )

        status, attempt_payload = self.create_attempt(
            self.diagnostic_questions[0],
            user_answer="b",
            practice_session_token=first_token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(attempt_payload["practice_session_stale"])
        self.assertIsNone(attempt_payload["practice_session"])

    def test_rejects_invalid_nonexistent_mixed_exam_and_duplicate_ids(self):
        invalid_cases = {
            "not-a-list": "invalid",
            "empty": [],
            "non-integer": ["x"],
            "nonexistent": [999999],
            "mixed-exam": [
                self.diagnostic_questions[0],
                self.nuclear_question,
            ],
            "duplicate": [
                self.diagnostic_questions[0],
                self.diagnostic_questions[0],
            ],
        }

        for label, question_ids in invalid_cases.items():
            with self.subTest(label=label):
                status, payload = self.create_session(question_ids=question_ids)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)

        status, payload = self.get_session()
        self.assertEqual(status, 200)
        self.assertIsNone(payload["practice_session"])

    def test_attempt_completes_items_regardless_of_correctness(self):
        _, session_payload = self.create_session(
            question_ids=self.diagnostic_questions[:2]
        )
        token = session_payload["practice_session"]["token"]

        status, wrong_payload = self.create_attempt(
            self.diagnostic_questions[0],
            user_answer="e",
            self_mark="wrong",
            practice_session_token=token,
        )
        self.assertEqual(status, 200)
        self.assertFalse(wrong_payload["correct"])
        self.assertFalse(wrong_payload.get("practice_session_stale", False))
        after_wrong = wrong_payload["practice_session"]
        self.assertEqual(
            after_wrong["completed_question_ids"],
            [self.diagnostic_questions[0]],
        )
        self.assert_session_counts(
            after_wrong,
            total=2,
            completed=1,
            remaining=1,
            status="active",
        )

        status, correct_payload = self.create_attempt(
            self.diagnostic_questions[1],
            user_answer="b",
            self_mark="ok",
            practice_session_token=token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(correct_payload["correct"])
        completed = correct_payload["practice_session"]
        self.assertEqual(
            completed["completed_question_ids"],
            self.diagnostic_questions[:2],
        )
        self.assert_session_counts(
            completed,
            total=2,
            completed=2,
            remaining=0,
            status="completed",
        )

    def test_repeated_attempt_of_same_item_is_idempotent_for_progress(self):
        _, session_payload = self.create_session(
            question_ids=self.diagnostic_questions[:2]
        )
        token = session_payload["practice_session"]["token"]

        for answer in ("e", "a"):
            status, payload = self.create_attempt(
                self.diagnostic_questions[0],
                user_answer=answer,
                practice_session_token=token,
            )
            self.assertEqual(status, 200)
            self.assert_session_counts(
                payload["practice_session"],
                total=2,
                completed=1,
                remaining=1,
                status="active",
            )

        with server.db() as conn:
            attempts_count = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM attempts
                WHERE user_name = ? AND question_id = ?
                """,
                ("alice", self.diagnostic_questions[0]),
            ).fetchone()["total"]

        self.assertEqual(attempts_count, 2)

    def test_last_item_completes_session(self):
        _, session_payload = self.create_session(
            question_ids=[self.diagnostic_questions[0]]
        )
        token = session_payload["practice_session"]["token"]

        status, payload = self.create_attempt(
            self.diagnostic_questions[0],
            user_answer="a",
            self_mark="ok",
            practice_session_token=token,
        )

        self.assertEqual(status, 200)
        practice_session = payload["practice_session"]
        self.assert_session_counts(
            practice_session,
            total=1,
            completed=1,
            remaining=0,
            status="completed",
        )
        self.assertIsNotNone(practice_session["completed_at"])

        _, fetched_payload = self.get_session()
        self.assertEqual(
            fetched_payload["practice_session"]["status"],
            "completed",
        )

    def test_stale_token_saves_attempt_without_updating_current_progress(self):
        _, old_payload = self.create_session(
            question_ids=self.diagnostic_questions[:2]
        )
        old_token = old_payload["practice_session"]["token"]
        _, current_payload = self.create_session(
            question_ids=self.diagnostic_questions[1:]
        )
        current_token = current_payload["practice_session"]["token"]

        status, payload = self.create_attempt(
            self.diagnostic_questions[0],
            user_answer="e",
            practice_session_token=old_token,
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["practice_session_stale"])
        self.assertIsNone(payload["practice_session"])
        with server.db() as conn:
            attempts_count = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = ?",
                ("alice",),
            ).fetchone()["total"]
        self.assertEqual(attempts_count, 1)

        _, fetched_payload = self.get_session()
        current = fetched_payload["practice_session"]
        self.assertEqual(current["token"], current_token)
        self.assert_session_counts(
            current,
            total=2,
            completed=0,
            remaining=2,
            status="active",
        )

    def test_delete_practice_session(self):
        self.create_session(question_ids=self.diagnostic_questions[:2])

        status, payload = self.delete_session()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["practice_session"])
        status, fetched_payload = self.get_session()
        self.assertEqual(status, 200)
        self.assertIsNone(fetched_payload["practice_session"])

    def test_clearing_attempts_also_clears_only_that_users_sessions(self):
        _, alice_diagnostic_payload = self.create_session(
            user_name="alice",
            exam=DIAGNOSTIC_EXAM,
            question_ids=self.diagnostic_questions[:2],
        )
        self.create_session(
            user_name="alice",
            exam=NUCLEAR_EXAM,
            question_ids=[self.nuclear_question],
        )
        _, bob_payload = self.create_session(
            user_name="bob",
            exam=DIAGNOSTIC_EXAM,
            question_ids=[self.diagnostic_questions[2]],
        )
        self.create_attempt(
            self.diagnostic_questions[0],
            user_name="alice",
            user_answer="a",
            self_mark="ok",
            practice_session_token=alice_diagnostic_payload["practice_session"][
                "token"
            ],
        )

        query = urlencode({"user": "alice"})
        status, payload = self.request_json("DELETE", f"/api/attempts?{query}")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        for exam in (DIAGNOSTIC_EXAM, NUCLEAR_EXAM):
            _, fetched_payload = self.get_session("alice", exam)
            self.assertIsNone(fetched_payload["practice_session"])

        _, bob_fetched_payload = self.get_session("bob", DIAGNOSTIC_EXAM)
        self.assertEqual(
            bob_fetched_payload["practice_session"]["token"],
            bob_payload["practice_session"]["token"],
        )
        with server.db() as conn:
            alice_attempts = conn.execute(
                "SELECT COUNT(*) AS total FROM attempts WHERE user_name = ?",
                ("alice",),
            ).fetchone()["total"]
        self.assertEqual(alice_attempts, 0)

    def test_deleted_question_cascades_and_get_normalizes_session(self):
        _, session_payload = self.create_session(
            question_ids=self.diagnostic_questions[:2]
        )
        token = session_payload["practice_session"]["token"]
        self.create_attempt(
            self.diagnostic_questions[0],
            user_answer="a",
            self_mark="ok",
            practice_session_token=token,
        )

        with server.db() as conn:
            conn.execute(
                "DELETE FROM questions WHERE id = ?",
                (self.diagnostic_questions[1],),
            )
            remaining_items = conn.execute(
                "SELECT COUNT(*) AS total FROM practice_session_items"
            ).fetchone()["total"]
        self.assertEqual(remaining_items, 1)

        status, payload = self.get_session()

        self.assertEqual(status, 200)
        normalized = payload["practice_session"]
        self.assertEqual(
            normalized["question_ids"],
            [self.diagnostic_questions[0]],
        )
        self.assertEqual(
            normalized["completed_question_ids"],
            [self.diagnostic_questions[0]],
        )
        self.assert_session_counts(
            normalized,
            total=1,
            completed=1,
            remaining=0,
            status="completed",
        )
        self.assertIsNotNone(normalized["completed_at"])


if __name__ == "__main__":
    unittest.main()
