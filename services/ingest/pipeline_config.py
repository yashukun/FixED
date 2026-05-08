import os

EMBED_MODEL = os.environ.get("INGEST_EMBED_MODEL", "text-embedding-3-large")
EMBED_BATCH_SIZE = 200  # stay well below the 2,048 input limit
CHUNK_SIZE = int(os.environ.get("INGEST_CHUNK_SIZE", "350"))
CHUNK_OVERLAP = int(os.environ.get("INGEST_CHUNK_OVERLAP", "70"))
CHAPTER_MODEL = os.environ.get("INGEST_CHAPTER_MODEL", "gpt-4o-mini")
MAX_CHAPTER_SAMPLE_PAGES = int(os.environ.get("INGEST_MAX_CHAPTER_SAMPLE_PAGES", "180"))
