"""Shared embedding configuration — single source of truth for vector size.

Every service (ingest, search, qpaper, viva) embeds text with the SAME
dimensionality, because the Postgres pgvector column
(``DocumentChunk.embedding``) and the Qdrant collection are both built for
exactly this size. Mismatched dimensions silently corrupt the vector store or
break inserts, so every ``embeddings.create(...)`` call MUST pass
``dimensions=EMBEDDING_DIMENSIONS``.

OpenAI's ``text-embedding-3-small`` (native 1536) and ``text-embedding-3-large``
(native 3072) both accept the ``dimensions`` parameter, so the same value works
for either model — ``3-large`` is simply truncated to ``EMBEDDING_DIMENSIONS``.

IMPORTANT: changing this value is a breaking change. It requires a database
migration (the ``Vector(N)`` column) AND a full re-embed of every document, so
override ``EMBEDDING_DIMENSIONS`` only as part of a deliberate migration.
"""

import os

EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
