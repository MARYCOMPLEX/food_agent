# Usage Runbook

## Environment Requirements

- Python >= 3.10, `uv`, Node.js (the XHS signer needs Node).
- LLM credentials: `OPENAI_API_KEY`, `OPENAI_API_BASE`, `DEFAULT_LLM_MODEL`.
- XHS auth: `uv run python -m xhs_food.auth qr` or a valid `XHS_COOKIES`/profile.
- Amap key is needed for POI enrichment (`GAODE_APIKEY` or `AMAP_MAPS_API_KEY`).
- Redis/PostgreSQL are optional fallbacks in code, but required for durable multi-worker behavior.

## Installation

```bash
uv sync --extra dev
cd frontend
npm install
```

Copy `.env.example` to `.env` and fill secrets. The current repository does not include `frontend/tsconfig.json` or a committed `frontend/package-lock.json`, so the frontend CI build is not reproducible as checked in.

## Run

```bash
uv run python -m xhs_food.auth qr
uv run uvicorn src.api.main:app --reload --port 8000
cd frontend && npm run dev
```

The API health endpoint is `GET /health`; Swagger is `/docs`. Search uses `POST /v1/search/` followed by `GET /v1/search/stream/{sessionId}`.

## Verification

`pytest -q` passed 106 tests in the inspected checkout. `npm run build` currently stops before compilation because `tsconfig.json` is missing. A successful production setup also requires checking SSE events, Amap enrichment, and PostgreSQL recovery, none of which are covered by the current integration tests.

## Common Commands

| Task | Command |
|---|---|
| Backend tests | `uv run pytest -q` |
| Backend lint | `uv run ruff check src tests` |
| Type check | `uv run pyright` |
| Frontend lint | `cd frontend && npm run lint` |
| Frontend build | `cd frontend && npm run build` |
| DB turn migration | `uv run python scripts/migrate_turn_id.py` |
