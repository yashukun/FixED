import os

EMBED_MODEL = os.environ.get("QPAPER_EMBED_MODEL", "text-embedding-3-large")
CHAT_MODEL = os.environ.get("QPAPER_CHAT_MODEL", "gpt-4o-mini")
VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")

DEFAULT_TOP_K = 20
MAX_TOP_K = 40
MAX_CONTEXT_CHARS = 20000
MAX_CHUNK_CHARS = 900
