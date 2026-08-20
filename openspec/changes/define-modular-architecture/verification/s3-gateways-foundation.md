# S3 Gateways And Foundation Facades Verification

Date: 2026-08-21

Evidence status: complete. The implementation commit is pushed and the
detached-worktree revert restored the exact S2 tree with all required checks
passing.

## Scope

S3 places the existing XHS, Amap/POI, LLM, repository, task-state, EventBus,
session-window, configuration, and observability responsibilities behind
project-owned ports. It also adds disabled target adapters for SQLAlchemy 2
Async, Redis hot state, Temporal, S3-compatible object storage, and
OpenTelemetry instrumentation.

S3 is structural. The default Composition Root still selects the S2
`LegacyResearchTaskFacade` and the existing Food workflow. It does not add an
Alembic revision, create or alter a table, dual-write data, start a Temporal
workflow, create a target SQLAlchemy engine, create an S3 client during module
import or root construction, or enable a new Redis/OTel runtime.

The S2 base revision is
`82bce06932a6689d61f7d64c054f84acbc57f7ad`.

- S3 implementation revision:
  `65c9cc978b9a3225e2f48c4587820ebb52a8edfb`
- Detached revert revision: `05f158a1331558f94f3056222c463b3cca3e06b9`

## Adapter And Binding Inventory

### Enabled legacy-compatible bindings

| Registry binding | Contract | Concrete responsibility | S3 default |
|---|---|---|---|
| `foundation.xhs_service` | `legacy/v1` | Existing XHS service factory | Enabled, legacy |
| `tools.xhs_tool_registry` | `legacy/v1` | Existing `xhs_search`, `xhs_note`, and `xhs_batch` registry | Enabled, legacy |
| `sources.xhs_compat` | `xhs-connector/v1` | `XHSSourceConnector` over the three legacy providers | Enabled, legacy-compatible |
| `sources.place_compat` | `amap-connector/v1` | `AmapPlaceSourceConnector` over `AmapAPI` | Enabled, legacy-compatible |
| `sources.place_tool_compat` | `place-tool/v1` | `PlaceLookupToolAdapter` over `AmapAPI` | Enabled, legacy-compatible |
| `models.legacy_llm_provider` | `model-provider/v1` | `LegacyLLMProviderAdapter` over `LLMService` | Enabled, legacy-compatible |
| `repositories.session_legacy` | `repository/v1` | Existing session manager | Enabled, legacy-compatible |
| `repositories.user_legacy` | `repository/v1` | Existing user storage | Enabled, legacy-compatible |
| `repositories.history_legacy` | `repository/v1` | Existing history storage | Enabled, legacy-compatible |
| `repositories.favorites_legacy` | `repository/v1` | Existing favorites storage | Enabled, legacy-compatible |
| `repositories.search_result_legacy` | `repository/v1` | Existing search-result storage | Enabled, legacy-compatible |
| `repositories.place_cache_legacy` | `repository/v1` | Public place-cache read over existing storage | Enabled, legacy-compatible |
| `repositories.public_evidence_disabled` | `repository/v1` | Explicit disabled sentinel; all operations raise `TargetAdapterDisabled` | Registered as legacy sentinel; no target read/write |
| `state.task_state_legacy` | `legacy-hot-state/v1` | Existing Redis/in-memory task state selection | Enabled, legacy-compatible |
| `state.event_bus_legacy` | `legacy-hot-state/v1` | Existing Redis Streams/in-memory EventBus selection | Enabled, legacy-compatible |
| `state.session_window_legacy` | `legacy-hot-state/v1` | Existing `RedisMemory` session window | Enabled, legacy-compatible |
| `orchestrators.xhs_food_orchestrator` | `legacy/v1` | Existing Food orchestrator | Enabled, legacy |
| `use_cases.research_task` | `legacy/v1` | `LegacyResearchTaskFacade` | Enabled, legacy |

The only logical selection remains:

```text
modular_core
  -> use_cases.research_task
  -> LegacyResearchTaskFacade
  -> legacy/v1
```

### Disabled target bindings

| Registry binding | Contract | Disabled-state guarantee |
|---|---|---|
| `tools.schema_tool_gateway` | `tool-gateway/v1` | Cannot be resolved; no target tool is callable |
| `target_foundation.sqlalchemy` | `sqlalchemy-async/v1` | Cannot be resolved; a disabled adapter cannot create an engine or session |
| `target_foundation.temporal` | `temporal-workflow/v1` | Cannot be resolved or connect; Research, Refresh, and Media queues are declarations only |
| `target_foundation.temporal_activities` | `temporal-activity/v1` | Cannot be resolved; no model/tool or ordinary Activity is dispatched |
| `target_foundation.object_store` | `object-store/v1` | Cannot be resolved; factory/client construction remains lazy |
| `target_foundation.redis_contract` | `redis-hot-state/v1` | Cannot be resolved; target Redis keys and policy are contract-only |
| `target_foundation.observability` | `observability/v1` | Cannot be resolved; instrumentation/exporters are not installed into the running app |

Every non-legacy binding above is registered with `enabled=False`.
`TargetSettings.target_adapters_enabled` also defaults to `False`, but the S3
registry does not derive activation from that setting: the bindings remain
explicitly disabled. `CompositionRoot.assert_legacy_only()` rejects any enabled
non-legacy binding before activation.

## Frozen Legacy Behavior

| Boundary | Frozen S3 behavior |
|---|---|
| XHS providers | Provider names and order remain `xhs_search`, `xhs_note`, `xhs_batch`. Search keeps `keyword`, `count=10`, `sort_type="most_comments"`, `include_details=True`, and `include_comments=True`; note fetch keeps `note_id` and `max_comments=30`; batch keeps ordered `topics` and `notes_per_topic`. |
| XHS deadlines | The compatibility connector adds no implicit deadline. A hanging provider remains pending until its caller cancels it; cancellation propagates instead of being converted to a source error. |
| Source coverage | Each canonical batch may carry typed attempt facts (`success_nonempty`, `success_empty`, `partial`, or `failure`), item counts, watermarks, and indexes into `errors`. These facts contain no domain coverage threshold or sufficiency decision. |
| Place/POI | Amap calls keep `keywords`, `city`, and `types="050000"`; both `poi_id` and `id` are accepted at the normalization boundary. POI cache lookup now uses the public `get_cached_restaurant_by_name()` repository method and no longer reads another object's `_pool` or `_initialized` fields. The zero-argument Python facade resolves only a Composition-owned pair of place ports; constructor injection remains compatible. |
| Source query projection | A supplied projection pins source, language, renderer ID/version, rendered text, and optional locality; source/language mismatch fails before provider I/O. Omission preserves the S1 payload and uses only the S3 legacy fallback. |
| Model provider | `LLMService` still owns provider selection and request behavior. The adapter preserves message roles, configured model, temperature/max tokens, provider options, tool calls, usage, timeout, and exception propagation for SiliconFlow/OpenAI/DeepSeek-compatible endpoints. |
| Repositories | Session, user, history, favorites, and result facades return project-owned JSON values while delegating to the same legacy services. No SQLAlchemy write or public Evidence write is active and no dual write exists. |
| Task state | Redis key `task:{session_id}:state`, TTL 3600 seconds, corrupt-JSON miss behavior, and Redis-initialization fallback to in-memory remain unchanged. |
| EventBus | Redis key `stream:{session_id}:events`, configured TTL/MAXLEN, `Last-Event-ID` exclusive continuation, heartbeat, terminal stop, Redis/in-memory backend selection, and Redis-initialization fallback remain unchanged. |
| Session window | Redis key `session:{session_id}:window`, maximum 20 messages, TTL 86400 seconds, oldest-first recent reads, and existing per-operation in-memory fallback remain unchanged. |

ADR-0010 fixes the internal taxonomy without unifying incompatible legacy
projections:

- A valid source response with no items is `success_empty`; timeout, 429,
  malformed payload, dependency failure, and provider exception remain failures.
- Surviving canonical items plus isolated errors are `partial`; `partial` is
  coverage metadata and is not a new `TaskStatus`.
- No XHS notes through direct `SearchExecutor.handle_new_search` remains
  `status="ok"` with an empty recommendation list and the legacy summary.
- The same no-note condition through streaming remains `step_error(step2)` and
  terminal `error` with `未找到相关笔记`. The characterized outer background
  projection may still become `completed`; B0, not S3, owns that repair.
- Amap/POI true-empty or failure remains optional: the basic restaurant is
  preserved and legacy `result` plus `done` still succeeds.

## Target Foundation Contracts

| Adapter | S3 structural contract and spike evidence |
|---|---|
| SQLAlchemy | One `AsyncSession` per `SQLAlchemyUnitOfWork`; explicit begin/commit/rollback/close; one target engine owner; asyncpg URL normalization; no runtime `create_all`/`drop_all`; disabled state creates no engine. Driver failures map to repository-scoped `ContractError`; cancellation propagates. |
| Redis | Target-only state/session/event adapters enforce a 20-message/24-hour session window and a 1000-event/1-hour stream. Short idempotency is atomic `SET NX EX`; fixed-window rate limiting is an atomic Lua operation. Their public surface has no lock, lease, Redlock, workflow, checkpoint, or durable-state API. Driver and decode failures map to cache/event-bus scopes; cancellation propagates. |
| Temporal | Three distinct queue names (`research`, `refresh`, `media`), deterministic JSON payload ordering, disabled connect/start behavior, and workflow-scoped failure translation. Workflow replay, worker crash, cancellation race, and retry-exhaustion qualification remain task `1.20`/B0 evidence, not an S3 claim. |
| ObjectStore | Async streaming boundary over boto3, content SHA-256, opaque object keys, multipart configuration, bounded synchronous upload concurrency, lazy S3/MinIO client construction, explicit close, missing-object behavior, object-scoped failure translation, and cancellation propagation. Server-side encryption, retention, signed URL, and orphan policy values remain OQ-12/B4 and do not activate in S3. |
| Observability | Allow-listed and hashed correlation attributes, bounded Prometheus labels, idempotent FastAPI/httpx/Redis/SQLAlchemy instrumentation, and a Temporal tracing interceptor. Existing metric names and `/metrics` behavior remain unchanged because the target bootstrap is disabled. |
| Configuration | `MODULAR_` settings are parsed by Pydantic Settings into frozen owner-specific views. Existing environment names/defaults stay in the legacy `Settings`; client construction is deferred to adapter lifecycle calls. |

The architecture gate also rejects a second target database pool, runtime DDL,
Redis lock/lease/durable-state surfaces, and the core dependencies ARQ, Celery,
LangGraph, OpenAI Agents SDK, LiteLLM, Mem0, and Zep.

## Locked Dependency Record

The table records the Python packages resolved in `uv.lock`. License values were
checked on 2026-08-21 from the installed locked distribution metadata; the
official links and ownership disposition follow ADR-0002 and
`dependency-research.md`.

| Component | Exact locked version | Official source | Maintenance disposition | License | Upgrade/security owner |
|---|---:|---|---|---|---|
| Pydantic AI Slim | `2.5.1` | [Pydantic AI](https://pydantic.dev/docs/ai/overview/) | Adopted as the sole future Agent runtime; dependency locked, runtime disabled in S3 | MIT | AI Platform |
| Temporal Python SDK | `1.31.0` | [Temporal Python SDK](https://docs.temporal.io/develop/python) | Adopted as the sole durable runtime; SDK locked, client disabled in S3 | MIT | Platform Runtime |
| SQLAlchemy | `2.0.52` | [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) | Adopted; target engine disabled in S3 | MIT | Data Platform |
| asyncpg | `0.31.0` | [asyncpg](https://github.com/MagicStack/asyncpg) | Adopted only through the SQLAlchemy async dialect for target code | Apache-2.0 | Data Platform |
| Alembic | `1.19.1` | [Alembic](https://alembic.sqlalchemy.org/en/latest/) | Adopted as sole target schema authority; S3 adds no revision | MIT | Data Platform |
| redis-py | `7.4.0` | [redis-py asyncio](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) | Adopted for rebuildable hot state; target adapter disabled in S3 | MIT | Platform Runtime |
| boto3 | `1.43.75` | [Boto3 S3 guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html) | Adopted behind `ObjectStore`; target binding disabled in S3 | Apache-2.0 | Platform Storage |
| OpenTelemetry SDK | `1.44.0` | [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/) | Adopted for trace/context; target bootstrap disabled in S3 | Apache-2.0 | SRE |
| OTel FastAPI/httpx/Redis/SQLAlchemy instrumentation | `0.65b0` each | [OpenTelemetry Python contrib](https://github.com/open-telemetry/opentelemetry-python-contrib) | Adopted adapters; installation is composition-owned and disabled in S3 | Apache-2.0 | SRE |
| pgvector Python | `0.4.2` | [pgvector-python](https://github.com/pgvector/pgvector-python) | Adopted for later profile-aware repositories; no S3 read/write activation | MIT | AI Platform + Data Platform |
| Prometheus client | `0.25.0` | [Prometheus Python client](https://prometheus.github.io/client_python/) | Existing metric authority retained; label boundary added without metric rename | Apache-2.0 AND BSD-2-Clause | SRE |

PostgreSQL 16, Redis Server 7.4, Temporal Service, and a local MinIO service are
runtime baselines rather than Python lock entries. S3 does not start them or
claim a tested image digest. Exact service images and full-stack compatibility
remain release/B0-B4 gates; this does not reopen their accepted architecture
selection. OQ-11 and OQ-12 cover operational retry/encryption/retention values
and therefore do not justify closing task `1.13` from S3 evidence alone.

## Failure-Injection Coverage

| Injection | Required assertion | Evidence location |
|---|---|---|
| XHS true empty, timeout, 429, malformed envelope/item, dependency error, provider exception | The same legacy/target fixture matrix keeps empty and failure distinct with stable category/scope/retryability; required-source legacy projection remains terminal error | `tests/test_unit_s3_source_consumer_contract.py`, `tests/test_unit_s3_gateway_adapters.py` |
| XHS partial item, all-empty, all-failed, and mixed aggregate | Surviving documents remain ordered; attempt facts and errors remain typed in `CanonicalSourceBatch.coverage/errors`; legacy continues without a new wire field | `tests/test_unit_s3_source_consumer_contract.py` |
| XHS hang and caller cancellation | The same legacy/target fixture adds no S3 timeout; cancellation reaches the provider and propagates | `tests/test_unit_s3_source_consumer_contract.py`, `tests/test_unit_s3_gateway_adapters.py` |
| Tool denied/missing, invalid input/output, exhausted budget, unhealthy provider, timeout | Provider is not called before allow-list/schema checks; task budget and health are isolated; timeout cancels the provider and returns stable `ToolResult` failure | `tests/test_unit_s3_gateway_adapters.py` |
| Amap empty, 429, malformed response/item, timeout, dependency/provider exception | The same legacy/target fixture matrix keeps source taxonomy distinct while preserving the basic restaurant | `tests/test_unit_s3_source_consumer_contract.py`, `tests/test_unit_s3_gateway_adapters.py`, `tests/test_unit_s3_legacy_projection_matrix.py` |
| LLM provider exception and role mismatch | Existing error propagates; no hidden provider fallback or model change | `tests/test_unit_s3_legacy_adapters.py` |
| Repository unavailable/invalid JSON shape and disabled public Evidence | Legacy return policy is preserved; target Evidence operations fail closed; no double write | `tests/test_unit_s3_legacy_adapters.py` |
| SQL transaction exception and disabled start | UoW rolls back and closes the same session; disabled adapter creates no engine | `tests/test_unit_s3_foundation_adapters.py` |
| Repository/workflow/cache/event-bus/object-store driver failures and cancellation | Stable `ContractError` scope/category/retryability, redacted provider detail, and unmodified `asyncio.CancelledError` propagation | `tests/test_unit_s3_foundation_failure_taxonomy.py` |
| Redis TTL/window violation | Invalid TTL/read size is rejected; stream trim/expiry calls and absence of lock/lease API are asserted | `tests/test_unit_s3_foundation_adapters.py` |
| Redis idempotency/rate-limit contention and expiry | Exactly one idempotency claim wins; fixed-window allowed/remaining/retry-after values and key expiry are stable without exposing a lease | `tests/test_unit_s3_redis_contract.py` |
| Temporal duplicate queue names, disabled connect/start, unordered nested input | Duplicate queues fail validation; disabled calls perform no client I/O; serialized input is deterministic | `tests/test_unit_s3_foundation_adapters.py` |
| Object missing, upload contention, lazy lifecycle, invalid object key | Stable missing behavior, bounded upload concurrency, content hash, explicit close, and opaque key validation | `tests/test_unit_object_store_adapter.py` |
| Concurrent registry first resolve, factory failure, resolve/close race, and close failure | First construction is single-flight, failed construction remains retryable, close waits for in-flight construction, independent close failures are aggregated without skipping later instances/registries, and a later close retries only failed instances. | `tests/test_unit_composition_root.py` |
| Sensitive/high-cardinality observability attributes | IDs are hashed, private/free text is dropped, unapproved metric labels are rejected, and instrumentation is idempotent | `tests/test_unit_s3_foundation_adapters.py` |
| No-note direct/stream/read-view divergence and optional POI failure | ADR-0010 projections remain exactly separated through direct Python, streaming, outer status/results/recover, and result events | `tests/test_unit_s3_legacy_projection_matrix.py` |

## S3 Gate Commands

Bootstrap and lock integrity:

```powershell
uv sync --frozen --extra dev --python 3.12
uv lock --check
```

Focused S3 adapter, failure, projection, and architecture suite:

```powershell
uv run --frozen pytest -q -W error `
  tests/test_unit_contract_sdk.py `
  tests/test_unit_s3_gateway_adapters.py `
  tests/test_unit_s3_source_consumer_contract.py `
  tests/test_unit_s3_foundation_adapters.py `
  tests/test_unit_s3_foundation_failure_taxonomy.py `
  tests/test_unit_s3_composition_adapters.py `
  tests/test_unit_s3_legacy_adapters.py `
  tests/test_unit_s3_legacy_projection_matrix.py `
  tests/test_unit_s3_redis_contract.py `
  tests/test_unit_object_store_adapter.py `
  tests/test_unit_poi_place_boundary.py `
  tests/test_unit_composition_root.py `
  tests/test_unit_architecture_boundaries.py
```

Complete non-live S0-S3 backend regression:

```powershell
uv run --frozen pytest -q -m "unit or integration"
```

Static, OpenSpec, and tree-integrity gates:

```powershell
uv run --frozen ruff check `
  src/xhs_food/composition/adapters `
  src/xhs_food/composition/legacy_poi.py `
  src/xhs_food/contracts `
  src/xhs_food/foundation `
  src/xhs_food/gateways `
  tests/test_unit_s3_*.py `
  tests/test_unit_object_store_adapter.py `
  tests/test_unit_poi_place_boundary.py `
  tests/test_unit_contract_sdk.py `
  tests/test_unit_architecture_boundaries.py
uv run --frozen ruff format --check `
  src/xhs_food/composition/adapters `
  src/xhs_food/composition/legacy_poi.py `
  src/xhs_food/contracts `
  src/xhs_food/foundation `
  src/xhs_food/gateways `
  tests/test_unit_s3_*.py `
  tests/test_unit_object_store_adapter.py `
  tests/test_unit_poi_place_boundary.py `
  tests/test_unit_contract_sdk.py `
  tests/test_unit_architecture_boundaries.py
uv run --frozen pyright `
  src/xhs_food/agents/poi_enricher.py `
  src/xhs_food/agents/poi_search.py `
  src/xhs_food/composition/root.py `
  src/xhs_food/composition/legacy_poi.py `
  src/xhs_food/composition/adapters `
  src/xhs_food/contracts `
  src/xhs_food/foundation `
  src/xhs_food/gateways `
  src/xhs_food/services/session_manager.py
openspec validate define-modular-architecture --strict --json
git -c core.autocrlf=false diff --check
```

`uv run --frozen pyright src/` is also recorded as a non-blocking repository
baseline. Existing errors outside the S3 ownership set are not waived into the
blocking scoped command and are not fixed opportunistically in this milestone.

## Final Gate Record

Do not replace a pending value with `passed` until the exact command has run on
the final S3 implementation tree.

| Gate | Final result |
|---|---|
| Python/uv runtime and `uv sync --frozen --extra dev --python 3.12` | Passed on Windows x86_64 with Python 3.12.0 and uv 0.11.14; 115 installed packages checked |
| `uv lock --check` and locked package count | Passed; 117 locked packages resolved |
| Focused S3 suite count/duration | 158 passed in 15.84s |
| Complete non-live S0-S3 suite count/deselections/warnings/duration | 657 passed, 5 deselected, 2 pre-existing `PytestReturnNotNoneWarning` warnings in 41.41s |
| Ruff check and format check | Passed; all checks passed and 45 scoped files plus 2 lifecycle files already formatted |
| Pyright error/warning count | Blocking S3 scope: 0 errors, 0 warnings, 0 informations |
| Full-repository Pyright baseline (informational) | Pyright 1.1.409 analyzed 142 files: 210 errors, 5 warnings, 0 informations; non-blocking legacy baseline |
| Architecture/dependency gates | 11 passed in 5.85s |
| `openspec validate ... --strict --json` | Passed; 1/1 change valid with no issues |
| `git -c core.autocrlf=false diff --check` | Passed; all S3 intent files also verified LF-only |

## Revert Drill

The procedure is defined in
`runbooks/s3-adapter-rollback.md`. Record the detached-worktree evidence here
after the S3 implementation commit has been pushed:

| Revert evidence | Final value |
|---|---|
| S3 implementation commit | `65c9cc978b9a3225e2f48c4587820ebb52a8edfb` (pushed) |
| Detached revert commit | `05f158a1331558f94f3056222c463b3cca3e06b9` |
| S2 base tree hash | `75381dd23774107dc387d6f014a9fe2d0849b42b` |
| Reverted tree hash | `75381dd23774107dc387d6f014a9fe2d0849b42b` |
| `git diff --exit-code` comparison | Passed with exit 0 and no content difference |
| Reverted S2 baseline command/result | `uv --directory $drill run --frozen pytest -q -m "unit or integration"`: 518 passed, 5 deselected, 2 pre-existing warnings in 39.74s |
| Authority SSE LF check | Passed; 2/2 fixtures contain no CR bytes |
| Worktree cleanup/prune result | Clean before removal; worktree removed and metadata pruned |

The drill must use `core.autocrlf=false` so the authority `.sse` fixtures remain
LF-only. A successful drill removes only the S3 structural commit, restores the
exact S2 tree, and needs no database, Redis, Temporal, or object-store cleanup.
