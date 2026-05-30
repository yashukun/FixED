"""
Ingest Service — upload documents to storage and track jobs in PostgreSQL.
"""

import os
import uuid
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, status, Response, Request
from starlette.concurrency import run_in_threadpool

from config import settings
from db import (
    init_db,
    get_job,
    get_all_jobs,
    get_book_chapters,
    get_db_context,
    Job,
    JobStatus,
)
from storage import get_storage_backend
from observability import install_observability


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FixED — Ingest Service", lifespan=lifespan)
install_observability(app, "ingest")

# ── Storage backend (provider-agnostic) ──────────────────────────────────

storage = get_storage_backend(
    provider=settings.STORAGE_PROVIDER,
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    bucket=settings.STORAGE_BUCKET,
    secure=settings.MINIO_SECURE,
)


from tasks import process_document_task

# Accepted upload types (the processing pipeline only handles PDF and plain text).
ALLOWED_EXTENSIONS = {".pdf", ".txt"}
_READ_CHUNK = 1024 * 1024  # 1 MB


def _extract_storage_key(storage_path: str) -> str:
    bucket_prefix = f"{settings.STORAGE_BUCKET}/"
    return storage_path.split(bucket_prefix, 1)[-1] if bucket_prefix in storage_path else storage_path


def _store_and_enqueue(
    *, content: bytes, filename: str, storage_key: str, content_type: str,
    file_size: int, job_id: uuid.UUID,
) -> None:
    """Blocking work (object-storage upload, DB insert, Celery enqueue) — run in a
    threadpool so it never blocks the event loop during a large upload."""
    storage_path = storage.upload(data=content, key=storage_key, content_type=content_type)
    with get_db_context() as db:
        db.add(Job(
            id=job_id,
            filename=filename,
            storage_path=storage_path,
            file_size=file_size,
            status=JobStatus.PENDING,
        ))
    process_document_task.delay(str(job_id))

# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "ingest"}


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    """Upload a document → store in object storage → create a pending job."""

    max_size = settings.MAX_FILE_SIZE
    max_mb = max_size // (1024 * 1024)

    # Reject early using Content-Length when the client provides it, so we never
    # start buffering an oversized upload.
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_size:
                raise HTTPException(status_code=413, detail=f"File too large. Max {max_mb}MB.")
        except ValueError:
            pass

    # Validate the file type at the boundary (the pipeline only handles PDF/TXT).
    filename = file.filename or "unknown.bin"
    if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Only PDF and TXT files are accepted.",
        )

    # Stream the body in chunks with a hard cap so a spoofed/absent Content-Length
    # can't exhaust memory.
    chunks: list[bytes] = []
    file_size = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        file_size += len(chunk)
        if file_size > max_size:
            raise HTTPException(status_code=413, detail=f"File too large. Max {max_mb}MB.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    job_id = uuid.uuid4()
    storage_key = f"{job_id}/{filename}"

    # Offload blocking storage/DB/queue work so the event loop stays free.
    await run_in_threadpool(
        _store_and_enqueue,
        content=content,
        filename=filename,
        storage_key=storage_key,
        content_type=file.content_type or "application/octet-stream",
        file_size=file_size,
        job_id=job_id,
    )

    return {"job_id": str(job_id), "status": "pending"}


@app.get("/job/{job_id}")
def job_status(job_id: str):
    """Poll the processing status of a previously uploaded document."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs")
def list_jobs():
    """Retrieve all previously uploaded documents."""
    return get_all_jobs()


@app.get("/job/{job_id}/chapters")
def job_chapters(job_id: str):
    """Return detected chapters for a processed file."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return get_book_chapters(job_id)


@app.get("/job/{job_id}/file")
def job_file(job_id: str):
    """Return the original uploaded file for viewer rendering."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    storage_key = _extract_storage_key(job["storage_path"])
    try:
        file_bytes = storage.download(storage_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to fetch file: {exc}") from exc

    media_type = mimetypes.guess_type(job["filename"])[0] or "application/octet-stream"
    headers = {"Content-Disposition": f'inline; filename="{job["filename"]}"'}
    return Response(content=file_bytes, media_type=media_type, headers=headers)
