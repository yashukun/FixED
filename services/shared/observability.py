"""Shared observability + CORS wiring for all FixED FastAPI services.

One entrypoint, ``install_observability(app, service_name)``, configures:
  * structured JSON logging (CloudWatch-friendly; set LOG_FORMAT=text for local),
  * a request-ID middleware (honours/echoes ``X-Request-ID`` and threads it into
    logs via a contextvar, so a request can be traced across services),
  * CORS with an env-driven allowlist (``CORS_ALLOW_ORIGINS``, comma-separated).

Logging level (LOG_LEVEL) and format (LOG_FORMAT) are env-controlled.
"""

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Holds the current request's correlation id for the duration of a request.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SERVICE_NAME = ""


def get_request_id() -> str:
    """Current request's correlation id (for propagating to downstream calls)."""
    return request_id_ctx.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        if _SERVICE_NAME:
            payload["service"] = _SERVICE_NAME
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service_name: str) -> None:
    global _SERVICE_NAME
    _SERVICE_NAME = service_name

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route server/worker loggers through the same handler (no double logging).
    for name in (
        "uvicorn", "uvicorn.error", "uvicorn.access",
        "gunicorn.error", "gunicorn.access", "celery",
    ):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
        lg.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


def install_observability(app, service_name: str) -> None:
    """Configure logging and attach request-ID + CORS middleware to ``app``."""
    configure_logging(service_name)
    app.add_middleware(RequestIdMiddleware)

    origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
