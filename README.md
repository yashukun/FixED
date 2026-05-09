## FixED Monorepo

FixED is a multi-service stack for uploading textbooks (PDFs), indexing them into a vector store, and answering student questions with retrieval-augmented generation (RAG). The UI is a React SPA; backends are FastAPI services with PostgreSQL, Redis, Celery, object storage, and either **pgvector** (Postgres) or **Qdrant** for vectors.

All project documentation for this repository lives in this root `README.md`.

---

## Architecture

**Request path (high level)**

1. **Upload** — The ingest API stores the file in MinIO (or another configured backend), creates a job row in Postgres, and enqueues a Celery task.
2. **Processing** — The worker downloads bytes, extracts text, detects chapters (PDF outline first; optional LLM pass if the outline is thin), chunks text, calls OpenAI embeddings, and upserts vectors plus chapter metadata.
3. **Search** — The search API applies lightweight guardrails, classifies intent (LLM with heuristic fallback), embeds the query, retrieves hybrid-ranked chunks, then generates an answer with an OpenAI chat model using only retrieved context.

**Services**

| Path | Port | Role |
|------|------|------|
| `frontend/` | 3000 | React + Vite (production build served by nginx; proxies `/api/*` to backends) |
| `services/gateway/` | 8000 | Mock dashboard, learn, and upcoming APIs for the UI shell |
| `services/ingest/` | 8001 | Upload, job status, triggers Celery processing |
| `services/search/` | 8002 | `/search`, `/search/stream` (SSE), retrieval + answer generation |
| `services/qpaper/` | 8003 | Health-only stub |
| `services/viva/` | 8004 | Health-only stub |
| `services/shared/` | — | Database models, cost recording, queue helpers, storage backends |

**Infrastructure (Docker Compose)**

- **postgres** — `pgvector/pgvector:pg17`; relational data, pgvector column for chunks when `VECTOR_DB_PROVIDER=pgvector`.
- **redis** — Celery broker.
- **qdrant** — Optional external vector database when `VECTOR_DB_PROVIDER=qdrant`.
- **minio** — Object storage for uploaded PDFs.

The frontend nginx config forwards `/api/gateway/`, `/api/ingest/`, and `/api/search/` to the corresponding containers (`frontend/nginx.conf`).

---

## Prerequisites

- Docker and Docker Compose
- Node.js 20+ (local frontend lint/test)
- Python 3.11+ (local backend unit tests)
- An OpenAI API key for embeddings and chat unless you only exercise health endpoints

---

## Configuration

Create a `.env` file at the repo root (Compose loads it for services). There is no committed `.env.example`; set variables according to your deployment.

**Required for full RAG behavior**

- `OPENAI_API_KEY` — Used by ingest (embeddings, optional chapter detection) and search (embeddings, intent classification, final answer).

**Vector store**

- `VECTOR_DB_PROVIDER` — `pgvector` (default) or `qdrant`. Ingest and search must agree.
- For Qdrant: `QDRANT_URL`, optional `QDRANT_API_KEY`, `QDRANT_COLLECTION`.

**Embedding and chat models (override defaults as needed)**

- Search: `SEARCH_EMBED_MODEL` (default `text-embedding-3-large`), `SEARCH_CHAT_MODEL` / `SEARCH_INTENT_MODEL` (default `gpt-4o-mini`).
- Ingest: `INGEST_EMBED_MODEL`, `INGEST_CHAPTER_MODEL`, chunk sizes via `INGEST_CHUNK_SIZE`, `INGEST_CHUNK_OVERLAP`.

**Important:** Postgres `document_chunks.embedding` and the Qdrant collection are built for **1536-dimensional** vectors. If you use an embedding model whose default output size is not 1536 (for example, `text-embedding-3-large` defaults to a larger size in the OpenAI API), you must either choose a 1536-default model such as `text-embedding-3-small`, or ensure your application passes a matching `dimensions` parameter everywhere embeddings are created. **Misaligned dimensions will break ingestion or search.**

---

## Run the full stack

```bash
docker compose up --build
```

**URLs**

- Frontend: `http://localhost:3000`
- Gateway: `http://localhost:8000`
- Ingest: `http://localhost:8001`
- Search: `http://localhost:8002`
- QPaper / Viva: `8003` / `8004` (health checks only)

Through the frontend nginx proxy (same origin): `/api/gateway/`, `/api/ingest/`, `/api/search/`.

---

## API smoke checks

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
```

The `bruno/` directory contains Bruno requests for ingest and search (e.g. upload, job status, search).

---

## Local quality checks

**Frontend**

```bash
cd frontend
npm install
npm run lint
npm run test
```

**Gateway**

```bash
cd services/gateway
python -m unittest -v test_main.py
```

**Search**

```bash
cd services/search
python -m unittest -v test_config.py test_text_utils.py test_guardrails.py
```

**Ingest**

```bash
cd services/ingest
python -m unittest -v test_pipeline_config.py
```

---

## What works well

- **End-to-end upload pipeline** — HTTP upload, durable job record, background worker, text extraction, recursive chunking, batched OpenAI embeddings, upsert into pgvector or Qdrant, chapter rows in Postgres when detection succeeds.
- **Search/RAG** — Hybrid-style retrieval (vector plus lexical helpers), scoped retrieval (whole book / chapter / page when metadata and routing allow), teacher-style system prompts, non-streaming and **SSE streaming** answers, search history and **per-request cost breakdown** (`ApiCostEvent`).
- **Resilience shortcuts** — Deterministic **guardrails** answer simple greetings and arithmetic without touching the book stack; **heuristic intent** runs when the API key is missing or the intent LLM returns unusable JSON.
- **Operational toggles** — Same codebase can target pgvector or Qdrant; nginx buffering disabled for streaming search.
- **UI shell** — Dashboard, learn, and assistant flows against the gateway mock plus real ingest/search for the document assistant.

---

## Limitations and known gaps

- **Gateway data is mock** — Responses are labeled `source: "mock"` (static dashboard metrics, book lists, subjects, upcoming events). They are not synced to Postgres or real LMS data.
- **QPaper and Viva** — Only `/health`; no question-paper or viva logic yet.
- **OpenAI dependency** — Without a valid key, ingest cannot embed documents; search cannot retrieve with embeddings or synthesize answers (guardrail-only queries still behave deterministically).
- **Intent classification** — JSON parsed from the model with regex; malformed output silently falls back to keyword heuristics, which can mis-route ambiguous queries.
- **Chapter detection** — Strong when the PDF has a usable outline; the LLM fallback depends on sampled pages and may yield a single synthetic **“Full Document”** chapter when detection fails.
- **Final answer failures** — Chat completion errors surface a generic apology to the user while retrieval may still have succeeded (check logs).
- **Retrieval failures** — Exceptions during embedding or DB/Qdrant access return HTTP 500 from search rather than a soft degradation.
- **Pinecone** — Code paths exist in `vector_store.py` for future use but are not the default Compose path; they require separate credentials and setup.
- **Celery retries** — Failed jobs may retry; persistent infrastructure or API errors still mark jobs failed after exhaustion.

---

## Repository layout (concise)

| Area | Contents |
|------|-----------|
| `frontend/src` | Pages (dashboard, learn, assistant), API client (`services/api.js`), PDF viewer, cost context |
| `services/ingest` | FastAPI app, Celery task, `embedder.py`, `vector_store.py`, `store_helpers.py` |
| `services/search` | FastAPI app, guardrails, prompting, Qdrant/pgvector retrieval |
| `services/shared` | SQLAlchemy models (`db/models.py`), cost helpers, MinIO/S3-style storage |
