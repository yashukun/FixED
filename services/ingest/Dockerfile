# syntax=docker/dockerfile:1
# Build from the REPO ROOT:  docker build -f services/ingest/Dockerfile .

# ---- builder: install deps into an isolated venv ----
FROM python:3.11-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv && python -m venv /opt/venv
WORKDIR /app
COPY services/ingest/requirements.txt .
RUN uv pip install -r requirements.txt

# ---- runtime: slim image, non-root, app code only ----
FROM python:3.11-slim-bookworm AS runtime
ENV VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app:/app/shared"
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY services/ingest .
COPY services/shared shared
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"
CMD exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}
