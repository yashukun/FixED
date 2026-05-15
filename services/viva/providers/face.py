from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class FaceAuditResult:
    is_present: bool
    is_match: bool
    confidence: float
    reason: str


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def _normalize_reason(reason: str) -> str:
    value = (reason or "").strip().lower().replace(" ", "_")
    if value in {"match", "face_match"}:
        return "match"
    if value in {"mismatch", "face_mismatch"}:
        return "mismatch"
    if value in {"face_not_present", "no_face", "not_present"}:
        return "face_not_present"
    if value in {"multiple_faces", "more_than_one_face"}:
        return "multiple_faces"
    if value in {"low_quality", "blurry", "occluded"}:
        return "low_quality"
    if value in {"occluded_face", "occlusion", "covered_face"}:
        return "occluded_face"
    if value in {"suspicious_accessory", "hat", "cap", "dark_glasses", "glasses", "mask"}:
        return "suspicious_accessory"
    if value in {"uncertain", "ambiguous"}:
        return "uncertain"
    return value or "unknown"


def _vision_face_compare(
    client: OpenAI,
    model: str,
    reference_photo_b64: str,
    frame_b64: str,
) -> FaceAuditResult:
    completion = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict exam proctoring face verifier. "
                    "Return JSON only with keys: "
                    "is_present (boolean), is_match (boolean), confidence (number 0..1), "
                    "reason (one of: match, mismatch, face_not_present, multiple_faces, "
                    "low_quality, occluded_face, suspicious_accessory, uncertain)."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Compare these two images. The first is the reference candidate photo, "
                            "the second is a live proctoring frame from the same session. "
                            "Set is_present=false if no clear face is visible in the frame. "
                            "Set is_match=true only when identity match is clear. "
                            "If another person appears, use multiple_faces. "
                            "If face is hidden by cap, sunglasses, mask, or heavy occlusion, "
                            "use suspicious_accessory or occluded_face."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{reference_photo_b64}"},
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
                    },
                ],
            },
        ],
    )
    content = completion.choices[0].message.content or ""
    parsed = _extract_json(content)
    is_present = bool(parsed.get("is_present", True))
    is_match = bool(parsed.get("is_match", False))
    confidence_raw = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    reason = _normalize_reason(str(parsed.get("reason", "")))
    if not is_present:
        reason = "face_not_present"
    elif is_match:
        reason = "match"
    elif reason in {"unknown", ""}:
        reason = "mismatch"
    return FaceAuditResult(
        is_present=is_present,
        is_match=is_match,
        confidence=confidence,
        reason=reason,
    )


def verify_face(
    reference_photo_b64: str | None,
    frame_b64: str | None,
    threshold: float = 0.75,
    *,
    client: OpenAI | None = None,
    model: str = "gpt-4o-mini",
) -> FaceAuditResult:
    if not frame_b64:
        return FaceAuditResult(is_present=False, is_match=False, confidence=0.0, reason="no_frame")
    if len(frame_b64.strip()) < 32:
        return FaceAuditResult(is_present=False, is_match=False, confidence=0.0, reason="frame_too_small")
    if not reference_photo_b64:
        return FaceAuditResult(is_present=True, is_match=False, confidence=0.0, reason="missing_reference")
    if client is None:
        return FaceAuditResult(is_present=False, is_match=False, confidence=0.0, reason="provider_unavailable")
    try:
        result = _vision_face_compare(client, model=model, reference_photo_b64=reference_photo_b64, frame_b64=frame_b64)
        if result.is_present and not result.is_match and result.reason == "mismatch" and result.confidence >= threshold:
            # Model hinted mismatch but confidence is high; mark uncertain for conservative handling upstream.
            return FaceAuditResult(is_present=True, is_match=False, confidence=result.confidence, reason="uncertain")
        return result
    except Exception:
        return FaceAuditResult(is_present=False, is_match=False, confidence=0.0, reason="provider_error")
