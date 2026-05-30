import os

# When false (default/production) the /debug/retrieval endpoint returns 404.
DEBUG = os.environ.get("DEBUG", "false").lower() in {"1", "true", "yes"}

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
QDRANT_GLOBAL_QUERY_EF = max(int(os.environ.get("SEARCH_QDRANT_GLOBAL_QUERY_EF", "64")), 0)
QDRANT_SCOPED_QUERY_EF = max(int(os.environ.get("SEARCH_QDRANT_SCOPED_QUERY_EF", "128")), 0)
GLOBAL_PROBE_TOP_K = max(int(os.environ.get("SEARCH_GLOBAL_PROBE_TOP_K", "24")), 1)
GLOBAL_ROUTE_CANDIDATE_LIMIT = max(int(os.environ.get("SEARCH_GLOBAL_ROUTE_CANDIDATE_LIMIT", "2")), 1)
VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")
QPAPER_SERVICE_URL = os.environ.get("QPAPER_SERVICE_URL", "http://qpaper:8000")
QPAPER_DEFAULT_TOTAL_MARKS = int(os.environ.get("QPAPER_DEFAULT_TOTAL_MARKS", "100"))
QPAPER_DEFAULT_MODE = os.environ.get("QPAPER_DEFAULT_MODE", "official")
