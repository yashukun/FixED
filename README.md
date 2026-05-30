# FixED

A multi-service RAG platform for education: upload textbooks (PDF/TXT), index them
into a vector store, and answer student questions, generate question papers, and
run proctored oral vivas — all grounded in the uploaded material.

- **Frontend**: React 19 + Vite SPA, served by nginx (which also reverse-proxies `/api/*`).
- **Backends**: FastAPI services — `gateway`, `ingest`, `search`, `qpaper`, `viva` — plus a Celery worker.
- **Data**: Postgres + pgvector, Redis (Celery), Qdrant (vectors), object storage (MinIO local / S3 on AWS), OpenAI.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and [DEPLOY.md](DEPLOY.md)
for AWS deployment.

## Run locally (Docker Compose)

```bash
cp .env.example .env        # set OPENAI_API_KEY (and Qdrant key if not local)
docker compose up --build
```

Compose starts the data backends, runs the **`migrate`** one-shot (Alembic creates
the schema + pgvector extension + HNSW index), then the services.

- Frontend: <http://localhost:3000>
- Per-service health: `:8000` gateway, `:8001` ingest, `:8002` search, `:8003` qpaper, `:8004` viva
- Through the nginx proxy (same origin): `/api/{gateway,ingest,search,qpaper,viva}/...`

```bash
for p in 8000 8001 8002 8003 8004; do curl -s localhost:$p/health; echo; done
```

The `bruno/` directory has example API requests.

## Configuration

All config is environment-driven; copy `.env.example` to `.env`. Key variables:
`OPENAI_API_KEY`, `VECTOR_DB_PROVIDER` (`qdrant`), `STORAGE_PROVIDER`
(`minio` local / `s3` on AWS), `EMBEDDING_DIMENSIONS` (default 1536), the DB pool /
`PGSSLMODE` / Celery / logging knobs, and `CORS_ALLOW_ORIGINS`. In production set
`APP_ENV=production` (the app then refuses insecure default credentials).

## Database migrations

Schema is owned by **Alembic** (`services/shared/db/migrations`), applied by a
one-shot job — never by services at startup.

```bash
# apply locally (compose runs this for you):
docker compose run --rm migrate
# create a new revision after changing models:
cd services/shared/db && POSTGRES_URL=postgresql://raguser:ragpass@localhost:5432/ragdb \
  alembic -c alembic.ini revision --autogenerate -m "describe change"
```

## Quality checks

```bash
# Frontend
cd frontend && npm ci && npm run lint && npm run test && npm run build

# Backend (per service) — shared package must be importable
PYTHONPATH=services/<svc>:services/shared python -m unittest discover -s services/<svc> -p 'test_*.py'

# Infrastructure
cd infra && tofu fmt -check -recursive && tofu init -backend=false && tofu validate
```

CI (`.github/workflows/ci.yml`) runs all of the above on every PR.

## Layout

```
frontend/                 React SPA + nginx ingress (default.conf.template)
services/{gateway,ingest,search,qpaper,viva}/   FastAPI services
services/shared/          db (+ Alembic), storage (MinIO/S3), queue, cost, embedding, observability
infra/                    Terraform (AWS ECS Fargate) — see infra/README.md
.github/workflows/        CI + deploy (OIDC, build → ECR → migrate → deploy)
scripts/                  CI helpers (migration run-task, smoke test)
docker-compose.yml        local dev stack
```
