import json
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import ceil
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

CURRENT_DIR = Path(__file__).resolve().parent
SHARED_DIR = CURRENT_DIR.parent / "shared"
if SHARED_DIR.exists() and str(SHARED_DIR) not in sys.path:
    sys.path.append(str(SHARED_DIR))

from config import (  # noqa: E402
    CHAT_MODEL,
    DEFAULT_TOP_K,
    EMBED_MODEL,
    MAX_CHUNK_CHARS,
    MAX_CONTEXT_CHARS,
    MAX_TOP_K,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
    VECTOR_DB_PROVIDER,
)
from cost import compute_chat_cost, compute_embedding_cost, parse_usage_tokens, record_cost  # noqa: E402
from db import DocumentChunk, GeneratedPaper, embedding_request_kwargs, get_db_context, init_db  # noqa: E402
from prompting import (  # noqa: E402
    build_question_paper_prompt,
    build_repair_prompt,
    normalize_distribution,
)

app = FastAPI(title="FixED - QPaper Service")
logger = logging.getLogger(__name__)

_openai_client = None
_qdrant_client = None

SECTION_KEYS = ("mcq", "subjective", "true_false", "fill_blank")
SECTION_LABELS = {
    "mcq": "Section A - Multiple Choice Questions",
    "subjective": "Section B - Subjective Questions",
    "true_false": "Section C - True / False",
    "fill_blank": "Section D - Fill in the Blanks",
}
DEFAULT_TIME_PER_MARK_MIN = 1.2
_PERCENT_TOKEN_PATTERN = r"(?:%|percent(?:age)?|per\s*cent|pct)"
_SECTION_ALIAS_PATTERN = (
    r"(?:"
    r"aptitude\s+mcqs?|scenario(?:-|\s)?based\s+mcqs?|assertion(?:-|\s)?reason(?:ing)?(?:\s+mcqs?)?|"
    r"multiple(?:-|\s)?choice(?:\s+questions?)?|mcqs?|"
    r"coding(?:-|\s)?based\s+subjective|long(?:-|\s)?form\s+theoretical|"
    r"viva(?:-|\s)?style|map(?:-|\s)?based|short\s+notes?|"
    r"descriptive(?:\s+questions?)?|subjective(?:\s+questions?)?|short(?:\s+answer)?|"
    r"long(?:\s+answer)?|case(?:-|\s)?based(?:\s+questions?)?|theoretical(?:\s+questions?)?|"
    r"picture(?:-|\s)?based\s+identification|match(?:-|\s)?the(?:-|\s)?following|"
    r"true\s*(?:/|or)?\s*false|t\s*/\s*f|tf|"
    r"fill(?:\s+in)?(?:\s+the)?\s+blanks?|fib"
    r")"
)


def _canonicalize_section_text(section_text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s/]+", " ", section_text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _strip_section_qualifiers(section_text: str) -> str:
    cleaned = _canonicalize_section_text(section_text)
    qualifiers = [
        "questions",
        "question",
        "type",
        "types",
        "based",
        "style",
        "section",
    ]
    for qualifier in qualifiers:
        cleaned = re.sub(rf"\b{qualifier}\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@dataclass
class SectionPlan:
    key: str
    title: str
    percent: int
    target_marks: int
    question_marks: list[int]
    mark_range: tuple[int, int]
    style_hint: str


@dataclass
class GenerationPlan:
    topic: str
    mode: str
    total_marks: int
    exam_time_minutes: int
    estimated_time_minutes: int
    section_distribution_percent: dict[str, int]
    section_mark_targets: dict[str, int]
    section_question_plan: dict[str, dict[str, Any]]
    source_request: str


class CostBreakdown(BaseModel):
    kind: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usd: float = 0.0


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
        self._rows.append(
            CostBreakdown(
                kind=kind,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                usd=float(usd_decimal),
            )
        )
        record_cost(
            service="qpaper",
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
        return {"usd": float(self._total), "breakdown": [row.model_dump() for row in self._rows]}


class GeneratePaperRequest(BaseModel):
    doc_id: str
    topic: str
    total_marks: int = Field(gt=0)
    distribution: dict[str, int]
    mode: Literal["official", "practice"] = "official"
    top_k: int = DEFAULT_TOP_K
    chapter_number: Optional[int] = None
    request_text: Optional[str] = None
    exam_time_minutes: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_distribution(self) -> "GeneratePaperRequest":
        normalized = normalize_distribution(self.distribution)
        if any(value < 0 for value in normalized.values()):
            raise ValueError("Distribution values must be non-negative.")
        if sum(normalized.values()) != 100 and not (self.request_text and self.request_text.strip()):
            raise ValueError("Distribution values must sum to 100.")
        if self.top_k < 1:
            raise ValueError("top_k must be at least 1.")
        return self


class RetrievedChunk(BaseModel):
    ref_id: str
    chunk_id: str
    file_id: str
    filename: str
    chunk_index: int
    text_content: str
    score: float
    page_number: Optional[int] = None
    chapter_number: Optional[int] = None


class GeneratedPaperResponse(BaseModel):
    paper_id: str
    file_id: str
    topic: str
    mode: str
    total_marks: int
    distribution: dict[str, int]
    paper: dict[str, Any]
    retrieved_chunks: list[RetrievedChunk]
    cost: dict[str, Any]
    created_at: str


class GeneratedPaperHistoryItem(BaseModel):
    paper_id: str
    file_id: str
    topic: str
    mode: str
    total_marks: int
    distribution: dict[str, int]
    paper: dict[str, Any]
    cost_usd: float
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


def _chunk_from_payload(payload: dict[str, Any], chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        ref_id="",
        chunk_id=chunk_id,
        file_id=str(payload.get("file_id", "")),
        filename=str(payload.get("filename", "")),
        chunk_index=int(payload.get("chunk_index", 0)),
        text_content=str(payload.get("text", "") or ""),
        score=score,
        page_number=_metadata_int(payload, "page_number"),
        chapter_number=_metadata_int(payload, "chapter_number"),
    )


def _retrieve_with_qdrant(
    file_id: str,
    topic_embedding: list[float],
    top_k: int,
    chapter_number: Optional[int] = None,
) -> list[RetrievedChunk]:
    client = get_qdrant_client()
    must = [FieldCondition(key="file_id", match=MatchValue(value=file_id))]
    if chapter_number is not None:
        must.append(FieldCondition(key="chapter_number", match=MatchValue(value=chapter_number)))
    query_filter = Filter(must=must)

    if hasattr(client, "search"):
        hits = client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=topic_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    else:
        query_result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=topic_embedding,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        hits = getattr(query_result, "points", query_result)

    chunks: list[RetrievedChunk] = []
    for hit in hits:
        payload = hit.payload or {}
        chunks.append(_chunk_from_payload(payload, str(getattr(hit, "id", "")), float(hit.score)))
    chunks.sort(key=lambda row: row.score, reverse=True)
    return _assign_ref_ids(chunks)


def _retrieve_with_pgvector(
    file_id: str,
    topic_embedding: list[float],
    top_k: int,
    chapter_number: Optional[int] = None,
) -> list[RetrievedChunk]:
    with get_db_context() as db:
        distance_col = DocumentChunk.embedding.cosine_distance(topic_embedding).label("distance")
        stmt = (
            select(DocumentChunk, distance_col)
            .where(DocumentChunk.file_id == file_id)
            .order_by(distance_col)
            .limit(top_k)
        )
        rows = db.execute(stmt).all()

    chunks: list[RetrievedChunk] = []
    for chunk, dist in rows:
        metadata = chunk.metadata_ or {}
        chunk_chapter = _metadata_int(metadata, "chapter_number")
        if chapter_number is not None and chunk_chapter != chapter_number:
            continue
        chunks.append(
            RetrievedChunk(
                ref_id="",
                chunk_id=chunk.id,
                file_id=chunk.file_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                score=1.0 - float(dist if dist is not None else 0.0),
                page_number=_metadata_int(metadata, "page_number"),
                chapter_number=chunk_chapter,
            )
        )
    chunks.sort(key=lambda row: row.score, reverse=True)
    return _assign_ref_ids(chunks[:top_k])


def _assign_ref_ids(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    for idx, row in enumerate(chunks, start=1):
        row.ref_id = f"Ref {idx}"
    return chunks


def _retrieve_topic_chunks(
    file_id: str,
    topic_embedding: list[float],
    top_k: int,
    chapter_number: Optional[int] = None,
) -> list[RetrievedChunk]:
    if _normalized_provider() == "qdrant":
        return _retrieve_with_qdrant(
            file_id=file_id,
            topic_embedding=topic_embedding,
            top_k=top_k,
            chapter_number=chapter_number,
        )
    return _retrieve_with_pgvector(
        file_id=file_id,
        topic_embedding=topic_embedding,
        top_k=top_k,
        chapter_number=chapter_number,
    )


def _build_context_text(chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    total_chars = 0
    for row in chunks:
        trimmed = (row.text_content or "").strip()
        if len(trimmed) > MAX_CHUNK_CHARS:
            trimmed = f"{trimmed[:MAX_CHUNK_CHARS]}..."
        block = (
            f"[{row.ref_id}]\n"
            f"File ID: {row.file_id}\n"
            f"Filename: {row.filename}\n"
            f"Page: {row.page_number}\n"
            f"Chapter: {row.chapter_number}\n"
            f"Content: {trimmed}"
        )
        total_chars += len(block)
        if total_chars > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
    return "\n\n".join(blocks)


def _extract_total_marks_from_text(text: str) -> Optional[int]:
    match = re.search(r"\b(\d{1,3})\s*marks?\b", text.lower())
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return max(value, 1)


def _extract_exam_time_minutes(text: str) -> Optional[int]:
    lowered = text.lower()
    hour_match = re.search(r"\b(\d{1,2})\s*(?:hours?|hrs?)\b", lowered)
    minute_match = re.search(r"\b(\d{1,3})\s*(?:minutes?|mins?)\b", lowered)
    minutes = 0
    if hour_match:
        try:
            minutes += int(hour_match.group(1)) * 60
        except ValueError:
            minutes += 0
    if minute_match:
        try:
            minutes += int(minute_match.group(1))
        except ValueError:
            minutes += 0
    return minutes if minutes > 0 else None


def _normalize_qpaper_section(section_text: str) -> Optional[str]:
    lowered = _strip_section_qualifiers(section_text)
    if not lowered:
        return None

    if any(
        token in lowered
        for token in (
            "mcq",
            "multiple choice",
            "aptitude",
            "scenario",
            "assertion reason",
            "picture based identification",
            "match the following",
        )
    ):
        return "mcq"
    if any(
        token in lowered
        for token in (
            "subjective",
            "descriptive",
            "short note",
            "short answer",
            "long form theoretical",
            "long answer",
            "theoretical",
            "coding",
            "viva",
            "map",
            "case",
        )
    ):
        return "subjective"
    if any(token in lowered for token in ("true false", "true or false", "true/false", "t/f", "tf")):
        return "true_false"
    if any(token in lowered for token in ("fill blank", "fill blanks", "fill in the blank", "fill in the blanks", "fib")):
        return "fill_blank"
    return None


def _round_distribution_to_hundred(values: dict[str, float]) -> dict[str, int]:
    rounded = {key: int(round(max(values.get(key, 0.0), 0.0))) for key in SECTION_KEYS}
    mismatch = 100 - sum(rounded.values())
    if mismatch == 0:
        return rounded
    largest = max(
        SECTION_KEYS,
        key=lambda key: (values.get(key, 0.0), rounded.get(key, 0)),
    )
    rounded[largest] += mismatch
    if rounded[largest] < 0:
        rounded[largest] = 0
    if sum(rounded.values()) != 100:
        total = max(sum(rounded.values()), 1)
        scaled = {key: (rounded[key] * 100.0) / total for key in SECTION_KEYS}
        rounded = {key: int(round(scaled[key])) for key in SECTION_KEYS}
        mismatch = 100 - sum(rounded.values())
        if mismatch != 0:
            largest = max(SECTION_KEYS, key=lambda key: rounded.get(key, 0))
            rounded[largest] += mismatch
    return rounded


def _equal_distribution_percent() -> dict[str, int]:
    base = {key: 100.0 / len(SECTION_KEYS) for key in SECTION_KEYS}
    return _round_distribution_to_hundred(base)


def _parse_distribution_from_text(text: str) -> Optional[dict[str, int]]:
    lowered = text.lower()
    if any(token in lowered for token in ("equal distribution", "equally distribute", "equal marks", "same marks")):
        listed_sections: list[str] = []
        equal_scope_match = re.search(
            rf"(?:equal distribution|equally distribute|equal marks|same marks)(?:\s+of|\s+among|\s+between)?\s+(.+?)(?:$|(?:\s+(?:for|on)\s+))",
            text,
            flags=re.IGNORECASE,
        )
        if equal_scope_match:
            scope_text = str(equal_scope_match.group(1) or "")
            for raw_section in re.findall(_SECTION_ALIAS_PATTERN, scope_text, flags=re.IGNORECASE):
                normalized = _normalize_qpaper_section(raw_section)
                if normalized and normalized not in listed_sections:
                    listed_sections.append(normalized)
        if listed_sections:
            share = 100.0 / len(listed_sections)
            values = {key: (share if key in listed_sections else 0.0) for key in SECTION_KEYS}
            return _round_distribution_to_hundred(values)
        return _equal_distribution_percent()

    percent_token = _PERCENT_TOKEN_PATTERN
    section_pattern = _SECTION_ALIAS_PATTERN
    assignments: dict[str, Optional[int]] = {key: None for key in SECTION_KEYS}
    found_assignment = False

    for match in re.finditer(
        rf"(\d{{1,3}})\s*{percent_token}\s*(?:of\s+)?({section_pattern})",
        text,
        flags=re.IGNORECASE,
    ):
        section = _normalize_qpaper_section(str(match.group(2) or ""))
        if section is None:
            continue
        assignments[section] = max(0, min(int(match.group(1)), 100))
        found_assignment = True

    for match in re.finditer(
        rf"({section_pattern})\s*(?:is|are|at|of)?\s*(\d{{1,3}})\s*{percent_token}",
        text,
        flags=re.IGNORECASE,
    ):
        section = _normalize_qpaper_section(str(match.group(1) or ""))
        if section is None:
            continue
        assignments[section] = max(0, min(int(match.group(2)), 100))
        found_assignment = True

    remaining_match = re.search(
        rf"\b(?:remaining|rest)\b(?:\s+(?:is|are|marks?|portion|questions?|to|for|in|of|go(?:es)?\s+to)){{0,6}}\s+({section_pattern})",
        text,
        flags=re.IGNORECASE,
    )
    if remaining_match:
        section = _normalize_qpaper_section(str(remaining_match.group(1) or ""))
        if section:
            known = sum(value for value in assignments.values() if value is not None)
            assignments[section] = max(0, 100 - known)
            found_assignment = True

    if not found_assignment:
        return None

    known_sum = sum(value for value in assignments.values() if value is not None)
    unspecified = [key for key in SECTION_KEYS if assignments[key] is None]
    if known_sum < 100 and unspecified:
        remainder = 100 - known_sum
        share = remainder // len(unspecified)
        extra = remainder % len(unspecified)
        for idx, key in enumerate(unspecified):
            assignments[key] = share + (1 if idx < extra else 0)
    filled = {key: int(assignments.get(key) or 0) for key in SECTION_KEYS}
    return _round_distribution_to_hundred(filled)


def _extract_topic_from_request(topic: str, request_text: str) -> str:
    if not request_text.strip():
        return topic
    topic_match = re.search(
        r"\b(?:on|for)\s+(?:the\s+)?(?:topic|chapter|subject)(?:\s+of)?\s+(.+?)(?:$|(?:\s+with\s+\d{1,3}\s*(?:%|percent(?:age)?|per\s*cent|pct)))",
        request_text,
        flags=re.IGNORECASE,
    )
    if topic_match:
        extracted = str(topic_match.group(1) or "").strip(" .,:-")
        if extracted:
            return extracted

    cleaned = request_text
    cleaned = re.sub(
        r"\b(create|generate|make|prepare)\s+(an?\s+)?(exam|question\s*paper|test\s*paper)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b\d{1,3}\s*marks?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\b\d{{1,3}}\s*{_PERCENT_TOKEN_PATTERN}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(_SECTION_ALIAS_PATTERN, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:remaining|rest)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:minutes?|mins?|hours?|hrs?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:-")
    return cleaned or topic


def _mark_targets(total_marks: int, distribution_percent: dict[str, int]) -> dict[str, int]:
    safe_distribution = {key: max(int(distribution_percent.get(key, 0) or 0), 0) for key in SECTION_KEYS}
    if sum(safe_distribution.values()) <= 0:
        safe_distribution = _equal_distribution_percent()

    raw_targets = {key: (total_marks * safe_distribution[key]) / 100.0 for key in SECTION_KEYS}
    floored = {key: int(raw_targets[key]) for key in SECTION_KEYS}
    remainder = total_marks - sum(floored.values())
    ranked = sorted(
        SECTION_KEYS,
        key=lambda key: (raw_targets[key] - floored[key], safe_distribution[key], raw_targets[key]),
        reverse=True,
    )
    idx = 0
    while remainder > 0 and ranked:
        key = ranked[idx % len(ranked)]
        floored[key] += 1
        remainder -= 1
        idx += 1

    if any(value < 0 for value in floored.values()):
        floored = {key: max(value, 0) for key, value in floored.items()}
        mismatch = total_marks - sum(floored.values())
        if mismatch > 0:
            largest = max(SECTION_KEYS, key=lambda key: floored.get(key, 0))
            floored[largest] += mismatch
    return floored


def _best_mark_list(current: Optional[list[int]], candidate: list[int]) -> list[int]:
    if current is None:
        return candidate
    if len(candidate) > len(current):
        return candidate
    if len(candidate) < len(current):
        return current
    return candidate if sorted(candidate) < sorted(current) else current


def _compose_question_marks(target_marks: int, allowed_marks: list[int]) -> list[int]:
    if target_marks <= 0:
        return []
    unique_marks = sorted({mark for mark in allowed_marks if mark > 0})
    if not unique_marks:
        return [target_marks]

    best: list[Optional[list[int]]] = [None] * (target_marks + 1)
    best[0] = []
    for score in range(1, target_marks + 1):
        best_candidate: Optional[list[int]] = None
        for mark in unique_marks:
            prev = score - mark
            if prev < 0 or best[prev] is None:
                continue
            candidate = list(best[prev]) + [mark]
            best_candidate = _best_mark_list(best_candidate, candidate)
        best[score] = best_candidate

    composed = best[target_marks]
    if composed is None:
        return [target_marks]
    return sorted(composed)


def _subjective_mark_range(source_request: str) -> tuple[tuple[int, int], str]:
    lowered = source_request.lower()
    if "derivation" in lowered or "long" in lowered:
        return (5, 8), "Use long/derivation-style subjective questions."
    if "case" in lowered:
        return (4, 5), "Use case-based subjective questions."
    if "short" in lowered or "brief" in lowered:
        return (2, 3), "Use short-answer subjective questions."
    return (2, 5), "Prefer short answers, add medium complexity where needed."


def _section_mark_profile(section_key: str, source_request: str) -> tuple[tuple[int, int], str]:
    if section_key in {"mcq", "true_false", "fill_blank"}:
        return (1, 1), "Keep these as 1-mark objective questions."
    return _subjective_mark_range(source_request)


def _build_section_plan(
    section_key: str,
    percent: int,
    target_marks: int,
    source_request: str,
) -> SectionPlan:
    mark_range, style_hint = _section_mark_profile(section_key, source_request)
    allowed_marks = list(range(mark_range[0], mark_range[1] + 1))
    question_marks = _compose_question_marks(target_marks, allowed_marks)
    return SectionPlan(
        key=section_key,
        title=SECTION_LABELS[section_key],
        percent=percent,
        target_marks=target_marks,
        question_marks=question_marks,
        mark_range=mark_range,
        style_hint=style_hint,
    )


def _build_generation_plan(req: GeneratePaperRequest) -> GenerationPlan:
    request_text = (req.request_text or "").strip()
    source_request = request_text or req.topic.strip()

    parsed_total_marks = _extract_total_marks_from_text(source_request)
    total_marks = int(parsed_total_marks or req.total_marks)

    parsed_distribution = _parse_distribution_from_text(source_request)
    if parsed_distribution is None:
        parsed_distribution = normalize_distribution(req.distribution)
    section_distribution_percent = _round_distribution_to_hundred(
        {key: float(parsed_distribution.get(key, 0)) for key in SECTION_KEYS}
    )
    section_mark_targets = _mark_targets(total_marks, section_distribution_percent)

    parsed_time = _extract_exam_time_minutes(source_request)
    estimated_time = int(ceil(total_marks * DEFAULT_TIME_PER_MARK_MIN))
    exam_time_minutes = int(req.exam_time_minutes or parsed_time or estimated_time)
    topic = _extract_topic_from_request(req.topic.strip(), source_request)

    section_question_plan: dict[str, dict[str, Any]] = {}
    for key in SECTION_KEYS:
        section_plan = _build_section_plan(
            section_key=key,
            percent=section_distribution_percent.get(key, 0),
            target_marks=section_mark_targets.get(key, 0),
            source_request=source_request,
        )
        section_question_plan[key] = {
            "title": section_plan.title,
            "percent": section_plan.percent,
            "target_marks": section_plan.target_marks,
            "question_marks": section_plan.question_marks,
            "mark_range": [section_plan.mark_range[0], section_plan.mark_range[1]],
            "style_hint": section_plan.style_hint,
        }

    return GenerationPlan(
        topic=topic,
        mode=req.mode,
        total_marks=total_marks,
        exam_time_minutes=exam_time_minutes,
        estimated_time_minutes=estimated_time,
        section_distribution_percent=section_distribution_percent,
        section_mark_targets=section_mark_targets,
        section_question_plan=section_question_plan,
        source_request=source_request,
    )


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw_text, flags=re.I)
    if fence_match:
        fenced = fence_match.group(1).strip()
        parsed = json.loads(fenced)
        if isinstance(parsed, dict):
            return parsed

    in_string = False
    escaped = False
    depth = 0
    start_idx = None
    candidates: list[str] = []
    for idx, ch in enumerate(raw_text):
        if ch == '"' and not escaped:
            in_string = not in_string
        if ch == "\\" and not escaped:
            escaped = True
            continue
        escaped = False
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    candidates.append(raw_text[start_idx : idx + 1])
                    start_idx = None

    for candidate in sorted(candidates, key=len, reverse=True):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("Model response did not include a valid JSON object.")


def _validate_paper_json(
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
) -> list[str]:
    errors: list[str] = []
    section_totals: dict[str, int] = {key: 0 for key in SECTION_KEYS}
    for key in SECTION_KEYS:
        section_rows = payload.get(key)
        if section_rows is None:
            errors.append(f"Missing key: {key}")
            continue
        if not isinstance(section_rows, list):
            errors.append(f"Key {key} must be an array.")
            continue
        for idx, row in enumerate(section_rows, start=1):
            if not isinstance(row, dict):
                errors.append(f"{key}[{idx}] must be an object.")
                continue
            if not isinstance(row.get("question"), str) or not row.get("question", "").strip():
                errors.append(f"{key}[{idx}] must include a non-empty question.")
            marks = row.get("marks")
            if not isinstance(marks, int) or marks <= 0:
                errors.append(f"{key}[{idx}] marks must be a positive integer.")
            else:
                section_totals[key] += marks
            if not isinstance(row.get("answer"), str) or not row.get("answer", "").strip():
                errors.append(f"{key}[{idx}] must include a non-empty answer.")
            source_refs = row.get("source_refs")
            if not isinstance(source_refs, list) or not source_refs:
                errors.append(f"{key}[{idx}] must include source_refs array.")

            if key == "mcq":
                options = row.get("options")
                if not isinstance(options, list) or len(options) < 2:
                    errors.append(f"{key}[{idx}] must include options array with at least 2 entries.")

    overall = sum(section_totals.values())
    if overall != total_marks:
        errors.append(f"Total marks mismatch: expected {total_marks}, got {overall}.")
    for key in SECTION_KEYS:
        expected = section_targets.get(key, 0)
        if section_totals[key] != expected:
            errors.append(
                f"Section marks mismatch for {key}: expected {expected}, got {section_totals[key]}."
            )
    return errors


def _is_marks_only_error(error: str) -> bool:
    return error.startswith("Total marks mismatch:") or error.startswith("Section marks mismatch for ")


def _section_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _section_total(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        marks = row.get("marks")
        if isinstance(marks, int) and marks > 0:
            total += marks
    return total


def _normalize_mcq_options(answer: str, options: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(options, list):
        for option in options:
            if isinstance(option, str) and option.strip():
                rows.append(option.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for option in rows:
        lowered = option.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(option)
    return deduped[:4]


def _sanitize_paper_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = json.loads(json.dumps(payload))
    if isinstance(sanitized.get("sections"), list):
        for section_row in sanitized.get("sections", []):
            if not isinstance(section_row, dict):
                continue
            section_key = str(section_row.get("section_key") or "").strip()
            if section_key not in SECTION_KEYS:
                continue
            questions = section_row.get("questions")
            if isinstance(questions, list):
                sanitized[section_key] = questions
    for key in SECTION_KEYS:
        rows = sanitized.get(key)
        if not isinstance(rows, list):
            sanitized[key] = []
            continue
        cleaned_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            question = row.get("question")
            answer = row.get("answer")
            marks = row.get("marks")
            source_refs = row.get("source_refs")

            if not isinstance(question, str) or not question.strip():
                question = ""
            if not isinstance(answer, str) or not answer.strip():
                answer = ""
            if not isinstance(marks, int) or marks <= 0:
                marks = 0
            if not isinstance(source_refs, list) or not source_refs:
                source_refs = []
            else:
                normalized_refs = [ref for ref in source_refs if isinstance(ref, str) and ref.strip()]
                source_refs = normalized_refs

            cleaned = {
                "question": question.strip(),
                "answer": answer.strip(),
                "marks": marks,
                "source_refs": source_refs,
            }
            if key == "mcq":
                cleaned["options"] = _normalize_mcq_options(answer=cleaned["answer"], options=row.get("options"))
            elif "options" in row and isinstance(row.get("options"), list):
                cleaned["options"] = row.get("options")
            cleaned_rows.append(cleaned)
        sanitized[key] = cleaned_rows
    return sanitized


def _enforce_question_plan(
    payload: dict[str, Any],
    section_targets: dict[str, int],
    section_question_plan: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enforced = json.loads(json.dumps(payload))
    for key in SECTION_KEYS:
        target = int(section_targets.get(key, 0) or 0)
        if target <= 0:
            enforced[key] = []
            continue
        raw_marks = section_question_plan.get(key, {}).get("question_marks") if section_question_plan else []
        planned_marks = [int(mark) for mark in raw_marks if isinstance(mark, int) and mark > 0]
        if not planned_marks:
            continue
        rows = _section_rows(enforced, key)
        if not rows:
            enforced[key] = []
            continue
        if len(rows) > len(planned_marks):
            rows = rows[: len(planned_marks)]
        elif len(rows) < len(planned_marks):
            templates = [json.loads(json.dumps(row)) for row in rows]
            idx = 0
            while len(rows) < len(planned_marks) and templates:
                rows.append(json.loads(json.dumps(templates[idx % len(templates)])))
                idx += 1
        for idx, mark in enumerate(planned_marks):
            if idx >= len(rows):
                break
            rows[idx]["marks"] = mark
        enforced[key] = rows
    return enforced


def _range_for_section(section_key: str, source_request: str) -> tuple[int, int]:
    section_range, _ = _section_mark_profile(section_key, source_request)
    return section_range


def _inject_structure_and_summary(
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
    section_question_plan: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = json.loads(json.dumps(payload))
    sections: list[dict[str, Any]] = []
    marks_summary: list[dict[str, Any]] = []
    grand_actual = 0
    question_count = 0
    for key in SECTION_KEYS:
        rows = _section_rows(enriched, key)
        actual = _section_total(rows)
        target = int(section_targets.get(key, 0) or 0)
        title = str(section_question_plan.get(key, {}).get("title") or SECTION_LABELS.get(key, key))
        sections.append(
            {
                "section_key": key,
                "section_title": title,
                "target_marks": target,
                "questions": rows,
            }
        )
        marks_summary.append(
            {
                "section_key": key,
                "section_title": title,
                "target_marks": target,
                "actual_marks": actual,
                "question_count": len(rows),
            }
        )
        grand_actual += actual
        question_count += len(rows)
    marks_summary.append(
        {
            "section_key": "grand_total",
            "section_title": "Grand Total",
            "target_marks": total_marks,
            "actual_marks": grand_actual,
            "question_count": question_count,
        }
    )
    enriched["section_headers"] = {key: SECTION_LABELS[key] for key in SECTION_KEYS}
    enriched["sections"] = sections
    enriched["marks_summary_heading"] = "Final Marks Summary"
    enriched["marks_summary"] = marks_summary
    # Keep legacy API behavior while adding richer structure for consumers.
    enriched["computed_mark_targets"] = {key: int(section_targets.get(key, 0) or 0) for key in SECTION_KEYS}
    enriched["computed_total_marks"] = int(total_marks)
    return enriched


def _section_presence_errors(payload: dict[str, Any], section_targets: dict[str, int]) -> list[str]:
    errors: list[str] = []
    for key in SECTION_KEYS:
        target = int(section_targets.get(key, 0) or 0)
        rows = _section_rows(payload, key)
        if target > 0 and not rows:
            errors.append(f"Section {key} requires questions because target marks is {target}.")
    return errors


def _quality_errors(
    payload: dict[str, Any],
    section_targets: dict[str, int],
    source_request: str,
) -> list[str]:
    errors: list[str] = []
    placeholder_answers = {
        "answer unavailable from model output",
        "not provided",
        "n/a",
    }
    generic_option_pattern = re.compile(r"^option\s+[a-d]$", flags=re.IGNORECASE)
    for key in SECTION_KEYS:
        if int(section_targets.get(key, 0) or 0) <= 0:
            continue
        rows = _section_rows(payload, key)
        for idx, row in enumerate(rows, start=1):
            question = str(row.get("question") or "").strip()
            answer = str(row.get("answer") or "").strip()
            if question.lower() in {"question", "sample question", "n/a"}:
                errors.append(f"{key}[{idx}] question is too generic.")
            if answer.lower() in placeholder_answers:
                errors.append(f"{key}[{idx}] answer is placeholder text.")
            if key == "true_false" and answer.lower() not in {"true", "false"}:
                errors.append(f"{key}[{idx}] answer must be True or False.")
            if key == "fill_blank" and "____" not in question:
                errors.append(f"{key}[{idx}] question must include a blank placeholder like ____.")
            if key == "mcq":
                options = row.get("options")
                if not isinstance(options, list) or len(options) != 4:
                    errors.append(f"{key}[{idx}] must include exactly 4 options.")
                    continue
                cleaned_options = [str(opt).strip() for opt in options if isinstance(opt, str) and str(opt).strip()]
                if len(cleaned_options) != 4:
                    errors.append(f"{key}[{idx}] options must be non-empty strings.")
                    continue
                if any(generic_option_pattern.match(opt) for opt in cleaned_options):
                    errors.append(f"{key}[{idx}] options are generic placeholders.")
                if answer and answer not in cleaned_options:
                    errors.append(f"{key}[{idx}] answer must match one provided option.")

            marks = row.get("marks")
            if isinstance(marks, int) and marks > 0:
                min_mark, max_mark = _range_for_section(key, source_request)
                section_target = int(section_targets.get(key, 0) or 0)
                if section_target > 0 and section_target < min_mark:
                    min_mark = 1
                if marks < min_mark or marks > max_mark:
                    errors.append(
                        f"{key}[{idx}] marks must be between {min_mark} and {max_mark}."
                    )
    return errors


def _paper_errors(
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
    source_request: str,
) -> list[str]:
    errors = _validate_paper_json(payload, total_marks, section_targets)
    errors.extend(_section_presence_errors(payload, section_targets))
    errors.extend(_quality_errors(payload, section_targets, source_request=source_request))
    if str(payload.get("marks_summary_heading") or "").strip().lower() != "final marks summary":
        errors.append("marks_summary_heading must be 'Final Marks Summary'.")
    marks_summary = payload.get("marks_summary")
    if not isinstance(marks_summary, list) or not marks_summary:
        errors.append("marks_summary must be a non-empty array.")
    return errors


def _sections_needing_questions(payload: dict[str, Any], section_targets: dict[str, int]) -> list[str]:
    missing: list[str] = []
    for key in SECTION_KEYS:
        if int(section_targets.get(key, 0) or 0) <= 0:
            continue
        if not _section_rows(payload, key):
            missing.append(key)
    return missing


def _increase_marks(
    rows: list[dict[str, Any]],
    amount: int,
    min_mark: int = 1,
    max_mark: Optional[int] = None,
) -> int:
    if amount <= 0 or not rows:
        return amount
    idx = 0
    guard = 0
    max_iters = max(len(rows) * max(amount, 1) * 4, 1)
    while amount > 0 and guard < max_iters:
        row = rows[idx % len(rows)]
        marks = row.get("marks")
        if not isinstance(marks, int) or marks <= 0:
            marks = max(min_mark, 1)
        can_increase = True if max_mark is None else marks < max_mark
        if can_increase:
            row["marks"] = marks + 1
            amount -= 1
        idx += 1
        guard += 1
    return amount


def _decrease_marks(rows: list[dict[str, Any]], amount: int, min_mark: int = 1) -> int:
    if amount <= 0 or not rows:
        return amount
    idx = 0
    guard = 0
    max_iters = max(len(rows) * max(amount, 1) * 3, 1)
    while amount > 0 and guard < max_iters:
        row = rows[idx % len(rows)]
        marks = row.get("marks")
        if isinstance(marks, int) and marks > max(min_mark, 1):
            row["marks"] = marks - 1
            amount -= 1
        idx += 1
        guard += 1
    return amount


def _rebalance_marks_to_targets(
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
    source_request: str = "",
) -> dict[str, Any]:
    # Work on a deep copy so we do not mutate intermediate model output in-place unexpectedly.
    balanced = json.loads(json.dumps(payload))

    section_rows_map: dict[str, list[dict[str, Any]]] = {
        key: _section_rows(balanced, key) for key in SECTION_KEYS
    }

    # First pass: make each section close to requested target.
    for key in SECTION_KEYS:
        rows = section_rows_map[key]
        target = section_targets.get(key, 0)
        current = _section_total(rows)
        min_mark, max_mark = _range_for_section(key, source_request)
        if current < target:
            _increase_marks(rows, target - current, min_mark=min_mark, max_mark=max_mark)
        elif current > target:
            _decrease_marks(rows, current - target, min_mark=min_mark)

    # Second pass: force overall total if section balancing could not fully converge.
    overall = sum(_section_total(section_rows_map[key]) for key in SECTION_KEYS)
    if overall < total_marks:
        deficit = total_marks - overall
        preferred_sections = [
            key
            for key in SECTION_KEYS
            if section_rows_map[key] and _section_total(section_rows_map[key]) < section_targets.get(key, 0)
        ]
        if not preferred_sections:
            preferred_sections = [key for key in SECTION_KEYS if section_rows_map[key]]
        if not preferred_sections:
            return balanced
        idx = 0
        while deficit > 0:
            key = preferred_sections[idx % len(preferred_sections)]
            min_mark, max_mark = _range_for_section(key, source_request)
            before = deficit
            deficit = _increase_marks(
                section_rows_map[key],
                deficit,
                min_mark=min_mark,
                max_mark=max_mark,
            )
            if deficit == before:
                break
            idx += 1
    elif overall > total_marks:
        surplus = overall - total_marks
        preferred_sections = [key for key in SECTION_KEYS if section_rows_map[key]]
        if not preferred_sections:
            return balanced
        idx = 0
        guard = 0
        max_iters = max(len(preferred_sections) * max(surplus, 1) * 5, 1)
        while surplus > 0 and guard < max_iters:
            key = preferred_sections[idx % len(preferred_sections)]
            before = surplus
            min_mark, _ = _range_for_section(key, source_request)
            surplus = _decrease_marks(section_rows_map[key], surplus, min_mark=min_mark)
            if surplus == before:
                idx += 1
            else:
                idx += 1
            guard += 1

    return balanced


def _repair_paper_payload(
    file_id: str,
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
    section_question_plan: dict[str, dict[str, Any]],
    validation_errors: list[str],
    focus_sections: Optional[list[str]],
    source_request: str,
    cost_tracker: _CostTracker,
) -> dict[str, Any]:
    repair_completion = get_openai_client().chat.completions.create(
        model=CHAT_MODEL,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {
                "role": "user",
                "content": build_repair_prompt(
                    previous_json_text=json.dumps(payload),
                    total_marks=total_marks,
                    section_mark_targets=section_targets,
                    section_question_plan=section_question_plan,
                    validation_errors=validation_errors,
                    focus_sections=focus_sections,
                    source_request=source_request,
                ),
            },
        ],
    )
    cost_tracker.add_chat(
        kind="chat",
        model=CHAT_MODEL,
        usage=getattr(repair_completion, "usage", None),
        file_id=file_id,
        meta={"reason": "paper_generation_repair", "focus_sections": focus_sections or []},
    )
    repaired_text = repair_completion.choices[0].message.content or ""
    repaired = _extract_json_payload(repaired_text)
    repaired = _sanitize_paper_payload(repaired)
    repaired = _enforce_question_plan(
        payload=repaired,
        section_targets=section_targets,
        section_question_plan=section_question_plan,
    )
    repaired = _rebalance_marks_to_targets(
        payload=repaired,
        total_marks=total_marks,
        section_targets=section_targets,
        source_request=source_request,
    )
    repaired = _inject_structure_and_summary(
        payload=repaired,
        total_marks=total_marks,
        section_targets=section_targets,
        section_question_plan=section_question_plan,
    )
    return repaired


def _save_generated_paper(
    file_id: str,
    topic: str,
    mode: str,
    total_marks: int,
    distribution: dict[str, int],
    paper_payload: dict[str, Any],
    retrieved_chunks: list[RetrievedChunk],
    cost_payload: dict[str, Any],
) -> tuple[str, str]:
    with get_db_context() as db:
        row = GeneratedPaper(
            file_id=file_id,
            topic=topic,
            mode=mode,
            total_marks=total_marks,
            distribution_json=distribution,
            paper_json=paper_payload,
            retrieval_json=[chunk.model_dump() for chunk in retrieved_chunks],
            cost_usd=Decimal(str(cost_payload.get("usd", 0.0))),
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        paper_id = str(row.id)
        created_at = row.created_at.isoformat() if row.created_at else datetime.utcnow().isoformat()
        return paper_id, created_at


def _history_item(row: GeneratedPaper) -> GeneratedPaperHistoryItem:
    return GeneratedPaperHistoryItem(
        paper_id=str(row.id),
        file_id=row.file_id,
        topic=row.topic,
        mode=row.mode,
        total_marks=row.total_marks,
        distribution=dict(row.distribution_json or {}),
        paper=dict(row.paper_json or {}),
        cost_usd=float(row.cost_usd or 0.0),
        created_at=row.created_at.isoformat(),
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "qpaper"}


@app.post("/generate", response_model=GeneratedPaperResponse)
def generate_paper(req: GeneratePaperRequest):
    file_id = req.doc_id.strip()
    plan = _build_generation_plan(req)
    topic = plan.topic.strip()
    if not file_id:
        raise HTTPException(status_code=400, detail="doc_id cannot be empty.")
    if not topic:
        raise HTTPException(status_code=400, detail="topic cannot be empty.")

    normalized_distribution = plan.section_distribution_percent
    section_targets = plan.section_mark_targets
    safe_top_k = min(max(req.top_k, 1), MAX_TOP_K)
    cost_tracker = _CostTracker()

    try:
        emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[topic], **embedding_request_kwargs(EMBED_MODEL))
        cost_tracker.add_embedding(
            kind="embedding",
            model=EMBED_MODEL,
            usage=getattr(emb_resp, "usage", None),
            file_id=file_id,
            meta={"reason": "paper_topic_embedding"},
        )
        topic_embedding = emb_resp.data[0].embedding
    except Exception as exc:
        logger.exception("Topic embedding failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to embed topic query.")

    try:
        retrieved = _retrieve_topic_chunks(
            file_id=file_id,
            topic_embedding=topic_embedding,
            top_k=safe_top_k,
            chapter_number=req.chapter_number,
        )
    except Exception as exc:
        logger.exception("Retrieval failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Vector retrieval failed: {str(exc)}")

    if not retrieved:
        raise HTTPException(status_code=404, detail="No relevant chunks found for this topic.")

    context_text = _build_context_text(retrieved)
    system_prompt = build_question_paper_prompt(
        topic=topic,
        mode=req.mode,
        total_marks=plan.total_marks,
        exam_time_minutes=plan.exam_time_minutes,
        estimated_time_minutes=plan.estimated_time_minutes,
        section_mark_targets=section_targets,
        section_question_plan=plan.section_question_plan,
        source_request=plan.source_request,
    )

    llm_text = ""
    try:
        completion = get_openai_client().chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Retrieved context:\n{context_text}\n\n"
                        "Generate the question paper now."
                    ),
                },
            ],
        )
        cost_tracker.add_chat(
            kind="chat",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=file_id,
            meta={"reason": "paper_generation"},
        )
        llm_text = completion.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("Question paper generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="LLM generation failed.")

    try:
        paper_payload = _extract_json_payload(llm_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {str(exc)}")

    paper_payload = _sanitize_paper_payload(paper_payload)
    paper_payload = _enforce_question_plan(
        payload=paper_payload,
        section_targets=section_targets,
        section_question_plan=plan.section_question_plan,
    )
    paper_payload = _rebalance_marks_to_targets(
        payload=paper_payload,
        total_marks=plan.total_marks,
        section_targets=section_targets,
        source_request=plan.source_request,
    )
    paper_payload = _inject_structure_and_summary(
        payload=paper_payload,
        total_marks=plan.total_marks,
        section_targets=section_targets,
        section_question_plan=plan.section_question_plan,
    )
    errors = _paper_errors(
        paper_payload,
        plan.total_marks,
        section_targets,
        source_request=plan.source_request,
    )
    if errors and all(_is_marks_only_error(error) for error in errors):
        paper_payload = _enforce_question_plan(
            payload=paper_payload,
            section_targets=section_targets,
            section_question_plan=plan.section_question_plan,
        )
        paper_payload = _rebalance_marks_to_targets(
            payload=paper_payload,
            total_marks=plan.total_marks,
            section_targets=section_targets,
            source_request=plan.source_request,
        )
        paper_payload = _inject_structure_and_summary(
            payload=paper_payload,
            total_marks=plan.total_marks,
            section_targets=section_targets,
            section_question_plan=plan.section_question_plan,
        )
        errors = _paper_errors(
            paper_payload,
            plan.total_marks,
            section_targets,
            source_request=plan.source_request,
        )
    if errors:
        try:
            paper_payload = _repair_paper_payload(
                file_id=file_id,
                payload=paper_payload,
                total_marks=plan.total_marks,
                section_targets=section_targets,
                section_question_plan=plan.section_question_plan,
                validation_errors=errors,
                focus_sections=None,
                source_request=plan.source_request,
                cost_tracker=cost_tracker,
            )
            errors = _paper_errors(
                paper_payload,
                plan.total_marks,
                section_targets,
                source_request=plan.source_request,
            )
            if errors and all(_is_marks_only_error(error) for error in errors):
                paper_payload = _enforce_question_plan(
                    payload=paper_payload,
                    section_targets=section_targets,
                    section_question_plan=plan.section_question_plan,
                )
                paper_payload = _rebalance_marks_to_targets(
                    payload=paper_payload,
                    total_marks=plan.total_marks,
                    section_targets=section_targets,
                    source_request=plan.source_request,
                )
                paper_payload = _inject_structure_and_summary(
                    payload=paper_payload,
                    total_marks=plan.total_marks,
                    section_targets=section_targets,
                    section_question_plan=plan.section_question_plan,
                )
                errors = _paper_errors(
                    paper_payload,
                    plan.total_marks,
                    section_targets,
                    source_request=plan.source_request,
                )

            missing_sections = _sections_needing_questions(paper_payload, section_targets)
            if errors and missing_sections:
                paper_payload = _repair_paper_payload(
                    file_id=file_id,
                    payload=paper_payload,
                    total_marks=plan.total_marks,
                    section_targets=section_targets,
                    section_question_plan=plan.section_question_plan,
                    validation_errors=errors,
                    focus_sections=missing_sections,
                    source_request=plan.source_request,
                    cost_tracker=cost_tracker,
                )
                errors = _paper_errors(
                    paper_payload,
                    plan.total_marks,
                    section_targets,
                    source_request=plan.source_request,
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not repair model JSON output: {str(exc)}")
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Generated paper did not pass validation.", "errors": errors},
        )

    cost_payload = cost_tracker.summary()
    try:
        paper_id, created_at = _save_generated_paper(
            file_id=file_id,
            topic=topic,
            mode=req.mode,
            total_marks=plan.total_marks,
            distribution=normalized_distribution,
            paper_payload=paper_payload,
            retrieved_chunks=retrieved,
            cost_payload=cost_payload,
        )
    except Exception as exc:
        logger.exception("Failed to persist generated paper: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to persist generated paper: {str(exc)}")
    try:
        return GeneratedPaperResponse(
            paper_id=paper_id,
            file_id=file_id,
            topic=topic,
            mode=req.mode,
            total_marks=plan.total_marks,
            distribution=normalized_distribution,
            paper=paper_payload,
            retrieved_chunks=retrieved,
            cost=cost_payload,
            created_at=created_at,
        )
    except Exception as exc:
        logger.exception("Failed to build generate response: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to build generate response: {str(exc)}")


@app.get("/history/papers", response_model=list[GeneratedPaperHistoryItem])
def paper_history(file_id: Optional[str] = None, limit: int = 25, offset: int = 0):
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    with get_db_context() as db:
        stmt = select(GeneratedPaper).order_by(GeneratedPaper.created_at.desc())
        if file_id:
            stmt = stmt.where(GeneratedPaper.file_id == file_id)
        rows = db.execute(stmt.offset(safe_offset).limit(safe_limit)).scalars().all()
        return [_history_item(row) for row in rows]


@app.get("/history/papers/{paper_id}", response_model=GeneratedPaperHistoryItem)
def paper_history_by_id(paper_id: str):
    try:
        parsed_id = uuid.UUID(paper_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid paper id format.")
    with get_db_context() as db:
        row = db.get(GeneratedPaper, parsed_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Generated paper not found.")
        return _history_item(row)
