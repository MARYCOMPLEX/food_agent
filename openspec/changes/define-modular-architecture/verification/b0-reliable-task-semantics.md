# B0 Reliable Task Semantics Verification

Status: Draft - offline, SDK, PostgreSQL authority, and Redis Streams evidence recorded; Temporal/HTTP production integration pending

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
| Executable checkpoint | Temporal history | live SDK history replay passes; target-service and process-crash qualification pending |
| Business result/projection | PostgreSQL adapter port | SQLAlchemy adapter, Alembic 0006 schema, cross-connection admission/CAS, terminal receipts, same-run conflict handling, and live projection ordering pass; crash-after-commit reconciliation remains pending |
| Hot replay state | Redis Streams, one hour/1000 entries | Redis target contract plus live Redis 7 exclusive replay and unknown-cursor expiry; trim/TTL outage and HTTP resync remain pending |
| Public HTTP/SSE | existing mapper and ADR-0004 | authority fixtures and mapper suite (pending B0 integration) |

The in-memory `InMemoryReliableTaskAuthority` and
`InMemoryReliableTaskEventPublisher` are explicit test doubles. They are not
valid production bindings. The Composition Root rejects an enabled reliable
flag without an explicitly injected Temporal/PostgreSQL policy.

## Gate Status By Task

| Task | Gate | Status | Evidence or remaining work |
|---|---|---|---|
| 8.1 | Independent policy versions, terminal set, old-terminal and mapper rules | PASS (contract/mapper) | `legacy-task/v1`, `reliable-task/v1`, `research-task/v1`, `research-activity/v1`; normative fixture, ADR-0011, and `ReliableEventMapper` contract tests. HTTP/SSE route binding remains the 8.9 B0 gate. |
| 8.2 | Opt-in Research Workflow, stable Workflow ID, duplicate start/single-flight | PARTIAL | Stable identity, same-process concurrent admission coalescing, durable-owner hydration, Temporal adapter duplicate-start handling, and cross-connection PostgreSQL admission are covered. Reliable refine is rejected with `RELIABLE_REFINE_IDENTITY_UNAPPROVED` until its cross-turn identity contract is approved. Live Temporal duplicate-start qualification remains pending. |
| 8.3 | Coordinator-only transitions, Temporal checkpoint, PG commit barrier, reconciliation | PARTIAL | Coordinator-only transitions, `ReliableTaskStorePort`, Alembic-owned schema, PostgreSQL admission/CAS, projection turn ordering, completed/cancelled/failed receipts, same-run terminal competition, late-run guards, idempotent commit/reconcile, and reconciliation Activity are covered; live PostgreSQL qualification now passes. Crash-after-commit reconciliation against Temporal remains pending. |
| 8.4 | Pydantic AI Temporal integration, bounded Activities, retry/timeout/heartbeat/cancel policy | PASS (SDK qualification) | Factory, plugin, JSON boundary, policy constants, and the official live model/tool Activity replay and determinism suite pass; production worker/provider rollout remains a separate gate. |
| 8.5 | Separate Research queue and reserved Refresh/Media queues | PARTIAL (structural) | `TemporalTaskQueues` now carries explicit per-queue `TemporalWorkerQuota`, enables only `research` by default, and rejects disabled `refresh/media` execution until B4. Real Temporal worker registration, concurrency caps, and priority/isolation smoke remain pending with the target service. |
| 8.6 | PG projection + Temporal history + Redis replay/resync | PARTIAL | Fake and live Redis 7 `xrange`/`xread` contracts prove exact retained-cursor validation, exclusive continuation, and `replay_expired` for unknown cursors; Alembic-backed PostgreSQL projection ordering passes through the reliable Composition-Root adapter, and reliable `TaskEvent` values have an EventBus publisher adapter. Redis trim/TTL/restart and HTTP/SSE resync integration remain pending. |
| 8.7 | Failure-injection and differential suite | PARTIAL | Eight live SDK/application tests pass: determinism/replay, adapter duplicate start, model/tool Activities, retry/exhaustion, clean worker restart+replay, SDK cancellation race, reliable cancellation receipt, and patch replay. Offline failed-receipt ordering, same-run terminal competition, commit failure, reconciliation, late-run, and Redis replay contracts also pass. Process-level in-flight crash, duplicate Activity against a live worker, PG/Temporal integration, and SSE/HTTP cases remain pending. |
| 8.8 | Redis outage semantics | PARTIAL | `get_event_bus(require_redis=True)` returns stable `EVENT_BUS_DEPENDENCY_UNAVAILABLE` for missing configuration and connection failure instead of creating an in-memory bus; live Redis 7 stream behavior passes and legacy callers retain their characterized fallback. Live Workflow continuity after Redis outage, persistent-result reads, and new HTTP/SSE admission mapping remain pending. |
| 8.9 | HTTP/SSE compatibility and post-commit terminal publication | PARTIAL (offline) | Legacy HTTP/SSE snapshots, reliable event mapping, and a reliable-mode SSE dependency-unavailable `503` route contract pass; route selects `require_redis=True` from the Composition Root app-state flag. PostgreSQL-backed snapshot/resync, same task/turn reconnect, terminal publication against live Redis, and full reliable-vs-legacy differential behavior remain pending. |
| 8.10 | Dependency/runtime prohibition gate | PASS (static, needs final scan) | No B0 code introduces Redis lock/lease, ARQ, Celery, LangGraph, or second scheduler. Re-run import/dependency scan before commit. |
| 8.11 | Disable/rebind legacy and independent revert | PARTIAL | The independent Git revert drill passed for implementation head `796a6c9` against `3b59232` with an identical base tree and clean detached worktree; production flag flip/rebind and runtime no-new-admission checks remain pending. |

## Offline Evidence Already Available

The following commands were run against the current working tree:

```powershell
uv run --frozen pytest -q tests/test_unit_b0_reliable_task.py
  # 20 passed (current B0 reliable-task suite)

uv run --frozen pytest -q tests/test_unit_s3_redis_contract.py
  # 10 passed in 3.49s

uv run --frozen pytest -q -m "not live" -ra --durations=0
  # 859 passed, 16 deselected, 2 warnings in 55.35s

uv lock --check
# passed

$env:B0_POSTGRES_URL='postgresql+asyncpg://postgres:postgres@localhost:55432/xhs_food_agent'
uv run --frozen pytest -q -m live tests/test_live_b0_reliable_task.py
  # 1 passed in 6.52s (PostgreSQL 16.14; Alembic 20260824_0006_b0_reliable_task)

$env:B0_REDIS_URL='redis://localhost:56380/0'
uv run --frozen pytest -q -m live tests/test_live_b0_redis.py
  # 1 passed in 3.33s (Redis 7.x; temporary local container)
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

The live PostgreSQL B0 suite additionally proves cross-connection admission
coalescing, task CAS hydration, same-run completed/cancelled receipt
competition, idempotent result receipts, reconciliation reads, and a newer
turn replacing a terminal projection. The S3 Redis contract suite additionally
proves exact-cursor validation and
exclusive replay for a cursor inside the retained window. A trimmed cursor and
an unknown cursor numerically inside that window both raise
`RedisReplayExpiredError`, preventing silent event gaps. PostgreSQL
snapshot/resync wiring is still an integration gate.

The live Redis B0 suite proves that the target Redis Streams adapter resumes
exclusively after a retained cursor and maps an unknown cursor to the stable
`SSE_REPLAY_EXPIRED`/`resync` contract. The suite uses a disposable Redis
container and does not make Redis a task or result authority.

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

Recorded SDK result: `8 passed` in `38.25s` on Python `3.12.0`, Temporal SDK
`1.31.0`, Pydantic AI `2.5.1`, Windows 11 build `22631`, UTC
`2026-08-24`. The first nine qualification observations are implemented by
eight isolated tests; retry recovery and exhaustion share one test function.
The worker case is clean stop/restart plus explicit
history replay, not an in-flight process crash; that deployment harness and
the application PG/Redis/SSE cases remain required.

The run is accepted only when all of the following are recorded in
[b0-temporal-qualification.md](./b0-temporal-qualification.md):

- workflow history replay has no nondeterminism failure;
- Pydantic AI model request and function-tool calls appear as Temporal
  Activities;
- transient retry recovers and exhausted retry produces one failed Workflow;
- a stopped worker resumes the same persisted history after restart;
- cancellation race produces one terminal history event;
- an old history replays under the patched deployment branch;
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
| Implementation commit | `796a6c9` (reliable SSE dependency gate; live PostgreSQL qualification pending) |
| Qualification commit | `796a6c9` |
| Python/runtime | `CPython 3.12.x` |
| Temporal SDK / service | `1.31.0 / official time-skipping test server` |
| Pydantic AI | `2.5.1` |
| PostgreSQL / Redis | `16 / 7.4` |
| Focused unit count/duration | `20 passed` in the B0 reliable-task unit module; `42 passed in 14.17s` in the B0/Redis/architecture targeted gate; `45 passed in 16.47s` in the HTTP/SSE/reliable route gate |
| Redis contract count/duration | `10 passed in 3.49s` offline; `1 passed in 3.33s` live B0 stream |
| Live qualification count/duration | `8 passed in 39.07s` |
| Full non-live count/duration | `859 passed, 16 deselected, 2 warnings in 55.35s` |
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
| Base commit/tree | `3b59232 / 5d321b13340cd971f816d7cb03770cbbc02b0f7e` |
| B0 head/tree | `796a6c9 / d2ecb7effa410f26a57db3da486511f545e478be` |
| Generated revert commits | `none (detached worktree used --no-commit revert); worktree removed` |
| Reverted tree equals base | `pass` |
| Reverted test count/duration | `not rerun; tree identity and empty diff were the drill assertions` |
| Empty diff and clean status | `pass` |
| Worktree cleanup/prune | `pass` |
