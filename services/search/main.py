import json
import logging
import os
import re
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sqlalchemy import select

from db import BookChapter, DocumentChunk, get_db_context, init_db

app = FastAPI(title="FixED - Search Service")
logger = logging.getLogger(__name__)

openai_client = None
qdrant_client = None

EMBED_MODEL = os.environ.get("SEARCH_EMBED_MODEL", "text-embedding-3-large")
CHAT_MODEL = os.environ.get("SEARCH_CHAT_MODEL", "gpt-4o-mini")
INTENT_MODEL = os.environ.get("SEARCH_INTENT_MODEL", CHAT_MODEL)
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
RETRIEVAL_POOL_MULTIPLIER = 5
MAX_RETRIEVAL_POOL = 100
WHOLE_BOOK_LIMIT = 400
CHAPTER_SCOPE_LIMIT = 150
PAGE_SCOPE_LIMIT = 60
FACTOID_CONTEXT_CHARS = 1200
CHAPTER_CONTEXT_CHARS = 1600
WHOLE_BOOK_CONTEXT_CHARS = 1800
HYBRID_VECTOR_WEIGHT = min(
    max(float(os.environ.get("SEARCH_HYBRID_VECTOR_WEIGHT", "1.0")), 0.0),
    1.0,
)
VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")


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
    needs_clarification: bool = False
    clarification_options: Optional[list[ChapterOption]] = None


class RetrievalDebugResponse(BaseModel):
    provider: str
    query: str
    top_k_requested: int
    result_count: int
    results: List[SearchResult]


@app.on_event("startup")
def startup_event():
    init_db()


def _normalized_provider() -> str:
    return (VECTOR_DB_PROVIDER or "pgvector").strip().lower()


def get_openai_client() -> OpenAI:
    global openai_client
    if openai_client is None:
        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    return openai_client


def get_qdrant_client() -> QdrantClient:
    global qdrant_client
    if qdrant_client is None:
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return qdrant_client


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]{3,}\b", text.lower()))


def _keyword_overlap_score(query_tokens: set[str], text_content: str) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = _tokenize(text_content)
    if not chunk_tokens:
        return 0.0
    overlap = len(query_tokens & chunk_tokens)
    return overlap / max(len(query_tokens), 1)


def _extract_quoted_phrases(query: str) -> list[str]:
    phrases = re.findall(r"'([^']+)'|\"([^\"]+)\"", query)
    cleaned: list[str] = []
    for a, b in phrases:
        candidate = (a or b).strip().lower()
        if candidate:
            cleaned.append(candidate)
    return cleaned


def _quoted_phrase_boost(phrases: list[str], text_content: str) -> float:
    if not phrases:
        return 0.0
    lowered = text_content.lower()
    matches = sum(1 for phrase in phrases if phrase in lowered)
    if matches == 0:
        return 0.0
    return min(0.15, 0.05 * matches)


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


def _trim_context(text_content: str, max_chars: int) -> str:
    cleaned = " ".join(text_content.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."


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


def _classify_query(query: str, chapters: list[ChapterOption]) -> dict[str, Any]:
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
    quoted_phrases = _extract_quoted_phrases(raw_query)
    scored: list[SearchResult] = []
    for hit in hits:
        payload = hit.payload or {}
        text_content = payload.get("text", "") or ""
        vector_similarity = float(hit.score)
        lexical_similarity = _keyword_overlap_score(query_tokens, text_content)
        phrase_boost = _quoted_phrase_boost(quoted_phrases, text_content)
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
    quoted_phrases = _extract_quoted_phrases(raw_query)
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
        lexical_similarity = _keyword_overlap_score(query_tokens, chunk.text_content)
        phrase_boost = _quoted_phrase_boost(quoted_phrases, chunk.text_content)
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
    quoted_phrases = _extract_quoted_phrases(raw_query)
    rows: list[SearchResult] = []
    for point in points:
        payload = point.payload or {}
        lexical_similarity = _keyword_overlap_score(query_tokens, payload.get("text", "") or "")
        phrase_boost = _quoted_phrase_boost(quoted_phrases, payload.get("text", "") or "")
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

    quoted_phrases = _extract_quoted_phrases(raw_query)
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

        lexical_similarity = _keyword_overlap_score(query_tokens, chunk.text_content)
        phrase_boost = _quoted_phrase_boost(quoted_phrases, chunk.text_content)
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


def _build_system_prompt(task: str, style: str, language: str) -> str:
    task_instructions = {
        "summarize": "Produce a compact but comprehensive summary and key takeaways.",
        "explain": "Explain step-by-step with examples and simple wording when possible.",
        "qa": "Answer directly and concisely.",
        "generate_questions": "Generate practice questions from context. Include a short answer key at the end.",
        "compare": "Present comparisons clearly. Use a markdown table when useful.",
        "translate": f"Translate the requested content to {language}. Preserve meaning over literal wording.",
        "mind_map": "Return a mind-map style nested bullet structure from the context.",
        "quiz": "Generate a quiz with numbered questions and an answer key.",
        "other": "Answer clearly using the available context.",
    }
    style_instructions = {
        "beginner": "Write for a beginner student.",
        "child": "Write in child-friendly language.",
        "academic": "Use formal academic language.",
        "default": "Use clear student-friendly language.",
    }
    return (
        "You are a helpful student assistant for document QA.\n"
        "Answer strictly from retrieved context and do not invent facts.\n"
        "Always cite references using [Ref N] and include page/location guidance from that reference.\n"
        "Never use the word 'chunk' in citations.\n"
        f"Task behavior: {task_instructions.get(task, task_instructions['other'])}\n"
        f"Style behavior: {style_instructions.get(style, style_instructions['default'])}"
    )


def _context_char_budget(scope: str) -> int:
    if scope == "whole_book":
        return WHOLE_BOOK_CONTEXT_CHARS
    if scope in ("chapter", "page", "paragraph"):
        return CHAPTER_CONTEXT_CHARS
    return FACTOID_CONTEXT_CHARS


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


@app.get("/health")
def health():
    return {"status": "ok", "service": "search"}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    top_k = min(max(req.top_k, 1), MAX_TOP_K)
    query_tokens = _tokenize(query)
    chapters = _fetch_chapters(req.file_id)
    intent = _classify_query(query, chapters)
    scope = _resolve_scope(str(intent.get("scope", "factoid")))
    task = str(intent.get("task", "qa"))
    style = str(intent.get("style", "default"))
    language = str(intent.get("language", "en"))
    resolved_chapter = _resolve_chapter_number(req, intent, chapters)
    query_embedding: Optional[list[float]] = None

    if scope == "chapter" and req.file_id and chapters and resolved_chapter is None:
        try:
            emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[query])
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

    # If chapter cannot be inferred, continue with regular factoid retrieval
    # instead of blocking the user with a clarification requirement.
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

    if not results:
        return SearchResponse(
            answer="I could not find relevant content in the indexed documents for this query.",
            results=[],
        )

    ordered_results = sorted(results, key=lambda row: (row.score, -row.chunk_index), reverse=True)
    budget = _context_char_budget(scope)
    context_blocks = []
    for idx, row in enumerate(ordered_results, start=1):
        location = _build_location_hint(row)
        context_blocks.append(
            "\n".join(
                [
                    f"[Ref {idx}]",
                    f"Location: {location}",
                    f"Filename: {row.filename}",
                    f"File ID: {row.file_id}",
                    f"Similarity Score: {row.score:.4f}",
                    f"Content: {_trim_context(row.text_content, max_chars=budget)}",
                ]
            )
        )

    system_prompt = _build_system_prompt(task=task, style=style, language=language)
    context_text = "\n\n".join(context_blocks)
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
        answer = completion.choices[0].message.content or (
            "I could not generate an answer from the retrieved document context."
        )
    except Exception as exc:
        logger.exception("LLM answer generation failed: %s", exc)
        answer = "Sorry, I encountered an error while generating the answer from the document."

    return SearchResponse(answer=answer, results=ordered_results)


@app.post("/debug/retrieval", response_model=RetrievalDebugResponse)
def debug_retrieval(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    top_k = min(max(req.top_k, 1), MAX_TOP_K)
    query_tokens = _tokenize(query)
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
