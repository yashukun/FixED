## FixED Monorepo

FixED is a multi-service learning assistant stack with:
- `frontend` (React + Vite)
- `services/gateway` (mock dashboard/learn/upcoming APIs)
- `services/ingest` (upload + processing pipeline)
- `services/search` (retrieval + answer generation)
- `services/qpaper` and `services/viva` (health-only stubs for now)
- shared infra in `services/shared`

All project docs are consolidated in this root `README.md`.

## Prerequisites

- Docker + Docker Compose
- Node.js 20+ (for local frontend checks)
- Python 3.11+ (for local backend checks)
- `OPENAI_API_KEY` in `.env` for embedding/LLM features

## Run the full stack

```bash
docker compose up --build
```

Service ports:
- Gateway: `http://localhost:8000`
- Ingest: `http://localhost:8001`
- Search: `http://localhost:8002`
- QPaper: `http://localhost:8003`
- Viva: `http://localhost:8004`
- Frontend: `http://localhost:3000`

## Local quality checks

Frontend:

```bash
cd frontend
npm install
npm run lint
npm run test
```

Gateway service tests:

```bash
cd services/gateway
python -m unittest -v test_main.py
```

Search service tests:

```bash
cd services/search
python -m unittest -v test_config.py test_text_utils.py test_guardrails.py
```

## API smoke checks

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
```
