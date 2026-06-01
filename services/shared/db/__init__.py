"""
Shared database utilities.

Exports: engine, SessionLocal, get_db, get_db_context,
         init_db, set_status, get_job, Base, Job, JobStatus
"""

import os
import json
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import sessionmaker

from .embedding import (  # noqa: F401 — re-export
    EMBEDDING_DIMENSION,
    embedding_request_kwargs,
    model_native_dimension,
    resolve_embedding_dimension,
)
from .models import (  # noqa: F401 — re-export
    ApiCostEvent,
    Base,
    BookChapter,
    DocumentChunk,
    GeneratedPaper,
    Job,
    JobStatus,
    SearchHistory,
    VivaProctorEvent,
    VivaQuestion,
    VivaResult,
    VivaSession,
    VivaSessionStatus,
    VivaTurn,
)

# ── Engine ───────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "POSTGRES_URL", "postgresql://raguser:ragpass@localhost:5432/ragdb"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Session helpers ──────────────────────────────────────────────────────

def get_db():
    """FastAPI Depends() generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context-manager for non-FastAPI code (scripts, tests)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── DB operations ────────────────────────────────────────────────────────

from sqlalchemy import text


def _serialize_job(job: Job) -> dict:
    result_payload = None
    cost_usd_total = None
    if job.result:
        try:
            result_payload = json.loads(job.result)
            if isinstance(result_payload, dict):
                value = result_payload.get("cost_usd_total")
                if value is not None:
                    cost_usd_total = float(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            result_payload = None
    return {
        "id": str(job.id),
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "filename": job.filename,
        "storage_path": job.storage_path,
        "file_size": job.file_size,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "error_message": job.error_message,
        "result": job.result,
        "result_payload": result_payload,
        "cost_usd_total": cost_usd_total,
    }

def init_db():
    """Create all tables that don't exist yet."""
    # Ensure the pgvector extension is installed before creating vector columns
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    _ensure_search_history_columns()


def _ensure_search_history_columns():
    """Add newly introduced search history columns for existing deployments."""
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE search_history "
                "ADD COLUMN IF NOT EXISTS chat_session_id VARCHAR(128)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE search_history "
                "ADD COLUMN IF NOT EXISTS response_kind VARCHAR(32) NOT NULL DEFAULT 'answer'"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_search_history_session_created_at "
                "ON search_history (chat_session_id, created_at)"
            )
        )
        conn.commit()


def set_status(job_id: str, status: str, error: str | None = None):
    """Update a job's status (and optional error message)."""
    with get_db_context() as db:
        try:
            job = db.query(Job).filter(Job.id == job_id).one()
            job.status = status
            if error:
                job.error_message = error
        except NoResultFound:
            pass


def get_job(job_id: str) -> dict | None:
    """Return a job as a plain dict, or None if not found."""
    with get_db_context() as db:
        try:
            job = db.query(Job).filter(Job.id == job_id).one()
            return _serialize_job(job)
        except NoResultFound:
            return None


def get_all_jobs() -> list[dict]:
    """Return all jobs ordered by created_at descending."""
    with get_db_context() as db:
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
        return [_serialize_job(job) for job in jobs]


def get_book_chapters(file_id: str) -> list[dict]:
    """Return chapter metadata for a file ordered by chapter number."""
    with get_db_context() as db:
        rows = (
            db.query(BookChapter)
            .filter(BookChapter.file_id == file_id)
            .order_by(BookChapter.number.asc())
            .all()
        )
        return [
            {
                "number": row.number,
                "title": row.title,
                "start_page": row.start_page,
                "end_page": row.end_page,
            }
            for row in rows
        ]
