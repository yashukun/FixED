import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class _FakeEmbeddings:
    @staticmethod
    def create(model, input):  # noqa: A002
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )


class _FakeCompletions:
    @staticmethod
    def create(model, temperature, messages):  # noqa: ARG004
        payload = (
            '{"mcq":[{"question":"Q1","options":["A","B","C","D"],"answer":"A","marks":7,'
            '"source_refs":["Ref 1"]}],"subjective":[{"question":"Q2","answer":"Ans",'
            '"marks":2,"source_refs":["Ref 2"]}],"true_false":[{"question":"Q3","answer":"True",'
            '"marks":1,"source_refs":["Ref 3"]}],"fill_blank":[]}'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )


class _FakeOpenAI:
    embeddings = _FakeEmbeddings()
    chat = SimpleNamespace(completions=_FakeCompletions())


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
