import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from decimal import Decimal
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
from db import DocumentChunk, GeneratedPaper, get_db_context, init_db  # noqa: E402
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

    @model_validator(mode="after")
    def validate_distribution(self) -> "GeneratePaperRequest":
        normalized = normalize_distribution(self.distribution)
        if any(value < 0 for value in normalized.values()):
            raise ValueError("Distribution values must be non-negative.")
        if sum(normalized.values()) != 100:
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


def _mark_targets(total_marks: int, distribution_percent: dict[str, int]) -> dict[str, int]:
    raw_targets: dict[str, float] = {}
    base_targets: dict[str, int] = {}
    for key in SECTION_KEYS:
        raw = (total_marks * distribution_percent.get(key, 0)) / 100.0
        raw_targets[key] = raw
        base_targets[key] = int(raw)
    remaining = total_marks - sum(base_targets.values())
    if remaining > 0:
        ranked = sorted(
            SECTION_KEYS,
            key=lambda key: (raw_targets[key] - base_targets[key], distribution_percent.get(key, 0)),
            reverse=True,
        )
        for key in ranked:
            if remaining == 0:
                break
            base_targets[key] += 1
            remaining -= 1
    return base_targets


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
    answer_clean = answer.strip() if isinstance(answer, str) else ""
    if answer_clean and answer_clean not in rows:
        rows.insert(0, answer_clean)
    filler_seed = ["Option A", "Option B", "Option C", "Option D"]
    for label in filler_seed:
        if len(rows) >= 4:
            break
        if label not in rows:
            rows.append(label)
    return rows[:4]


def _sanitize_paper_payload(payload: dict[str, Any], fallback_ref: str = "Ref 1") -> dict[str, Any]:
    sanitized: dict[str, Any] = json.loads(json.dumps(payload))
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
                question = "Question"
            if not isinstance(answer, str) or not answer.strip():
                answer = "Answer unavailable from model output"
            if not isinstance(marks, int) or marks <= 0:
                marks = 1
            if not isinstance(source_refs, list) or not source_refs:
                source_refs = [fallback_ref]
            else:
                normalized_refs = [ref for ref in source_refs if isinstance(ref, str) and ref.strip()]
                source_refs = normalized_refs or [fallback_ref]

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


def _increase_marks(rows: list[dict[str, Any]], amount: int) -> int:
    if amount <= 0 or not rows:
        return amount
    idx = 0
    while amount > 0:
        row = rows[idx % len(rows)]
        marks = row.get("marks")
        if not isinstance(marks, int) or marks <= 0:
            marks = 1
        row["marks"] = marks + 1
        amount -= 1
        idx += 1
    return amount


def _decrease_marks(rows: list[dict[str, Any]], amount: int) -> int:
    if amount <= 0 or not rows:
        return amount
    idx = 0
    guard = 0
    max_iters = max(len(rows) * max(amount, 1) * 3, 1)
    while amount > 0 and guard < max_iters:
        row = rows[idx % len(rows)]
        marks = row.get("marks")
        if isinstance(marks, int) and marks > 1:
            row["marks"] = marks - 1
            amount -= 1
        idx += 1
        guard += 1
    return amount


def _rebalance_marks_to_targets(
    payload: dict[str, Any],
    total_marks: int,
    section_targets: dict[str, int],
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
        if current < target:
            _increase_marks(rows, target - current)
        elif current > target:
            _decrease_marks(rows, current - target)

    # Second pass: force overall total if section balancing could not fully converge.
    overall = sum(_section_total(section_rows_map[key]) for key in SECTION_KEYS)
    if overall < total_marks:
        deficit = total_marks - overall
        preferred_sections = [key for key in SECTION_KEYS if section_rows_map[key]]
        if not preferred_sections:
            return balanced
        idx = 0
        while deficit > 0:
            key = preferred_sections[idx % len(preferred_sections)]
            _increase_marks(section_rows_map[key], 1)
            deficit -= 1
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
            surplus = _decrease_marks(section_rows_map[key], surplus)
            if surplus == before:
                idx += 1
            else:
                idx += 1
            guard += 1

    return balanced


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
    topic = req.topic.strip()
    if not file_id:
        raise HTTPException(status_code=400, detail="doc_id cannot be empty.")
    if not topic:
        raise HTTPException(status_code=400, detail="topic cannot be empty.")

    normalized_distribution = normalize_distribution(req.distribution)
    section_targets = _mark_targets(req.total_marks, normalized_distribution)
    safe_top_k = min(max(req.top_k, 1), MAX_TOP_K)
    cost_tracker = _CostTracker()

    try:
        emb_resp = get_openai_client().embeddings.create(model=EMBED_MODEL, input=[topic])
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
        total_marks=req.total_marks,
        section_mark_targets=section_targets,
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

    fallback_ref = retrieved[0].ref_id if retrieved else "Ref 1"
    paper_payload = _sanitize_paper_payload(paper_payload, fallback_ref=fallback_ref)
    paper_payload = _rebalance_marks_to_targets(
        payload=paper_payload,
        total_marks=req.total_marks,
        section_targets=section_targets,
    )
    errors = _validate_paper_json(paper_payload, req.total_marks, section_targets)
    if errors and all(_is_marks_only_error(error) for error in errors):
        paper_payload = _rebalance_marks_to_targets(
            payload=paper_payload,
            total_marks=req.total_marks,
            section_targets=section_targets,
        )
        errors = _validate_paper_json(paper_payload, req.total_marks, section_targets)
    if errors:
        try:
            repair_completion = get_openai_client().chat.completions.create(
                model=CHAT_MODEL,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Return JSON only."},
                    {
                        "role": "user",
                        "content": build_repair_prompt(
                            previous_json_text=json.dumps(paper_payload),
                            total_marks=req.total_marks,
                            section_mark_targets=section_targets,
                            validation_errors=errors,
                        ),
                    },
                ],
            )
            cost_tracker.add_chat(
                kind="chat",
                model=CHAT_MODEL,
                usage=getattr(repair_completion, "usage", None),
                file_id=file_id,
                meta={"reason": "paper_generation_repair"},
            )
            repaired_text = repair_completion.choices[0].message.content or ""
            paper_payload = _extract_json_payload(repaired_text)
            paper_payload = _sanitize_paper_payload(paper_payload, fallback_ref=fallback_ref)
            paper_payload = _rebalance_marks_to_targets(
                payload=paper_payload,
                total_marks=req.total_marks,
                section_targets=section_targets,
            )
            errors = _validate_paper_json(paper_payload, req.total_marks, section_targets)
            if errors and all(_is_marks_only_error(error) for error in errors):
                paper_payload = _rebalance_marks_to_targets(
                    payload=paper_payload,
                    total_marks=req.total_marks,
                    section_targets=section_targets,
                )
                errors = _validate_paper_json(paper_payload, req.total_marks, section_targets)
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
            total_marks=req.total_marks,
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
            total_marks=req.total_marks,
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
