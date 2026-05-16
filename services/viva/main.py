import base64
import json
import os
import re
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from math import ceil
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from openai import OpenAI
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc, select

CURRENT_DIR = Path(__file__).resolve().parent
SHARED_DIR = CURRENT_DIR.parent / "shared"
if SHARED_DIR.exists() and str(SHARED_DIR) not in sys.path:
    sys.path.append(str(SHARED_DIR))

from config import (  # noqa: E402
    CHAT_MODEL,
    DEFAULT_FACE_MATCH_THRESHOLD,
    DEFAULT_PER_QUESTION_LIMIT_SECONDS,
    DEFAULT_QUESTION_COUNT,
    FOLLOWUP_MIN_COUNT,
    FOLLOWUP_MIN_RATIO,
    MAX_QUESTION_COUNT,
    MIN_QUESTION_COUNT,
    PROCTOR_AMBIGUOUS_CONFIDENCE_MIN,
    PROCTOR_ACCESSORY_IS_VIOLATION,
    PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING,
    PROCTOR_MIN_FRAME_INTERVAL_MS,
    PROCTOR_WARNING_MIN_INTERVAL_MS,
    PROCTOR_WINDOW_ANOMALY_THRESHOLD,
    PROCTOR_WINDOW_SIZE,
    PROCTOR_VIOLATE_ON_AMBIGUOUS,
    STT_MODEL,
    TTS_MODEL,
    VIVA_MEDIA_BUCKET,
    VIVA_STORE_ALL_FRAMES,
    VISION_MODEL,
)
from cost import compute_chat_cost, parse_usage_tokens, record_cost  # noqa: E402
from db import (  # noqa: E402
    ApiCostEvent,
    VivaProctorEvent,
    VivaQuestion,
    VivaResult,
    VivaSession,
    VivaSessionStatus,
    VivaTurn,
    get_db_context,
    init_db,
)
from prompting import (  # noqa: E402
    build_answer_evaluation_prompt,
    build_followup_prompt,
    build_initial_question_prompt,
    build_question_bank_prompt,
    build_result_summary_prompt,
)
from storage import get_storage_backend  # noqa: E402
from providers.face import verify_face  # noqa: E402
from providers.voice import synthesize_question_audio, transcribe_audio  # noqa: E402

app = FastAPI(title="FixED - Viva Service")

_openai_client = None
_storage_backend = None


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
            service="viva",
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


class StartSessionRequest(BaseModel):
    file_id: str
    topic: str
    chapter_number: Optional[int] = None
    question_count: int = DEFAULT_QUESTION_COUNT
    per_question_limit_seconds: int = DEFAULT_PER_QUESTION_LIMIT_SECONDS
    session_limit_seconds: Optional[int] = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "StartSessionRequest":
        if self.question_count < MIN_QUESTION_COUNT or self.question_count > MAX_QUESTION_COUNT:
            raise ValueError(f"question_count must be between {MIN_QUESTION_COUNT} and {MAX_QUESTION_COUNT}")
        if self.per_question_limit_seconds < 20:
            raise ValueError("per_question_limit_seconds must be at least 20")
        if self.session_limit_seconds is None:
            self.session_limit_seconds = self.question_count * self.per_question_limit_seconds
        if self.session_limit_seconds < self.per_question_limit_seconds:
            raise ValueError("session_limit_seconds must be >= per_question_limit_seconds")
        return self


class ReferencePhotoRequest(BaseModel):
    image_b64: str


class ProctorFrameRequest(BaseModel):
    frame_b64: str
    threshold: float = DEFAULT_FACE_MATCH_THRESHOLD


class AnswerRequest(BaseModel):
    transcript: Optional[str] = None
    audio_b64: Optional[str] = None
    latency_ms: int = 0
    question_id: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    status: str
    warning_count: int
    question_count: int
    current_question_index: int
    topic: str
    file_id: str
    chapter_number: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    termination_reason: Optional[str] = None
    base_question_count: Optional[int] = None
    followup_min_count: Optional[int] = None
    total_question_target: Optional[int] = None


class QuestionPayload(BaseModel):
    question_id: str
    question_order: int
    question_text: str
    expected_points: list[str] = Field(default_factory=list)
    audio_b64: Optional[str] = None


@app.on_event("startup")
def startup_event():
    init_db()


def get_openai_client() -> OpenAI | None:
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def get_storage_client():
    global _storage_backend
    if _storage_backend is not None:
        return _storage_backend
    _storage_backend = get_storage_backend(provider="minio", bucket=VIVA_MEDIA_BUCKET)
    return _storage_backend


def _decode_base64_image(image_b64: str | None) -> bytes | None:
    if not image_b64:
        return None
    try:
        return base64.b64decode(image_b64.encode("utf-8"), validate=False)
    except Exception:
        return None


def _store_image_to_object_storage(session_id: Any, kind: str, image_b64: str | None) -> str | None:
    payload = _decode_base64_image(image_b64)
    if not payload:
        return None
    key = f"viva/{session_id}/{kind}/{uuid.uuid4()}.jpg"
    try:
        return get_storage_client().upload(payload, key=key, content_type="image/jpeg")
    except Exception:
        return None


def _parse_media_object_key(session_id: str, object_path: str) -> str:
    raw = (object_path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="object_path is required")
    expected_prefix = f"{VIVA_MEDIA_BUCKET}/viva/{session_id}/"
    if not raw.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Invalid object_path for session")
    key = raw[len(f"{VIVA_MEDIA_BUCKET}/") :]
    if not key:
        raise HTTPException(status_code=400, detail="Invalid object key")
    return key


def _session_summary(session: VivaSession) -> SessionSummary:
    base_question_count = int(session.question_count or 0)
    followup_min_count = _followup_min_count(base_question_count)
    total_question_target = base_question_count + followup_min_count
    return SessionSummary(
        session_id=str(session.id),
        status=session.status.value if hasattr(session.status, "value") else str(session.status),
        warning_count=int(session.warning_count or 0),
        question_count=base_question_count,
        current_question_index=int(session.current_question_index or 0),
        topic=session.topic,
        file_id=session.file_id,
        chapter_number=session.chapter_number,
        started_at=session.started_at.isoformat() if session.started_at else None,
        finished_at=session.finished_at.isoformat() if session.finished_at else None,
        termination_reason=session.termination_reason,
        base_question_count=base_question_count,
        followup_min_count=followup_min_count,
        total_question_target=total_question_target,
    )


def _extract_json(raw: str, fallback: dict[str, Any]) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        return fallback
    try:
        value = json.loads(match.group(0))
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return fallback


def _get_session_or_404(session_id: str) -> VivaSession:
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        return session


def _ensure_active(session: VivaSession) -> None:
    if session.status not in (VivaSessionStatus.PENDING, VivaSessionStatus.ACTIVE):
        raise HTTPException(status_code=409, detail=f"Session is not active. Status={session.status}")


def _session_timed_out(session: VivaSession) -> bool:
    if not session.started_at:
        return False
    elapsed = (datetime.utcnow() - session.started_at).total_seconds()
    return elapsed > int(session.session_limit_seconds or 0)


def _question_timed_out(question: VivaQuestion, limit_seconds: int) -> bool:
    elapsed = (datetime.utcnow() - question.asked_at).total_seconds()
    return elapsed > int(limit_seconds or 0)


def _mark_timeout(session: VivaSession) -> None:
    session.status = VivaSessionStatus.TERMINATED_TIMEOUT
    session.finished_at = datetime.utcnow()
    session.termination_reason = "session_timeout"


def _latest_proctor_event(db, session_id: Any, event_types: list[str]) -> VivaProctorEvent | None:
    return (
        db.execute(
            select(VivaProctorEvent)
            .where(VivaProctorEvent.session_id == session_id, VivaProctorEvent.event_type.in_(event_types))
            .order_by(VivaProctorEvent.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _recent_frame_checks(db, session_id: Any, limit: int) -> list[VivaProctorEvent]:
    return (
        db.execute(
            select(VivaProctorEvent)
            .where(VivaProctorEvent.session_id == session_id, VivaProctorEvent.event_type == "frame_check")
            .order_by(VivaProctorEvent.created_at.desc())
            .limit(max(1, limit))
        )
        .scalars()
        .all()
    )


def _proctor_snapshot_from_event(event: VivaProctorEvent | None) -> dict[str, Any]:
    if event is None:
        return {"is_present": True, "is_match": True, "confidence": 1.0}
    return {
        "is_present": bool(event.is_present),
        "is_match": bool(event.is_match),
        "confidence": float(event.confidence or 0),
    }


def _is_proctor_violation(result, threshold: float) -> tuple[bool, str]:
    if not result.is_present:
        return True, result.reason or "face_not_present"
    if result.is_match:
        return False, "match"
    hard_reasons = {
        "face_not_present",
        "multiple_faces",
        "missing_reference",
        "provider_unavailable",
    }
    if PROCTOR_ACCESSORY_IS_VIOLATION:
        hard_reasons.update({"suspicious_accessory", "occluded_face"})
    if result.reason in hard_reasons:
        return True, result.reason
    if result.reason in {"provider_error", "low_quality", "uncertain"}:
        if PROCTOR_VIOLATE_ON_AMBIGUOUS:
            return True, result.reason
        return result.confidence < PROCTOR_AMBIGUOUS_CONFIDENCE_MIN, result.reason
    return result.confidence < threshold, result.reason or "mismatch"


def _is_proctor_anomaly(result, threshold: float) -> tuple[bool, str]:
    severe_reasons = {
        "face_not_present",
        "multiple_faces",
        "mismatch",
        "suspicious_accessory",
        "occluded_face",
        "provider_error",
        "provider_unavailable",
    }
    if result.reason in severe_reasons:
        return True, result.reason
    violated, reason = _is_proctor_violation(result, threshold)
    return violated, reason


def _followup_min_count(base_question_count: int) -> int:
    safe_base = max(int(base_question_count or 0), 0)
    if safe_base <= 1:
        return 0
    if FOLLOWUP_MIN_COUNT is not None:
        return max(0, min(safe_base - 1, int(FOLLOWUP_MIN_COUNT)))
    return max(1, min(safe_base - 1, ceil(safe_base * FOLLOWUP_MIN_RATIO)))


def _total_question_target(base_question_count: int) -> int:
    safe_base = max(int(base_question_count or 0), 0)
    return safe_base + _followup_min_count(safe_base)


def _base_question_order(base_index: int, followup_min_count: int) -> int:
    if base_index <= followup_min_count:
        return (base_index * 2) - 1
    return base_index + followup_min_count


def _plan_question(order: int, base_question_count: int) -> dict[str, int | str]:
    followup_count = _followup_min_count(base_question_count)
    if order <= 0:
        return {"kind": "base", "base_index": 1, "followup_index": 0}
    if order <= followup_count * 2:
        if order % 2 == 1:
            return {"kind": "base", "base_index": ((order + 1) // 2), "followup_index": 0}
        return {"kind": "followup", "base_index": (order // 2), "followup_index": (order // 2)}
    return {"kind": "base", "base_index": order - followup_count, "followup_index": 0}


def _generate_question_bank_with_llm(
    topic: str,
    chapter_number: Optional[int],
    question_count: int,
    cost_tracker: _CostTracker,
    file_id: str,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    fallback = [
        {
            "question": f"Question {idx + 1}: Explain a key concept in {topic} with one practical example.",
            "expected_points": [f"Core concept {idx + 1}", "Correct terminology", "Relevant example"],
        }
        for idx in range(question_count)
    ]
    client = get_openai_client()
    if client is None:
        return fallback
    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.35,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": build_question_bank_prompt(topic, chapter_number, question_count)},
            ],
        )
        cost_tracker.add_chat(
            kind="question_bank_generation",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=file_id,
            meta={"question_count": question_count, "session_id": session_id} if session_id else {"question_count": question_count},
        )
        parsed = _extract_json(completion.choices[0].message.content or "", {"questions": fallback})
        rows = parsed.get("questions")
        if not isinstance(rows, list):
            return fallback
        normalized: list[dict[str, Any]] = []
        for idx, row in enumerate(rows[:question_count]):
            if not isinstance(row, dict):
                continue
            question = str(row.get("question") or "").strip()
            expected_points = row.get("expected_points") or []
            if not isinstance(expected_points, list):
                expected_points = []
            normalized_points = [str(item).strip() for item in expected_points if str(item).strip()][:6]
            if not question:
                question = fallback[idx]["question"]
            normalized.append(
                {
                    "question": question,
                    "expected_points": normalized_points or fallback[idx]["expected_points"],
                }
            )
        if len(normalized) < question_count:
            normalized.extend(fallback[len(normalized) : question_count])
        return normalized[:question_count]
    except Exception:
        return fallback


def _ensure_base_question_bank(
    db,
    session: VivaSession,
    cost_tracker: _CostTracker,
    target_base_indexes: Optional[list[int]] = None,
) -> None:
    base_question_count = int(session.question_count or 0)
    if base_question_count <= 0:
        return
    followup_count = _followup_min_count(base_question_count)
    existing_by_order = {
        int(row.question_order or 0): row
        for row in db.execute(select(VivaQuestion).where(VivaQuestion.session_id == session.id)).scalars().all()
    }
    requested_base_indexes = target_base_indexes or list(range(1, base_question_count + 1))
    valid_base_indexes = [
        int(base_index)
        for base_index in requested_base_indexes
        if 1 <= int(base_index) <= base_question_count
    ]
    missing_base_indexes: list[int] = []
    for base_index in valid_base_indexes:
        planned_order = _base_question_order(base_index, followup_count)
        row = existing_by_order.get(planned_order)
        if row is None:
            missing_base_indexes.append(base_index)
    if not missing_base_indexes:
        return

    # During live submit transitions, create only missing required base questions
    # to keep manual progression responsive.
    if target_base_indexes:
        now = datetime.utcnow()
        for base_index in missing_base_indexes:
            payload = _generate_question_with_llm(
                topic=session.topic,
                chapter_number=session.chapter_number,
                question_count=base_question_count,
                question_index=base_index - 1,
                previous_question=None,
                previous_answer=None,
                cost_tracker=cost_tracker,
                file_id=session.file_id,
                session_id=str(session.id),
            )
            question_order = _base_question_order(base_index, followup_count)
            db.add(
                VivaQuestion(
                    session_id=session.id,
                    question_order=question_order,
                    question_text=payload["question"],
                    expected_points_json=payload["expected_points"],
                    asked_at=now,
                )
            )
        db.flush()
        return

    question_bank = _generate_question_bank_with_llm(
        topic=session.topic,
        chapter_number=session.chapter_number,
        question_count=base_question_count,
        cost_tracker=cost_tracker,
        file_id=session.file_id,
        session_id=str(session.id),
    )
    now = datetime.utcnow()
    for base_index in missing_base_indexes:
        payload = question_bank[base_index - 1]
        question_order = _base_question_order(base_index, followup_count)
        db.add(
            VivaQuestion(
                session_id=session.id,
                question_order=question_order,
                question_text=payload["question"],
                expected_points_json=payload["expected_points"],
                asked_at=now,
            )
        )
    db.flush()


def _generate_question_with_llm(
    topic: str,
    chapter_number: Optional[int],
    question_count: int,
    question_index: int,
    previous_question: Optional[str],
    previous_answer: Optional[str],
    cost_tracker: _CostTracker,
    file_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    client = get_openai_client()
    if question_index == 0:
        user_prompt = build_initial_question_prompt(topic, chapter_number, question_count)
    else:
        user_prompt = build_followup_prompt(
            topic=topic,
            previous_question=previous_question or "",
            answer_transcript=previous_answer or "",
            question_index=question_index,
            total_questions=question_count,
        )

    fallback = {
        "question": (
            f"Question {question_index + 1}: Explain the most important concept in {topic} "
            "and support your answer with an example."
        ),
        "expected_points": [f"Core concept in {topic}", "Correct terminology", "One practical example"],
    }
    if client is None:
        return fallback
    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.4,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": user_prompt},
            ],
        )
        cost_tracker.add_chat(
            kind="question_generation",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=file_id,
            meta=(
                {"question_index": question_index + 1, "session_id": session_id}
                if session_id
                else {"question_index": question_index + 1}
            ),
        )
        parsed = _extract_json(completion.choices[0].message.content or "", fallback)
        question = str(parsed.get("question") or fallback["question"]).strip()
        expected_points = parsed.get("expected_points") or fallback["expected_points"]
        if not isinstance(expected_points, list):
            expected_points = fallback["expected_points"]
        expected_points = [str(item).strip() for item in expected_points if str(item).strip()][:6]
        return {"question": question, "expected_points": expected_points or fallback["expected_points"]}
    except Exception:
        return fallback


def _evaluate_answer(
    question_text: str,
    expected_points: list[str],
    answer_transcript: str,
    cost_tracker: _CostTracker,
    file_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    fallback = {
        "score": 6,
        "max_score": 10,
        "strengths": ["Attempted a complete response"],
        "weaknesses": ["Needs stronger conceptual precision"],
        "feedback": "Good attempt. Improve with clearer definitions and one specific example.",
    }
    client = get_openai_client()
    if client is None:
        return fallback
    prompt = build_answer_evaluation_prompt(question_text, expected_points, answer_transcript)
    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        cost_tracker.add_chat(
            kind="answer_evaluation",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=file_id,
            meta={"question": question_text[:120], "session_id": session_id} if session_id else {"question": question_text[:120]},
        )
        parsed = _extract_json(completion.choices[0].message.content or "", fallback)
        score = float(parsed.get("score", fallback["score"]))
        max_score = float(parsed.get("max_score", fallback["max_score"]))
        return {
            "score": max(0.0, min(score, max_score if max_score > 0 else 10.0)),
            "max_score": max(1.0, max_score),
            "strengths": [str(item) for item in parsed.get("strengths", fallback["strengths"])][:5],
            "weaknesses": [str(item) for item in parsed.get("weaknesses", fallback["weaknesses"])][:5],
            "feedback": str(parsed.get("feedback", fallback["feedback"])),
        }
    except Exception:
        return fallback


def _compute_result_payload(
    topic: str,
    question_breakdown: list[dict[str, Any]],
    cost_tracker: _CostTracker,
    file_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    total_score = sum(float(item.get("score", 0)) for item in question_breakdown)
    max_score = sum(float(item.get("max_score", 0)) for item in question_breakdown)
    strengths = []
    weak_areas = []
    for item in question_breakdown:
        strengths.extend([str(v) for v in item.get("strengths", [])])
        weak_areas.extend([str(v) for v in item.get("weaknesses", [])])
    strengths = list(dict.fromkeys([s for s in strengths if s]))[:6]
    weak_areas = list(dict.fromkeys([w for w in weak_areas if w]))[:6]

    fallback = {
        "summary": f"Viva session completed on {topic}. Score {total_score:.1f}/{max_score:.1f}.",
        "strengths": strengths or ["Showed willingness to reason through answers"],
        "weak_areas": weak_areas or ["Need more precise subject vocabulary"],
        "recommendations": [
            "Revise core definitions in selected chapter/topic",
            "Practice structured answers: concept -> explanation -> example",
        ],
    }
    client = get_openai_client()
    if client is None:
        return {**fallback, "overall_score": total_score, "max_score": max_score}
    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": build_result_summary_prompt(topic, question_breakdown)},
            ],
        )
        cost_tracker.add_chat(
            kind="result_summary",
            model=CHAT_MODEL,
            usage=getattr(completion, "usage", None),
            file_id=file_id,
            meta={"questions": len(question_breakdown), "session_id": session_id} if session_id else {"questions": len(question_breakdown)},
        )
        parsed = _extract_json(completion.choices[0].message.content or "", fallback)
        return {
            "overall_score": total_score,
            "max_score": max_score,
            "summary": str(parsed.get("summary", fallback["summary"])),
            "strengths": [str(v) for v in parsed.get("strengths", fallback["strengths"])][:6],
            "weak_areas": [str(v) for v in parsed.get("weak_areas", fallback["weak_areas"])][:6],
            "recommendations": [str(v) for v in parsed.get("recommendations", fallback["recommendations"])][:6],
        }
    except Exception:
        return {**fallback, "overall_score": total_score, "max_score": max_score}


def _serialize_question(question: VivaQuestion, with_audio: bool = False) -> QuestionPayload:
    audio_b64 = None
    if with_audio:
        audio_b64 = synthesize_question_audio(get_openai_client(), question.question_text, TTS_MODEL)
    return QuestionPayload(
        question_id=str(question.id),
        question_order=question.question_order,
        question_text=question.question_text,
        expected_points=[str(v) for v in (question.expected_points_json or [])],
        audio_b64=audio_b64,
    )


def _find_session_question_by_id(db, session_id: Any, question_id: str) -> VivaQuestion | None:
    rows = db.execute(select(VivaQuestion).where(VivaQuestion.session_id == session_id)).scalars().all()
    return next((row for row in rows if str(row.id) == str(question_id)), None)


def _find_latest_turn_for_question(db, session_id: Any, question_id: Any) -> VivaTurn | None:
    rows = db.execute(select(VivaTurn).where(VivaTurn.session_id == session_id)).scalars().all()
    matched = [row for row in rows if str(row.question_id) == str(question_id)]
    if not matched:
        return None
    return sorted(matched, key=lambda row: row.created_at or datetime.min)[-1]


def _build_idempotent_submit_recovery(
    db,
    session: VivaSession,
    submitted_question: VivaQuestion,
    submitted_turn: VivaTurn,
    total_question_target: int,
    tracker: _CostTracker,
) -> dict[str, Any] | None:
    turn_payload = {
        "question_id": str(submitted_question.id),
        "question_order": int(submitted_question.question_order or 0),
        "answer_transcript": submitted_turn.answer_transcript,
        "evaluation": {
            "score": float(submitted_turn.score or 0),
            "max_score": float(submitted_turn.max_score or 0),
            "strengths": submitted_turn.strengths_json or [],
            "weaknesses": submitted_turn.weaknesses_json or [],
            "feedback": submitted_turn.feedback,
        },
    }
    # Duplicate submit for an already-accepted question should return authoritative state.
    if int(session.current_question_index or 0) >= int(total_question_target or 0):
        finalized = _finalize_session_with_db(db, session.id)
        return {
            "session": finalized["session"],
            "turn": turn_payload,
            "done": True,
            "result": finalized["result"],
            "cost": tracker.summary(),
            "recovered_conflict": True,
        }
    next_order = int(session.current_question_index or 0) + 1
    next_question = (
        db.execute(
            select(VivaQuestion)
            .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == next_order)
            .limit(1)
        )
        .scalars()
        .first()
    )
    if next_question is None:
        return None
    next_question.asked_at = datetime.utcnow()
    db.flush()
    return {
        "session": _session_summary(session),
        "turn": turn_payload,
        "next_question": _serialize_question(next_question, with_audio=True),
        "done": False,
        "cost": tracker.summary(),
        "recovered_conflict": True,
    }


def _ensure_question_for_order(
    db,
    session: VivaSession,
    order: int,
    cost_tracker: _CostTracker,
    total_question_target: int,
) -> VivaQuestion | None:
    question = (
        db.execute(
            select(VivaQuestion)
            .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == int(order))
            .limit(1)
        )
        .scalars()
        .first()
    )
    if question is not None:
        return question

    base_question_count = int(session.question_count or 0)
    if base_question_count <= 0:
        return None
    plan = _plan_question(int(order), base_question_count)
    if plan["kind"] == "base":
        _ensure_base_question_bank(db, session, cost_tracker, target_base_indexes=[int(plan["base_index"])])
    else:
        previous_order = max(int(order) - 1, 1)
        previous_question = (
            db.execute(
                select(VivaQuestion)
                .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == previous_order)
                .limit(1)
            )
            .scalars()
            .first()
        )
        previous_turn = _find_latest_turn_for_question(db, session.id, previous_question.id) if previous_question else None
        if previous_question and previous_turn:
            followup_data = _generate_question_with_llm(
                topic=session.topic,
                chapter_number=session.chapter_number,
                question_count=total_question_target,
                question_index=int(order) - 1,
                previous_question=previous_question.question_text,
                previous_answer=previous_turn.answer_transcript,
                cost_tracker=cost_tracker,
                file_id=session.file_id,
                session_id=str(session.id),
            )
            db.add(
                VivaQuestion(
                    session_id=session.id,
                    question_order=int(order),
                    question_text=followup_data["question"],
                    expected_points_json=followup_data["expected_points"],
                    asked_at=datetime.utcnow(),
                )
            )
    db.flush()
    return (
        db.execute(
            select(VivaQuestion)
            .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == int(order))
            .limit(1)
        )
        .scalars()
        .first()
    )


def _load_proctor_events(db, session_id) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(VivaProctorEvent)
            .where(VivaProctorEvent.session_id == session_id)
            .order_by(VivaProctorEvent.created_at.asc())
        )
        .scalars()
        .all()
    )
    events = []
    for row in rows:
        details = dict(row.details_json or {})
        events.append(
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "is_present": bool(row.is_present),
                "is_match": bool(row.is_match),
                "confidence": float(row.confidence or 0),
                "warning_count": int(row.warning_count or 0),
                "action": row.action,
                "details": details,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return events


def _load_questions(db, session_id) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(VivaQuestion)
            .where(VivaQuestion.session_id == session_id)
            .order_by(VivaQuestion.question_order.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "question_order": row.question_order,
            "question_text": row.question_text,
            "expected_points": row.expected_points_json or [],
            "asked_at": row.asked_at.isoformat() if row.asked_at else None,
        }
        for row in rows
    ]


def _load_turns(db, session_id) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(VivaTurn)
            .where(VivaTurn.session_id == session_id)
            .order_by(VivaTurn.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "question_id": str(row.question_id),
            "answer_transcript": row.answer_transcript,
            "score": float(row.score or 0),
            "max_score": float(row.max_score or 0),
            "strengths": row.strengths_json or [],
            "weaknesses": row.weaknesses_json or [],
            "feedback": row.feedback,
            "latency_ms": int(row.latency_ms or 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _load_cost_summary(db, session_id: Any) -> dict[str, Any]:
    sid = str(session_id)
    rows = (
        db.execute(
            select(ApiCostEvent)
            .where(ApiCostEvent.service == "viva", ApiCostEvent.meta.contains({"session_id": sid}))
            .order_by(ApiCostEvent.created_at.asc())
        )
        .scalars()
        .all()
    )
    prompt_tokens = sum(int(getattr(row, "prompt_tokens", 0) or 0) for row in rows)
    completion_tokens = sum(int(getattr(row, "completion_tokens", 0) or 0) for row in rows)
    total_tokens = sum(int(getattr(row, "total_tokens", 0) or 0) for row in rows)
    total_usd = sum(float(getattr(row, "cost_usd", 0) or 0) for row in rows)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "usd": round(total_usd, 8),
        "events": [
            {
                "kind": row.kind,
                "model": row.model,
                "prompt_tokens": int(row.prompt_tokens or 0),
                "completion_tokens": int(row.completion_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "usd": float(row.cost_usd or 0),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


def _serialize_result_row(row: VivaResult | None, proctor_events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "overall_score": float(row.overall_score or 0),
        "max_score": float(row.max_score or 0),
        "strengths": row.strengths_json or [],
        "weak_areas": row.weak_areas_json or [],
        "recommendations": row.recommendations_json or [],
        "question_breakdown": row.question_breakdown_json or [],
        "proctor_events": proctor_events or [],
        "summary": row.summary,
    }


def _build_session_history_item(db, session: VivaSession) -> dict[str, Any]:
    result = db.execute(select(VivaResult).where(VivaResult.session_id == session.id)).scalar_one_or_none()
    turns = db.execute(select(VivaTurn).where(VivaTurn.session_id == session.id)).scalars().all()
    proctor_rows = db.execute(select(VivaProctorEvent).where(VivaProctorEvent.session_id == session.id)).scalars().all()
    return {
        "session": _session_summary(session).model_dump(),
        "metrics": {
            "overall_score": float(result.overall_score or 0) if result else 0.0,
            "max_score": float(result.max_score or 0) if result else 0.0,
            "turn_count": len(turns),
            "proctor_event_count": len(proctor_rows),
        },
    }


def _finalize_session_with_db(db, session_id: Any, force_termination_reason: str | None = None) -> dict[str, Any]:
        db_session = db.get(VivaSession, session_id)
        if db_session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        turns = (
            db.execute(select(VivaTurn).where(VivaTurn.session_id == db_session.id).order_by(VivaTurn.created_at.asc()))
            .scalars()
            .all()
        )
        questions = {
            str(q.id): q
            for q in db.execute(select(VivaQuestion).where(VivaQuestion.session_id == db_session.id)).scalars().all()
        }
        breakdown = []
        for turn in turns:
            q = questions.get(str(turn.question_id))
            breakdown.append(
                {
                    "question_id": str(turn.question_id),
                    "question": q.question_text if q else "",
                    "answer_transcript": turn.answer_transcript,
                    "score": float(turn.score or 0),
                    "max_score": float(turn.max_score or 0),
                    "strengths": turn.strengths_json or [],
                    "weaknesses": turn.weaknesses_json or [],
                    "feedback": turn.feedback,
                }
            )
        tracker = _CostTracker()
        payload = _compute_result_payload(
            db_session.topic,
            breakdown,
            tracker,
            db_session.file_id,
            session_id=str(db_session.id),
        )
        row = db.execute(select(VivaResult).where(VivaResult.session_id == db_session.id)).scalar_one_or_none()
        if row is None:
            row = VivaResult(
                session_id=db_session.id,
                overall_score=payload["overall_score"],
                max_score=payload["max_score"],
                strengths_json=payload["strengths"],
                weak_areas_json=payload["weak_areas"],
                recommendations_json=payload["recommendations"],
                question_breakdown_json=breakdown,
                summary=payload["summary"],
            )
            db.add(row)
        else:
            row.overall_score = payload["overall_score"]
            row.max_score = payload["max_score"]
            row.strengths_json = payload["strengths"]
            row.weak_areas_json = payload["weak_areas"]
            row.recommendations_json = payload["recommendations"]
            row.question_breakdown_json = breakdown
            row.summary = payload["summary"]

        if db_session.status in (VivaSessionStatus.PENDING, VivaSessionStatus.ACTIVE):
            db_session.status = VivaSessionStatus.COMPLETED
        if force_termination_reason:
            db_session.termination_reason = force_termination_reason
        db_session.finished_at = datetime.utcnow()
        summary = _session_summary(db_session).model_dump()
        proctor_events = _load_proctor_events(db, db_session.id)
        total_cost = _load_cost_summary(db, db_session.id)
        return {
            "session": summary,
            "result": {
                "overall_score": float(payload["overall_score"]),
                "max_score": float(payload["max_score"]),
                "strengths": payload["strengths"],
                "weak_areas": payload["weak_areas"],
                "recommendations": payload["recommendations"],
                "summary": payload["summary"],
                "question_breakdown": breakdown,
                "proctor_events": proctor_events,
                "cost": total_cost,
            },
        }


def _finalize_session(session: VivaSession, force_termination_reason: str | None = None) -> dict[str, Any]:
    with get_db_context() as db:
        return _finalize_session_with_db(db, session.id, force_termination_reason)


@app.get("/health")
def health():
    return {"status": "ok", "service": "viva"}


@app.post("/viva/sessions/start")
def start_session(payload: StartSessionRequest):
    tracker = _CostTracker()
    now = datetime.utcnow()
    with get_db_context() as db:
        session = VivaSession(
            file_id=payload.file_id,
            topic=payload.topic.strip(),
            chapter_number=payload.chapter_number,
            question_count=payload.question_count,
            per_question_limit_seconds=payload.per_question_limit_seconds,
            session_limit_seconds=payload.session_limit_seconds,
            status=VivaSessionStatus.ACTIVE,
            warning_count=0,
            current_question_index=0,
            started_at=now,
        )
        db.add(session)
        db.flush()
        first_question_data = _generate_question_with_llm(
            topic=payload.topic.strip(),
            chapter_number=payload.chapter_number,
            question_count=payload.question_count,
            question_index=0,
            previous_question=None,
            previous_answer=None,
            cost_tracker=tracker,
            file_id=payload.file_id,
            session_id=str(session.id),
        )
        first_question = VivaQuestion(
            session_id=session.id,
            question_order=1,
            question_text=first_question_data["question"],
            expected_points_json=first_question_data["expected_points"],
            asked_at=now,
        )
        db.add(first_question)
        followup_min_count = _followup_min_count(int(session.question_count or 0))
        db.add(
            VivaProctorEvent(
                session_id=session.id,
                event_type="session_start",
                is_present=1,
                is_match=1,
                confidence=1,
                warning_count=0,
                action="ok",
                details_json={
                    "topic": session.topic,
                    "chapter_number": session.chapter_number,
                    "question_count": session.question_count,
                    "session_limit_seconds": session.session_limit_seconds,
                    "base_question_count": int(session.question_count or 0),
                    "followup_min_count": followup_min_count,
                    "total_question_target": int(session.question_count or 0) + followup_min_count,
                },
            )
        )
        db.flush()
        return {
            "session": _session_summary(session),
            "current_question": _serialize_question(first_question, with_audio=False),
            "cost": tracker.summary(),
        }


@app.post("/viva/sessions/{session_id}/reference-photo")
def set_reference_photo(session_id: str, payload: ReferencePhotoRequest):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        _ensure_active(session)
        session.reference_photo_b64 = payload.image_b64
        reference_object_path = _store_image_to_object_storage(session.id, "reference", payload.image_b64)
        db.add(
            VivaProctorEvent(
                session_id=session.id,
                event_type="reference_photo",
                is_present=1,
                is_match=1,
                confidence=1,
                warning_count=int(session.warning_count or 0),
                action="ok",
                details_json={"captured": True, "reference_object_path": reference_object_path},
            )
        )
        return {
            "session": _session_summary(session),
            "reference_photo_captured": True,
            "reference_object_path": reference_object_path,
        }


@app.post("/viva/sessions/{session_id}/proctor/frame")
def audit_frame(session_id: str, payload: ProctorFrameRequest):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        _ensure_active(session)
        if _session_timed_out(session):
            _mark_timeout(session)
            finalized = _finalize_session_with_db(db, session.id, force_termination_reason="session_timeout")
            return {"session": finalized["session"], "action": "terminated", "reason": "session_timeout"}

        now = datetime.utcnow()
        last_proctor_event = _latest_proctor_event(db, session.id, ["frame_check", "frame_check_skipped"])
        if PROCTOR_MIN_FRAME_INTERVAL_MS > 0 and last_proctor_event and last_proctor_event.created_at:
            elapsed_ms = int((now - last_proctor_event.created_at).total_seconds() * 1000)
            if elapsed_ms < PROCTOR_MIN_FRAME_INTERVAL_MS:
                retry_after_ms = max(PROCTOR_MIN_FRAME_INTERVAL_MS - elapsed_ms, 0)
                last_paid_check = _latest_proctor_event(db, session.id, ["frame_check"])
                snapshot = _proctor_snapshot_from_event(last_paid_check)
                db.add(
                    VivaProctorEvent(
                        session_id=session.id,
                        event_type="frame_check_skipped",
                        is_present=1 if snapshot["is_present"] else 0,
                        is_match=1 if snapshot["is_match"] else 0,
                        confidence=snapshot["confidence"],
                        warning_count=int(session.warning_count or 0),
                        action="ok",
                        details_json={
                            "reason": "throttled_min_interval",
                            "min_interval_ms": PROCTOR_MIN_FRAME_INTERVAL_MS,
                            "retry_after_ms": retry_after_ms,
                        },
                    )
                )
                return {
                    "session": _session_summary(session),
                    "proctor": snapshot,
                    "action": "ok",
                    "warnings": int(session.warning_count or 0),
                    "throttled": True,
                    "retry_after_ms": retry_after_ms,
                }

        result = verify_face(
            session.reference_photo_b64,
            payload.frame_b64,
            payload.threshold,
            client=get_openai_client(),
            model=VISION_MODEL,
        )
        anomaly, anomaly_reason = _is_proctor_anomaly(result, payload.threshold)
        recent_checks = _recent_frame_checks(db, session.id, max(1, PROCTOR_WINDOW_SIZE - 1))
        prior_anomaly_count = sum(1 for item in recent_checks if bool((item.details_json or {}).get("anomaly")))
        window_anomaly_count = prior_anomaly_count + (1 if anomaly else 0)
        anomaly_threshold_reached = anomaly and window_anomaly_count >= max(1, PROCTOR_WINDOW_ANOMALY_THRESHOLD)
        latest_warning_event = next(
            (item for item in recent_checks if item.action in {"warning", "terminated"}),
            None,
        )
        cooldown_elapsed = True
        if latest_warning_event and latest_warning_event.created_at and PROCTOR_WARNING_MIN_INTERVAL_MS > 0:
            warning_elapsed = int((now - latest_warning_event.created_at).total_seconds() * 1000)
            cooldown_elapsed = warning_elapsed >= PROCTOR_WARNING_MIN_INTERVAL_MS
        violated, decision_reason = _is_proctor_violation(result, payload.threshold)
        answered_questions = int(session.current_question_index or 0)
        warning_eligible = answered_questions >= max(0, PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING)
        should_raise_warning = violated and anomaly_threshold_reached and cooldown_elapsed and warning_eligible
        action = "ok"
        if should_raise_warning:
            session.warning_count = int(session.warning_count or 0) + 1
            if session.warning_count >= 4:
                session.status = VivaSessionStatus.TERMINATED_PROCTORING
                session.finished_at = datetime.utcnow()
                session.termination_reason = "left_frame_or_identity_mismatch"
                action = "terminated"
            else:
                action = "warning"
        elif violated and anomaly:
            action = "ok"
            if not warning_eligible:
                decision_reason = f"grace_period_hold:{anomaly_reason}"
            else:
                decision_reason = f"buffered_window_hold:{anomaly_reason}"

        frame_object_path = None
        frame_b64_fallback = None
        if anomaly or VIVA_STORE_ALL_FRAMES or action in {"warning", "terminated"}:
            frame_object_path = _store_image_to_object_storage(session.id, "frames", payload.frame_b64)
            if frame_object_path is None:
                # Keep evidence even if object storage is temporarily unavailable.
                frame_b64_fallback = payload.frame_b64

        event = VivaProctorEvent(
            session_id=session.id,
            event_type="frame_check",
            is_present=1 if result.is_present else 0,
            is_match=1 if result.is_match else 0,
            confidence=result.confidence,
            warning_count=int(session.warning_count or 0),
            action=action,
            details_json={
                "reason": result.reason,
                "decision_reason": decision_reason,
                "threshold": payload.threshold,
                "anomaly": anomaly,
                "anomaly_reason": anomaly_reason,
                "window_size": PROCTOR_WINDOW_SIZE,
                "window_anomaly_count": window_anomaly_count,
                "window_threshold": PROCTOR_WINDOW_ANOMALY_THRESHOLD,
                "cooldown_elapsed": cooldown_elapsed,
                "warning_eligible": warning_eligible,
                "answered_questions": answered_questions,
                "min_answered_for_warning": PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING,
                "frame_object_path": frame_object_path,
                "frame_b64_fallback": frame_b64_fallback,
            },
        )
        db.add(event)
        db.flush()

        if action == "terminated":
            finalized = _finalize_session_with_db(db, session.id, force_termination_reason=session.termination_reason)
            return {
                "session": finalized["session"],
                "proctor": {
                    "is_present": result.is_present,
                    "is_match": result.is_match,
                    "confidence": result.confidence,
                    "anomaly": anomaly,
                    "reason": result.reason,
                    "decision_reason": decision_reason,
                },
                "action": action,
                "warnings": int(session.warning_count or 0),
            }

        return {
            "session": _session_summary(session),
            "proctor": {
                "is_present": result.is_present,
                "is_match": result.is_match,
                "confidence": result.confidence,
                "anomaly": anomaly,
                "reason": result.reason,
                "decision_reason": decision_reason,
            },
            "action": action,
            "warnings": int(session.warning_count or 0),
        }


@app.post("/viva/sessions/{session_id}/answer")
def submit_answer(session_id: str, payload: AnswerRequest):
    tracker = _CostTracker()
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        _ensure_active(session)
        if _session_timed_out(session):
            _mark_timeout(session)
            finalized = _finalize_session_with_db(db, session.id, force_termination_reason="session_timeout")
            return {"session": finalized["session"], "terminated": True, "result": finalized["result"]}

        base_question_count = int(session.question_count or 0)
        total_question_target = _total_question_target(base_question_count)
        current_order = int(session.current_question_index or 0) + 1
        submitted_question_id = str(payload.question_id or "").strip()
        question = _ensure_question_for_order(
            db=db,
            session=session,
            order=current_order,
            cost_tracker=tracker,
            total_question_target=total_question_target,
        )
        if question is None:
            if submitted_question_id:
                submitted_question = _find_session_question_by_id(db, session.id, submitted_question_id)
                if submitted_question and int(submitted_question.question_order or 0) == current_order:
                    question = submitted_question
            if question is None:
                question = _ensure_question_for_order(
                    db=db,
                    session=session,
                    order=current_order,
                    cost_tracker=tracker,
                    total_question_target=total_question_target,
                )
        if question is None:
            if submitted_question_id:
                submitted_question = _find_session_question_by_id(db, session.id, submitted_question_id)
                submitted_turn = (
                    _find_latest_turn_for_question(db, session.id, submitted_question.id) if submitted_question else None
                )
                if submitted_question and submitted_turn:
                    recovered = _build_idempotent_submit_recovery(
                        db=db,
                        session=session,
                        submitted_question=submitted_question,
                        submitted_turn=submitted_turn,
                        total_question_target=total_question_target,
                        tracker=tracker,
                    )
                    if recovered is not None:
                        return recovered
            raise HTTPException(status_code=409, detail="No active question found for session")
        if submitted_question_id and submitted_question_id != str(question.id):
            submitted_question = _find_session_question_by_id(db, session.id, submitted_question_id)
            submitted_turn = _find_latest_turn_for_question(db, session.id, submitted_question.id) if submitted_question else None
            if submitted_question and submitted_turn:
                recovered = _build_idempotent_submit_recovery(
                    db=db,
                    session=session,
                    submitted_question=submitted_question,
                    submitted_turn=submitted_turn,
                    total_question_target=total_question_target,
                    tracker=tracker,
                )
                if recovered is not None:
                    return recovered
            raise HTTPException(status_code=409, detail="Submitted question is stale for current session state")
        question_timed_out = _question_timed_out(question, int(session.per_question_limit_seconds or 0))

        transcript = (payload.transcript or "").strip()
        transcribe_usage = None
        if not transcript and payload.audio_b64:
            transcript, transcribe_usage = transcribe_audio(get_openai_client(), payload.audio_b64, STT_MODEL)
        if transcribe_usage is not None:
            tracker.add_chat(
                kind="stt",
                model=STT_MODEL,
                usage=transcribe_usage,
                file_id=session.file_id,
                meta={"session_id": str(session.id), "question_order": current_order},
            )
        if not transcript and question_timed_out:
            transcript = "No answer submitted before time limit."
        if not transcript:
            raise HTTPException(status_code=422, detail="Answer transcript is required (or valid audio_b64).")

        if question_timed_out:
            eval_payload = {
                "score": 0.0,
                "max_score": 10.0,
                "strengths": [],
                "weaknesses": ["No answer submitted within the time limit"],
                "feedback": "Time limit exceeded for this question. Moving to the next question.",
            }
        else:
            eval_payload = _evaluate_answer(
                question_text=question.question_text,
                expected_points=[str(v) for v in (question.expected_points_json or [])],
                answer_transcript=transcript,
                cost_tracker=tracker,
                file_id=session.file_id,
                session_id=str(session.id),
            )

        turn = VivaTurn(
            session_id=session.id,
            question_id=question.id,
            answer_transcript=transcript,
            answer_audio_b64=payload.audio_b64,
            score=eval_payload["score"],
            max_score=eval_payload["max_score"],
            strengths_json=eval_payload["strengths"],
            weaknesses_json=eval_payload["weaknesses"],
            feedback=eval_payload["feedback"],
            latency_ms=max(int(payload.latency_ms or 0), 0),
        )
        db.add(turn)
        session.current_question_index = current_order

        if session.current_question_index >= total_question_target:
            session.status = VivaSessionStatus.COMPLETED
            session.finished_at = datetime.utcnow()
            finalized = _finalize_session_with_db(db, session.id)
            return {
                "session": finalized["session"],
                "turn": {
                    "question_id": str(question.id),
                    "question_order": current_order,
                    "answer_transcript": transcript,
                    "evaluation": eval_payload,
                },
                "done": True,
                "result": finalized["result"],
                "cost": tracker.summary(),
            }

        next_order = int(session.current_question_index or 0) + 1
        plan = _plan_question(next_order, base_question_count)
        next_question = (
            db.execute(
                select(VivaQuestion)
                .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == next_order)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if next_question is None and plan["kind"] == "base":
            _ensure_base_question_bank(db, session, tracker, target_base_indexes=[int(plan["base_index"])])
            next_question = (
                db.execute(
                    select(VivaQuestion)
                    .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == next_order)
                    .limit(1)
                )
                .scalars()
                .first()
            )
        if next_question is None and plan["kind"] == "followup":
            followup_data = _generate_question_with_llm(
                topic=session.topic,
                chapter_number=session.chapter_number,
                question_count=total_question_target,
                question_index=next_order - 1,
                previous_question=question.question_text,
                previous_answer=transcript,
                cost_tracker=tracker,
                file_id=session.file_id,
                session_id=str(session.id),
            )
            next_question = VivaQuestion(
                session_id=session.id,
                question_order=next_order,
                question_text=followup_data["question"],
                expected_points_json=followup_data["expected_points"],
                asked_at=datetime.utcnow(),
            )
            db.add(next_question)
        if next_question is None:
            raise HTTPException(status_code=409, detail="Next question not found for session")

        next_question.asked_at = datetime.utcnow()
        db.flush()

        return {
            "session": _session_summary(session),
            "turn": {
                "question_id": str(question.id),
                "question_order": current_order,
                "answer_transcript": transcript,
                "evaluation": eval_payload,
            },
            "next_question": _serialize_question(next_question, with_audio=True),
            "done": False,
            "cost": tracker.summary(),
        }


@app.get("/viva/sessions/{session_id}")
def get_session(session_id: str):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        if session.status in (VivaSessionStatus.PENDING, VivaSessionStatus.ACTIVE) and _session_timed_out(session):
            _mark_timeout(session)
        current_order = int(session.current_question_index or 0) + 1
        current_question = (
            db.execute(
                select(VivaQuestion)
                .where(VivaQuestion.session_id == session.id, VivaQuestion.question_order == current_order)
                .limit(1)
            )
            .scalars()
            .first()
        )
        return {
            "session": _session_summary(session),
            "current_question": _serialize_question(current_question) if current_question else None,
        }


@app.post("/viva/sessions/{session_id}/finish")
def finish_session(session_id: str):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        db.add(
            VivaProctorEvent(
                session_id=session.id,
                event_type="manual_finish",
                is_present=1,
                is_match=1,
                confidence=1,
                warning_count=int(session.warning_count or 0),
                action="ok",
                details_json={"trigger": "user"},
            )
        )
        return _finalize_session_with_db(db, session.id)


@app.get("/viva/sessions/{session_id}/results")
def get_results(session_id: str):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        result = db.execute(select(VivaResult).where(VivaResult.session_id == session.id)).scalar_one_or_none()
        if result is None:
            if session.status in (VivaSessionStatus.PENDING, VivaSessionStatus.ACTIVE):
                raise HTTPException(status_code=409, detail="Session not finished yet")
            finalized = _finalize_session(session)
            return finalized

        return {
            "session": _session_summary(session),
            "result": {
                **(_serialize_result_row(result, _load_proctor_events(db, session.id)) or {}),
                "cost": _load_cost_summary(db, session.id),
            },
        }


@app.get("/viva/history/sessions")
def get_history(file_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20, offset: int = 0):
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    with get_db_context() as db:
        stmt = select(VivaSession)
        if file_id:
            stmt = stmt.where(VivaSession.file_id == file_id)
        if status:
            stmt = stmt.where(VivaSession.status == status)
        rows = (
            db.execute(stmt.order_by(desc(VivaSession.created_at)).limit(safe_limit).offset(safe_offset))
            .scalars()
            .all()
        )
        return [_build_session_history_item(db, row) for row in rows]


@app.get("/viva/sessions/{session_id}/audit")
def get_session_audit(session_id: str):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
        result = db.execute(select(VivaResult).where(VivaResult.session_id == session.id)).scalar_one_or_none()
        proctor_events = _load_proctor_events(db, session.id)
        return {
            "session": _session_summary(session),
            "reference_photo_b64": session.reference_photo_b64,
            "questions": _load_questions(db, session.id),
            "turns": _load_turns(db, session.id),
            "proctor_events": proctor_events,
            "result": _serialize_result_row(result, proctor_events),
        }


@app.get("/viva/sessions/{session_id}/media")
def get_session_media(session_id: str, object_path: str):
    with get_db_context() as db:
        session = db.get(VivaSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Viva session not found")
    key = _parse_media_object_key(session_id=session_id, object_path=object_path)
    try:
        payload = get_storage_client().download(key)
    except Exception:
        raise HTTPException(status_code=404, detail="Media object not found")
    return Response(content=payload, media_type="image/jpeg")
