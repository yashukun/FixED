"""
Shared database utilities.

Exports: engine, SessionLocal, get_db, get_db_context,
         init_db, set_status, get_job, Base, Job, JobStatus
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import sessionmaker

from .models import Base, Job, JobStatus, DocumentChunk, BookChapter  # noqa: F401 — re-export

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

from sqlalchemy import create_engine, text

def init_db():
    """Create all tables that don't exist yet."""
    # Ensure the pgvector extension is installed before creating vector columns
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        
    Base.metadata.create_all(bind=engine)


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
            }
        except NoResultFound:
            return None


def get_all_jobs() -> list[dict]:
    """Return all jobs ordered by created_at descending."""
    with get_db_context() as db:
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
        return [
            {
                "id": str(job.id),
                "status": job.status.value if hasattr(job.status, "value") else job.status,
                "filename": job.filename,
                "storage_path": job.storage_path,
                "file_size": job.file_size,
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
                "error_message": job.error_message,
                "result": job.result,
            }
            for job in jobs
        ]


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
