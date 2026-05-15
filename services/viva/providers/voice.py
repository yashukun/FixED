from __future__ import annotations

import base64
import io
from typing import Any

from openai import OpenAI


def transcribe_audio(client: OpenAI | None, audio_b64: str | None, model: str) -> tuple[str, Any]:
    if not audio_b64:
        return "", None
    if client is None:
        return "Audio transcript unavailable (missing OpenAI client).", None
    try:
        audio_bytes = base64.b64decode(audio_b64.encode("utf-8"), validate=False)
    except Exception:
        return "", None
    if not audio_bytes:
        return "", None

    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = "answer.wav"
    transcript = client.audio.transcriptions.create(model=model, file=file_obj)
    text = getattr(transcript, "text", "") or ""
    usage = getattr(transcript, "usage", None)
    return text.strip(), usage


def synthesize_question_audio(client: OpenAI | None, text: str, model: str, voice: str = "alloy") -> str | None:
    if not text:
        return None
    if client is None:
        return None
    try:
        audio = client.audio.speech.create(model=model, voice=voice, input=text)
        payload = audio.read()
        return base64.b64encode(payload).decode("utf-8")
    except Exception:
        return None
