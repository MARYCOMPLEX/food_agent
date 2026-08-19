# ADR-0002: Approved Infrastructure And Framework Baseline

- Status: Accepted
- Date: 2026-08-19
- Owners: Architecture, Platform, Data Platform, AI Platform, SRE
- Detailed evidence: [dependency research](../dependency-research.md)

## Decision

| Capability | Accepted implementation | Authority and replacement boundary | Upgrade/security owner |
|---|---|---|---|
| Agent runtime | Pydantic AI V2 stable core | One runtime behind `AgentRuntime`/`ModelGateway`; official Temporal integration maps model/tool calls to Activities; SiliconFlow/OpenAI/DeepSeek remain provider adapters | AI Platform |
| Durable execution | Temporal | Sole executable history for Research, Refresh, and Media Task Queues; Workflow ID owns single-flight | Platform Runtime |
| Business facts | PostgreSQL 16 | Sole authority for business facts, stable task projections, Bundle activation, memory, and outbox | Data Platform |
| Data access | SQLAlchemy 2 Async + asyncpg | Repository adapters only; one unit-of-work transaction owner | Data Platform |
| Schema migration | Alembic | Sole schema authority; no runtime DDL or parallel migration chain | Data Platform |
| Hot state | Redis 7.4 + `redis.asyncio` | Rebuildable 20-message/24-hour session window, 1-hour/1000-event SSE stream, cache, rate limit, and short idempotency only | Platform Runtime |
| Search and embedding | `pg_trgm`, pgvector, BGE-M3 `profile_v1` | 1024 dimensions, cosine, normalized; new profile/index, dual write, replayable backfill, quality gate, atomic read-pointer switch, and rollback | AI Platform + Data Platform |
| Object storage | S3-compatible API + boto3; local MinIO | Binary content only behind `ObjectStore`; PostgreSQL owns metadata and visibility | Platform Storage |
| Observability | OpenTelemetry + Prometheus | OTel trace/context and Prometheus metric contracts; exporters remain replaceable | SRE |
| External tool protocol | Official MCP Python SDK | External transport adapter only; internal `ToolGateway` remains project-owned | Integrations |
| Python/toolchain | CPython 3.12 + uv + committed `uv.lock` | Blocking runtime and reproducible dependency resolution | Build + Release |
| Verification tooling | import-linter, Schemathesis/Hypothesis, generated OpenAPI client, Playwright | Architecture, API property/contract, and browser gates only; no production ownership | Architecture + QA |

Exact deployed dependency versions are locked in `uv.lock`. Major upgrades require release-note, license, security, provider-contract, migration, and rollback review by the listed owner.

## Authority Rules

- Temporal history is the only executable checkpoint. PostgreSQL `task_progress_projection` is query-only and cannot drive replay.
- Redis is never a durable task queue, fact authority, lock/lease owner, Redlock provider, or Bundle activation authority.
- PostgreSQL commits business results before a success terminal can be emitted.
- S3-compatible storage owns bytes; PostgreSQL owns object metadata, provenance, tenancy, and discoverability.
- Framework and provider types terminate at adapters. Domain and capability contracts remain project-owned.

## Not Adopted As Core

ARQ, Celery, LangGraph, LangChain Agent, OpenAI Agents SDK, Mem0, Zep, LiteLLM SDK, Redis Vector, and an independent vector database do not enter the core. Existing LangChain remains only inside the legacy `LLMService` adapter until differential tests permit removal.

## Replacement Policy

An implementation can be replaced only behind its existing port, with the same contract suite, data migration, failure-injection evidence, and rollback path. Adding a second runtime or authority for the same capability requires a separate OpenSpec change and ADR.
