import json
import logging
import os
import re
import uuid
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sqlalchemy import select

from config import (
    CHAPTER_SCOPE_LIMIT,
    CHAT_MODEL,
    DEFAULT_TOP_K,
    EMBED_MODEL,
    HYBRID_VECTOR_WEIGHT,
    INTENT_MODEL,
    MAX_RETRIEVAL_POOL,
    MAX_TOP_K,
    PAGE_SCOPE_LIMIT,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RETRIEVAL_POOL_MULTIPLIER,
    VECTOR_DB_PROVIDER,
    WHOLE_BOOK_LIMIT,
)
from db import BookChapter, DocumentChunk, SearchHistory, get_db_context, init_db
from guardrails import build_guardrail_answer
from prompting import build_system_prompt, context_char_budget
from text_utils import (
    extract_quoted_phrases,
    keyword_overlap_score,
    quoted_phrase_boost,
    tokenize,
    trim_context,
)
from cost import compute_chat_cost, compute_embedding_cost, parse_usage_tokens, record_cost

app = FastAPI(title="FixED - Search Service")
logger = logging.getLogger(__name__)

_openai_client = None
_qdrant_client = None


class _CostTracker:
    def __init__(self) -> None:
        self._total = Decimal("0")
        self._rows: list[CostBreakdown] = []

    def add_chat(
        self,
        kind: str,
        model: str,
        usage: Any,
        file_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage)
        usd_decimal = compute_chat_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._append(
            kind=kind,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            usd_decimal=usd_decimal,
            file_id=file_id,
            meta=meta,
        )

    def add_embedding(
        self,
        kind: str,
        model: str,
        usage: Any,
        file_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage)
        usd_decimal = compute_embedding_cost(model=model, total_tokens=total_tokens)
        self._append(
            kind=kind,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            usd_decimal=usd_decimal,
            file_id=file_id,
            meta=meta,
        )

    def _append(
        self,
        kind: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        usd_decimal: Decimal,
        file_id: Optional[str],
        meta: Optional[dict[str, Any]],
    ) -> None:
        self._total += usd_decimal
        row = CostBreakdown(
            kind=kind,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            usd=float(usd_decimal),
        )
        self._rows.append(row)
        record_cost(
            service="search",
            kind=kind,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=usd_decimal,
            file_id=file_id,
            meta=meta or {},
        )

    def summary(self) -> dict[str, Any]:
        return {
            "usd": float(self._total),
            "breakdown": [row.model_dump() for row in self._rows],
        }


class SearchRequest(BaseModel):
    query: str
    top_k: int = DEFAULT_TOP_K
    file_id: Optional[str] = None
    active_page: Optional[int] = None
    chapter_number: Optional[int] = None


class SearchResult(BaseModel):
    chunk_id: str
    file_id: str
    filename: str
    chunk_index: int
    text_content: str
    score: float
    page_number: Optional[int] = None
    page_label: Optional[str] = None
    source: Optional[str] = None
    chapter_number: Optional[int] = None


class ChapterOption(BaseModel):
    number: int
    title: str
    start_page: int
    end_page: int


class SearchResponse(BaseModel):
    answer: str
    results: List[SearchResult]
    cost: Optional[dict[str, Any]] = None
    needs_clarification: bool = False
    clarification_options: Optional[list[ChapterOption]] = None


class CostBreakdown(BaseModel):
    kind: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usd: float = 0.0


class RetrievalDebugResponse(BaseModel):
    provider: str
    query: str
    top_k_requested: int
    result_count: int
    results: List[SearchResult]


class SearchHistoryItem(BaseModel):
    id: str
    query: str
    file_id: Optional[str] = None
    scope: str
    task: str
    style: str
    language: str
    answer: str
    results: List[SearchResult]
    cost_usd: float = 0.0
    created_at: str


@app.on_event("startup")
def startup_event():
    init_db()


def _normalized_provider() -> str:
    return (VECTOR_DB_PROVIDER or "pgvector").strip().lower()


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    return _openai_client


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client


def _metadata_int(payload: dict[str, Any], key: str) -> Optional[int]:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_search_result(payload: dict[str, Any], default_id: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=str(payload.get("chunk_id") or default_id),
        file_id=str(payload.get("file_id", "")),
        filename=str(payload.get("filename", "")),
        chunk_index=int(payload.get("chunk_index", 0)),
        text_content=str(payload.get("text", "") or ""),
        score=score,
        page_number=_metadata_int(payload, "page_number"),
        page_label=payload.get("page_label"),
        source=payload.get("source"),
        chapter_number=_metadata_int(payload, "chapter_number"),
    )


def _build_location_hint(result: SearchResult) -> str:
    if result.page_label:
        return f"Page {result.page_label} of {result.filename}"
    if result.page_number is not None:
        return f"Page {result.page_number} of {result.filename}"
    return f"{result.filename} (section around chunk {result.chunk_index})"


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen_ids = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.chunk_id in seen_ids:
            continue
        seen_ids.add(result.chunk_id)
        deduped.append(result)
    return deduped


def _fetch_chapters(file_id: Optional[str]) -> list[ChapterOption]:
    if not file_id:
        return []
    with get_db_context() as db:
        rows = (
            db.query(BookChapter)
            .filter(BookChapter.file_id == file_id)
            .order_by(BookChapter.number.asc())
            .all()
        )
        return [
            ChapterOption(
                number=row.number,
                title=row.title,
                start_page=row.start_page,
                end_page=row.end_page,
            )
            for row in rows
        ]


def _match_chapter_by_text(query_text: str, chapters: list[ChapterOption]) -> Optional[int]:
    lowered = query_text.lower().strip()
    if not lowered:
        return None
    chapter_num_match = re.search(r"\bchapter\s+(\d{1,3})\b", lowered)
    if chapter_num_match:
        number = int(chapter_num_match.group(1))
        if any(ch.number == number for ch in chapters):
            return number
    for chapter in chapters:
        title = chapter.title.lower()
        if title and title in lowered:
            return chapter.number
    return None


def _heuristic_intent(query: str) -> dict[str, Any]:
    lowered = query.lower()
    scope = "factoid"
    task = "qa"
    needs_chapter = False
    language = "en"
    style = "default"

    if any(k in lowered for k in ["summarize", "summary", "key concepts", "highlights"]):
        task = "summarize"
    elif any(k in lowered for k in ["quiz", "mcq", "questions", "practice"]):
        task = "generate_questions"
    elif "translate" in lowered:
        task = "translate"
        if "hindi" in lowered:
            language = "hi"
    elif "compare" in lowered or "difference" in lowered:
        task = "compare"
    elif "mind map" in lowered or "flowchart" in lowered:
        task = "mind_map"
    elif "explain" in lowered:
        task = "explain"

    if "whole book" in lowered or "uploaded book" in lowered or "this book" in lowered:
        scope = "whole_book"
    elif "chapter" in lowered:
        scope = "chapter"
        needs_chapter = True
    elif any(k in lowered for k in ["this page", "on this page", "paragraph"]):
        scope = "page"

    if "beginner" in lowered or "simple language" in lowered:
        style = "beginner"
    elif "child" in lowered or "5th grader" in lowered:
        style = "child"
    elif "academic" in lowered:
        style = "academic"

    return {
        "scope": scope,
        "task": task,
        "needs_chapter": needs_chapter,
        "mentioned_chapter": None,
        "style": style,
        "language": language,
    }


def _classify_query(
    query: str,
    chapters: list[ChapterOption],
    cost_tracker: Optional[_CostTracker] = None,
    file_id: Optional[str] = None,
) -> dict[str, Any]:
    fallback = _heuristic_intent(query)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return fallback

    chapter_strings = [f"{c.number}: {c.title}" for c in chapters[:40]]
    prompt = (
        "Classify this student query for retrieval routing. "
        "Return only JSON with keys: scope, task, needs_chapter, mentioned_chapter, style, language. "
        "scope in [whole_book, chapter, page, paragraph, factoid]. "
        "task in [summarize, explain, qa, generate_questions, compare, translate, mind_map, quiz, other]. "
        "style in [beginner, academic, child, default]."
    )
    try:
        completion = get_openai_client().chat.completions.create(
            model=INTENT_MODEL,
            temperature=0.0,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Query: {query}\n"
                        f"Available chapters: {chapter_strings}\n"
                        f"Fallback intent: {json.dumps(fallback)}"
                    ),
                },
            ],
        )
        if cost_tracker is not None:
            cost_tracker.add_chat(
                kind="intent",
                model=INTENT_MODEL,
                usage=getattr(completion, "usage", None),
                file_id=file_id,
                meta={"query_type": "intent_classification"},
            )
        raw = completion.choices[0].message.content or ""
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return fallback
        parsed = json.loads(match.group(0))
        return {
            "scope": parsed.get("scope", fallback["scope"]),
            "task": parsed.get("task", fallback["task"]),
            "needs_chapter": bool(parsed.get("needs_chapter", fallback["needs_chapter"])),
            "mentioned_chapter": parsed.get("mentioned_chapter"),
            "style": parsed.get("style", fallback["style"]),
            "language": parsed.get("language", fallback["language"]),
        }
    except Exception:
        return fallback


def _build_qdrant_filter(
    file_id: Optional[str],
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> Optional[Filter]:
    must: list[FieldCondition] = []
    if file_id:
        must.append(FieldCondition(key="file_id", match=MatchValue(value=file_id)))
    if chapter_number is not None:
        must.append(
            FieldCondition(key="chapter_number", match=MatchValue(value=chapter_number))
        )
    if page_range:
        must.append(
            FieldCondition(
                key="page_number",
                range=Range(gte=page_range[0], lte=page_range[1]),
            )
        )
    if not must:
        return None
    return Filter(must=must)


def _retrieve_with_qdrant(
    query_embedding: list[float],
    query_tokens: set[str],
    raw_query: str,
    file_id: Optional[str],
    top_k: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    retrieval_pool_size = min(max(top_k * RETRIEVAL_POOL_MULTIPLIER, top_k), MAX_RETRIEVAL_POOL)
    client = get_qdrant_client()
    query_filter = _build_qdrant_filter(file_id=file_id, chapter_number=chapter_number, page_range=page_range)

    if hasattr(client, "search"):
        hits = client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=query_embedding,
            query_filter=query_filter,
            limit=retrieval_pool_size,
            with_payload=True,
        )
    else:
        query_result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_embedding,
            query_filter=query_filter,
            limit=retrieval_pool_size,
            with_payload=True,
        )
        hits = getattr(query_result, "points", query_result)

    chapter_focused_query = "chapter" in query_tokens
    quoted_phrases = extract_quoted_phrases(raw_query)
    scored: list[SearchResult] = []
    for hit in hits:
        payload = hit.payload or {}
        text_content = payload.get("text", "") or ""
        vector_similarity = float(hit.score)
        lexical_similarity = keyword_overlap_score(query_tokens, text_content)
        phrase_boost = quoted_phrase_boost(quoted_phrases, text_content)
        vector_weight = HYBRID_VECTOR_WEIGHT if not chapter_focused_query else min(HYBRID_VECTOR_WEIGHT, 0.8)
        lexical_weight = 1.0 - vector_weight
        combined_score = (vector_weight * vector_similarity) + (lexical_weight * lexical_similarity) + phrase_boost
        scored.append(_as_search_result(payload, str(getattr(hit, "id", "")), combined_score))

    scored.sort(key=lambda row: row.score, reverse=True)
    return _dedupe_results(scored[:top_k])


def _retrieve_with_pgvector(
    query_embedding: list[float],
    query_tokens: set[str],
    raw_query: str,
    file_id: Optional[str],
    top_k: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    retrieval_pool_size = min(max(top_k * RETRIEVAL_POOL_MULTIPLIER, top_k), MAX_RETRIEVAL_POOL)
    with get_db_context() as db:
        distance_col = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
        stmt = select(DocumentChunk, distance_col)
        if file_id:
            stmt = stmt.where(DocumentChunk.file_id == file_id)
        stmt = stmt.order_by(distance_col).limit(retrieval_pool_size)
        rows = db.execute(stmt).all()

    chapter_focused_query = "chapter" in query_tokens
    quoted_phrases = extract_quoted_phrases(raw_query)
    scored: list[SearchResult] = []
    for chunk, dist in rows:
        metadata = chunk.metadata_ or {}
        page_number = _metadata_int(metadata, "page_number")
        chunk_chapter = _metadata_int(metadata, "chapter_number")

        if chapter_number is not None and chunk_chapter != chapter_number:
            continue
        if page_range and page_number is not None and not (page_range[0] <= page_number <= page_range[1]):
            continue
        if page_range and page_number is None:
            continue

        vector_similarity = 1.0 - float(dist if dist is not None else 0.0)
        lexical_similarity = keyword_overlap_score(query_tokens, chunk.text_content)
        phrase_boost = quoted_phrase_boost(quoted_phrases, chunk.text_content)
        vector_weight = HYBRID_VECTOR_WEIGHT if not chapter_focused_query else min(HYBRID_VECTOR_WEIGHT, 0.8)
        lexical_weight = 1.0 - vector_weight
        combined_score = (vector_weight * vector_similarity) + (lexical_weight * lexical_similarity) + phrase_boost
        scored.append(
            SearchResult(
                chunk_id=chunk.id,
                file_id=chunk.file_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                score=combined_score,
                page_number=page_number,
                page_label=metadata.get("page_label"),
                source=metadata.get("source"),
                chapter_number=chunk_chapter,
            )
        )

    scored.sort(key=lambda row: row.score, reverse=True)
    return _dedupe_results(scored[:top_k])


def _retrieve_scope_chunks_qdrant(
    query_tokens: set[str],
    raw_query: str,
    file_id: str,
    limit: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    client = get_qdrant_client()
    scoped_filter = _build_qdrant_filter(file_id=file_id, chapter_number=chapter_number, page_range=page_range)
    points, _ = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=scoped_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    quoted_phrases = extract_quoted_phrases(raw_query)
    rows: list[SearchResult] = []
    for point in points:
        payload = point.payload or {}
        lexical_similarity = keyword_overlap_score(query_tokens, payload.get("text", "") or "")
        phrase_boost = quoted_phrase_boost(quoted_phrases, payload.get("text", "") or "")
        rows.append(_as_search_result(payload, str(getattr(point, "id", "")), lexical_similarity + phrase_boost))
    rows.sort(key=lambda row: (row.score, -row.chunk_index), reverse=True)
    return _dedupe_results(rows[:limit])


def _retrieve_scope_chunks_pgvector(
    query_tokens: set[str],
    raw_query: str,
    file_id: str,
    limit: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    with get_db_context() as db:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.file_id == file_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(max(limit * 2, limit))
        )
        rows = db.execute(stmt).scalars().all()

    quoted_phrases = extract_quoted_phrases(raw_query)
    results: list[SearchResult] = []
    for chunk in rows:
        metadata = chunk.metadata_ or {}
        chunk_chapter = _metadata_int(metadata, "chapter_number")
        page_number = _metadata_int(metadata, "page_number")
        if chapter_number is not None and chunk_chapter != chapter_number:
            continue
        if page_range and page_number is not None and not (page_range[0] <= page_number <= page_range[1]):
            continue
        if page_range and page_number is None:
            continue

        lexical_similarity = keyword_overlap_score(query_tokens, chunk.text_content)
        phrase_boost = quoted_phrase_boost(quoted_phrases, chunk.text_content)
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                file_id=chunk.file_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                score=lexical_similarity + phrase_boost,
                page_number=page_number,
                page_label=metadata.get("page_label"),
                source=metadata.get("source"),
                chapter_number=chunk_chapter,
            )
        )

    results.sort(key=lambda row: (row.score, -row.chunk_index), reverse=True)
    return _dedupe_results(results[:limit])


def _retrieve_scope_chunks(
    query_tokens: set[str],
    raw_query: str,
    file_id: str,
    limit: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    if _normalized_provider() == "qdrant":
        return _retrieve_scope_chunks_qdrant(
            query_tokens=query_tokens,
            raw_query=raw_query,
            file_id=file_id,
            limit=limit,
            chapter_number=chapter_number,
            page_range=page_range,
        )
    return _retrieve_scope_chunks_pgvector(
        query_tokens=query_tokens,
        raw_query=raw_query,
        file_id=file_id,
        limit=limit,
        chapter_number=chapter_number,
        page_range=page_range,
    )


def _retrieve_factoid(
    query_embedding: list[float],
    query_tokens: set[str],
    raw_query: str,
    file_id: Optional[str],
    top_k: int,
    chapter_number: Optional[int] = None,
    page_range: Optional[tuple[int, int]] = None,
) -> list[SearchResult]:
    if _normalized_provider() == "qdrant":
        return _retrieve_with_qdrant(
            query_embedding=query_embedding,
            query_tokens=query_tokens,
            raw_query=raw_query,
            file_id=file_id,
            top_k=top_k,
            chapter_number=chapter_number,
            page_range=page_range,
        )
    return _retrieve_with_pgvector(
        query_embedding=query_embedding,
        query_tokens=query_tokens,
        raw_query=raw_query,
        file_id=file_id,
        top_k=top_k,
        chapter_number=chapter_number,
        page_range=page_range,
    )


def _resolve_scope(intent_scope: str) -> str:
    if intent_scope in {"whole_book", "chapter", "page", "paragraph"}:
        return intent_scope
    return "factoid"


def _resolve_chapter_number(
    req: SearchRequest,
    intent: dict[str, Any],
    chapters: list[ChapterOption],
) -> Optional[int]:
    if req.chapter_number is not None and any(ch.number == req.chapter_number for ch in chapters):
        return req.chapter_number
    mentioned = str(intent.get("mentioned_chapter") or "").strip()
    if mentioned:
        matched = _match_chapter_by_text(mentioned, chapters)
        if matched is not None:
            return matched
    return _match_chapter_by_text(req.query, chapters)


def _infer_chapter_from_probe_results(
    probe_results: list[SearchResult],
    chapters: list[ChapterOption],
) -> Optional[int]:
    if not probe_results or not chapters:
        return None
    valid_numbers = {chapter.number for chapter in chapters}
    chapter_scores: dict[int, float] = {}
    for row in probe_results:
        if row.chapter_number is None:
            continue
        if row.chapter_number not in valid_numbers:
            continue
        chapter_scores[row.chapter_number] = chapter_scores.get(row.chapter_number, 0.0) + max(row.score, 0.0)
    if not chapter_scores:
        return None
    return max(chapter_scores.items(), key=lambda item: item[1])[0]


def _serialize_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _results_to_payload(results: list[SearchResult]) -> list[dict[str, Any]]:
    return [_serialize_model(row) for row in results]


def _save_search_history(
    query: str,
    file_id: Optional[str],
    scope: str,
    task: str,
    style: str,
    language: str,
    answer: str,
    results: list[SearchResult],
    cost_payload: dict[str, Any],
) -> None:
    with get_db_context() as db:
        db.add(
            SearchHistory(
                query=query,
                file_id=file_id,
                scope=scope,
                task=task,
                style=style,
                language=language,
                answer=answer,
                results_json=_results_to_payload(results),
                cost_usd=Decimal(str(cost_payload.get("usd", 0.0))),
            )
        )


def _history_item(row: SearchHistory) -> SearchHistoryItem:
    parsed_results: list[SearchResult] = []
    for item in (row.results_json or []):
        try:
            parsed_results.append(SearchResult(**item))
        except Exception:
            continue
    return SearchHistoryItem(
        id=str(row.id),
        query=row.query,
        file_id=row.file_id,
        scope=row.scope,
        task=row.task,
        style=row.style,
        language=row.language,
        answer=row.answer,
        results=parsed_results,
        cost_usd=float(row.cost_usd or 0),
        created_at=row.created_at.isoformat(),
    )


def _retrieve_for_request(
    req: SearchRequest,
) -> tuple[str, str, str, str, str, Optional[int], list[SearchResult], Optional[str], _CostTracker]:
    cost_tracker = _CostTracker()
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    guardrail_answer = build_guardrail_answer(query)
    if guardrail_answer:
        return query, "factoid", "qa", "default", "en", None, [], guardrail_answer, cost_tracker

    top_k = min(max(req.top_k, 1), MAX_TOP_K)
    query_tokens = tokenize(query)
    chapters = _fetch_chapters(req.file_id)
    intent = _classify_query(
        query,
        chapters,
        cost_tracker=cost_tracker,
        file_id=req.file_id,
    )
    scope = _resolve_scope(str(intent.get("scope", "factoid")))
    task = str(intent.get("task", "qa"))
    style = str(intent.get("style", "default"))
    language = str(intent.get("language", "en"))
    resolved_chapter = _resolve_chapter_number(req, intent, chapters)
    query_embedding: Optional[list[float]] = None

    if scope == "chapter" and req.file_id and chapters and resolved_chapter is None:
        try:
            emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[query])
            cost_tracker.add_embedding(
                kind="embedding",
                model=EMBED_MODEL,
                usage=getattr(emb_resp, "usage", None),
                file_id=req.file_id,
                meta={"reason": "chapter_probe"},
            )
            query_embedding = emb_resp.data[0].embedding
            probe_results = _retrieve_factoid(
                query_embedding=query_embedding,
                query_tokens=query_tokens,
                raw_query=query,
                file_id=req.file_id,
                top_k=min(MAX_TOP_K, 15),
            )
            resolved_chapter = _infer_chapter_from_probe_results(probe_results, chapters)
        except Exception:
            resolved_chapter = None

    if scope == "chapter" and resolved_chapter is None:
        scope = "factoid"

    page_range: Optional[tuple[int, int]] = None
    if scope in {"page", "paragraph"} and req.active_page:
        page_range = (max(req.active_page - 1, 1), req.active_page + 1)

    try:
        results: list[SearchResult]
        if scope == "whole_book" and req.file_id:
            results = _retrieve_scope_chunks(
                query_tokens=query_tokens,
                raw_query=query,
                file_id=req.file_id,
                limit=WHOLE_BOOK_LIMIT,
            )
        elif scope == "chapter" and req.file_id and resolved_chapter is not None:
            results = _retrieve_scope_chunks(
                query_tokens=query_tokens,
                raw_query=query,
                file_id=req.file_id,
                limit=CHAPTER_SCOPE_LIMIT,
                chapter_number=resolved_chapter,
            )
        elif scope in {"page", "paragraph"} and req.file_id and page_range:
            results = _retrieve_scope_chunks(
                query_tokens=query_tokens,
                raw_query=query,
                file_id=req.file_id,
                limit=PAGE_SCOPE_LIMIT,
                page_range=page_range,
            )
        else:
            if query_embedding is None:
                emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[query])
                cost_tracker.add_embedding(
                    kind="embedding",
                    model=EMBED_MODEL,
                    usage=getattr(emb_resp, "usage", None),
                    file_id=req.file_id,
                    meta={"reason": "search_retrieval"},
                )
                query_embedding = emb_resp.data[0].embedding
            results = _retrieve_factoid(
                query_embedding=query_embedding,
                query_tokens=query_tokens,
                raw_query=query,
                file_id=req.file_id,
                top_k=top_k,
                chapter_number=resolved_chapter if scope == "chapter" else None,
                page_range=page_range,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector retrieval failed: {str(exc)}")

    ordered_results = sorted(results, key=lambda row: (row.score, -row.chunk_index), reverse=True)
    return query, scope, task, style, language, resolved_chapter, ordered_results, None, cost_tracker


def _build_context_text(results: list[SearchResult], scope: str) -> str:
    budget = context_char_budget(scope)
    context_blocks = []
    for idx, row in enumerate(results, start=1):
        location = _build_location_hint(row)
        context_blocks.append(
            "\n".join(
                [
                    f"[Ref {idx}]",
                    f"Location: {location}",
                    f"Filename: {row.filename}",
                    f"File ID: {row.file_id}",
                    f"Similarity Score: {row.score:.4f}",
                    f"Content: {trim_context(row.text_content, max_chars=budget)}",
                ]
            )
        )
    return "\n\n".join(context_blocks)


@app.get("/health")
def health():
    return {"status": "ok", "service": "search"}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    (
        query,
        scope,
        task,
        style,
        language,
        resolved_chapter,
        ordered_results,
        guardrail_answer,
        cost_tracker,
    ) = _retrieve_for_request(req)
    if guardrail_answer is not None:
        return SearchResponse(answer=guardrail_answer, results=[], cost=cost_tracker.summary())
    if not ordered_results:
        return SearchResponse(
            answer="I could not find relevant content in the indexed documents for this query.",
            results=[],
            cost=cost_tracker.summary(),
        )

    system_prompt = build_system_prompt(task=task, style=style, language=language)
    context_text = _build_context_text(ordered_results, scope)
    try:
        completion = get_openai_client().chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Retrieved Context:\n{context_text}\n\n"
                        f"Question: {query}\n"
                        f"Resolved scope: {scope}\n"
                        f"Resolved chapter number: {resolved_chapter}"
                    ),
                },
            ],
        )
        cost_tracker.add_chat(
            kind="chat",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=req.file_id,
            meta={"reason": "final_answer"},
        )
        answer = completion.choices[0].message.content or (
            "I could not generate an answer from the retrieved document context."
        )
    except Exception as exc:
        logger.exception("LLM answer generation failed: %s", exc)
        answer = "Sorry, I encountered an error while generating the answer from the document."

    cost_payload = cost_tracker.summary()
    _save_search_history(
        query=query,
        file_id=req.file_id,
        scope=scope,
        task=task,
        style=style,
        language=language,
        answer=answer,
        results=ordered_results,
        cost_payload=cost_payload,
    )
    return SearchResponse(answer=answer, results=ordered_results, cost=cost_payload)


@app.post("/search/stream")
def search_stream(req: SearchRequest):
    def event_generator():
        try:
            (
                query,
                scope,
                task,
                style,
                language,
                resolved_chapter,
                ordered_results,
                guardrail_answer,
                cost_tracker,
            ) = _retrieve_for_request(req)
            if guardrail_answer is not None:
                yield _sse_event("token", {"delta": guardrail_answer})
                yield _sse_event("cost", cost_tracker.summary())
                yield _sse_event("done", {"answer": guardrail_answer, "results": [], "cost": cost_tracker.summary()})
                return

            if not ordered_results:
                no_result_answer = "I could not find relevant content in the indexed documents for this query."
                yield _sse_event("token", {"delta": no_result_answer})
                yield _sse_event("cost", cost_tracker.summary())
                yield _sse_event("done", {"answer": no_result_answer, "results": [], "cost": cost_tracker.summary()})
                return

            yield _sse_event(
                "retrieval",
                {"results": [_serialize_model(row) for row in ordered_results]},
            )

            system_prompt = build_system_prompt(task=task, style=style, language=language)
            context_text = _build_context_text(ordered_results, scope)
            stream = get_openai_client().chat.completions.create(
                model=CHAT_MODEL,
                temperature=0.0,
                stream=True,
                stream_options={"include_usage": True},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Retrieved Context:\n{context_text}\n\n"
                            f"Question: {query}\n"
                            f"Resolved scope: {scope}\n"
                            f"Resolved chapter number: {resolved_chapter}"
                        ),
                    },
                ],
            )
            full_answer = ""
            stream_usage = None
            for chunk in stream:
                token = ""
                if chunk.choices:
                    token = chunk.choices[0].delta.content or ""
                if token:
                    full_answer += token
                    yield _sse_event("token", {"delta": token})
                if getattr(chunk, "usage", None) is not None:
                    stream_usage = chunk.usage

            if not full_answer:
                full_answer = "I could not generate an answer from the retrieved document context."
            cost_tracker.add_chat(
                kind="chat",
                model=CHAT_MODEL,
                usage=stream_usage,
                file_id=req.file_id,
                meta={"reason": "final_answer_stream"},
            )
            cost_payload = cost_tracker.summary()
            yield _sse_event("cost", cost_payload)
            _save_search_history(
                query=query,
                file_id=req.file_id,
                scope=scope,
                task=task,
                style=style,
                language=language,
                answer=full_answer,
                results=ordered_results,
                cost_payload=cost_payload,
            )
            yield _sse_event(
                "done",
                {
                    "answer": full_answer,
                    "results": [_serialize_model(row) for row in ordered_results],
                    "cost": cost_payload,
                },
            )
        except HTTPException as exc:
            yield _sse_event("error", {"message": str(exc.detail), "status_code": exc.status_code})
        except Exception as exc:
            logger.exception("Search streaming failed: %s", exc)
            yield _sse_event("error", {"message": "Sorry, I encountered an error while streaming the answer."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history/search", response_model=list[SearchHistoryItem])
def search_history(file_id: Optional[str] = None, limit: int = 25, offset: int = 0):
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    with get_db_context() as db:
        stmt = select(SearchHistory).order_by(SearchHistory.created_at.desc())
        if file_id:
            stmt = stmt.where(SearchHistory.file_id == file_id)
        rows = db.execute(stmt.offset(safe_offset).limit(safe_limit)).scalars().all()
        return [_history_item(row) for row in rows]


@app.get("/history/search/{history_id}", response_model=SearchHistoryItem)
def search_history_by_id(history_id: str):
    try:
        parsed_id = uuid.UUID(history_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid history id format.")
    with get_db_context() as db:
        row = db.get(SearchHistory, parsed_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Search history item not found.")
        return _history_item(row)


@app.post("/debug/retrieval", response_model=RetrievalDebugResponse)
def debug_retrieval(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    top_k = min(max(req.top_k, 1), MAX_TOP_K)
    query_tokens = tokenize(query)
    page_range = None
    if req.active_page:
        page_range = (max(req.active_page - 1, 1), req.active_page + 1)

    try:
        emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[query])
        query_embedding = emb_resp.data[0].embedding
        results = _retrieve_factoid(
            query_embedding=query_embedding,
            query_tokens=query_tokens,
            raw_query=query,
            file_id=req.file_id,
            top_k=top_k,
            chapter_number=req.chapter_number,
            page_range=page_range,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector retrieval failed: {str(exc)}")

    ordered = sorted(results, key=lambda row: (row.score, -row.chunk_index), reverse=True)
    return RetrievalDebugResponse(
        provider=_normalized_provider(),
        query=query,
        top_k_requested=top_k,
        result_count=len(ordered),
        results=ordered,
    )
