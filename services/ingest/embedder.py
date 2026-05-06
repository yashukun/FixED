from __future__ import annotations

import io
import os
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pypdf import PdfReader

from pinecone_client import upsert_vectors
from db import set_status, JobStatus, get_db_context, Job

# ---------------------------------------------------------------------------
# Clients (module-level singletons — instantiated once per worker process)
# ---------------------------------------------------------------------------

_openai_client: OpenAI | None = None

EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH_SIZE = 200  # stay well below the 2 048 input limit
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


# ---------------------------------------------------------------------------
# Step 2 — Text extraction
# ---------------------------------------------------------------------------

def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Return plain text from PDF or TXT bytes."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        full_text = "\n".join(pages).strip()
        if not full_text:
            raise ValueError("PDF appears to be empty or image-only (no extractable text).")
        return full_text

    if ext == "txt":
        try:
            return file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1").strip()

    raise ValueError(f"Unsupported file type: .{ext}. Only .pdf and .txt are accepted.")


# ---------------------------------------------------------------------------
# Step 3 — Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks = splitter.split_text(text)
    if not chunks:
        raise ValueError("Text produced zero chunks after splitting.")
    return chunks


# ---------------------------------------------------------------------------
# Step 4 — Batch embedding
# ---------------------------------------------------------------------------

def _embed_chunks(chunks: List[str]) -> List[List[float]]:
    """Return embeddings for all chunks, batching to avoid API limits."""
    client = _get_openai()
    all_embeddings: List[List[float]] = []

    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        response = client.embeddings.create(
            model=EMBED_MODEL,
            input=batch,
        )
        # Preserve order — the API returns items in the same order as input
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_and_store(
    file_bytes: bytes,
    filename: str,
    file_id: str,
) -> dict:
    """
    Full pipeline: extract → chunk → embed → upsert.

    Returns {"chunk_count": N}.
    Raises ValueError for unsupported formats / empty content.
    """
    try:
        # 0. Mark job as PROCESSING
        set_status(file_id, JobStatus.PROCESSING)

        # 1. Extract
        text = _extract_text(file_bytes, filename)

        # 2. Chunk
        chunks = _chunk_text(text)

        # 3. Embed
        embeddings = _embed_chunks(chunks)

        # 4. Build vectors matching the Pinecone schema
        vectors = [
            {
                "id": f"{file_id}_{idx}",
                "values": embedding,
                "metadata": {
                    "file_id": file_id,
                    "chunk_index": idx,
                    "text": chunk,
                    "filename": filename,
                },
            }
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        # 5. Upsert vectors
        upsert_vectors(vectors, namespace="documents")

        # 6. Mark job as COMPLETED and save the result
        with get_db_context() as db:
            job = db.query(Job).filter(Job.id == file_id).first()
            if job:
                job.status = JobStatus.COMPLETED
                job.result = f"Processed {len(chunks)} chunks"

        return {"chunk_count": len(chunks)}
    except Exception as e:
        # Mark job as FAILED
        set_status(file_id, JobStatus.FAILED, error=str(e))
        raise e