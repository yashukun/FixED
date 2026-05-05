"""
Ingest Service — upload documents to storage and track jobs in PostgreSQL.
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException

from config import settings
from db import init_db, get_job, get_db_context, Job, JobStatus
from storage import get_storage_backend


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FixED — Ingest Service", lifespan=lifespan)

# ── Storage backend (provider-agnostic) ──────────────────────────────────

storage = get_storage_backend(
    provider=settings.STORAGE_PROVIDER,
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    bucket=settings.STORAGE_BUCKET,
    secure=settings.MINIO_SECURE,
)


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "ingest"}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Upload a document → store in object storage → create a pending job."""

    # Read file
    content = await file.read()
    file_size = len(content)

    # Validate
    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.MAX_FILE_SIZE // (1024*1024)}MB.",
        )

    # Generate job id & storage key
    job_id = uuid.uuid4()
    storage_key = f"{job_id}/{file.filename}"

    # Upload to storage
    storage_path = storage.upload(
        data=content,
        key=storage_key,
        content_type=file.content_type or "application/octet-stream",
    )

    # Persist job record
    with get_db_context() as db:
        job = Job(
            id=job_id,
            filename=file.filename,
            storage_path=storage_path,
            file_size=file_size,
            status=JobStatus.PENDING,
        )
        db.add(job)

    return {"job_id": str(job_id), "status": "pending"}


@app.get("/job/{job_id}")
def job_status(job_id: str):
    """Poll the processing status of a previously uploaded document."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
