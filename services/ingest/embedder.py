from __future__ import annotations

import io
import json
import os
import re
from typing import List, Dict, Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pypdf import PdfReader

from vector_store import upsert_vectors
from db import set_status, JobStatus, get_db_context, Job, BookChapter

# ---------------------------------------------------------------------------
# Clients (module-level singletons — instantiated once per worker process)
# ---------------------------------------------------------------------------

_openai_client: OpenAI | None = None

EMBED_MODEL = os.environ.get("INGEST_EMBED_MODEL", "text-embedding-3-large")
EMBED_BATCH_SIZE = 200  # stay well below the 2 048 input limit
CHUNK_SIZE = int(os.environ.get("INGEST_CHUNK_SIZE", "350"))
CHUNK_OVERLAP = int(os.environ.get("INGEST_CHUNK_OVERLAP", "70"))
CHAPTER_MODEL = os.environ.get("INGEST_CHAPTER_MODEL", "gpt-4o-mini")
MAX_CHAPTER_SAMPLE_PAGES = int(os.environ.get("INGEST_MAX_CHAPTER_SAMPLE_PAGES", "180"))


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


# ---------------------------------------------------------------------------
# Step 2 — Text extraction
# ---------------------------------------------------------------------------

def _outline_entries(reader: PdfReader) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []

    def _walk(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                _walk(item)
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if not title:
                continue
            try:
                page_idx = reader.get_destination_page_number(item)
            except Exception:
                continue
            if page_idx is None:
                continue
            try:
                page_idx = int(page_idx)
            except (TypeError, ValueError):
                continue
            if page_idx < 0:
                continue
            entries.append((title, page_idx + 1))

    outline = getattr(reader, "outline", None)
    if isinstance(outline, list):
        _walk(outline)
    return entries


def _normalize_chapter_starts(
    starts: list[tuple[str, int]], total_pages: int
) -> list[dict[str, int | str]]:
    deduped: list[tuple[str, int]] = []
    seen = set()
    for title, start_page in starts:
        if start_page is None:
            continue
        try:
            start_page = int(start_page)
        except (TypeError, ValueError):
            continue
        if not title or start_page in seen:
            continue
        if start_page < 1 or start_page > total_pages:
            continue
        seen.add(start_page)
        deduped.append((title, start_page))

    deduped.sort(key=lambda item: item[1])
    chapters: list[dict[str, int | str]] = []
    for idx, (title, start_page) in enumerate(deduped, start=1):
        if idx < len(deduped):
            end_page = max(start_page, deduped[idx][1] - 1)
        else:
            end_page = total_pages
        chapters.append(
            {
                "number": idx,
                "title": title.strip(),
                "start_page": start_page,
                "end_page": end_page,
            }
        )
    return chapters


def _chapter_starts_from_llm(page_samples: list[tuple[int, str]], total_pages: int) -> list[tuple[str, int]]:
    if not page_samples or not os.environ.get("OPENAI_API_KEY"):
        return []

    prompt_lines = []
    for page_no, snippet in page_samples[:MAX_CHAPTER_SAMPLE_PAGES]:
        compact = " ".join(snippet.split())
        prompt_lines.append(f"Page {page_no}: {compact[:180]}")
    prompt = "\n".join(prompt_lines)

    client = _get_openai()
    try:
        completion = client.chat.completions.create(
            model=CHAPTER_MODEL,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract chapter starts from textbook pages. "
                        "Return only JSON with key 'chapters': "
                        "{\"chapters\":[{\"title\":\"...\",\"start_page\":1}]}. "
                        "Return at most 30 chapters. Use ascending page order."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Total pages: {total_pages}\n"
                        "Page snippets:\n"
                        f"{prompt}"
                    ),
                },
            ],
        )
    except Exception:
        return []

    raw = completion.choices[0].message.content or ""
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    starts: list[tuple[str, int]] = []
    for item in parsed.get("chapters", []):
        title = str(item.get("title", "")).strip()
        try:
            start_page = int(item.get("start_page"))
        except (TypeError, ValueError):
            continue
        if not title:
            continue
        if 1 <= start_page <= total_pages:
            starts.append((title, start_page))
    return starts


def _extract_chapters(reader: PdfReader, page_samples: list[tuple[int, str]], total_pages: int) -> list[dict[str, int | str]]:
    starts = _outline_entries(reader)
    if len(starts) < 2:
        starts = _chapter_starts_from_llm(page_samples, total_pages)
    chapters = _normalize_chapter_starts(starts, total_pages)
    if chapters:
        return chapters
    return [
        {
            "number": 1,
            "title": "Full Document",
            "start_page": 1,
            "end_page": max(total_pages, 1),
        }
    ]


def _chapter_for_page(chapters: list[dict[str, int | str]], page_number: int) -> int:
    for chapter in chapters:
        start_page = int(chapter["start_page"])
        end_page = int(chapter["end_page"])
        if start_page <= page_number <= end_page:
            return int(chapter["number"])
    return 1


def _extract_documents(file_bytes: bytes, filename: str) -> tuple[List[Dict[str, Any]], list[dict[str, int | str]]]:
    """
    Return page-aware documents and chapter metadata.
    For PDFs, each page is a source document.
    For TXT, treat the full file as one source document.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        docs: List[Dict[str, Any]] = []
        samples: list[tuple[int, str]] = []
        total_pages = len(reader.pages)
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            cleaned = text.strip()
            if not cleaned:
                continue
            samples.append((idx, "\n".join(cleaned.splitlines()[:2])))
            docs.append(
                {
                    "text": cleaned,
                    "metadata": {
                        "source": filename,
                        "page_number": idx,
                        "page_label": str(idx),
                    },
                }
            )
        if not docs:
            raise ValueError("PDF appears to be empty or image-only (no extractable text).")

        chapters = _extract_chapters(reader, samples, total_pages)
        for doc in docs:
            page_number = int(doc["metadata"].get("page_number", 1))
            doc["metadata"]["chapter_number"] = _chapter_for_page(chapters, page_number)
        return docs, chapters

    if ext == "txt":
        try:
            text = file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1").strip()
        if not text:
            raise ValueError("TXT file is empty after decoding.")
        return (
            [
                {
                    "text": text,
                    "metadata": {
                        "source": filename,
                        "page_number": 1,
                        "page_label": "1",
                        "chapter_number": 1,
                    },
                }
            ],
            [
                {
                    "number": 1,
                    "title": "Full Document",
                    "start_page": 1,
                    "end_page": 1,
                }
            ],
        )

    raise ValueError(f"Unsupported file type: .{ext}. Only .pdf and .txt are accepted.")


# ---------------------------------------------------------------------------
# Step 3 — Chunking
# ---------------------------------------------------------------------------

def _chunk_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks_with_metadata: List[Dict[str, Any]] = []
    for doc in documents:
        doc_text = doc.get("text", "")
        if not doc_text:
            continue
        doc_metadata = doc.get("metadata", {})
        doc_chunks = splitter.split_text(doc_text)
        for chunk in doc_chunks:
            chunks_with_metadata.append(
                {
                    "text": chunk,
                    "metadata": doc_metadata,
                }
            )
    chunks = [c["text"] for c in chunks_with_metadata]
    if not chunks:
        raise ValueError("Text produced zero chunks after splitting.")
    return chunks_with_metadata


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
        documents, chapters = _extract_documents(file_bytes, filename)

        # 2. Chunk
        chunks = _chunk_documents(documents)
        chunk_texts = [chunk["text"] for chunk in chunks]

        # 3. Embed
        embeddings = _embed_chunks(chunk_texts)

        # 4. Build vectors matching the Pinecone schema
        vectors = [
            {
                "id": f"{file_id}_{idx}",
                "values": embedding,
                "metadata": {
                    "file_id": file_id,
                    "chunk_index": idx,
                    "text": chunk["text"],
                    "filename": filename,
                    "source": chunk["metadata"].get("source", filename),
                    "page_number": chunk["metadata"].get("page_number"),
                    "page_label": chunk["metadata"].get("page_label"),
                    "chapter_number": chunk["metadata"].get("chapter_number"),
                },
            }
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        # 5. Upsert vectors
        upsert_vectors(vectors, namespace="documents")

        # 6. Upsert chapters for this file
        with get_db_context() as db:
            db.query(BookChapter).filter(BookChapter.file_id == file_id).delete(
                synchronize_session=False
            )
            for chapter in chapters:
                db.add(
                    BookChapter(
                        id=f"{file_id}_{chapter['number']}",
                        file_id=file_id,
                        number=int(chapter["number"]),
                        title=str(chapter["title"]),
                        start_page=int(chapter["start_page"]),
                        end_page=int(chapter["end_page"]),
                    )
                )

        # 7. Mark job as COMPLETED and save the result
        with get_db_context() as db:
            job = db.query(Job).filter(Job.id == file_id).first()
            if job:
                job.status = JobStatus.COMPLETED
                job.result = f"Processed {len(chunks)} chunks"

        return {"chunk_count": len(chunks), "chapter_count": len(chapters)}
    except Exception as e:
        # Mark job as FAILED
        set_status(file_id, JobStatus.FAILED, error=str(e))
        raise e