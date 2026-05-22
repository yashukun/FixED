import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from providers.face import FaceAuditResult, verify_face


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, session=None, questions=None, turns=None, proctor_events=None):
        self.session = session
        self.questions = questions or []
        self.turns = turns or []
        self.proctor_events = proctor_events or []
        self.results = []

    def get(self, model, key):  # noqa: ARG002
        if self.session and str(self.session.id) == str(key):
            return self.session
        return None

    def add(self, row):
        if isinstance(row, main.VivaSession):
            if not row.id:
                row.id = uuid.uuid4()
            self.session = row
        if isinstance(row, main.VivaTurn):
            if not row.id:
                row.id = uuid.uuid4()
            self.turns.append(row)
        if isinstance(row, main.VivaQuestion):
            if not row.id:
                row.id = uuid.uuid4()
            self.questions.append(row)
        if isinstance(row, main.VivaResult):
            self.results.append(row)
        if isinstance(row, main.VivaProctorEvent):
            if not row.id:
                row.id = uuid.uuid4()
            if not row.created_at:
                row.created_at = datetime.utcnow()
            self.proctor_events.append(row)

    def flush(self):
        return None

    def execute(self, stmt):  # noqa: ARG002
        entity = None
        if getattr(stmt, "column_descriptions", None):
            entity = stmt.column_descriptions[0].get("entity")
        where_items = getattr(stmt, "_where_criteria", ()) or ()

        def _where_equals(column_name):
            for item in where_items:
                left = getattr(item, "left", None)
                right = getattr(item, "right", None)
                if getattr(left, "name", None) != column_name:
                    continue
                value = getattr(right, "value", None)
                if value is not None:
                    return value
            return None

        if entity is main.VivaQuestion:
            rows = list(self.questions)
            session_id = _where_equals("session_id")
            if session_id is not None:
                rows = [row for row in rows if str(row.session_id) == str(session_id)]
            question_order = _where_equals("question_order")
            if question_order is not None:
                rows = [row for row in rows if int(row.question_order or 0) == int(question_order)]
            rows = sorted(rows, key=lambda item: int(item.question_order or 0))
            return _ExecuteResult(rows[:1] if question_order is not None else rows)
        if entity is main.VivaTurn:
            rows = list(self.turns)
            session_id = _where_equals("session_id")
            if session_id is not None:
                rows = [row for row in rows if str(row.session_id) == str(session_id)]
            return _ExecuteResult(rows)
        if entity is main.VivaResult:
            return _ExecuteResult(self.results)
        if entity is main.VivaProctorEvent:
            ordered = sorted(
                self.proctor_events,
                key=lambda item: item.created_at or datetime.min,
                reverse=True,
            )
            return _ExecuteResult(ordered)
        return _ExecuteResult([])


class VivaEndpointTests(unittest.TestCase):
    def setUp(self):
        self.init_db_patcher = patch("main.init_db", return_value=None)
        self.init_db_patcher.start()
        self.context_patcher = patch(
            "main._build_grounded_context",
            return_value="[Ref 1]\nContent: grounded textbook excerpt",
        )
        self.context_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.context_patcher.stop()
        self.init_db_patcher.stop()

    def test_start_session_rejects_invalid_question_count(self):
        response = self.client.post(
            "/viva/sessions/start",
            json={
                "file_id": "file-1",
                "topic": "Linear Algebra",
                "question_count": 2,
                "per_question_limit_seconds": 60,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_proctor_terminates_on_fourth_warning(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Electromagnetism",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=3,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session)

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.PROCTOR_WINDOW_ANOMALY_THRESHOLD", 1),
            patch("main.PROCTOR_WARNING_MIN_INTERVAL_MS", 0),
            patch(
                "main.verify_face",
                return_value=FaceAuditResult(
                    is_present=False,
                    is_match=False,
                    confidence=0.0,
                    reason="face_not_present",
                ),
            ),
            patch(
                "main._finalize_session_with_db",
                return_value={"session": {"status": "terminated_proctoring"}, "result": {"overall_score": 0}},
            ),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/proctor/frame",
                json={"frame_b64": "x" * 128, "threshold": 0.99},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "terminated")
        self.assertEqual(payload["warnings"], 4)

    def test_proctor_frame_match_keeps_warning_count(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=2,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session)

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.PROCTOR_WINDOW_ANOMALY_THRESHOLD", 1),
            patch("main.PROCTOR_WARNING_MIN_INTERVAL_MS", 0),
            patch(
                "main.verify_face",
                return_value=FaceAuditResult(is_present=True, is_match=True, confidence=0.96, reason="match"),
            ),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/proctor/frame",
                json={"frame_b64": "x" * 128, "threshold": 0.9},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "ok")
        self.assertEqual(payload["warnings"], 2)

    def test_proctor_frame_mismatch_triggers_warning(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=1,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session)

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.PROCTOR_WINDOW_ANOMALY_THRESHOLD", 1),
            patch("main.PROCTOR_WARNING_MIN_INTERVAL_MS", 0),
            patch(
                "main.verify_face",
                return_value=FaceAuditResult(is_present=True, is_match=False, confidence=0.21, reason="mismatch"),
            ),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/proctor/frame",
                json={"frame_b64": "x" * 128, "threshold": 0.9},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "warning")
        self.assertEqual(payload["warnings"], 2)

    def test_proctor_provider_error_triggers_warning(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session)

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.PROCTOR_WINDOW_ANOMALY_THRESHOLD", 1),
            patch("main.PROCTOR_WARNING_MIN_INTERVAL_MS", 0),
            patch(
                "main.verify_face",
                return_value=FaceAuditResult(
                    is_present=False,
                    is_match=False,
                    confidence=0.0,
                    reason="provider_error",
                ),
            ),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/proctor/frame",
                json={"frame_b64": "x" * 128, "threshold": 0.9},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "warning")
        self.assertEqual(payload["warnings"], 1)

    def test_proctor_frame_throttles_and_skips_vision_call(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=1,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        previous_event = main.VivaProctorEvent(
            id=uuid.uuid4(),
            session_id=session.id,
            event_type="frame_check",
            is_present=1,
            is_match=1,
            confidence=0.97,
            warning_count=1,
            action="ok",
            details_json={"reason": "match"},
            created_at=datetime.utcnow() - timedelta(milliseconds=300),
        )
        fake_db = _FakeDB(session=session, proctor_events=[previous_event])

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.PROCTOR_MIN_FRAME_INTERVAL_MS", 2500),
            patch("main.verify_face") as verify_face_mock,
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/proctor/frame",
                json={"frame_b64": "x" * 128, "threshold": 0.9},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["throttled"])
        self.assertEqual(payload["action"], "ok")
        self.assertEqual(payload["warnings"], 1)
        self.assertGreater(payload["retry_after_ms"], 0)
        verify_face_mock.assert_not_called()

    def test_verify_face_provider_unavailable_fallback(self):
        result = verify_face(reference_photo_b64="x" * 64, frame_b64="x" * 64, client=None, model="gpt-4o-mini")
        self.assertFalse(result.is_present)
        self.assertFalse(result.is_match)
        self.assertEqual(result.reason, "provider_unavailable")

    def test_followup_target_enforces_minimum_ratio(self):
        with patch("main.FOLLOWUP_MIN_COUNT", 2):
            self.assertEqual(main._followup_min_count(5), 2)
            self.assertEqual(main._total_question_target(5), 7)
            self.assertEqual(main._plan_question(1, 5)["kind"], "base")
            self.assertEqual(main._plan_question(2, 5)["kind"], "followup")
            self.assertEqual(main._plan_question(3, 5)["kind"], "base")
            self.assertEqual(main._plan_question(4, 5)["kind"], "followup")
            self.assertEqual(main._plan_question(7, 5)["kind"], "base")

    def test_start_session_returns_first_question_without_full_bank_generation(self):
        fake_db = _FakeDB()

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.FOLLOWUP_MIN_COUNT", 2),
            patch(
                "main._generate_question_with_llm",
                return_value={"question": "First base question", "expected_points": ["p1"]},
            ) as first_question_mock,
            patch("main._generate_question_bank_with_llm", side_effect=AssertionError("should not be called")),
        ):
            response = self.client.post(
                "/viva/sessions/start",
                json={
                    "file_id": "file-1",
                    "topic": "Control Systems",
                    "question_count": 5,
                    "per_question_limit_seconds": 60,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_question"]["question_text"], "First base question")
        self.assertIsNone(payload["current_question"]["audio_b64"])
        self.assertEqual(payload["session"]["question_count"], 5)
        self.assertEqual(payload["session"]["total_question_target"], 7)
        first_question_mock.assert_called_once()

    def test_submit_answer_asks_five_base_plus_two_followups(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=0,
            started_at=datetime.utcnow(),
        )
        first_question = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=1,
            question_text="Base Q1",
            expected_points_json=["b1"],
            asked_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session, questions=[first_question])

        @contextmanager
        def fake_db_context():
            yield fake_db

        def fake_finalize(db, session_id, force_termination_reason=None):  # noqa: ARG001
            return {
                "session": {"status": "completed", "current_question_index": fake_db.session.current_question_index},
                "result": {
                    "overall_score": sum(float(row.score or 0) for row in fake_db.turns),
                    "max_score": sum(float(row.max_score or 0) for row in fake_db.turns),
                    "summary": "Completed",
                    "question_breakdown": [{"question_id": str(row.question_id)} for row in fake_db.turns],
                },
            }

        followup_counter = {"count": 0}

        def fake_generate_question(
            topic,  # noqa: ARG001
            chapter_number,  # noqa: ARG001
            question_count,  # noqa: ARG001
            question_index,
            previous_question,
            previous_answer,  # noqa: ARG001
            cost_tracker,  # noqa: ARG001
            file_id,  # noqa: ARG001
            context_text="",  # noqa: ARG001
            session_id=None,  # noqa: ARG001
        ):
            if previous_question:
                followup_counter["count"] += 1
                return {
                    "question": f"Followup Q{followup_counter['count']}",
                    "expected_points": [f"f{followup_counter['count']}"],
                }
            return {
                "question": f"Base Q{question_index + 1}",
                "expected_points": [f"b{question_index + 1}"],
            }

        answer_orders = []
        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.FOLLOWUP_MIN_COUNT", 2),
            patch(
                "main._evaluate_answer",
                return_value={
                    "score": 8.0,
                    "max_score": 10.0,
                    "strengths": ["clear"],
                    "weaknesses": [],
                    "feedback": "ok",
                },
            ),
            patch("main._generate_question_bank_with_llm", side_effect=AssertionError("should not be called")),
            patch("main._generate_question_with_llm", side_effect=fake_generate_question),
            patch("main._finalize_session_with_db", side_effect=fake_finalize),
        ):
            final_payload = None
            for idx in range(7):
                response = self.client.post(
                    f"/viva/sessions/{session.id}/answer",
                    json={"transcript": f"answer {idx + 1}"},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                answer_orders.append(payload["turn"]["question_order"])
                if idx < 6:
                    self.assertFalse(payload["done"])
                    self.assertIn("next_question", payload)
                else:
                    self.assertTrue(payload["done"])
                    final_payload = payload

        self.assertEqual(answer_orders, [1, 2, 3, 4, 5, 6, 7])
        self.assertIsNotNone(final_payload)
        self.assertEqual(final_payload["result"]["max_score"], 70.0)
        self.assertEqual(final_payload["result"]["overall_score"], 56.0)
        self.assertEqual(len(final_payload["result"]["question_breakdown"]), 7)

    def test_submit_second_answer_progresses_without_waiting_for_full_base_bank(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        question_one = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=1,
            question_text="Base Q1",
            expected_points_json=["b1"],
            asked_at=datetime.utcnow(),
        )
        question_two = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=2,
            question_text="Followup Q1",
            expected_points_json=["f1"],
            asked_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session, questions=[question_one, question_two])

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.FOLLOWUP_MIN_COUNT", 2),
            patch(
                "main._evaluate_answer",
                return_value={
                    "score": 8.0,
                    "max_score": 10.0,
                    "strengths": ["clear"],
                    "weaknesses": [],
                    "feedback": "ok",
                },
            ),
            patch("main._generate_question_bank_with_llm", side_effect=AssertionError("should not be called")),
            patch(
                "main._generate_question_with_llm",
                return_value={"question": "Base Q2", "expected_points": ["b2"]},
            ) as generate_question_mock,
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/answer",
                json={
                    "transcript": "second answer",
                    "question_id": str(question_two.id),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["done"])
        self.assertEqual(payload["turn"]["question_order"], 2)
        self.assertEqual(payload["session"]["current_question_index"], 2)
        self.assertEqual(payload["next_question"]["question_order"], 3)
        self.assertEqual(payload["next_question"]["question_text"], "Base Q2")
        generate_question_mock.assert_called_once()

    def test_submit_answer_rejects_stale_question_id(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        question_one = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=1,
            question_text="Base Q1",
            expected_points_json=["b1"],
            asked_at=datetime.utcnow(),
        )
        question_two = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=2,
            question_text="Followup Q1",
            expected_points_json=["f1"],
            asked_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session, questions=[question_one, question_two])

        @contextmanager
        def fake_db_context():
            yield fake_db

        with patch("main.get_db_context", side_effect=fake_db_context):
            response = self.client.post(
                f"/viva/sessions/{session.id}/answer",
                json={
                    "transcript": "stale answer",
                    "question_id": str(question_one.id),
                },
            )

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertIn("Submitted question is stale", payload["detail"])

    def test_submit_answer_duplicate_for_already_accepted_question_returns_current_state(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Signals",
            question_count=5,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=1,
            started_at=datetime.utcnow(),
        )
        question_one = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=1,
            question_text="Base Q1",
            expected_points_json=["b1"],
            asked_at=datetime.utcnow(),
        )
        question_two = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=2,
            question_text="Followup Q1",
            expected_points_json=["f1"],
            asked_at=datetime.utcnow(),
        )
        existing_turn = main.VivaTurn(
            id=uuid.uuid4(),
            session_id=session.id,
            question_id=question_one.id,
            answer_transcript="accepted answer",
            score=7.0,
            max_score=10.0,
            strengths_json=["clear structure"],
            weaknesses_json=["needs detail"],
            feedback="Good attempt.",
            latency_ms=1200,
            created_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session, questions=[question_one, question_two], turns=[existing_turn])

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch("main.synthesize_question_audio", return_value=None),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/answer",
                json={
                    "transcript": "retry after flaky network",
                    "question_id": str(question_one.id),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["recovered_conflict"])
        self.assertFalse(payload["done"])
        self.assertEqual(payload["turn"]["question_id"], str(question_one.id))
        self.assertEqual(payload["turn"]["answer_transcript"], "accepted answer")
        self.assertEqual(payload["next_question"]["question_id"], str(question_two.id))

    def test_submit_answer_completes_when_limit_reached(self):
        session = main.VivaSession(
            id=uuid.uuid4(),
            file_id="file-1",
            topic="Cell Biology",
            question_count=1,
            per_question_limit_seconds=60,
            session_limit_seconds=600,
            status=main.VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=0,
            started_at=datetime.utcnow(),
        )
        question = main.VivaQuestion(
            id=uuid.uuid4(),
            session_id=session.id,
            question_order=1,
            question_text="Explain mitochondria function.",
            expected_points_json=["Energy production", "ATP"],
            asked_at=datetime.utcnow(),
        )
        fake_db = _FakeDB(session=session, questions=[question])

        @contextmanager
        def fake_db_context():
            yield fake_db

        with (
            patch("main.get_db_context", side_effect=fake_db_context),
            patch(
                "main._evaluate_answer",
                return_value={
                    "score": 8,
                    "max_score": 10,
                    "strengths": ["Good biological terms"],
                    "weaknesses": ["Could add more detail"],
                    "feedback": "Good answer.",
                },
            ),
            patch(
                "main._finalize_session_with_db",
                return_value={
                    "session": {"status": "completed"},
                    "result": {"overall_score": 8, "max_score": 10, "summary": "Completed"},
                },
            ),
        ):
            response = self.client.post(
                f"/viva/sessions/{session.id}/answer",
                json={"transcript": "Mitochondria produce ATP for cells."},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["done"])
        self.assertEqual(payload["result"]["overall_score"], 8)


if __name__ == "__main__":
    unittest.main()
