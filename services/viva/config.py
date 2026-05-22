import os

CHAT_MODEL = os.environ.get("VIVA_CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = (
    os.environ.get("VIVA_EMBED_MODEL")
    or os.environ.get("SEARCH_EMBED_MODEL")
    or os.environ.get("QPAPER_EMBED_MODEL")
    or os.environ.get("INGEST_EMBED_MODEL")
    or "text-embedding-3-large"
)
STT_MODEL = os.environ.get("VIVA_STT_MODEL", "gpt-4o-mini-transcribe")
TTS_MODEL = os.environ.get("VIVA_TTS_MODEL", "gpt-4o-mini-tts")
VISION_MODEL = os.environ.get("VIVA_VISION_MODEL", "gpt-4o-mini")

VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")
VIVA_RETRIEVAL_TOP_K = int(os.environ.get("VIVA_RETRIEVAL_TOP_K", "20"))
VIVA_MAX_CONTEXT_CHARS = int(os.environ.get("VIVA_MAX_CONTEXT_CHARS", "20000"))
VIVA_MAX_CHUNK_CHARS = int(os.environ.get("VIVA_MAX_CHUNK_CHARS", "900"))

MAX_QUESTION_COUNT = int(os.environ.get("VIVA_MAX_QUESTION_COUNT", "10"))
MIN_QUESTION_COUNT = int(os.environ.get("VIVA_MIN_QUESTION_COUNT", "5"))
DEFAULT_QUESTION_COUNT = int(os.environ.get("VIVA_DEFAULT_QUESTION_COUNT", "5"))
DEFAULT_PER_QUESTION_LIMIT_SECONDS = int(os.environ.get("VIVA_DEFAULT_PER_QUESTION_LIMIT_SECONDS", "60"))
DEFAULT_FACE_MATCH_THRESHOLD = float(os.environ.get("VIVA_FACE_MATCH_THRESHOLD", "0.9"))
PROCTOR_AMBIGUOUS_CONFIDENCE_MIN = float(os.environ.get("VIVA_PROCTOR_AMBIGUOUS_CONFIDENCE_MIN", "0.65"))
PROCTOR_VIOLATE_ON_AMBIGUOUS = os.environ.get("VIVA_PROCTOR_VIOLATE_ON_AMBIGUOUS", "1").lower() not in {
    "0",
    "false",
    "no",
}
PROCTOR_MIN_FRAME_INTERVAL_MS = int(os.environ.get("VIVA_PROCTOR_MIN_FRAME_INTERVAL_MS", "2500"))
FOLLOWUP_MIN_RATIO = float(os.environ.get("VIVA_FOLLOWUP_MIN_RATIO", "0.6"))
VIVA_MIN_FOLLOWUP_QUESTIONS = os.environ.get("VIVA_MIN_FOLLOWUP_QUESTIONS")
FOLLOWUP_MIN_COUNT = (
    int(VIVA_MIN_FOLLOWUP_QUESTIONS)
    if VIVA_MIN_FOLLOWUP_QUESTIONS is not None and str(VIVA_MIN_FOLLOWUP_QUESTIONS).strip() != ""
    else None
)
PROCTOR_WINDOW_SIZE = int(os.environ.get("VIVA_PROCTOR_WINDOW_SIZE", "8"))
PROCTOR_WINDOW_ANOMALY_THRESHOLD = int(os.environ.get("VIVA_PROCTOR_WINDOW_ANOMALY_THRESHOLD", "3"))
PROCTOR_WARNING_MIN_INTERVAL_MS = int(os.environ.get("VIVA_PROCTOR_WARNING_MIN_INTERVAL_MS", "10000"))
VIVA_MEDIA_BUCKET = os.environ.get("VIVA_MEDIA_BUCKET", "viva-media")
VIVA_STORE_ALL_FRAMES = os.environ.get("VIVA_STORE_ALL_FRAMES", "0").lower() in {"1", "true", "yes"}
PROCTOR_ACCESSORY_IS_VIOLATION = os.environ.get("VIVA_PROCTOR_ACCESSORY_IS_VIOLATION", "0").lower() in {
    "1",
    "true",
    "yes",
}
PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING = int(os.environ.get("VIVA_PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING", "1"))
