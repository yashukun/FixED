import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from db import get_db_context, DocumentChunk

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "document_chunks")
EMBEDDING_DIMENSION = 1536
BATCH_SIZE = 200


def ensure_collection(client: QdrantClient) -> None:
    collections = client.get_collections().collections
    exists = any(collection.name == QDRANT_COLLECTION for collection in collections)
    if exists:
        return
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
    )


def run() -> None:
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    ensure_collection(client)

    with get_db_context() as db:
        chunks = db.query(DocumentChunk).all()

    points = [
        PointStruct(
            id=chunk.id,
            vector=chunk.embedding,
            payload={
                "file_id": chunk.file_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text_content,
                "filename": chunk.filename,
            },
        )
        for chunk in chunks
    ]

    total = 0
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i : i + BATCH_SIZE]
        client.upsert(collection_name=QDRANT_COLLECTION, points=batch)
        total += len(batch)
        print(f"Upserted {total}/{len(points)} points")

    print(f"Backfill complete. Total points: {total}")


if __name__ == "__main__":
    run()
