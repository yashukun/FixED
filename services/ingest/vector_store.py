from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List

from db import DocumentChunk, get_db_context
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vector DB configuration
# ---------------------------------------------------------------------------
VECTOR_DB_PROVIDER = os.environ.get("VECTOR_DB_PROVIDER", "pgvector")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")
EMBEDDING_DIMENSION = 1536
QDRANT_RECREATE_ON_DIM_MISMATCH = (
    os.environ.get("QDRANT_RECREATE_ON_DIM_MISMATCH", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# Provider singletons
# ---------------------------------------------------------------------------

_pc = None
_index = None
_qdrant_client = None


def _normalized_provider() -> str:
    """Normalize provider env to avoid casing/whitespace config bugs."""
    return (VECTOR_DB_PROVIDER or "pgvector").strip().lower()


def _qdrant_safe_point_id(original_id: str) -> int:
    """
    Qdrant accepts uint64 or UUID point IDs. Convert any custom string ID to
    a deterministic uint64 so upserts are stable across retries.
    """
    digest = hashlib.sha256(original_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


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


def _get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client


def _get_qdrant_collection_vector_size(client: QdrantClient) -> int | None:
    info = client.get_collection(QDRANT_COLLECTION)
    vectors_cfg = info.config.params.vectors
    if isinstance(vectors_cfg, VectorParams):
        return int(vectors_cfg.size)
    if isinstance(vectors_cfg, dict):
        # Named vectors mode: use the first configured vector size.
        for _, cfg in vectors_cfg.items():
            if hasattr(cfg, "size"):
                return int(cfg.size)
    return None


def _ensure_qdrant_collection(client: QdrantClient, expected_dim: int) -> None:
    collections = client.get_collections().collections
    exists = any(collection.name == QDRANT_COLLECTION for collection in collections)
    if not exists:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=expected_dim, distance=Distance.COSINE),
        )
        logger.info(
            "Created Qdrant collection %s with vector_size=%s",
            QDRANT_COLLECTION,
            expected_dim,
        )
        return

    current_dim = _get_qdrant_collection_vector_size(client)
    if current_dim is None:
        logger.warning(
            "Unable to verify Qdrant vector dimension for collection=%s",
            QDRANT_COLLECTION,
        )
        return
    if current_dim == expected_dim:
        return

    if QDRANT_RECREATE_ON_DIM_MISMATCH:
        logger.warning(
            "Recreating Qdrant collection %s due to dimension mismatch: current=%s expected=%s",
            QDRANT_COLLECTION,
            current_dim,
            expected_dim,
        )
        client.delete_collection(collection_name=QDRANT_COLLECTION)
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=expected_dim, distance=Distance.COSINE),
        )
        return

    raise ValueError(
        f"Qdrant collection '{QDRANT_COLLECTION}' dimension mismatch: current={current_dim}, "
        f"expected={expected_dim}. Recreate the collection or keep embedding dimensions consistent. "
        "Set QDRANT_RECREATE_ON_DIM_MISMATCH=true to auto-recreate (destructive)."
    )


def upsert_vectors(
    vectors: List[Dict[str, Any]],
    namespace: str = "documents",
    batch_size: int = 100,
) -> int:
    """
    Upsert vectors to the active Vector DB (pgvector, qdrant, or pinecone).

    Each item in `vectors` must follow the shape:
        {"id": str, "values": List[float], "metadata": dict}

    Returns the total number of vectors upserted.
    """
    provider = _normalized_provider()
    logger.info("Upserting %s vectors using provider=%s", len(vectors), provider)

    if provider == "pinecone":
        index = _get_pinecone_index()
        total = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            index.upsert(vectors=batch, namespace=namespace)
            total += len(batch)
        return total

    if provider == "qdrant":
        client = _get_qdrant_client()
        if not vectors:
            return 0
        expected_dim = len(vectors[0].get("values", []))
        if expected_dim <= 0:
            raise ValueError("Invalid vector payload: missing 'values' for Qdrant upsert.")
        _ensure_qdrant_collection(client, expected_dim=expected_dim)
        total = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            points = [
                PointStruct(
                    id=_qdrant_safe_point_id(str(vector["id"])),
                    vector=vector["values"],
                    payload={
                        **vector.get("metadata", {}),
                        # Keep original deterministic chunk ID for retrieval/debug.
                        "chunk_id": str(vector["id"]),
                    },
                )
                for vector in batch
            ]
            client.upsert(collection_name=QDRANT_COLLECTION, points=points)
            total += len(batch)
            logger.info(
                "Qdrant upserted batch: size=%s collection=%s total=%s",
                len(batch),
                QDRANT_COLLECTION,
                total,
            )
        return total

    if provider == "pgvector":
        total = 0
        with get_db_context() as db:
            for vector in vectors:
                metadata = vector.get("metadata", {})
                chunk = DocumentChunk(
                    id=vector["id"],
                    file_id=metadata.get("file_id", "unknown"),
                    chunk_index=metadata.get("chunk_index", 0),
                    text_content=metadata.get("text", ""),
                    filename=metadata.get("filename", ""),
                    embedding=vector["values"],
                    metadata_=metadata,
                )
                db.merge(chunk)
            db.commit()
            total += len(vectors)
        return total

    raise ValueError(
        f"Unknown VECTOR_DB_PROVIDER: {VECTOR_DB_PROVIDER!r} (normalized={provider!r})"
    )

