"""Persistence helpers for ingest pipeline output."""

import json

from db import BookChapter, Job, JobStatus, get_db_context

VectorRecord = dict


def build_vectors(
    file_id: str,
    filename: str,
    chunks: list[dict],
    embeddings: list[list[float]],
) -> list[VectorRecord]:
    return [
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


def upsert_chapters(file_id: str, chapters: list[dict[str, int | str]]) -> None:
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


def mark_job_completed(
    file_id: str,
    chunk_count: int,
    chapter_count: int,
    cost_usd: float = 0.0,
) -> None:
    with get_db_context() as db:
        job = db.query(Job).filter(Job.id == file_id).first()
        if job:
            job.status = JobStatus.COMPLETED
            job.result = json.dumps(
                {
                    "chunk_count": int(chunk_count),
                    "chapter_count": int(chapter_count),
                    "cost_usd_total": float(cost_usd),
                }
            )
