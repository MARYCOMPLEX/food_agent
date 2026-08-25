# 14.x Release Gate Record

Status: **Partial qualification**. The blocking Python 3.12 contract suite and
the local architecture/failure gates pass on Windows 11. Cross-platform,
browser, and target-stack deployment observations are recorded as gaps rather
than inferred from local fixtures.

Recorded: 2026-08-25

## Environment

| Dimension | Blocking baseline | Observed result |
|---|---|---|
| Host | Ubuntu LTS x86_64 and Windows x86_64 | Windows 11 x86_64 plus Ubuntu 24.04 x86_64 container; hosted Ubuntu runner unavailable |
| Python | CPython 3.12.x | `3.12.0`, frozen lockfile |
| Probe Python | CPython 3.13 | `3.13.11` installed; rejected by the project `>=3.12,<3.13` constraint as expected |
| Browser | Chromium desktop/mobile | Chromium, Firefox, and WebKit local matrix passed at `1280x900` and `390x844` |
| Services | PostgreSQL 16 + pgvector/pg_trgm, Redis 7, Temporal, S3/MinIO | Release Compose stack ran locally; provider fake remains a contract fixture |
| Time/locale | UTF-8, UTC, Asia/Shanghai | Contract fixtures and fixed-clock tests pass |

## Gate Results

| Task | Result | Evidence and limitation |
|---|---|---|
| 14.1 Python 3.12 blocking gate | **PASS (Windows + Ubuntu 24.04 container)** | Windows `uv sync --frozen --extra dev`, `uv lock --check`, and backend CI mirror pass. An Ubuntu `24.04` LTS container using CPython `3.12.3` ran the frozen backend gate with the Compose PostgreSQL/Redis services: `961 passed, 24 deselected, 2 warnings in 255.25s`; a separate read-only Ubuntu lock check also passed. The hosted Ubuntu runner itself remains an environment probe, not a claim about GitHub runner parity. |
| 14.2 OS/Python probes | **PARTIAL** | CPython 3.13 probe is intentionally outside the support range; macOS/arm64 is unavailable. Neither result expands production support. |
| 14.3 target service contract suite | **PASS (local complete stack)** | The release Compose stack is healthy with PostgreSQL `16.14` + `pg_trgm 1.6`/`vector 0.8.2`, Redis `7.4.9`, Temporal `1.28.2`, and MinIO. An isolated CPython `3.12.12` runner joined that network; live B2 PostgreSQL/pgvector/pg_trgm qualification passed (`1 passed in 15.34s`) and the CI backend command passed (`961 passed, 24 deselected, 2 warnings in 242.58s`). A real `Boto3ObjectStore` put/get/stat/signed-URL/delete smoke against MinIO also passed. Target CI and production provider deployment remain separate closure gaps. |
| 14.4 browser matrix | **PASS (local mock-API matrix)** | `uv run --frozen python scripts/qualification_frontend_browser_matrix.py` passed search, first-503 SSE reconnect, favorites, history, and profile FAQ for Chromium, Firefox, and WebKit at desktop `1280x900` and mobile `390x844` (six browser/viewport runs). The API/provider boundary is mocked; production browser/deployment traffic remains a separate probe. |
| 14.5 encoding/time/freshness | **PASS (local)** | Canonical Query fixture includes UTF-8 Chinese and `Asia/Shanghai`; evidence timestamps normalize to UTC; freshness and connector tests use injected fixed clocks. |
| 14.6 non-root image/Compose smoke | **PASS (local)** | `docker build --file Dockerfile.release --tag xhs-food-agent:release-gate .` succeeded. `docker compose -f docker-compose.release.yml up -d --wait --no-build` brought PostgreSQL 16/pgvector, Redis 7, Temporal 1.28.2, MinIO, migration, and app healthy; migration exited 0, app `/health` returned `{"status":"ok","service":"xhs-food-agent","version":"1.0.0"}`, `id` reported UID/GID 1001, and `alembic_version` was `20260824_0007_b3_personalization_memory` with the `vector` extension present. The three serialized queue smoke containers (`research`, `refresh`, `media`) each exited 0 with `OOMKilled=false`; app restart recovered to healthy. An initial parallel queue launch reproduced a research smoke exit 139, so the manifest now serializes the qualification probes through `service_completed_successfully`. |
| 14.7 Alembic upgrade/downgrade/restore | **PARTIAL** | A disposable `release_gate_rehearsal` database completed `upgrade head`, `downgrade base`, and a second `upgrade head`. A 37,470-byte `pg_dump` was restored into a dropped/recreated database with `ON_ERROR_STOP=1`; the restored database reported `20260824_0007_b3_personalization_memory`, `vector`, `pg_trgm`, and 26 public tables. Clean/N-1 fixtures also pass. The source scan still finds legacy runtime `CREATE TABLE IF NOT EXISTS` paths in `src/xhs_food/services`, `src/scripts`, and `scripts/migrate_sse_recovery.py`; removal is explicitly deferred to `legacy-contraction`. |
| 14.8 BGE-M3 `profile_v1` | **PASS (fixture)** | The fixture pins `bge-m3/v1`, 1024 dimensions, normalized cosine distance, profile-aware index metadata, dual-write cursor and pointer rollback tests. No external model download is claimed. |
| 14.9 Redis contract/outage | **PASS (local/live evidence)** | Session 20/24h, stream 1h/`MAXLEN 1000`, rebuild, rate-limit, short idempotency, replay-expiry and outage semantics pass. Redis is not a lock, lease, queue, or durable task store. |
| 14.10 Temporal/operator gate | **PASS (local target stack)** | Nine isolated SDK qualification tests pass (`9 passed in 70.17s`). Against the real release Compose Temporal `1.28.2` service, `uv run --frozen python scripts/qualification_temporal_release_matrix.py` passed research/refresh/media queue isolation, clean worker handoff, retry exhaustion, visibility lookup, and same-Workflow-ID operator retry (`worker_rollout=PASS retry_exhaustion=PASS operator_retry=PASS`). The isolated CPython 3.12.12 target runner also passed `tests/test_live_b0_target_stack.py` (`1 passed in 22.40s`) against real PostgreSQL/Redis/Temporal, proving PG commit survives Redis loss and reconciles one terminal event. Production multi-worker rollout remains a deployment closure probe. |
| 14.11 S3/MinIO failure matrix | **PASS (contract)** | boto3/MinIO adapter tests cover streaming, hash de-duplication, content/size allow-list, encryption fail-closed behavior, signed URL policy, missing/corrupt objects, metadata abort and orphan cleanup. A deployed MinIO failure run is pending. |
| 14.12 OTel/Prometheus | **PASS (contract)** | Trace correlation, secret/URL/preference redaction and bounded label-cardinality tests pass. End-to-end API -> Temporal -> PostgreSQL/Redis/S3 trace capture is a deployment probe. |
| 14.13 dependency/import scan | **PASS** | `uv run --frozen pytest -q tests/test_unit_architecture_boundaries.py tests/test_unit_dependency_ledger.py tests/test_unit_b3_architecture.py` passed 17 tests; `uv lock --check` passed. The AST/import/lock scan rejects ARQ, Celery, LangGraph, OpenAI Agents SDK, LiteLLM, Mem0, Zep, Redis locks/Redlock, forbidden database pools/runtime DDL, and a second migration/runtime authority. |
| 14.14 milestone archive | **PASS (records)** | S0-S5 and B0-B5 verification records include commands, counts, versions, feature bindings and rollback runbooks. Release-gate status remains separate from milestone implementation status. |
| 14.15 strict OpenSpec/CI/dependency graph | **PARTIAL (local CI mirror)** | `openspec validate define-modular-architecture --strict`, `openspec validate legacy-contraction --strict`, `uv sync --frozen --extra dev --python 3.12`, `uv lock --check`, critical Ruff (`E9,F63,F7,F82`), frontend `npm ci`, `npm run lint`, and `npm run build` all pass locally. The backend CI-equivalent command `uv run --frozen pytest --cov=src --cov-report=xml -m "unit or integration" -ra --durations=0` passed `961 passed, 24 deselected, 2 warnings` in `178.17s`; the hosted Ubuntu parity run is separately recorded as passed in the container evidence. Full Ruff remains `796 errors` in the existing non-blocking/`continue-on-error` baseline, so this is not a clean CI qualification; target deployment CI, production provider/trace correlation, and production Temporal rollout remain pending. |
| 14.16 architecture/docs drift | **PASS (local)** | Added `tests/test_architecture_docs_drift.py`, which registers the live Food/Travel manifests and schema bundles, checks the contract catalog, validates architecture HTML/Draw.io anchors, verifies ADR-0009 compatibility anchors, and requires S0-S5/B0-B5 verification plus rollback assets. The Draw.io reference was refreshed to remove obsolete ARQ/OpenAI Agents SDK/Responses labels and reflect Pydantic AI V2, Temporal, Redis hot state, and Food/Travel Packs. Focused gate: `3 passed`. |
| 14.17 legacy contraction follow-up | **PASS** | The follow-up `legacy-contraction` change is created as a planning-only change. This change deletes no legacy path or field. |

## Reproducible Commands

```powershell
uv sync --frozen --extra dev
uv lock --check
uv run --frozen pytest -q -m "not live" -ra --durations=0
uv run --frozen pytest -q tests/test_release_gate_manifests.py
uv run --frozen pytest -q tests/test_architecture_docs_drift.py
uv run --frozen pytest -q tests/test_unit_architecture_boundaries.py tests/test_unit_dependency_ledger.py tests/test_unit_b3_architecture.py
uv lock --check
uv run --frozen ruff check src tests/test_release_gate_manifests.py
openspec validate define-modular-architecture --strict
openspec validate legacy-contraction --strict
uv run --frozen ruff check src/ tests/ --select E9,F63,F7,F82
Push-Location frontend
npm ci
npm run lint
npm run build
Pop-Location
uv run --frozen pytest --cov=src --cov-report=xml -m "unit or integration" -ra --durations=0
docker build --file Dockerfile.release --tag xhs-food-agent:release-gate .
docker compose -f docker-compose.release.yml up -d --wait --no-build
docker compose -f docker-compose.release.yml ps -a
docker compose -f docker-compose.release.yml restart app
docker compose -f docker-compose.release.yml exec -T app id
docker compose -f docker-compose.release.yml exec -T postgres psql -U postgres -d xhs_food_agent -Atc "select version_num from alembic_version; select extname from pg_extension where extname='vector';"
# Target-stack runner commands (run from a host with the release Compose stack up)
docker run --rm --network food-agent-release-gate_default -v "${PWD}:/workspace" -w /workspace -e B2_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@food-agent-release-gate-postgres-1:5432/xhs_food_agent ghcr.io/astral-sh/uv:python3.12-bookworm-slim bash -lc "uv sync --frozen --extra dev --python 3.12 && uv run --frozen pytest -q -m live tests/test_live_b2_query_reuse.py -vv -s --tb=short"
docker run --rm --network food-agent-release-gate_default -v "${PWD}:/workspace" -w /workspace -e EVENT_BUS_BACKEND=redis -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@food-agent-release-gate-postgres-1:5432/xhs_food_agent -e REDIS_HOST=food-agent-release-gate-redis-1 -e REDIS_PORT=6379 -e TEMPORAL_ADDRESS=food-agent-release-gate-temporal-1:7233 -e OPENAI_API_KEY=ci-dummy-key -e OPENAI_API_BASE=https://api.openai.com/v1/ ghcr.io/astral-sh/uv:python3.12-bookworm-slim bash -lc "uv sync --frozen --extra dev --python 3.12 && uv run --frozen pytest --cov=src --cov-report=xml -m 'unit or integration' -ra --durations=0"
$env:TEMPORAL_ADDRESS = "127.0.0.1:17233"
uv run --frozen python scripts/qualification_temporal_release_matrix.py
docker run --rm --network food-agent-release-gate_default -v "${PWD}:/workspace" -w /workspace -e UV_PROJECT_ENVIRONMENT=/tmp/food-agent-target-venv -e B0_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@food-agent-release-gate-postgres-1:5432/xhs_food_agent -e B0_REDIS_URL=redis://food-agent-release-gate-redis-1:6379/0 -e TEMPORAL_ADDRESS=food-agent-release-gate-temporal-1:7233 ghcr.io/astral-sh/uv:python3.12-bookworm-slim bash -lc "uv sync --frozen --extra dev --python 3.12 && uv run --frozen pytest -q -m live tests/test_live_b0_target_stack.py -vv -s --tb=short"
```

The non-live run is the blocking local baseline. Its two warnings are the
existing `pytest` warning for test functions returning a boolean; they do not
change application behavior. Live results are kept in the B0/B1/B2/B3/B4
verification records and are not silently converted into a target deployment
claim.

## Closure Criteria

The release gate can move from **Partial qualification** to **Qualified** only
after production Temporal rollout evidence and the legacy runtime-schema
contraction have attached their exact command output and environment. Until
then, the approved support matrix remains CPython 3.12 on Ubuntu/Windows x86_64
with the documented probe boundaries.
