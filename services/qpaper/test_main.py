import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main

PROMPT_REGRESSION_CASES = [
    "Generate an 80 marks question paper with 35% MCQ, 25% subjective and remaining true false",
    "Create 60 marks paper: 20 percent aptitude MCQs, 30 percent coding-based subjective, rest fill in the blanks",
    "Prepare 50 marks test with 25 per cent scenario-based MCQs and 25% short notes",
    "Generate 40 marks paper with equal distribution for all sections",
    "Generate 90 marks question paper with equal distribution of aptitude MCQs, long-form theoretical and assertion-reason",
    "Create 70 marks exam with 30% map-based, 30% viva-style and remaining picture-based identification",
    "Generate 100 marks paper with 20% true/false, 20% fill in the blanks and remaining long-form theoretical",
    "Prepare 45 marks paper with 25% match-the-following and 25% assertion-reason and remaining coding-based subjective",
    "Create 75 marks test with 33% MCQs, 33% short notes and rest true false",
    "Generate 55 marks exam: 40 percent descriptive questions and remaining fill blanks",
    "Prepare 65 marks question paper with 30% subjective questions, 30% aptitude mcqs, 20% picture-based identification",
    "Create 30 marks paper with 50% viva-style and 50% map-based on the topic Thermodynamics",
    "Generate 120 marks question paper with equal marks among coding-based subjective, short notes, and true false",
    "Prepare 48 marks exam with 25% mcq, 25% t/f, 25% fib and remaining long answer",
    "Generate 36 marks paper with 10% match-the-following, 20% assertion-reason mcqs and remaining short notes",
    "Create 42 marks paper with 25 percent scenario based mcqs, 25 percent picture based identification",
    "Make 80 marks exam with 20% map based, 20% viva style, 20% coding based subjective and remaining mcqs",
    "Generate 95 marks paper with 15% fib, 15% true false, 35% long-form theoretical and rest aptitude mcqs",
    "Prepare 52 marks question paper with 25% short notes, 25% coding-based subjective and 25% mcqs",
    "Create 88 marks test with equal distribution of map-based, viva-style, coding-based subjective, and fill in the blanks",
    "Generate 66 marks paper with 30% descriptive, rest assertion-reason",
    "Prepare 44 marks exam with 25% aptitude mcqs and remaining long answer on the topic Data Structures",
    "Create 58 marks paper where mcqs are 20 percent and subjective is 30 percent and remaining is true false",
    "Generate 84 marks test with same marks between short notes, viva-style and map-based",
    "Prepare an exam paper for 62 marks with 25% picture-based identification, 25% match-the-following, and rest coding-based subjective",
]


class _FakeEmbeddings:
    @staticmethod
    def create(model, input):  # noqa: A002
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )


class _FakeCompletions:
    @staticmethod
    def create(model, temperature, messages, **kwargs):  # noqa: ARG004
        payload_obj = {
            "mcq": [
                {
                    "question": f"MCQ {idx + 1} about photosynthesis?",
                    "options": ["A", "B", "C", "D"],
                    "answer": "A",
                    "marks": 1,
                    "source_refs": ["Ref 1"],
                }
                for idx in range(7)
            ],
            "subjective": [
                {
                    "question": "Explain the role of chlorophyll.",
                    "answer": "It absorbs sunlight.",
                    "marks": 2,
                    "source_refs": ["Ref 2"],
                }
            ],
            "true_false": [
                {
                    "question": "Plants can perform photosynthesis.",
                    "answer": "True",
                    "marks": 1,
                    "source_refs": ["Ref 3"],
                }
            ],
            "fill_blank": [],
        }
        payload = json.dumps(payload_obj)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )


class _FakeOpenAI:
    embeddings = _FakeEmbeddings()
    chat = SimpleNamespace(completions=_FakeCompletions())


class _InvalidCompletions:
    @staticmethod
    def create(model, temperature, messages, **kwargs):  # noqa: ARG004
        payload = (
            '{"mcq":[{"question":"Question","options":["Option A","Option B","Option C","Option D"],'
            '"answer":"Answer unavailable from model output","marks":10,"source_refs":["Ref 1"]}],'
            '"subjective":[],"true_false":[],"fill_blank":[]}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40, total_tokens=160),
        )


class _InvalidOpenAI:
    embeddings = _FakeEmbeddings()
    chat = SimpleNamespace(completions=_InvalidCompletions())


class _UnderfilledCompletions:
    @staticmethod
    def create(model, temperature, messages, **kwargs):  # noqa: ARG004
        payload_obj = {
            "mcq": [
                {
                    "question": f"MCQ {idx + 1} about investment habits?",
                    "options": ["Sip", "Fd", "Stock", "Gold"],
                    "answer": "Sip",
                    "marks": 1,
                    "source_refs": ["Ref 1"],
                }
                for idx in range(4)
            ],
            "subjective": [
                {
                    "question": f"Explain habit-investment principle {idx + 1}.",
                    "answer": "Consistent investing improves outcomes.",
                    "marks": 5,
                    "source_refs": ["Ref 2"],
                }
                for idx in range(8)
            ],
            "true_false": [],
            "fill_blank": [],
        }
        payload = json.dumps(payload_obj)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(prompt_tokens=110, completion_tokens=60, total_tokens=170),
        )


class _UnderfilledOpenAI:
    embeddings = _FakeEmbeddings()
    chat = SimpleNamespace(completions=_UnderfilledCompletions())


def _fake_retrieved_chunks():
    return [
        main.RetrievedChunk(
            ref_id="Ref 1",
            chunk_id="chunk-1",
            file_id="file-1",
            filename="science.pdf",
            chunk_index=0,
            text_content="Plants make food via photosynthesis.",
            score=0.98,
            page_number=5,
            chapter_number=2,
        ),
        main.RetrievedChunk(
            ref_id="Ref 2",
            chunk_id="chunk-2",
            file_id="file-1",
            filename="science.pdf",
            chunk_index=1,
            text_content="Chlorophyll helps absorb sunlight.",
            score=0.94,
            page_number=5,
            chapter_number=2,
        ),
    ]


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows, by_id):
        self._rows = rows
        self._by_id = by_id

    def execute(self, stmt):  # noqa: ARG002
        return _FakeExecuteResult(self._rows)

    def get(self, model, key):  # noqa: ARG002
        return self._by_id.get(str(key))


class QPaperEndpointTests(unittest.TestCase):
    def setUp(self):
        self.init_db_patcher = patch("main.init_db", return_value=None)
        self.init_db_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.init_db_patcher.stop()

    def test_generate_supports_official_mode(self):
        fake_row_id = uuid.uuid4()
        fake_created_at = datetime.utcnow().isoformat()

        with (
            patch("main.get_openai_client", return_value=_FakeOpenAI()),
            patch("main._retrieve_topic_chunks", return_value=_fake_retrieved_chunks()),
            patch("main._save_generated_paper", return_value=(str(fake_row_id), fake_created_at)),
        ):
            response = self.client.post(
                "/generate",
                json={
                    "doc_id": "file-1",
                    "topic": "Photosynthesis",
                    "total_marks": 10,
                    "distribution": {"mcq": 70, "subjective": 20, "true_false": 10},
                    "mode": "official",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "official")
        self.assertEqual(payload["distribution"]["mcq"], 70)
        self.assertEqual(payload["paper_id"], str(fake_row_id))

    def test_generate_supports_practice_mode(self):
        fake_row_id = uuid.uuid4()
        fake_created_at = datetime.utcnow().isoformat()

        with (
            patch("main.get_openai_client", return_value=_FakeOpenAI()),
            patch("main._retrieve_topic_chunks", return_value=_fake_retrieved_chunks()),
            patch("main._save_generated_paper", return_value=(str(fake_row_id), fake_created_at)),
        ):
            response = self.client.post(
                "/generate",
                json={
                    "doc_id": "file-1",
                    "topic": "Photosynthesis",
                    "total_marks": 10,
                    "distribution": {"mcq": 70, "subjective": 20, "true_false": 10},
                    "mode": "practice",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "practice")
        self.assertEqual(payload["paper"]["marks_summary_heading"], "Final Marks Summary")
        self.assertTrue(any(row["section_key"] == "grand_total" for row in payload["paper"]["marks_summary"]))

    def test_generate_rejects_invalid_distribution(self):
        response = self.client.post(
            "/generate",
            json={
                "doc_id": "file-1",
                "topic": "Photosynthesis",
                "total_marks": 10,
                "distribution": {"mcq": 70, "subjective": 20, "true_false": 5},
                "mode": "practice",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_generate_rejects_missing_required_sections_after_repair(self):
        with (
            patch("main.get_openai_client", return_value=_InvalidOpenAI()),
            patch("main._retrieve_topic_chunks", return_value=_fake_retrieved_chunks()),
        ):
            response = self.client.post(
                "/generate",
                json={
                    "doc_id": "file-1",
                    "topic": "Photosynthesis",
                    "total_marks": 10,
                    "distribution": {"mcq": 30, "subjective": 70, "true_false": 0, "fill_blank": 0},
                    "mode": "official",
                },
            )

        self.assertEqual(response.status_code, 422)
        detail = response.json().get("detail", {})
        errors = detail.get("errors", [])
        self.assertTrue(any("Section subjective requires questions" in item for item in errors))

    def test_quality_errors_flags_generic_mcq_options(self):
        payload = {
            "mcq": [
                {
                    "question": "What is photosynthesis?",
                    "answer": "A",
                    "marks": 1,
                    "source_refs": ["Ref 1"],
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                }
            ],
            "subjective": [],
            "true_false": [],
            "fill_blank": [],
        }
        errors = main._quality_errors(
            payload,
            {"mcq": 100, "subjective": 0, "true_false": 0, "fill_blank": 0},
            source_request="photosynthesis",
        )
        self.assertTrue(any("generic placeholders" in item for item in errors))

    def test_parse_distribution_with_remaining_and_rounding(self):
        parsed = main._parse_distribution_from_text(
            "Generate 80 marks with 35% mcq, 25% subjective and remaining true false"
        )
        self.assertEqual(parsed["mcq"], 35)
        self.assertEqual(parsed["subjective"], 25)
        self.assertEqual(parsed["true_false"], 40)
        self.assertEqual(parsed["fill_blank"], 0)

    def test_mark_targets_adjust_mismatch_on_largest_section(self):
        targets = main._mark_targets(
            total_marks=37,
            distribution_percent={"mcq": 33, "subjective": 33, "true_false": 17, "fill_blank": 17},
        )
        self.assertEqual(sum(targets.values()), 37)
        self.assertTrue(all(value >= 0 for value in targets.values()))

    def test_compose_question_marks_prefers_lower_marks(self):
        marks = main._compose_question_marks(target_marks=11, allowed_marks=[2, 3, 4, 5])
        self.assertEqual(sum(marks), 11)
        self.assertEqual(marks, [2, 2, 2, 2, 3])

    def test_generation_plan_estimates_time_when_missing(self):
        req = main.GeneratePaperRequest(
            doc_id="file-1",
            topic="Photosynthesis",
            total_marks=50,
            distribution={"mcq": 50, "subjective": 30, "true_false": 10, "fill_blank": 10},
            request_text="Create question paper on photosynthesis for 50 marks",
        )
        plan = main._build_generation_plan(req)
        self.assertEqual(plan.exam_time_minutes, 60)
        self.assertEqual(plan.estimated_time_minutes, 60)

    def test_parse_equal_distribution(self):
        parsed = main._parse_distribution_from_text("Generate paper with equal distribution for all sections")
        self.assertEqual(sum(parsed.values()), 100)
        self.assertEqual(parsed["mcq"], 25)
        self.assertEqual(parsed["subjective"], 25)
        self.assertEqual(parsed["true_false"], 25)
        self.assertEqual(parsed["fill_blank"], 25)

    def test_parse_equal_distribution_for_listed_sections(self):
        parsed = main._parse_distribution_from_text(
            "Generate paper with equal distribution of aptitude MCQs, short notes and true false"
        )
        self.assertEqual(sum(parsed.values()), 100)
        self.assertEqual(parsed["fill_blank"], 0)
        self.assertTrue(abs(parsed["mcq"] - parsed["subjective"]) <= 1)
        self.assertTrue(abs(parsed["subjective"] - parsed["true_false"]) <= 1)

    def test_parse_topic_tail_from_on_the_topic_phrase(self):
        topic = main._extract_topic_from_request(
            "General Science",
            "Create exam paper with 50% MCQ and 50% short notes on the topic Chemical Bonding",
        )
        self.assertEqual(topic, "Chemical Bonding")

    def test_regression_parsing_for_25_prompt_variants(self):
        for prompt in PROMPT_REGRESSION_CASES:
            with self.subTest(prompt=prompt):
                req = main.GeneratePaperRequest(
                    doc_id="file-1",
                    topic="General Science",
                    total_marks=40,
                    distribution={"mcq": 40, "subjective": 40, "true_false": 10, "fill_blank": 10},
                    request_text=prompt,
                )
                plan = main._build_generation_plan(req)
                self.assertGreater(plan.total_marks, 0)
                self.assertEqual(sum(plan.section_distribution_percent.values()), 100)
                self.assertEqual(sum(plan.section_mark_targets.values()), plan.total_marks)
                self.assertEqual(
                    sum(int(section["target_marks"]) for section in plan.section_question_plan.values()),
                    plan.total_marks,
                )

    def test_regression_remaining_and_rest_behaviour(self):
        remaining = main._parse_distribution_from_text(
            "Generate paper with 30% aptitude MCQs and remaining coding-based subjective"
        )
        self.assertEqual(remaining["mcq"], 30)
        self.assertEqual(remaining["subjective"], 70)

        rest = main._parse_distribution_from_text(
            "Create paper with 25% short notes and rest assertion-reason"
        )
        self.assertEqual(rest["subjective"], 25)
        self.assertEqual(rest["mcq"], 75)

    def test_parse_distribution_recognizes_rest_subjective_with_topic_suffix(self):
        parsed = main._parse_distribution_from_text(
            "generate a question paper of 100 mark with 20% MCQ and rest subjective on topic habits and investment."
        )
        self.assertEqual(parsed["mcq"], 20)
        self.assertEqual(parsed["subjective"], 80)
        self.assertEqual(parsed["true_false"], 0)
        self.assertEqual(parsed["fill_blank"], 0)

    def test_quality_check_allows_low_subjective_target_when_rounding_forces_one_mark(self):
        payload = {
            "mcq": [],
            "subjective": [
                {
                    "question": "Explain entropy in one line.",
                    "answer": "Entropy measures disorder.",
                    "marks": 1,
                    "source_refs": ["Ref 1"],
                }
            ],
            "true_false": [],
            "fill_blank": [],
        }
        errors = main._quality_errors(
            payload,
            {"mcq": 0, "subjective": 1, "true_false": 0, "fill_blank": 0},
            source_request="Create 3 marks paper with equal distribution",
        )
        self.assertFalse(any("marks must be between" in item for item in errors))

    def test_rebalance_does_not_break_objective_mark_bounds(self):
        payload = {
            "mcq": [
                {
                    "question": "What is ATP?",
                    "answer": "Adenosine triphosphate",
                    "marks": 1,
                    "source_refs": ["Ref 1"],
                    "options": [
                        "Adenosine triphosphate",
                        "Adenosine diphosphate",
                        "Amino triphosphate",
                        "Active transport protein",
                    ],
                }
            ],
            "subjective": [],
            "true_false": [],
            "fill_blank": [],
        }
        balanced = main._rebalance_marks_to_targets(
            payload=payload,
            total_marks=5,
            section_targets={"mcq": 5, "subjective": 0, "true_false": 0, "fill_blank": 0},
            source_request="5 marks all mcq",
        )
        self.assertEqual(balanced["mcq"][0]["marks"], 1)

    def test_generate_converges_for_underfilled_rest_subjective_prompt(self):
        fake_row_id = uuid.uuid4()
        fake_created_at = datetime.utcnow().isoformat()
        with (
            patch("main.get_openai_client", return_value=_UnderfilledOpenAI()),
            patch("main._retrieve_topic_chunks", return_value=_fake_retrieved_chunks()),
            patch("main._save_generated_paper", return_value=(str(fake_row_id), fake_created_at)),
        ):
            response = self.client.post(
                "/generate",
                json={
                    "doc_id": "file-1",
                    "topic": "Finance",
                    "total_marks": 100,
                    "distribution": {"mcq": 40, "subjective": 40, "true_false": 10, "fill_blank": 10},
                    "mode": "official",
                    "request_text": (
                        "generate a question paper of 100 mark with 20% MCQ and rest subjective "
                        "on topic habits and investment."
                    ),
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        summary_by_key = {
            row["section_key"]: row
            for row in payload["paper"]["marks_summary"]
            if isinstance(row, dict) and "section_key" in row
        }
        self.assertEqual(summary_by_key["mcq"]["actual_marks"], 20)
        self.assertEqual(summary_by_key["subjective"]["actual_marks"], 80)
        self.assertEqual(summary_by_key["grand_total"]["actual_marks"], 100)
        self.assertEqual(len(payload["paper"]["mcq"]), 20)
        self.assertEqual(len(payload["paper"]["subjective"]), 40)

    def test_history_list_and_get_by_id(self):
        paper_id = uuid.uuid4()
        row = SimpleNamespace(
            id=paper_id,
            file_id="file-1",
            topic="Photosynthesis",
            mode="official",
            total_marks=10,
            distribution_json={"mcq": 70, "subjective": 20, "true_false": 10, "fill_blank": 0},
            paper_json={"mcq": [], "subjective": [], "true_false": [], "fill_blank": []},
            retrieval_json=[],
            cost_usd=0.01,
            created_at=datetime.utcnow(),
        )
        fake_session = _FakeSession(rows=[row], by_id={str(paper_id): row})

        @contextmanager
        def fake_db_context():
            yield fake_session

        with patch("main.get_db_context", side_effect=fake_db_context):
            list_response = self.client.get("/history/papers?file_id=file-1&limit=10&offset=0")
            self.assertEqual(list_response.status_code, 200)
            list_payload = list_response.json()
            self.assertEqual(len(list_payload), 1)
            self.assertEqual(list_payload[0]["paper_id"], str(paper_id))

            get_response = self.client.get(f"/history/papers/{paper_id}")
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(get_response.json()["paper_id"], str(paper_id))


if __name__ == "__main__":
    unittest.main()
