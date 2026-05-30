# FixED — Architecture

FixED is a RAG education platform: upload textbooks (PDF/TXT), index them into a
vector store, and answer student questions, generate question papers, and run
proctored oral vivas — all grounded in the uploaded material.

## Services

| Service | Port | Role |
|---|---|---|
| `frontend` | 80 (nginx) | React/Vite SPA **and** the reverse-proxy ingress: serves static, proxies `/api/*` to the backends. |
| `gateway` | 8000 | Dashboard/analytics over Postgres (pooled `psycopg`). |
| `ingest` | 8000 | Upload → object storage → enqueues a Celery job; job status/file APIs. |
| `search` | 8000 | RAG retrieval + LLM answer, incl. SSE streaming; calls `qpaper` for paper generation. |
| `qpaper` | 8000 | Grounded question-paper generation. |
| `viva` | 8000 | Oral viva: question gen, STT/TTS, vision proctoring, scoring. |
| `celery_worker` | — | Runs the ingest pipeline (extract → chunk → embed → upsert). No inbound. |

Shared library (`services/shared`): SQLAlchemy models + engine (`db/`), Alembic
migrations (`db/migrations`), object storage backends (`storage/` — MinIO + S3),
Celery app (`queue/`), cost tracking (`cost.py`), the embedding-dimension
constant (`embedding.py`), and JSON logging + request-ID + CORS (`observability.py`).

## Data backends

- **Postgres + pgvector** — relational data + the `document_chunks.embedding`
  `vector(1536)` column with a cosine **HNSW** index. Local: container; AWS: RDS.
- **Redis** — Celery broker + result backend. Local: container; AWS: ElastiCache (TLS+AUTH).
- **Qdrant** — active vector store (`VECTOR_DB_PROVIDER=qdrant`). Local: container;
  AWS: Qdrant Cloud (default) or self-hosted on ECS+EBS.
- **Object storage** — uploaded files + viva media. Local: MinIO; AWS: S3 (IAM task role).

All embeddings are created with `dimensions=EMBEDDING_DIMENSIONS` (default 1536, a
single shared constant) so the model output, the pgvector column, and the Qdrant
collection always agree.

## Request flow

1. **Upload** (`ingest /upload`): size-capped streaming read + type check → object
   storage → `Job` row → Celery enqueue (all blocking work off the event loop).
2. **Process** (worker): download → extract text → detect chapters → chunk →
   batched embeddings → upsert vectors + chapter rows.
3. **Search** (`search /search[/stream]`): guardrails → intent → embed query →
   hybrid retrieval → grounded LLM answer (SSE streams tokens). Question-paper
   requests are delegated to `qpaper` over the internal network.

## AWS topology (ECS Fargate)

```
app/api domain → ALB (HTTPS, WAF, idle 300s)
                   └─ frontend (nginx ingress, ECS) ──Service Connect──▶ gateway/ingest/search/qpaper/viva (ECS, private)
celery_worker (ECS, private, no inbound)  ── Redis queue
RDS pg16+pgvector (Multi-AZ) · ElastiCache Redis (TLS+AUTH) · S3 · Qdrant (Cloud)
Secrets Manager (OPENAI/DB/Redis/Qdrant) · CloudWatch logs+alarms · ECR
```

- **Only the ALB is public.** All ECS tasks, RDS, Redis and Qdrant live in private
  subnets with no public IPs. `qpaper` and the worker have no ALB target at all.
- **Service Connect** replaces Docker DNS: backends advertise short aliases
  (`gateway:8000`, `qpaper:8000`, …) so the same hostnames resolve locally and on AWS.
- **Schema** is applied by a one-shot migration task (`python -m db.migrate` →
  Alembic), never by services on startup.
- See [infra/README.md](infra/README.md) for the Terraform, and [DEPLOY.md](DEPLOY.md) to deploy.

## Security model

- **TLS everywhere**: ALB HTTPS, RDS `sslmode=require` + `rds.force_ssl`, Redis
  in-transit encryption, S3 TLS-only bucket policy.
- **Secrets** via AWS Secrets Manager, injected into tasks at runtime (never in images).
- Production **fails closed** on insecure default DB/MinIO credentials (`APP_ENV=production`).
- **WAF** (rate limiting + AWS managed rules) on the ALB.

## Known limitations / follow-ups

- **No authentication** (deferred by request). Network isolation + WAF reduce
  exposure, but anyone who can reach the ALB can call the APIs. In particular,
  `viva GET /sessions/{id}/audit` returns biometric face photos + transcripts;
  do not expose `/api/viva/*` publicly until auth lands.
- **Viva DB-transaction scope**: `/proctor/frame` and `/answer` hold a DB
  connection across multi-second LLM calls. Mitigated by a tunable/recyclable
  pool; a transaction-scope refactor (with viva tests) is a tracked follow-up.
- **Worker autoscaling** uses CPU; queue-depth scaling (custom CloudWatch metric)
  is a documented follow-up.
- **Self-hosted Qdrant on Fargate** uses a per-task EBS volume that is not durable
  across task replacement — prefer Qdrant Cloud, or add snapshot-to-S3.
