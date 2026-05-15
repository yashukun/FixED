import unittest
from types import SimpleNamespace

import store_helpers
import vector_store
from qdrant_client.models import Distance, VectorParams


class _FakeQdrantClient:
    def __init__(self):
        self.created_indexes = []

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=vector_store.QDRANT_COLLECTION)])

    def get_collection(self, collection_name):  # noqa: ARG002
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=VectorParams(size=1536, distance=Distance.COSINE)
                )
            )
        )

    def create_payload_index(self, collection_name, field_name, field_schema, wait):  # noqa: ARG002
        self.created_indexes.append((field_name, str(field_schema)))


class IngestVectorStoreTests(unittest.TestCase):
    def test_ensure_collection_adds_payload_indexes_for_existing_collection(self):
        client = _FakeQdrantClient()
        vector_store._ensure_qdrant_collection(client, expected_dim=1536)
        indexed_fields = [field for field, _ in client.created_indexes]
        self.assertIn("file_id", indexed_fields)
        self.assertIn("chapter_number", indexed_fields)
        self.assertIn("page_number", indexed_fields)

    def test_build_vectors_normalizes_page_and_chapter_numbers(self):
        chunks = [
            {
                "text": "Chunk text",
                "metadata": {
                    "page_number": "12",
                    "page_label": "12",
                    "chapter_number": "3",
                    "source": "book.pdf",
                },
            }
        ]
        embeddings = [[0.1, 0.2]]
        vectors = store_helpers.build_vectors(
            file_id="file-1",
            filename="book.pdf",
            chunks=chunks,
            embeddings=embeddings,
        )
        metadata = vectors[0]["metadata"]
        self.assertEqual(metadata["page_number"], 12)
        self.assertEqual(metadata["chapter_number"], 3)


if __name__ == "__main__":
    unittest.main()
