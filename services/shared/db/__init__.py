"""
Shared database utilities.

Exports: engine, SessionLocal, get_db, get_db_context,
         init_db, set_status, get_job, Base, Job, JobStatus
"""

import logging
import os
import json
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

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

APP_ENV = os.getenv("APP_ENV", "development").lower()
_INSECURE_DB_DEFAULT = "postgresql://raguser:ragpass@localhost:5432/ragdb"
DATABASE_URL = os.getenv("POSTGRES_URL", _INSECURE_DB_DEFAULT)

# Fail closed: never run in production against the insecure local default.
if APP_ENV in {"production", "prod"} and "raguser:ragpass" in DATABASE_URL:
    raise RuntimeError(
        "POSTGRES_URL must be set to a real database in production "
        "(refusing the insecure local default)."
    )

# Pool + connection tuning — env-overridable for RDS / managed Postgres.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
# Recycle connections before RDS / proxy idle timeouts drop them out from under us.
_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))
_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
# "prefer" works locally (no TLS) and with RDS; set "require"/"verify-full" in prod.
_SSLMODE = os.getenv("PGSSLMODE", "prefer")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    pool_recycle=_POOL_RECYCLE,
    connect_args={"sslmode": _SSLMODE, "connect_timeout": _CONNECT_TIMEOUT},
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
    """Verify database connectivity at startup (no DDL).

    Schema is owned by Alembic migrations under ``services/shared/db/migrations``
    and applied out-of-band by a one-shot migration job — NOT by the application
    on boot (running ``create_all`` / ``CREATE EXTENSION`` from every service on
    every start races on a shared RDS instance and needs elevated privileges).
    This performs only a lightweight, non-fatal connectivity probe so a
    misconfigured database surfaces early in logs without crash-looping the task.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connectivity OK (schema managed by Alembic).")
    except Exception as exc:  # pragma: no cover — best-effort startup probe
        logger.warning("Database connectivity check failed at startup: %s", exc)


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
