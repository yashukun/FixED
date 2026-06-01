"""Single source of truth for the embedding model → vector dimension.

Storage (the pgvector column, the Qdrant collection, the Pinecone index) and
the OpenAI embedding calls must all agree on the vector dimension. The number
used to be hardcoded in several places, so it drifted: the model was bumped to
``text-embedding-3-large`` (3072-dim) while storage stayed at 1536, which broke
both uploads and search with a dimension-mismatch error. Resolve it from one
place so it can no longer drift.

Resolution priority for the *storage* dimension:
    1. ``EMBED_DIMENSIONS`` env override (explicit integer), else
    2. the native dimension of the *ingest* embedding model (the writer), else
    3. the global default model.

If you set ``EMBED_DIMENSIONS`` you must keep it consistent across every
service, and the embedding calls will pin the OpenAI ``dimensions`` parameter to
match (only the ``text-embedding-3-*`` models support that parameter).
"""
from __future__ import annotations

import os

# Default embedding model used across services when none is configured.
DEFAULT_EMBED_MODEL = "text-embedding-3-large"

# Native output dimensionality for known OpenAI embedding models.
MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

# Models that accept the OpenAI ``dimensions`` parameter (Matryoshka truncation).
_SUPPORTS_DIMENSIONS = {"text-embedding-3-small", "text-embedding-3-large"}

# Fallback when the model is unknown — matches the most common OpenAI default.
_FALLBACK_DIMENSION = 1536


def model_native_dimension(model: str | None) -> int:
    """Return the native output dimension for a known model (or the fallback)."""
    return MODEL_DIMENSIONS.get((model or "").strip(), _FALLBACK_DIMENSION)


def _dimension_override() -> int | None:
    raw = os.environ.get("EMBED_DIMENSIONS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_embedding_dimension(model: str | None = None) -> int:
    """Vector dimension that storage must use.

    Priority: explicit ``EMBED_DIMENSIONS`` override → the ingest/writer model's
    native dimension → the global default model's native dimension.
    """
    override = _dimension_override()
    if override is not None:
        return override
    resolved_model = (
        model
        or os.environ.get("EMBED_MODEL")
        or os.environ.get("INGEST_EMBED_MODEL")
        or DEFAULT_EMBED_MODEL
    )
    return model_native_dimension(resolved_model)


def supports_dimensions_param(model: str | None) -> bool:
    return (model or "").strip() in _SUPPORTS_DIMENSIONS


def embedding_request_kwargs(model: str | None = None) -> dict[str, int]:
    """Extra kwargs for ``client.embeddings.create`` so output matches storage.

    Only pin ``dimensions`` when an explicit ``EMBED_DIMENSIONS`` override is set
    and the model supports the parameter; otherwise return ``{}`` and let the
    model emit its native dimension (which equals the resolved storage
    dimension).
    """
    override = _dimension_override()
    if override is None:
        return {}
    resolved_model = (
        model
        or os.environ.get("EMBED_MODEL")
        or os.environ.get("INGEST_EMBED_MODEL")
        or DEFAULT_EMBED_MODEL
    )
    if not supports_dimensions_param(resolved_model):
        return {}
    return {"dimensions": override}


# Resolved once at import time — storage schemas read this constant.
EMBEDDING_DIMENSION = resolve_embedding_dimension()
