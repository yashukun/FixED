import logging
import traceback

from db import get_job, set_status, JobStatus
from storage import get_storage_backend
from config import settings

from shared.queue.celery_app import celery_app
from embedder import process_and_store

logger = logging.getLogger(__name__)

storage = get_storage_backend(
    provider=settings.STORAGE_PROVIDER,
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    bucket=settings.STORAGE_BUCKET,
    secure=settings.MINIO_SECURE,
)

@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, job_id: str):
    """
    Celery task to run the document embedding process in the background.
    """
    logger.info(f"Starting processing for job {job_id}")
    
    # 1. Fetch job from Postgres
    job = get_job(job_id)
    if not job:
        logger.error(f"Job {job_id} not found in database.")
        # Cannot process without a job record
        return
        
    try:
        # 2. Extract key from storage_path (removing the bucket prefix if minio)
        # e.g., "documents/123-456/test.pdf" -> "123-456/test.pdf"
        storage_path = job["storage_path"]
        bucket_prefix = f"{settings.STORAGE_BUCKET}/"
        key = storage_path.split(bucket_prefix, 1)[-1] if bucket_prefix in storage_path else storage_path

        # 3. Download raw bytes from storage
        file_bytes = storage.download(key)
        
        # 4. Process and store (this function handles DB status to PROCESSING and COMPLETED)
        process_and_store(
            file_bytes=file_bytes,
            filename=job["filename"],
            file_id=job_id,
        )
        
        logger.info(f"Successfully processed job {job_id}")
        
    except Exception as exc:
        logger.error(f"Failed to process job {job_id}: {exc}")
        logger.error("Processing traceback for job %s:\n%s", job_id, traceback.format_exc())
        # Note: process_and_store already marks as FAILED if an error happens during embedding,
        # but if download fails, we catch it here and mark it FAILED.
        set_status(job_id, JobStatus.FAILED, error=str(exc))
        
        # Retry logic for transient errors (e.g. Minio/Network blip)
        raise self.retry(exc=exc, countdown=30)
