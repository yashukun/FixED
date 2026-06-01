"""Recreate the Qdrant vector collection at the active embedding dimension.

DESTRUCTIVE: deletes the existing collection (and all stored vectors) and
recreates it empty at the dimension resolved from the active embedding model
(see db.embedding). Run this once after changing the embedding model to a model
with a different vector dimension; then re-ingest every document.

Usage (from the repo root, with the stack running):

    QDRANT_URL=http://localhost:6333 VECTOR_DB_PROVIDER=qdrant \
    PYTHONPATH=services/ingest:services/shared:services \
    python services/ingest/recreate_qdrant_collection.py

Add --yes to skip the confirmation prompt (e.g. in CI/automation).
"""
from __future__ import annotations

import sys

import vector_store as v


def main(argv: list[str]) -> int:
    assume_yes = "--yes" in argv or "-y" in argv

    client = v._get_qdrant_client()
    expected_dim = v.EMBEDDING_DIMENSION

    existing = {c.name for c in client.get_collections().collections}
    if v.QDRANT_COLLECTION in existing:
        current_dim = v._get_qdrant_collection_vector_size(client)
        info = client.get_collection(v.QDRANT_COLLECTION)
        print(
            f"Collection '{v.QDRANT_COLLECTION}': current dim={current_dim}, "
            f"points={info.points_count}"
        )
        if current_dim == expected_dim:
            print(f"Already at dim={expected_dim}; ensuring payload indexes only.")
            v._ensure_qdrant_collection(client, expected_dim=expected_dim)
            return 0
        if not assume_yes:
            answer = input(
                f"This will DELETE all {info.points_count} vectors and recreate at "
                f"dim={expected_dim}. Type 'yes' to proceed: "
            ).strip().lower()
            if answer != "yes":
                print("Aborted.")
                return 1
        client.delete_collection(collection_name=v.QDRANT_COLLECTION)
        print(f"Deleted collection '{v.QDRANT_COLLECTION}'.")
    else:
        print(f"Collection '{v.QDRANT_COLLECTION}' does not exist; creating fresh.")

    v._ensure_qdrant_collection(client, expected_dim=expected_dim)
    after = client.get_collection(v.QDRANT_COLLECTION)
    print(
        f"Recreated '{v.QDRANT_COLLECTION}' at dim="
        f"{v._get_qdrant_collection_vector_size(client)} "
        f"(points={after.points_count}, status={after.status})."
    )
    print("Done. Re-ingest your documents to repopulate the collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
