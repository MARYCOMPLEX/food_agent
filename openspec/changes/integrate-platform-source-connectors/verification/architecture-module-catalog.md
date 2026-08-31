# Architecture Module Catalog

**Repository fixture:** `C:\Users\14158\Documents\ChatGPT\fagent\food_agent`
**Recorded branch:** `codex/integrate-platform-source-connectors`
**Recorded date:** 2026-08-31
**Purpose:** describe the modules that exist in the repository, their
technology, process placement, interactions, and authority boundaries.

The catalog distinguishes the current compatibility path from the
feature-gated platform path. A module marked **legacy-compatible** remains
available for existing callers; a module marked **target/opt-in** is inert until
its Composition Root flags and dependencies are qualified.

## 1. Runtime topology

| Process / service | Technology | Main modules | Owns | Talks to |
|---|---|---|---|---|
| Browser UI | React 19, TypeScript, Vite, Zustand, Tailwind/Radix | `frontend/src/App.tsx`, `frontend/src/api`, `frontend/src/stores`, views/components | presentation state and public session ID | FastAPI REST/SSE |
| API process | CPython 3.12, FastAPI, Uvicorn, SSE-Starlette, SlowAPI | `src/api/main.py`, `src/api/search`, history/favorites/user routers | request lifecycle, rate limit, dependency projection | Composition Root, use cases, EventBus, storage |
| Composition process boundary | Python factories/registries, Pydantic settings | `src/xhs_food/composition/root.py`, `platform_bindings.py`, `adapters/` | binding selection, lifecycle, feature flags | contracts, gateways, foundation adapters |
| Research/agent worker | Pydantic AI V2 target; legacy agents remain | `orchestrator/agent_runtime.py`, `coordinator.py`, `scheduler.py`, `agents/`, `domain_packs/` | deterministic plan execution and model/tool policy | ToolGateway, SourceGateway, LLM, Temporal activities |
| Temporal workers | Temporal SDK (`temporalio`) | `foundation/temporal.py`, `orchestrator/reliable_task.py`, `refresh_media.py`, `platform_login_temporal.py` | durable workflow history/checkpoints and bounded retry | PostgreSQL projections, Redis event bus, account gateway, ObjectStore |
| Provider activity / sidecar | Playwright; Spider_XHS Python + Node 20 signer when enabled | `composition/adapters/platforms.py`, `gateways/platform_sources.py` | one account-local mutable client per activity | Dianping/XHS endpoints through typed ports |
| PostgreSQL | PostgreSQL 16 + `pgvector`/`pg_trgm`, SQLAlchemy 2 async/asyncpg | `foundation/database.py`, `platform_account_repository.py`, services storage | business facts, evidence, account authority, schema | API, repositories, Temporal activities |
| Redis | Redis 7 (`redis.asyncio`) | `foundation/redis.py`, `events/bus.py`, `services/redis_memory.py` | hot state, SSE streams, rate/circuit projections | API, workers, SessionManager |
| Object storage | AWS S3 via Boto3; MinIO local/release fixture | `foundation/object_store.py` | QR/media bytes and lifecycle | login/media activities, API presentation refs |
| LLM endpoint | OpenAI-compatible HTTP endpoint (SiliconFlow/OpenAI/DeepSeek) | `services/llm_service.py`, target model adapter | model responses; no account secrets | agents/orchestrator |

The release fixture is declared in `docker-compose.release.yml`: `app`,
`migrate`, `postgres`, `redis`, `temporal`, `minio`, and queue smoke workers.
The default `docker-compose.yml` is a development/legacy fixture and does not
enable platform bindings by itself.

## 2. Edge and API modules

| Module path | Stack | Responsibility | Interaction / boundary | Status |
|---|---|---|---|---|
| `src/api/main.py` | FastAPI lifespan, CORS, SlowAPI, Prometheus middleware | create app, initialize storage/session/event bus/composition, expose health/metrics | calls `_load_platform_runtime()`; only an explicitly injected `app.state.platform_runtime_factory` can supply platform dependencies | legacy-compatible; no factory means exact legacy kwargs |
| `src/api/platform.py` | FastAPI router + redacted validation route | account registration, QR/phone/cookie command envelopes, status/QR/cancel/re-auth/readiness | delegates to `PlatformLoginService`; never echoes request body or ObjectStore key | target/opt-in; returns `503 PLATFORM_DISABLED` when runtime is absent |
| `src/api/search/routes.py` | FastAPI + SSE-Starlette | new/refine/recover search, event stream, reliable projection snapshot | SSE receives redacted events and Redis replay IDs | active |
| `src/api/search/tasks.py` | async use-case facade | bridge API requests to legacy or reliable task port | public request remains account-agnostic | active |
| `src/api/history.py`, `favorites.py`, `user.py`, `help.py` | FastAPI routers | CRUD/presentation endpoints | storage adapters own persistence | active |
| `frontend/src/api/*.ts` | TypeScript `fetch` clients | REST/SSE transport and error mapping | stores only UI/session state | active |
| `frontend/src/components`, `views`, `pages` | React 19 + Tailwind/Radix | search pipeline, result cards, history/favorites/profile | no provider credentials | active |

## 3. Composition and adapter modules

| Module path | Technology | Responsibility | Key interactions | Status |
|---|---|---|---|---|
| `composition/root.py` | typed factories, `BindingRegistry`, `CompositionRoot` | configure/activate/close registries atomically; preserve legacy bindings | receives `TargetSettings`, injects ports and factories | active; platform branch opt-in |
| `composition/platform_bindings.py` | immutable dataclasses + readiness gate | resolve Dianping/XHS factories, capability snapshots, gateway/login readiness | requires authority, codec, checkout, provenance, license refs | target/opt-in |
| `composition/adapters/platforms.py` | lazy imports, Playwright bridge, Python/Node protocol bridge | adapt pinned provider checkouts to small provider ports | provider modules loaded only inside activity/factory | target/opt-in |
| `composition/adapters/sources.py` | legacy source factories | `xhs_compat`, Amap/place compatibility | existing public source path | legacy-compatible |
| `composition/adapters/llm.py`, `food_tools.py`, `repositories.py` | project-owned ports | LLM/tool/repository bindings | selected through root | active |
| `composition/adapters/reliable_*` | Temporal/Postgres/Redis adapters | reliable task events/projections/worker lifecycle | explicit `reliable_task_lifecycle` flag | target milestone/opt-in |

The `platform` registry is created only when platform flags or injection seams
are supplied. With a no-argument `build_legacy_composition_root()` call, the
exact legacy registry remains the default.

## 4. Contract and domain modules

| Module path | Main types/policies | Responsibility | Boundary |
|---|---|---|---|
| `contracts/base.py`, `errors.py`, `ports.py` | `ContractModel`, `ContractError`, ports | stable typed seams and error taxonomy | provider details terminate at adapter boundary |
| `contracts/query_reuse*.py`, `evidence*.py`, `tasks.py` | Query Family, Evidence, task/projection contracts | public research identity and lifecycle | unchanged by account selection |
| `contracts/account.py` | `PlatformAccountRef`, session/grant/lease/health/login/invocation models | tenant/channel/account isolation and secret-free envelopes | opaque IDs only outside activity memory |
| `domain_packs/food/*` | Food behavior, intent, scoring, schema resources | domain policy and output contract | no provider-specific credential fields |
| `agents/intent_parser.py` | legacy LLM parser | parse user intent | calls legacy LLM service |
| `agents/analyzer.py` | Python preprocessing + LLM semantic labels + Python scoring | comment/shop analysis | canonical comments only |
| `agents/poi_search.py`, `poi_enricher.py` | Amap `PlaceLookupPort` | enrich recommendations | legacy place source remains compatible |

## 5. Orchestration and agent runtime

| Module path | Runtime | Responsibility | Durable/ephemeral behavior |
|---|---|---|---|
| `orchestrator/coordinator.py` | async Python | plan/review/replan/stopping decisions; legacy behavior-preserving policy | in-process unless reliable policy injected |
| `orchestrator/scheduler.py` | deterministic typed DAG | dependency order, budgets, step states | deterministic; no broker |
| `orchestrator/agent_runtime.py` | Pydantic AI V2 | one shared Agent runtime, tool policy, usage limits, output validation | target runtime; provider-neutral |
| `orchestrator/reliable_task.py` | Temporal workflow/activity definitions | durable submit/progress/commit/fail/cancel/reconcile | Temporal is sole checkpoint; PG projection is authority |
| `orchestrator/refresh_media.py` | Temporal refresh/media workflows | evidence refresh and ObjectStore media work | queues isolated by workload |
| `orchestrator/platform_login.py` | lazy compatibility exports | re-export account-auth Temporal workflow/activity symbols without importing SDK at package import time | resolves `foundation.platform_login_temporal` on attribute access | target/opt-in |
| `experience/platform_login.py` | application use case, Pydantic contracts | validates principal/grant/idempotency and maps login commands to workflow/coordinator | injected by API lifespan/Composition Root; only opaque refs leave boundary | target/opt-in |
| `foundation/temporal.py` | `temporalio` client/worker adapters | queue names, quotas, retry/heartbeat policies | research/refresh/media plus optional account-auth |

The optional `account-auth` queue is absent from default queue configuration;
when present it must be distinct and explicitly enabled. No ARQ, Celery,
LangGraph, OpenAI Agents SDK, Redis lock, or SQLite task queue is part of the
target runtime.

## 6. Account, authentication, and secret modules

| Module path | Technology | Responsibility | Persisted data |
|---|---|---|---|
| `foundation/platform_accounts.py` | in-memory qualification authority + AES-GCM test codec | reference implementation of account/session/grant/lease/health semantics | test-only memory; ciphertext contract |
| `foundation/platform_account_repository.py` | SQLAlchemy 2 async + PostgreSQL dialect | project-owned account/session/grant/lease/login/health repository | encrypted envelope metadata and audit rows |
| `foundation/platform_account_schema.py` | SQLAlchemy table metadata | additive table declarations | schema is provisioned by Alembic only |
| `contracts/account.py` | Pydantic v2 validators/redaction | reject secret-bearing fields and enforce monotonic state | no raw secret |
| `foundation/platform_login.py` | async coordinator + ObjectStore port | split-phase QR/phone/cookie flow, CAS session activation | flow metadata and QR object ref |
| `foundation/platform_login_temporal.py` | Temporal workflows/activities | account-auth queue execution, bounded polling/cancellation | only redacted flow state in history |
| `composition/adapters/platform_login.py` | injected Spider_XHS PC/Creator protocol bridge | lower-level split-phase QR/phone/cookie calls, account-local signer/client state, encrypted sidecar seam | built-in XHS qualification adapter; deployment supplies durable state store/sidecar |
| `auth/*` | existing XHS browser/Node signer helpers | legacy/manual XHS login compatibility | local profiles only on legacy path |

Session material is decrypted only in an activity-local byte buffer, consumed by
one provider client, then zeroized. QR bytes are short-lived ObjectStore
objects; Redis may project status but is not the authority.

## 7. Gateway and provider modules

| Module path | Technology | Responsibility | Isolation rule |
|---|---|---|---|
| `gateways/source_gateway.py` | async source control | legacy connector admission/rate/circuit boundary | source-level only |
| `gateways/platform_gateway.py` | async typed gateway | grant → account → session → lease → connector; canonical outcome mapping | one invocation, one account-local client; lease in PG |
| `gateways/platform_sources.py` | adapter protocols + canonical normalizers | map provider envelopes/items/comments/media to canonical contracts | strips access-bearing URL queries; no raw responses |
| `gateways/capabilities.py` | immutable registration/multiplexer | versioned source/capability resolution and collision rejection | explicit source/version required on collision |
| `composition/adapters/platforms.py` | lazy checkout importer and bridges | create Dianping or XHS PC/Creator provider objects | allow-list only; sidecar seam; no top-level upstream import |
| `providers/xhs_providers.py` | legacy MCP tool provider facade | existing XHS search/note/batch tools | retained for compatibility; not the account authority |

### Platform channel map

| Channel | Public source ID | Enabled read surface | Provider runtime |
|---|---|---|---|
| `dianping` | `dianping` | place search/detail, reviews, media refs | Playwright protocol modules from pinned checkout |
| `xhs_pc` | `xhs` | note search/detail/comments/media refs | Spider_XHS PC auth/API bridge; optional Node signer |
| `xhs_creator` | `xhs` | own-note read/health probe only | Spider_XHS Creator auth/API bridge |

Creator publishing/upload/scheduling and unrelated upstream APIs are not
registered. PC and Creator retain separate account/session/lease/health keys.

## 8. Storage, evidence, events, and observability

| Module path | Stack | Role | Authority / retention |
|---|---|---|---|
| `foundation/database.py` | SQLAlchemy async engine/UoW | transaction/session ownership | transaction boundary supplied by use case |
| `foundation/schema_authority.py` | asyncpg readiness probes | verify Alembic-provisioned tables/extensions | read-only; fail closed |
| `foundation/legacy_schema.py`, `evidence_schema.py`, `memory_schema.py` | schema requirement manifests | readiness metadata | no runtime DDL |
| `services/postgres_storage.py`, `postgres_vector.py` | asyncpg + pgvector | long-term chat history/vector search | PostgreSQL persistence |
| `services/redis_memory.py` | Redis List + in-memory fallback | sliding context window | TTL/rebuildable |
| `services/session_manager.py` | coordinator | Redis-first read, Postgres fallback/write | legacy context path; platform account data uses authority repository |
| `events/bus.py`, `events/types.py`, `events/step_projection.py` | in-memory or Redis Streams | SSE publish/subscribe/replay | Redis stream bounded; terminal event semantics |
| `evidence/*` | canonical/evidence lifecycle modules | collect, refresh, diff, media, query reuse | public evidence excludes credential fields |
| `foundation/object_store.py` | Boto3 async facade | bounded S3/MinIO put/get/delete, signed refs, orphan cleanup | binary lifecycle and policy |
| `observability/*` | Prometheus + OpenTelemetry adapters | low-cardinality metrics/traces and health | labels exclude account secrets and raw URLs |

## 9. Configuration and deployment modules

| Path | Configuration/runtime | Notes |
|---|---|---|
| `src/xhs_food/config.py` | legacy `Settings` (Pydantic Settings) | API, Redis, Postgres, XHS legacy profile, LLM |
| `src/xhs_food/foundation/config.py` | `TargetSettings` + immutable owner views | platform flags, Temporal queues, ObjectStore, target adapters |
| `src/xhs_food/composition/adapters/config.py` | `OwnerConfigFacade` | maps legacy settings to owner-scoped views |
| `docker-compose.yml` | dev app + Redis + Postgres/pgvector | legacy/dev fixture |
| `docker-compose.release.yml` | release app + migrate + queue smoke + Redis/Postgres/Temporal/MinIO | target-stack qualification fixture |
| `Dockerfile.release` | CPython 3.12 + Node 20 + frozen `uv.lock` | non-root release image |
| `alembic/versions/*` | Alembic revisions | sole PostgreSQL schema authority |
| `scripts/qualification_*` | Python operational probes | record exact stack/canary evidence; no credentials | `qualification_schema_authority.py` scans source only and skips `.venv`, `.venv-win`, `.venv-auth`, bytecode, tests, and Alembic; legacy SQLite request-log telemetry is classified separately |

## 10. End-to-end interaction sequences

### Public search (legacy-compatible default)

`Browser → FastAPI /v1/search → ResearchTaskPort → Domain/Agent pipeline →
legacy SourceGateway/tools → Redis EventBus + PostgreSQL history → SSE/browser`.

### Account-bound platform collection (feature-gated)

`Caller → PlatformSourceInvocation → SourceControl admission → grant → account
lookup → active session/CAS version → PostgreSQL lease → activity-local codec
decrypt → Dianping/XHS connector → canonical batch → health/event projection →
close/zeroize/release → evidence/media workflows`.

### QR login (optional queue)

`Caller → PlatformLoginWorkflow (account-auth) → create QR → ObjectStore ref →
Redis status projection → poll/confirm → encrypted session CAS in PostgreSQL →
terminal flow + QR cleanup`.

The repository includes this provider bridge for `xhs_pc` and `xhs_creator`.
The Dianping snapshot's QR helper owns one long-running Playwright loop, so the
initial Dianping rollout imports its resulting storage state through an opaque
vault handle or injects a deployment-owned account-auth sidecar implementing
the same `PlatformLoginProvider` port. The upstream FastAPI/SQLite worker is
never started in the application process.

## 11. Architecture invariants checklist

- [x] PostgreSQL/Alembic remains the only business/schema authority.
- [x] Temporal remains the only durable execution runtime.
- [x] Redis is hot/rebuildable state only; no lock/lease/durable account fact.
- [x] Source IDs/capabilities are versioned and collision resolution is explicit.
- [x] New provider bindings are disabled by default and fail closed on missing
  checkout, authority, codec, provenance, license approval, or auth queue.
- [x] No secret appears in Temporal history, SSE, logs, metrics, Evidence, or
  object metadata.
- [x] `xhs_pc` and `xhs_creator` never share mutable account state.
- [x] Upstream API servers, SQLite task tables, CLI writers, and retry queues
  are excluded from the application process.
- [x] Rollback is a flag/queue change; legacy routes and stored evidence remain
  unchanged.

The companion diagram is
[`platform-integration-architecture.svg`](../references/platform-integration-architecture.svg),
with a browser-readable HTML view at
[`platform-integration-architecture.html`](../references/platform-integration-architecture.html).
