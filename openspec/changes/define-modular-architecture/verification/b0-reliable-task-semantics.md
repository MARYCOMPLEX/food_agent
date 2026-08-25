# B0 Reliable Task Semantics Verification

Status: Draft - offline, SDK, PostgreSQL authority, Redis Streams, HTTP/SSE, local process-crash, and PG/Temporal crash-reconciliation evidence recorded; target-service and deployment rollback gates pending

Change: `define-modular-architecture`

Milestone: B0 (`Reliable Task Semantics`)

Date of this record: 2026-08-24

## Purpose And Entry Criteria

This record is the implementation gate for tasks 8.1-8.11. The target policy
has one task owner, one Temporal execution authority, a PostgreSQL commit
barrier, and a rebuildable Redis/SSE projection while the legacy policy remains
independently selectable. The evidence below proves the offline and SDK-tested
parts of that contract; it does not yet qualify the production bindings.

The normative contract is
[reliable_task_semantics_v1.json](../fixtures/reliable_task_semantics_v1.json).
The semantic decision is [ADR-0011](../decisions/ADR-0011-reliable-task-semantics.md).
The public wire authority remains [ADR-0004](../decisions/ADR-0004-http-sse-authority.md);
S0-S5 legacy behavior remains governed by [ADR-0009](../decisions/ADR-0009-legacy-gap-disposition.md).

`PASS` below means a reproducible test or static check has been run. `PARTIAL`
means only an offline or structural portion is proven. `PENDING` is a release
gate and MUST NOT be represented as production qualification.

## Contract And Authority Matrix

| Concern | B0 authority | Evidence |
|---|---|---|
| Policy version | `legacy-task/v1` versus `reliable-task/v1` | `reliable_task.py` constants and fixture |
| Workflow contract | `research-task/v1` | `build_workflow_start()` contract test |
| Activity contract | `research-activity/v1` | Activity version validation and fixture |
| Semantic state transition | `ResearchCoordinator` | coordinator owner methods and architecture tests |
| Executable checkpoint | Temporal history | live SDK history replay, local OS process-crash/resume, and PG/Temporal crash-after-commit recovery pass; target-service restart qualification remains pending |
| Business result/projection | PostgreSQL adapter port | SQLAlchemy adapter, Alembic 0006 schema, cross-connection admission/CAS, terminal receipts, same-run conflict handling, live projection ordering, and crash-after-commit reconciliation pass |
| Hot replay state | Redis Streams, one hour/1000 entries | Redis target contract plus live Redis 7 exclusive replay, bounded trim/TTL, restart loss, and HTTP resync; real service restart smoke remains pending |
| Public HTTP/SSE | existing mapper and ADR-0004 | authority fixtures, reliable mapper suite, and live retained/expired/dependency-unavailable route qualification |

The in-memory `InMemoryReliableTaskAuthority` and
`InMemoryReliableTaskEventPublisher` are explicit test doubles. They are not
valid production bindings. The Composition Root rejects an enabled reliable
flag without an explicitly injected Temporal/PostgreSQL policy.

## Gate Status By Task

| Task | Gate | Status | Evidence or remaining work |
|---|---|---|---|
| 8.1 | Independent policy versions, terminal set, old-terminal and mapper rules | PASS (contract/mapper) | `legacy-task/v1`, `reliable-task/v1`, `research-task/v1`, `research-activity/v1`; normative fixture, ADR-0011, and `ReliableEventMapper` contract tests. HTTP/SSE route binding remains the 8.9 B0 gate. |
| 8.2 | Opt-in Research Workflow, stable Workflow ID, duplicate start/single-flight | PASS (SDK/PG qualification) | Stable identity, same-process concurrent admission coalescing, durable-owner hydration, Temporal adapter duplicate-start handling, cross-connection PostgreSQL admission, and the live Temporal duplicate-start qualification pass. Reliable refine remains rejected with `RELIABLE_REFINE_IDENTITY_UNAPPROVED` until its separately approved cross-turn identity contract exists. |
| 8.3 | Coordinator-only transitions, Temporal checkpoint, PG commit barrier, reconciliation | PASS (live target-store qualification) | Coordinator-only transitions, `ReliableTaskStorePort`, Alembic-owned schema, PostgreSQL admission/CAS, projection turn ordering, completed/cancelled/failed receipts, same-run terminal competition, late-run guards, idempotent commit/reconcile, live Temporal -> PostgreSQL commit barrier, and live PG/Temporal process-crash-after-commit recovery all pass. Target Temporal service rollout and multi-worker deployment remain separate gates. |
| 8.4 | Pydantic AI Temporal integration, bounded Activities, retry/timeout/heartbeat/cancel policy | PASS (SDK qualification) | Factory, plugin, JSON boundary, policy constants, and the official live model/tool Activity replay and determinism suite pass; production worker/provider rollout remains a separate gate. |
| 8.5 | Separate Research queue and reserved Refresh/Media queues | PARTIAL (binding + structural) | `TemporalTaskQueues` carries explicit per-queue `TemporalWorkerQuota`, enables only `research` by default, rejects disabled `refresh/media` execution until B4, and `build_reliable_research_worker()` registers the Research Workflow, Activities, and official Pydantic AI plugin with the Research quota. Real Temporal service concurrency/priority/isolation smoke remains pending. |
| 8.6 | PG projection + Temporal history + Redis replay/resync | PASS (local target qualification) | Fake and live Redis 7 `xrange`/`xread` contracts prove exact retained-cursor validation, exclusive continuation, and `replay_expired` for unknown cursors. Live stream tests prove approximate `MAXLEN 1000`, TTL, Redis service restart behavior, and `replay_expired` after stream loss; a live ASGI/Redis/PostgreSQL test proves retained and expired reliable SSE mapping with the authoritative task snapshot. Explicit reliable runtime bindings now construct PostgreSQL, Redis, Temporal, projection store, and policy resources without process-local fallback. A real production Temporal service restart and multi-worker deployment smoke remain outside this local qualification. |
| 8.7 | Failure-injection and differential suite | PASS (local qualification) | Seventeen combined live tests pass: nine Temporal SDK tests including Pydantic AI history replay and duplicate commit Activity delivery, PostgreSQL authority, three Redis replay/retention/restart tests, application commit/reconcile, HTTP/SSE retained/expired cursor cases, local OS process-crash/resume, and live PG/Temporal crash-after-commit recovery. Offline failed-receipt ordering, same-run terminal competition, commit failure, reconciliation, late-run, Redis replay, and legacy-policy differential contracts also pass. Production Temporal service restart and browser-scale differential qualification remain outside this local gate. |
| 8.8 | Redis outage semantics | PASS (live continuity + HTTP binding) | `get_event_bus(require_redis=True)` returns stable `EVENT_BUS_DEPENDENCY_UNAVAILABLE` for missing configuration and connection failure instead of creating an in-memory bus; the reliable Redis adapter now performs a preflight `PING` before SSE headers, and the live HTTP test maps an unreachable endpoint to `503` without an in-memory fallback. The live application test closes the Redis connection after the PostgreSQL commit, verifies the Workflow still returns a committed result, reconnects, and reconciles the terminal event. |
| 8.9 | HTTP/SSE compatibility and post-commit terminal publication | PASS (contract/route) | Legacy HTTP/SSE snapshots, reliable event mapping, opt-in reliable admission, canonical `sseVersion=v1`, exclusive retained replay, missing projection `404`, expired-cursor `replay_expired/resync` without an id, dependency-unavailable `503`, and live Redis terminal publication after PostgreSQL commit pass. Full-stack differential qualification and production Temporal service qualification remain B0 gaps. |
| 8.10 | Dependency/runtime prohibition gate | PASS (static, needs final scan) | No B0 code introduces Redis lock/lease, ARQ, Celery, LangGraph, or second scheduler. Re-run import/dependency scan before commit. |
| 8.11 | Disable/rebind legacy and independent revert | PASS (rollback/rebind contract) | `tests/test_unit_b0_rollback.py` closes reliable admission, rebinds `MODULAR_RESEARCH_CORE_VERSION=legacy/v1` with `MODULAR_RELIABLE_TASK_LIFECYCLE=false`, preserves the existing Temporal run snapshot, proves the legacy facade remains callable, and proves a post-flip legacy request does not increment Temporal starts. The runbook records the staged ingress drain, active-workflow reconciliation, explicit configuration flip, and no-delete/no-schema-downgrade boundary. Production operator execution remains a deployment gate, not a code-path fallback. The independent Git revert drill also passed with an identical base tree and clean detached worktree. |

## Offline Evidence Already Available

The following commands were run against the current working tree:

```powershell
uv run --frozen pytest -q tests/test_unit_b0_reliable_task.py
  # 20 passed (current B0 reliable-task suite)

uv run --frozen pytest -q tests/test_unit_s3_redis_contract.py
  # 11 passed in 3.17s

uv run --frozen pytest -q -m "not live" -ra --durations=0
  # 955 passed, 24 deselected, 2 warnings in 108.26s

uv lock --check
# passed

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
uv run --frozen pytest -q -m live tests/test_live_b0_reliable_task.py
  # 1 passed in 6.08s (PostgreSQL 16.14; Alembic 20260824_0006_b0_reliable_task)

$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_live_b0_redis.py
  # 1 passed in 3.14s (Redis 7.x; temporary local container)

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_live_b0_application.py
  # 1 passed in 12.63s (Temporal time-skipping server + PostgreSQL 16.14 + Redis 7.x; Redis connection loss after PG commit and reconnect reconciliation)

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_live_b0_http_sse.py
  # 1 passed in 7.99s (FastAPI ASGI transport + PostgreSQL 16.14 + Redis 7.x; retained/expired replay and unreachable Redis 503)

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_temporal_qualification.py tests/test_live_b0_reliable_task.py tests/test_live_b0_redis.py tests/test_live_b0_application.py
  # 11 passed in 43.55s (qualification snapshot before HTTP/SSE and Redis retention additions)

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_temporal_qualification.py tests/test_live_b0_reliable_task.py tests/test_live_b0_redis.py tests/test_live_b0_application.py tests/test_live_b0_http_sse.py tests/test_live_b0_process_crash.py tests/test_live_b0_process_crash_reconciliation.py -ra --durations=0
  # 17 passed in 119.27s
```

The focused unit suite proves:

1. two equivalent submissions map to one task and one Temporal identity;
2. result commit precedes terminal publication and duplicate commit delivery
   returns the original receipt;
3. cancellation is sent to Temporal and does not fabricate a terminal state;
4. Workflow input, queue, policy version, Activity policy, and idempotency key
   are versioned and JSON-compatible;
5. an execution failure is committed as a PostgreSQL-authority receipt before
   its failed terminal event can be published;
6. completed and cancelled commits racing for the same
   `(task_id, workflow_id, run_id)` return one authoritative terminal status;
   and
7. reliable refine is rejected until its cross-turn identity contract is
   approved.

The worker-binding contract suite additionally proves that the Foundation
worker factory passes the Research queue's activity/workflow concurrency caps,
rejects the disabled Refresh/Media queues, and that the reliable Research
factory registers the Workflow, all reliable Activities, and the official
Pydantic AI plugin. The live application fixture uses this same factory; a
target Temporal service smoke is still required before enabling multiple
worker pools in production.

The rollback/rebind contract in
[`tests/test_unit_b0_rollback.py`](../../../../tests/test_unit_b0_rollback.py)
proves that disabling the reliable policy leaves an existing Workflow history
untouched, removes reliable logical bindings from a newly built Composition
Root, selects `LegacyResearchTaskFacade`, and accepts a legacy request without
issuing another Temporal start. It also asserts that target foundation
bindings remain disabled and that the test path performs no Evidence or
database cleanup. The deployment still has to perform the staged configuration
flip and verify all API instances before enabling the rollback in production.

The live PostgreSQL B0 suite additionally proves cross-connection admission
coalescing, task CAS hydration, same-run completed/cancelled receipt
competition, idempotent result receipts, reconciliation reads, and a newer
turn replacing a terminal projection. The S3 Redis contract suite additionally
proves exact-cursor validation and
exclusive replay for a cursor inside the retained window. A trimmed cursor and
an unknown cursor numerically inside that window both raise
`RedisReplayExpiredError`, preventing silent event gaps. The live HTTP/SSE
suite now qualifies PostgreSQL snapshot/resync wiring.

The live Redis B0 suite proves that the target Redis Streams adapter resumes
exclusively after a retained cursor and maps an unknown cursor to the stable
`SSE_REPLAY_EXPIRED`/`resync` contract. The suite uses a disposable Redis
container and does not make Redis a task or result authority.

The live application B0 suite registers the real `TemporalResearchWorkflow`
and `ReliableResearchActivities` against the SDK test server and persists task
and result facts through PostgreSQL. It injects failure on the first Redis
terminal publication after the PostgreSQL commit, verifies the Workflow still
returns a committed but unpublished result, and then reconciles the receipt to
republish the same deterministic `task.completed` event. The companion live
HTTP/SSE suite proves retained and expired cursor mapping plus a stable Redis
dependency-unavailable response. The separate process-crash suite starts a
local Temporal dev server, crashes an OS worker after Activity start, and
confirms a replacement worker completes the same Workflow history; it does
not qualify a production Temporal service.

The PG/Temporal crash-reconciliation suite uses the same local Temporal dev
server with PostgreSQL 16 and Redis 7. It confirms the result receipt and
terminal projection before a worker exits during publication, then confirms
replacement completion and one retained terminal event.

The existing authority fixtures prove the wire-level replay rules:

- [`sse_v1_contract.json`](../../../../tests/fixtures/authority/sse_v1_contract.json)
- [`sse_v1_window_replay.sse`](../../../../tests/fixtures/authority/sse_v1_window_replay.sse)
- [`sse_v1_replay_expired.sse`](../../../../tests/fixtures/authority/sse_v1_replay_expired.sse)

Ruff and targeted Pyright pass for the changed event-bus, route, and Redis
contract modules. Full-tree Pyright remains a pre-existing noisy baseline (`206 errors`,
`28 warnings`) and is not represented as passing. The complete non-live suite
passes with the count recorded above. The B0, Redis, and architecture targeted
gate includes the B0 migration contract; the HTTP/SSE/reliable route gate passes
45 tests. Live Temporal qualification is recorded below.

## Required Live Qualification

Run the isolated Temporal/Pydantic AI suite with the `live` marker. It uses
Temporal's official time-skipping test server and the deterministic Pydantic
AI `TestModel`; it does not contact a real provider or write application data.

```powershell
uv run --frozen pytest -q -m live tests/test_temporal_qualification.py
```

Recorded SDK result: `9 passed` in `39.93s` on Python `3.12.0`, Temporal SDK
`1.31.0`, Pydantic AI `2.5.1`, Windows 11 build `22631`, UTC
`2026-08-24`. The combined live command records seventeen isolated tests in
`119.27s`; retry recovery and exhaustion share one test function. The local
process-crash and PG/Temporal crash-after-commit harnesses pass; target
Temporal service restart remains a separate deployment gate.

The run is accepted only when all of the following are recorded in
[b0-temporal-qualification.md](./b0-temporal-qualification.md):

- workflow history replay has no nondeterminism failure;
- Pydantic AI model request and function-tool calls appear as Temporal
  Activities;
- transient retry recovers and exhausted retry produces one failed Workflow;
- a stopped worker resumes the same persisted history after restart;
- cancellation race produces one terminal history event;
- an old history replays under the patched deployment branch;
- the local process-crash harness resumes the same Workflow after an OS worker
  exits during an Activity;
- PG/Temporal crash-after-commit preserves the PostgreSQL receipt/projection
  and one terminal Redis event after replacement;
- duplicate Activity delivery, PG/Temporal reconciliation, and SSE retained /
  expired cursor tests pass in the application integration suite.

If the SDK test server cannot start or download in the current environment,
record the concrete environment error and mark the gate `BLOCKED`; do not
convert the offline tests into live qualification.

## Failure-Injection Matrix

The following cases are mandatory before B0 is marked complete:

| Injection point | Expected invariant |
|---|---|
| Temporal start reports duplicate Workflow ID | Return existing `workflow_id/run_id`; no second task or Redis lock |
| Execute Activity timeout/transient error | Bounded retry; no terminal success before commit |
| Execute/model/tool failure before result commit | Commit one failed receipt before failed projection/event publication |
| Validation/policy/commit-rejected Activity error | Non-retryable classification; no success terminal |
| PostgreSQL result commit unavailable | Workflow retry/failure; no success event and no competing failed receipt |
| Worker crash after PG commit, before publish | Reconciliation emits the same terminal event ID once |
| Worker crash before PG commit | Temporal history resumes; result is committed once |
| Duplicate commit Activity delivery | Same receipt/idempotency key; one result version |
| Late old-run progress/terminal | Current run projection remains unchanged/monotonic |
| Cancel versus completion race | One authoritative terminal; no request-time fabricated terminal |
| Completed/cancelled/failed writes race for one run | First `(task_id, workflow_id, run_id)` receipt wins; all contenders observe its terminal status |
| Redis stream trim/TTL/restart | `replay_expired` + `resync` snapshot; same task/turn; no new task |
| Redis outage with active Workflow | Workflow and committed PG result remain valid; new realtime request gets dependency-unavailable |
| Legacy policy differential path | Legacy six-step/event/status behavior remains unchanged when flag is off |

## Production Binding Boundary

Before enabling the flag in a multi-worker deployment, the following bindings
must be completed and tested:

- bind the existing SQLAlchemy `PostgresReliableTaskAuthority` to the
  Alembic-owned schema and qualify its transactional idempotency and same-run
  uniqueness constraints against PostgreSQL;
- qualify the `PostgresReliableTaskStore` durable owner/repository against the
  deployment schema and prove cross-worker admission/CAS without process-local
  state. The adapter expects an Alembic-owned table contract with
  `task_id` primary key, unique `workflow_id`, `status`, `turn_id`, `run_id`,
  JSONB `task_payload`, JSONB `request_payload`, and `updated_at`; it never
  creates this table at runtime;
- a Temporal `WorkflowPort` connected to the `research` queue and a worker
  registration containing the reliable Activities and, when used, the
  `PydanticAIPlugin`;
- a Redis EventBus adapter with `xrange` support and explicit replay-expired
  mapping; and
- the HTTP/SSE mapper binding that preserves ADR-0004 fields and terminal
  ordering.

No runtime table creation, second migration chain, Redis lock/lease, or
process-local production fallback is permitted while closing these gaps.

## Final Acceptance Record

Complete this table after the gates run; do not fill a `PASS` from an
unexecuted command.

| Field | Value |
|---|---|
| Implementation commit | `a234726` (PG/Temporal crash-after-commit qualification increment) |
| Qualification commit | `a234726` |
| Python/runtime | `CPython 3.12.x` |
| Temporal SDK / service | `1.31.0 / official time-skipping test server` |
| Pydantic AI | `2.5.1` |
| PostgreSQL / Redis | `16 / 7.4` |
| Focused unit count/duration | `20 passed` in the B0 reliable-task unit module; `48 passed in 16.44s` in the B0/Redis/worker/architecture/rollback targeted gate; `45 passed in 16.47s` in the HTTP/SSE/reliable route gate |
| Redis contract count/duration | `11 passed in 3.17s` offline; `3 passed in 8.20s` live B0 streams and restart smoke |
| Live qualification count/duration | `9 passed in 39.93s` |
| Live application binding count/duration | `1 passed in 12.63s`; live HTTP/SSE `1 passed in 7.99s`; local process-crash `1 passed in 19.78s`; PG/Temporal crash-after-commit `1 passed in 44.28s`; current combined Temporal/PostgreSQL/Redis/application/process gate `17 passed in 119.27s` |
| Full non-live count/duration | `955 passed, 24 deselected, 2 warnings in 108.26s` |
| `uv lock --check` | `pass` |
| Ruff / Pyright | `targeted changed-file Ruff pass; targeted Pyright 0 errors; legacy full-tree baseline remains noisy` |
| `openspec validate define-modular-architecture --strict` | `pass` |
| Revert drill | `pass for qualification head; see evidence below and rollback runbook` |

B0 is complete only when all required rows are `pass`, the production binding
boundary is closed, and the independent revert drill has been recorded.

## Independent Revert Drill Evidence

The implementation commit was independently reverted in a detached worktree
using the procedure in `b0-reliable-task-rollback.md`:

| Revert evidence | Value |
|---|---|
| Base commit/tree | `4986922 / c8ed0ebbf9db5a5e0e1a02771277760aa54f27e7` |
| B0 head/tree | `a3fcb6d / 20d872ed465c2fbfbcfc522ded9615a181287315` |
| Generated revert commits | `none (detached worktree used --no-commit revert); worktree removed` |
| Reverted tree equals base | `pass (reverted a3fcb6d and 2590171; index matched 4986922)` |
| Reverted test count/duration | `not rerun; tree identity and empty diff were the drill assertions` |
| Empty diff and clean status | `pass` |
| Worktree cleanup/prune | `pass` |
