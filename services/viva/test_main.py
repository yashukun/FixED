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
        if entity is main.VivaQuestion:
            return _ExecuteResult(self.questions[:1])
        if entity is main.VivaTurn:
            return _ExecuteResult(self.turns)
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
        self.client = TestClient(main.app)

    def tearDown(self):
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
        self.assertEqual(main._followup_target(5), 3)
        self.assertTrue(main._should_apply_followup(current_order=1, total_questions=5))
        self.assertTrue(main._should_apply_followup(current_order=3, total_questions=5))
        self.assertFalse(main._should_apply_followup(current_order=4, total_questions=5))

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
                "main._finalize_session",
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
