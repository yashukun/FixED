from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from fastapi import FastAPI
from pydantic import BaseModel

from observability import install_observability

logger = logging.getLogger(__name__)


def _postgres_url() -> str:
    url = os.getenv("POSTGRES_URL", "postgresql://raguser:ragpass@localhost:5432/ragdb")
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"} and "raguser:ragpass" in url:
        raise RuntimeError(
            "POSTGRES_URL must be set to a real database in production "
            "(refusing the insecure local default)."
        )
    return url


# Module-level connection pool — opened once, reused across requests, instead of
# a fresh TCP connect per query (which would exhaust RDS max_connections as the
# gateway scales out).
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_postgres_url(),
            min_size=int(os.getenv("GATEWAY_DB_POOL_MIN", "1")),
            max_size=int(os.getenv("GATEWAY_DB_POOL_MAX", "10")),
            max_idle=float(os.getenv("GATEWAY_DB_POOL_MAX_IDLE", "300")),
            timeout=float(os.getenv("GATEWAY_DB_POOL_TIMEOUT", "10")),
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        _get_pool()  # warm the pool at startup
    except Exception:
        logger.exception("Gateway connection pool failed to open at startup")
    yield
    if _pool is not None:
        _pool.close()


app = FastAPI(lifespan=lifespan)
install_observability(app, "gateway")


def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    try:
        with _get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception:
        logger.exception("Gateway query failed")
        return []


def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict:
    try:
        with _get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else {}
    except Exception:
        logger.exception("Gateway query failed")
        return {}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _human_when(dt: datetime | None) -> str:
    if not dt:
        return "Unknown"
    local_dt = dt.replace(tzinfo=timezone.utc).astimezone()
    return local_dt.strftime("%a, %I:%M %p")


class Metric(BaseModel):
    label: str
    value: int


class FocusItem(BaseModel):
    title: str
    time: str
    type: str


class DashboardOverviewResponse(BaseModel):
    source: str
    metrics: list[Metric]
    todayFocus: list[FocusItem]


class BookItem(BaseModel):
    id: str
    title: str
    subject: str
    status: str
    lastOpened: str


class LearnBooksResponse(BaseModel):
    source: str
    books: list[BookItem]


class SubjectItem(BaseModel):
    id: str
    name: str
    teacher: str
    pendingAssignments: int
    progress: int


class LearnSubjectsResponse(BaseModel):
    source: str
    subjects: list[SubjectItem]


class UpcomingEvent(BaseModel):
    id: str
    title: str
    when: str
    subject: str
    kind: str


class UpcomingEventsResponse(BaseModel):
    source: str
    events: list[UpcomingEvent]


class DashboardNavResponse(BaseModel):
    source: str
    student: dict
    sections: list[dict]


class UsageVolume(BaseModel):
    searches: int
    generated_papers: int
    uploads: int
    viva_sessions: int


class AnalyticsSummaryResponse(BaseModel):
    source: str
    total_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    usage_volume: UsageVolume


class TimeseriesPoint(BaseModel):
    bucket: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    requests: int


class AnalyticsTimeseriesResponse(BaseModel):
    source: str
    points: list[TimeseriesPoint]


class BreakdownItem(BaseModel):
    key: str
    cost_usd: float
    total_tokens: int
    requests: int


class AnalyticsBreakdownResponse(BaseModel):
    source: str
    by_service: list[BreakdownItem]
    by_model: list[BreakdownItem]
    by_kind: list[BreakdownItem]


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.get("/dashboard/nav", response_model=DashboardNavResponse)
def dashboard_nav():
    counts = _fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM jobs) AS uploads,
          (SELECT COUNT(*) FROM generated_papers) AS papers,
          (SELECT COUNT(*) FROM viva_sessions) AS viva_sessions
        """
    )
    return {
        "source": "live",
        "student": {
            "id": "global",
            "name": "Global Workspace",
            "grade": "All Features",
        },
        "sections": [
            {"name": "Dashboard", "path": "/", "count": _to_int(counts.get("uploads"))},
            {"name": "Learn / Books", "path": "/learn/books", "count": _to_int(counts.get("uploads"))},
            {"name": "Learn / Subjects", "path": "/learn/subjects", "count": _to_int(counts.get("papers"))},
            {"name": "Upcoming", "path": "/upcoming", "count": _to_int(counts.get("viva_sessions"))},
        ],
    }


@app.get("/dashboard/overview", response_model=DashboardOverviewResponse)
def dashboard_overview():
    counts = _fetch_one(
        """
        SELECT
          (SELECT COUNT(DISTINCT COALESCE(file_id, 'na')) FROM search_history) AS assigned_subjects,
          (SELECT COUNT(*) FROM jobs) AS active_books,
          (SELECT COUNT(*) FROM jobs WHERE status IN ('PENDING', 'PROCESSING')) AS pending_assignments,
          (SELECT COUNT(*) FROM generated_papers WHERE created_at >= NOW() - INTERVAL '7 days') AS tests_this_week
        """
    )
    focus_rows = _fetch_all(
        """
        SELECT title, event_time, kind FROM (
          SELECT topic AS title, created_at AS event_time, 'test' AS kind
          FROM generated_papers
          UNION ALL
          SELECT topic AS title, created_at AS event_time, 'viva' AS kind
          FROM viva_sessions
        ) AS feed
        ORDER BY event_time DESC
        LIMIT 3
        """
    )
    today_focus = [
        {"title": row.get("title") or "Activity", "time": _human_when(row.get("event_time")), "type": row.get("kind") or "study"}
        for row in focus_rows
    ]
    if not today_focus:
        today_focus = [{"title": "No recent activity yet", "time": "Add your first upload", "type": "study"}]
    return {
        "source": "live",
        "metrics": [
            {"label": "Assigned Subjects", "value": _to_int(counts.get("assigned_subjects"))},
            {"label": "Active Books", "value": _to_int(counts.get("active_books"))},
            {"label": "Pending Assignments", "value": _to_int(counts.get("pending_assignments"))},
            {"label": "Tests This Week", "value": _to_int(counts.get("tests_this_week"))},
        ],
        "todayFocus": today_focus,
    }


@app.get("/learn/books", response_model=LearnBooksResponse)
def learn_books():
    rows = _fetch_all(
        """
        SELECT id::text AS id, filename, status, updated_at
        FROM jobs
        ORDER BY updated_at DESC
        LIMIT 30
        """
    )
    books: list[dict] = []
    for row in rows:
        books.append({
            "id": row.get("id", ""),
            "title": row.get("filename") or "Untitled Upload",
            "subject": "General",
            "status": str(row.get("status") or "unknown"),
            "lastOpened": (row.get("updated_at") or datetime.utcnow()).strftime("%Y-%m-%d"),
        })
    return {"source": "live", "books": books[:20]}


@app.get("/learn/subjects", response_model=LearnSubjectsResponse)
def learn_subjects():
    rows = _fetch_all(
        """
        SELECT
          LOWER(SPLIT_PART(COALESCE(filename, 'general'), '.', 1)) AS subject_key,
          COUNT(*) AS total_items,
          SUM(CASE WHEN status IN ('pending', 'processing') THEN 1 ELSE 0 END) AS pending_items,
          AVG(CASE WHEN status = 'completed' THEN 100 ELSE 45 END) AS progress_score
        FROM jobs
        GROUP BY 1
        ORDER BY total_items DESC
        LIMIT 6
        """
    )
    subjects = [
        {
            "id": f"sub-{idx + 1}",
            "name": (row.get("subject_key") or "general").replace("_", " ").title(),
            "teacher": "System",
            "pendingAssignments": _to_int(row.get("pending_items")),
            "progress": _to_int(round(_to_float(row.get("progress_score")))),
        }
        for idx, row in enumerate(rows)
    ]
    return {
        "source": "live",
        "subjects": subjects,
    }


@app.get("/upcoming/events", response_model=UpcomingEventsResponse)
def upcoming_events():
    rows = _fetch_all(
        """
        SELECT id, title, when_value, subject, kind FROM (
          SELECT
            ('paper-' || id::text) AS id,
            topic AS title,
            created_at AS when_value,
            COALESCE(file_id, 'General') AS subject,
            'test' AS kind
          FROM generated_papers
          UNION ALL
          SELECT
            ('viva-' || id::text) AS id,
            topic AS title,
            created_at AS when_value,
            COALESCE(file_id, 'General') AS subject,
            'viva' AS kind
          FROM viva_sessions
        ) events
        ORDER BY when_value DESC
        LIMIT 10
        """
    )
    return {
        "source": "live",
        "events": [
            {
                "id": row.get("id"),
                "title": row.get("title") or "Untitled Event",
                "when": _human_when(row.get("when_value")),
                "subject": row.get("subject") or "General",
                "kind": row.get("kind") or "test",
            }
            for row in rows
        ],
    }


@app.get("/dashboard/analytics/summary", response_model=AnalyticsSummaryResponse)
def dashboard_analytics_summary():
    totals = _fetch_one(
        """
        SELECT
          COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
          COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
          COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
          COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM api_cost_events
        """
    )
    usage = _fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM search_history) AS searches,
          (SELECT COUNT(*) FROM generated_papers) AS generated_papers,
          (SELECT COUNT(*) FROM jobs) AS uploads,
          (SELECT COUNT(*) FROM viva_sessions) AS viva_sessions
        """
    )
    return {
        "source": "live",
        "total_cost_usd": _to_float(totals.get("total_cost_usd")),
        "total_prompt_tokens": _to_int(totals.get("total_prompt_tokens")),
        "total_completion_tokens": _to_int(totals.get("total_completion_tokens")),
        "total_tokens": _to_int(totals.get("total_tokens")),
        "usage_volume": {
            "searches": _to_int(usage.get("searches")),
            "generated_papers": _to_int(usage.get("generated_papers")),
            "uploads": _to_int(usage.get("uploads")),
            "viva_sessions": _to_int(usage.get("viva_sessions")),
        },
    }


@app.get("/dashboard/analytics/timeseries", response_model=AnalyticsTimeseriesResponse)
def dashboard_analytics_timeseries():
    rows = _fetch_all(
        """
        SELECT
          DATE_TRUNC('day', created_at) AS bucket,
          COALESCE(SUM(cost_usd), 0) AS cost_usd,
          COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
          COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COUNT(*) AS requests
        FROM api_cost_events
        WHERE created_at >= NOW() - INTERVAL '14 days'
        GROUP BY 1
        ORDER BY 1 ASC
        """
    )
    return {
        "source": "live",
        "points": [
            {
                "bucket": (row.get("bucket") or datetime.utcnow()).strftime("%Y-%m-%d"),
                "cost_usd": _to_float(row.get("cost_usd")),
                "prompt_tokens": _to_int(row.get("prompt_tokens")),
                "completion_tokens": _to_int(row.get("completion_tokens")),
                "total_tokens": _to_int(row.get("total_tokens")),
                "requests": _to_int(row.get("requests")),
            }
            for row in rows
        ],
    }


def _breakdown(sql: str) -> list[dict]:
    rows = _fetch_all(sql)
    return [
        {
            "key": str(row.get("key") or "unknown"),
            "cost_usd": _to_float(row.get("cost_usd")),
            "total_tokens": _to_int(row.get("total_tokens")),
            "requests": _to_int(row.get("requests")),
        }
        for row in rows
    ]


@app.get("/dashboard/analytics/breakdown", response_model=AnalyticsBreakdownResponse)
def dashboard_analytics_breakdown():
    by_service = _breakdown(
        """
        SELECT
          service AS key,
          COALESCE(SUM(cost_usd), 0) AS cost_usd,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COUNT(*) AS requests
        FROM api_cost_events
        GROUP BY service
        ORDER BY cost_usd DESC, requests DESC
        LIMIT 10
        """
    )
    by_model = _breakdown(
        """
        SELECT
          model AS key,
          COALESCE(SUM(cost_usd), 0) AS cost_usd,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COUNT(*) AS requests
        FROM api_cost_events
        GROUP BY model
        ORDER BY cost_usd DESC, requests DESC
        LIMIT 10
        """
    )
    by_kind = _breakdown(
        """
        SELECT
          kind AS key,
          COALESCE(SUM(cost_usd), 0) AS cost_usd,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COUNT(*) AS requests
        FROM api_cost_events
        GROUP BY kind
        ORDER BY cost_usd DESC, requests DESC
        LIMIT 10
        """
    )
    return {"source": "live", "by_service": by_service, "by_model": by_model, "by_kind": by_kind}
