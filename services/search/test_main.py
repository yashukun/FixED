import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm.exc import DetachedInstanceError

import main


class _FakeTracker:
    def __init__(self):
        self._cost = {"usd": 0.01, "breakdown": []}

    def add_chat(self, **kwargs):  # noqa: ARG002
        return None

    def summary(self):
        return self._cost


class _CaptureCompletions:
    def __init__(self):
        self.messages = None

    def create(self, model, temperature, messages):  # noqa: ARG002
        self.messages = messages
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Answer from model"))],
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        )


class _FakeOpenAI:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


class SearchEndpointTests(unittest.TestCase):
    def setUp(self):
        self.init_db_patcher = patch("main.init_db", return_value=None)
        self.init_db_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.init_db_patcher.stop()

    def test_search_routes_exam_intent_to_qpaper(self):
        fake_tracker = _FakeTracker()
        with (
            patch(
                "main._retrieve_for_request",
                return_value=(
                    "create question paper on chapter 2",
                    "chapter",
                    "qa",
                    "default",
                    "en",
                    2,
                    [],
                    None,
                    fake_tracker,
                    None,
                ),
            ),
            patch(
                "main._generate_question_paper",
                return_value=(
                    {
                        "paper_id": "paper-1",
                        "topic": "chapter 2",
                        "resolved_file_id": "file-1",
                        "cost": {"usd": 0.2, "breakdown": []},
                    },
                    [],
                    "Generated a question paper from your request. You can review the paper details below.",
                ),
            ) as qpaper_mock,
            patch("main._save_search_history", return_value=None),
        ):
            response = self.client.post(
                "/search",
                json={
                    "query": "create question paper on chapter 2",
                    "file_id": "file-1",
                    "chat_session_id": "chat-123",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_kind"], "generated_paper")
        self.assertEqual(payload["generated_paper"]["paper_id"], "paper-1")
        self.assertEqual(payload["generated_paper"]["resolved_file_id"], "file-1")
        self.assertEqual(qpaper_mock.call_args.kwargs["resolved_file_id"], "file-1")
        self.assertTrue(qpaper_mock.called)

    def test_search_routes_exam_intent_without_file_id(self):
        fake_tracker = _FakeTracker()
        routed_results = [
            main.SearchResult(
                chunk_id="c1",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=1,
                text_content="topic a",
                score=0.94,
                chapter_number=2,
            ),
            main.SearchResult(
                chunk_id="c2",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=2,
                text_content="topic a2",
                score=0.83,
                chapter_number=2,
            ),
            main.SearchResult(
                chunk_id="c3",
                file_id="book-b",
                filename="b.pdf",
                chunk_index=3,
                text_content="topic b",
                score=0.42,
                chapter_number=1,
            ),
        ]
        with (
            patch(
                "main._retrieve_for_request",
                return_value=(
                    "generate question paper on chapter 2 plants",
                    "factoid",
                    "qa",
                    "default",
                    "en",
                    2,
                    routed_results,
                    None,
                    fake_tracker,
                    {"mode": "global_probe_then_candidate_books"},
                ),
            ),
            patch(
                "main._generate_question_paper",
                return_value=(
                    {
                        "paper_id": "paper-2",
                        "topic": "chapter 2 plants",
                        "resolved_file_id": "book-a",
                        "cost": {"usd": 0.1, "breakdown": []},
                    },
                    [],
                    "Generated a question paper from your request. You can review the paper details below.",
                ),
            ) as qpaper_mock,
            patch("main._save_search_history", return_value=None),
        ):
            response = self.client.post(
                "/search",
                json={
                    "query": "generate question paper on chapter 2 plants",
                    "chat_session_id": "chat-global",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["response_kind"], "generated_paper")
        self.assertEqual(payload["generated_paper"]["resolved_file_id"], "book-a")
        self.assertEqual(qpaper_mock.call_args.kwargs["resolved_file_id"], "book-a")
        self.assertEqual(
            payload["retrieval_routing"]["qpaper_route"]["resolved_file_id"],
            "book-a",
        )

    def test_search_exam_without_file_id_returns_clear_error_when_no_candidates(self):
        fake_tracker = _FakeTracker()
        with patch(
            "main._retrieve_for_request",
            return_value=(
                "generate question paper on chapter 7",
                "factoid",
                "qa",
                "default",
                "en",
                None,
                [],
                None,
                fake_tracker,
                {"mode": "global_probe_only", "candidate_file_ids": []},
            ),
        ):
            response = self.client.post(
                "/search",
                json={"query": "generate question paper on chapter 7", "chat_session_id": "chat-1"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("could not determine which book", str(response.json().get("detail", "")).lower())

    def test_resolve_qpaper_file_id_prefers_high_coverage_book(self):
        req = main.SearchRequest(query="generate question paper", file_id=None)
        results = [
            main.SearchResult(
                chunk_id="a1",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=1,
                text_content="a",
                score=0.8,
                chapter_number=1,
                page_number=2,
            ),
            main.SearchResult(
                chunk_id="a2",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=2,
                text_content="a2",
                score=0.7,
                chapter_number=2,
                page_number=10,
            ),
            main.SearchResult(
                chunk_id="b1",
                file_id="book-b",
                filename="b.pdf",
                chunk_index=1,
                text_content="b",
                score=0.95,
                chapter_number=1,
                page_number=3,
            ),
        ]

        resolved_file_id, route_meta = main._resolve_qpaper_file_id(req, results, {"mode": "global"})

        self.assertEqual(resolved_file_id, "book-a")
        self.assertEqual(route_meta["resolved_file_id"], "book-a")

    def test_parse_distribution_and_paper_name_from_query(self):
        query = (
            "Create question paper 30% MCQ 40% subjective and rest true or false "
            "name the question paper mock test 1"
        )
        distribution = main._parse_distribution_from_query(query)
        self.assertEqual(distribution["mcq"], 30)
        self.assertEqual(distribution["subjective"], 40)
        self.assertEqual(distribution["true_false"], 30)
        self.assertEqual(distribution["fill_blank"], 0)
        self.assertEqual(main._extract_paper_name(query), "mock test 1")

    def test_extract_paper_name_with_name_it_as_phrase(self):
        query = "generate a question paper on light chapter and name it as mock test 1"
        self.assertEqual(main._extract_paper_name(query), "mock test 1")

    def test_parse_distribution_supports_percent_wording_and_partial_remainder(self):
        query = "Generate 100 marks question paper with 30 percent mcq and 20% subjective"
        distribution = main._parse_distribution_from_query(query)
        self.assertEqual(distribution["mcq"], 30)
        self.assertEqual(distribution["subjective"], 20)
        self.assertEqual(distribution["fill_blank"], 25)
        self.assertEqual(distribution["true_false"], 25)

    def test_parse_distribution_supports_remaining_section(self):
        query = "Generate question paper with 30% mcq and remaining subjective"
        distribution = main._parse_distribution_from_query(query)
        self.assertEqual(distribution["mcq"], 30)
        self.assertEqual(distribution["subjective"], 70)
        self.assertEqual(distribution["true_false"], 0)
        self.assertEqual(distribution["fill_blank"], 0)

    def test_parse_distribution_scales_when_total_exceeds_hundred(self):
        query = "Create paper with 80% mcq and 50% subjective"
        distribution = main._parse_distribution_from_query(query)
        self.assertEqual(sum(distribution.values()), 100)
        self.assertEqual(distribution["mcq"], 62)
        self.assertEqual(distribution["subjective"], 38)

    def test_search_uses_chat_context_in_prompt(self):
        fake_tracker = _FakeTracker()
        capture = _CaptureCompletions()
        openai_client = _FakeOpenAI(capture)
        result = main.SearchResult(
            chunk_id="chunk-1",
            file_id="file-1",
            filename="book.pdf",
            chunk_index=0,
            text_content="Photosynthesis is a process used by plants.",
            score=0.91,
            page_number=5,
            chapter_number=2,
        )
        with (
            patch(
                "main._retrieve_for_request",
                return_value=(
                    "Explain this concept",
                    "factoid",
                    "qa",
                    "default",
                    "en",
                    None,
                    [result],
                    None,
                    fake_tracker,
                    None,
                ),
            ),
            patch("main.get_openai_client", return_value=openai_client),
            patch(
                "main._load_chat_context",
                return_value=[SimpleNamespace(query="What is chlorophyll?", answer="It helps absorb sunlight.")],
            ),
            patch("main._save_search_history", return_value=None),
        ):
            response = self.client.post(
                "/search",
                json={"query": "Explain this concept", "file_id": "file-1", "chat_session_id": "chat-xyz"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response_kind"], "answer")
        self.assertIsNotNone(capture.messages)
        user_prompt = capture.messages[1]["content"]
        self.assertIn("What is chlorophyll?", user_prompt)
        self.assertIn("It helps absorb sunlight.", user_prompt)

    def test_build_chat_context_text_skips_detached_rows(self):
        class _DetachedHistoryRow:
            @property
            def query(self):
                raise DetachedInstanceError("detached query")

            @property
            def answer(self):
                raise DetachedInstanceError("detached answer")

        chat_context = main._build_chat_context_text(
            [
                _DetachedHistoryRow(),
                {"query": "What is chlorophyll?", "answer": "It helps absorb sunlight."},
            ]
        )

        self.assertIn("User: What is chlorophyll?", chat_context)
        self.assertIn("Assistant: It helps absorb sunlight.", chat_context)

    def test_retrieve_without_file_id_routes_via_global_probe(self):
        query_embedding = [0.1, 0.2, 0.3]
        probe_results = [
            main.SearchResult(
                chunk_id="g1",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=1,
                text_content="global a",
                score=0.95,
            ),
            main.SearchResult(
                chunk_id="g2",
                file_id="book-b",
                filename="b.pdf",
                chunk_index=2,
                text_content="global b",
                score=0.92,
            ),
        ]
        scoped_a = [
            main.SearchResult(
                chunk_id="a1",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=3,
                text_content="scoped a",
                score=0.96,
            )
        ]
        scoped_b = [
            main.SearchResult(
                chunk_id="b1",
                file_id="book-b",
                filename="b.pdf",
                chunk_index=4,
                text_content="scoped b",
                score=0.93,
            )
        ]
        fake_embedding_resp = SimpleNamespace(
            data=[SimpleNamespace(embedding=query_embedding)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )
        with (
            patch("main.tokenize", return_value={"plants"}),
            patch("main._fetch_chapters", return_value=[]),
            patch(
                "main._classify_query",
                return_value={
                    "scope": "factoid",
                    "task": "qa",
                    "style": "default",
                    "language": "en",
                    "needs_chapter": False,
                    "mentioned_chapter": None,
                },
            ),
            patch("main.build_guardrail_answer", return_value=None),
            patch(
                "main.get_openai_client",
                return_value=SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs: fake_embedding_resp)),
            ),
            patch(
                "main._retrieve_factoid",
                side_effect=[probe_results, scoped_a, scoped_b],
            ) as retrieve_mock,
        ):
            req = main.SearchRequest(query="explain photosynthesis", file_id=None, top_k=2)
            _, _, _, _, _, _, ordered_results, _, _, routing = main._retrieve_for_request(req)

        self.assertEqual([row.chunk_id for row in ordered_results], ["a1", "b1"])
        self.assertEqual(routing["mode"], "global_probe_then_candidate_books")
        self.assertEqual(routing["candidate_file_ids"], ["book-a", "book-b"])
        self.assertEqual(retrieve_mock.call_args_list[0].kwargs["file_id"], None)
        self.assertEqual(retrieve_mock.call_args_list[0].kwargs["query_mode"], "global_probe")
        self.assertEqual(retrieve_mock.call_args_list[1].kwargs["file_id"], "book-a")
        self.assertEqual(retrieve_mock.call_args_list[2].kwargs["file_id"], "book-b")

    def test_retrieve_with_file_id_keeps_scoped_behavior(self):
        query_embedding = [0.1, 0.2, 0.3]
        scoped_results = [
            main.SearchResult(
                chunk_id="s1",
                file_id="book-a",
                filename="a.pdf",
                chunk_index=1,
                text_content="scoped",
                score=0.9,
            )
        ]
        fake_embedding_resp = SimpleNamespace(
            data=[SimpleNamespace(embedding=query_embedding)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )
        with (
            patch("main.tokenize", return_value={"plants"}),
            patch("main._fetch_chapters", return_value=[]),
            patch(
                "main._classify_query",
                return_value={
                    "scope": "factoid",
                    "task": "qa",
                    "style": "default",
                    "language": "en",
                    "needs_chapter": False,
                    "mentioned_chapter": None,
                },
            ),
            patch("main.build_guardrail_answer", return_value=None),
            patch(
                "main.get_openai_client",
                return_value=SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs: fake_embedding_resp)),
            ),
            patch("main._retrieve_factoid", return_value=scoped_results) as retrieve_mock,
        ):
            req = main.SearchRequest(query="explain photosynthesis", file_id="book-a", top_k=2)
            _, _, _, _, _, _, ordered_results, _, _, routing = main._retrieve_for_request(req)

        self.assertEqual([row.chunk_id for row in ordered_results], ["s1"])
        self.assertIsNone(routing)
        self.assertEqual(retrieve_mock.call_count, 1)
        self.assertEqual(retrieve_mock.call_args.kwargs["file_id"], "book-a")
        self.assertEqual(retrieve_mock.call_args.kwargs["query_mode"], "scoped")

    def test_infer_candidate_file_ids_ranks_by_peak_relevance_not_volume(self):
        # A large book contributes many mediocre chunks; a small book has one
        # strong match. The strong match should win even though its summed score
        # is lower — otherwise small books get buried in all-books search.
        probe = [
            main.SearchResult(chunk_id="b1", file_id="big", filename="big.pdf",
                              chunk_index=1, text_content="x", score=0.60),
            main.SearchResult(chunk_id="b2", file_id="big", filename="big.pdf",
                              chunk_index=2, text_content="x", score=0.55),
            main.SearchResult(chunk_id="b3", file_id="big", filename="big.pdf",
                              chunk_index=3, text_content="x", score=0.50),
            main.SearchResult(chunk_id="s1", file_id="small", filename="small.pdf",
                              chunk_index=1, text_content="x", score=0.90),
        ]
        self.assertEqual(main._infer_candidate_file_ids(probe, limit=2), ["small", "big"])
        self.assertEqual(main._infer_candidate_file_ids(probe, limit=1), ["small"])

    def test_global_whole_book_routes_to_most_relevant_book_with_full_scope(self):
        # "Summarize this book" with no book selected: route to the most
        # relevant book (by peak relevance) and retrieve it with whole-book
        # scope, instead of collapsing to a few factoid chunks.
        query_embedding = [0.1, 0.2, 0.3]
        probe_results = [
            main.SearchResult(chunk_id="b1", file_id="big", filename="big.pdf",
                              chunk_index=1, text_content="big", score=0.60),
            main.SearchResult(chunk_id="b2", file_id="big", filename="big.pdf",
                              chunk_index=2, text_content="big", score=0.55),
            main.SearchResult(chunk_id="s1", file_id="small", filename="small.pdf",
                              chunk_index=1, text_content="small", score=0.90),
        ]
        whole_book_results = [
            main.SearchResult(chunk_id="w1", file_id="small", filename="small.pdf",
                              chunk_index=0, text_content="full book", score=0.5),
        ]
        fake_embedding_resp = SimpleNamespace(
            data=[SimpleNamespace(embedding=query_embedding)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )
        with (
            patch("main.tokenize", return_value={"book"}),
            patch("main._fetch_chapters", return_value=[]),
            patch(
                "main._classify_query",
                return_value={
                    "scope": "whole_book",
                    "task": "summarize",
                    "style": "default",
                    "language": "en",
                    "needs_chapter": False,
                    "mentioned_chapter": None,
                },
            ),
            patch("main.build_guardrail_answer", return_value=None),
            patch(
                "main.get_openai_client",
                return_value=SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs: fake_embedding_resp)),
            ),
            patch("main._retrieve_factoid", return_value=probe_results) as factoid_mock,
            patch("main._retrieve_scope_chunks", return_value=whole_book_results) as scope_mock,
        ):
            req = main.SearchRequest(query="summarize this book", file_id=None, top_k=5)
            _, scope, _, _, _, _, ordered_results, _, _, routing = main._retrieve_for_request(req)

        self.assertEqual(scope, "whole_book")
        self.assertEqual([row.chunk_id for row in ordered_results], ["w1"])
        self.assertEqual(routing["mode"], "global_scope_routed_to_book")
        self.assertEqual(routing["resolved_file_id"], "small")
        # probe ran once across all books; full-book retrieval targeted the
        # most relevant book only.
        self.assertEqual(factoid_mock.call_count, 1)
        self.assertIsNone(factoid_mock.call_args.kwargs["file_id"])
        self.assertEqual(scope_mock.call_args.kwargs["file_id"], "small")
        self.assertEqual(scope_mock.call_args.kwargs["limit"], main.WHOLE_BOOK_LIMIT)

    def test_history_supports_chat_session_filter(self):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            chat_session_id="chat-1",
            query="Q",
            file_id="file-1",
            scope="factoid",
            task="qa",
            style="default",
            language="en",
            response_kind="answer",
            answer="A",
            results_json=[],
            cost_usd=0.0,
            created_at=datetime.utcnow(),
        )

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
            def execute(self, stmt):  # noqa: ARG002
                return _FakeExecuteResult([row])

        @contextmanager
        def fake_db_context():
            yield _FakeSession()

        with patch("main.get_db_context", side_effect=fake_db_context):
            response = self.client.get("/history/search?file_id=file-1&chat_session_id=chat-1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["chat_session_id"], "chat-1")


if __name__ == "__main__":
    unittest.main()
