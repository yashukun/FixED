from __future__ import annotations

import os
from typing import List, Dict, Any

from db import get_db_context, DocumentChunk

# ---------------------------------------------------------------------------
# Vector DB configuration
# ---------------------------------------------------------------------------
# To use pinecone later, change this to "pinecone" and ensure PINECONE_API_KEY
# is set in your .env file.
VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")

# ---------------------------------------------------------------------------
# Pinecone Singleton setup (For future use)
# ---------------------------------------------------------------------------

_pc = None
_index = None

def _get_pinecone_index():
    """Return (and lazily initialise) the Pinecone index singleton."""
    global _pc, _index

    if _index is not None:
        return _index

    # Import locally to avoid requiring the pinecone package if we use pgvector
    from pinecone import Pinecone, ServerlessSpec
    
    api_key = os.environ["PINECONE_API_KEY"]
    index_name = os.environ["PINECONE_INDEX_NAME"]

    _pc = Pinecone(api_key=api_key)

    # Create index if it doesn't exist yet (idempotent)
    existing = [i.name for i in _pc.list_indexes()]
    if index_name not in existing:
        _pc.create_index(
            name=index_name,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    _index = _pc.Index(index_name)
    return _index


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def upsert_vectors(
    vectors: List[Dict[str, Any]],
    namespace: str = "documents",
    batch_size: int = 100,
) -> int:
    """
    Upsert vectors to the active Vector DB (pgvector or pinecone).

    Each item in `vectors` must follow the shape:
        {"id": str, "values": List[float], "metadata": dict}

    Returns the total number of vectors upserted.
    """
    if VECTOR_DB_PROVIDER == "pinecone":
        # ── PINECONE CLOUD USAGE ──
        index = _get_pinecone_index()
        total = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            index.upsert(vectors=batch, namespace=namespace)
            total += len(batch)
        return total
    
    elif VECTOR_DB_PROVIDER == "pgvector":
        # ── LOCAL PGVECTOR USAGE ──
        total = 0
        with get_db_context() as db:
            for vector in vectors:
                metadata = vector.get("metadata", {})
                
                # Merge performs an UPSERT (insert or update on primary key)
                chunk = DocumentChunk(
                    id=vector["id"],
                    file_id=metadata.get("file_id", "unknown"),
                    chunk_index=metadata.get("chunk_index", 0),
                    text_content=metadata.get("text", ""),
                    filename=metadata.get("filename", ""),
                    embedding=vector["values"],
                    metadata_=metadata
                )
                db.merge(chunk)
            db.commit()
            total += len(vectors)
        return total
        
    else:
        raise ValueError(f"Unknown VECTOR_DB_PROVIDER: {VECTOR_DB_PROVIDER}")