# ADR-0011: Reliable Research Task Semantics

Status: Draft - contract decision recorded; implementation qualification pending

Date: 2026-08-24

Owners: Architecture + Platform Runtime + Data Platform + API

Decides: B0 tasks 8.1-8.11 and the reliable-lifecycle portion of OQ-21

## Context

S2-S5 intentionally preserve several legacy task defects, including an error
event followed by a completed projection and a same-session stream that can
replay an older terminal. Those behaviors are evidence for the
`legacy-task/v1` policy; they are not a durable execution contract. B0 adds a
separate policy with one semantic owner, a Temporal execution history, a
PostgreSQL result barrier, and an idempotent event projection. The policy must
be independently selectable and reversible without changing the legacy wire
contract.

The decision is constrained by:

- [ADR-0004](./ADR-0004-http-sse-authority.md), which remains the authority for
  HTTP and SSE mapping;
- [ADR-0009](./ADR-0009-legacy-gap-disposition.md), which requires the legacy
  divergence to remain characterized while B0 is opt-in;
- the task lifecycle and persistence requirements in
  [modular-research-core](../specs/modular-research-core/spec.md); and
- the machine-readable contract in
  [reliable_task_semantics_v1.json](../fixtures/reliable_task_semantics_v1.json).

This ADR records the target semantics. A B0 milestone is not considered
qualified until the verification gates in
[b0-reliable-task-semantics.md](../verification/b0-reliable-task-semantics.md)
are complete.

## Decision 1: Independent, Versioned Policies

The two task policies are different contracts and MUST never be selected by
implicit capability detection:

| Boundary | Legacy policy | Reliable policy |
|---|---|---|
| Task policy | `legacy-task/v1` | `reliable-task/v1` |
| Workflow type | process/background legacy facade | `research-task/v1` |
| Activity contract | legacy implementation-defined | `research-activity/v1` |
| Default binding | enabled for existing deployments | opt-in through `reliable_task_lifecycle` |
| Rollback | n/a | bind `LegacyResearchTaskFacade` and stop new Temporal admissions |

`completed`, `failed`, and `cancelled` are the only reliable terminal task
statuses. A reliable task/turn has at most one terminal transition. A successful
terminal is not implied by a normal Python return: it requires an authoritative
PostgreSQL result receipt. Legacy status/event anomalies remain observable only
when the legacy policy is selected.

`REFRESH` remains owned by B2. B0 handles query, recover, cancellation, and
retry of a failed/cancelled reliable task. It does not invent an external
refresh or cancel wire route.

B0 only guarantees single-flight for equivalent derived identities. A refine
request whose query or target changes can currently derive a different task
hash; it MUST NOT be presented as the same task/turn until a dedicated refine
identity contract is approved. The current policy enforces this boundary by
rejecting reliable refine admission with
`RELIABLE_REFINE_IDENTITY_UNAPPROVED`. Until that decision is made, refine
requests remain on the legacy policy and the B0 qualification suite covers
only equivalent-request deduplication.

## Decision 2: Stable Identity And Temporal Single-Flight

The stable task identity is derived in this order:

1. a non-empty `public_inputs.idempotency_key`, when supplied;
2. the canonical operation/domain/query/target-task/query-family/session/tenant
   and compatibility version tuple; or
3. `request_id` only for an anonymous one-shot request with no session.

The identity is encoded as a canonical, sorted JSON object and hashed into
`task-<sha256-prefix>`. The corresponding Temporal Workflow ID is
`research:<task_id>`, and the reliable command idempotency key is `task_id`.
Temporal's Workflow ID is the single-flight authority. A duplicate start MUST
return the existing task/workflow identity (including when Temporal reports
`WorkflowAlreadyStartedError`) and MUST NOT acquire a Redis lock, lease, or
Redlock. Redis MUST NOT decide whether a task exists.

The production task authority MUST enforce the same identity with a durable
PostgreSQL uniqueness/CAS boundary. The current in-memory Coordinator and test
doubles prove sequential behavior only; concurrent admission qualification is
still a B0 gate.

## Decision 3: State Ownership, Checkpoint, And Commit Barrier

`ResearchCoordinator` is the only component that computes reliable
`ResearchTask`/`TaskEvent` semantic transitions. Experience routes issue
commands and map results. Temporal workers execute Activities. Foundation
adapters persist or publish; they do not invent task state.

Temporal history is the only executable checkpoint. PostgreSQL
`task_progress_projection` is a query-only business projection and result
authority; it MUST NOT be read as instructions for Workflow replay. A
reconciler joins `task_id`, `workflow_id`, and `run_id` and handles the
following deterministic sequence:

```text
admit -> start/attach Workflow -> progress projection
      -> execute/model/tool Activities
      -> PostgreSQL result commit (idempotency key)
      -> Coordinator terminal projection
      -> terminal EventBus/SSE publication
```

The terminal EventBus publication is rebuildable hot state. Completed,
cancelled, and failed terminals each require an authoritative PostgreSQL
receipt before the Coordinator terminal projection and EventBus publication.
If execution fails before the result barrier, the failure Activity commits a
failed receipt and only then publishes `task.failed`. If publication fails
after any terminal receipt, reconciliation republishes the same deterministic
event ID.

All terminal writes for one `(task_id, workflow_id, run_id)` compete at one
idempotency/CAS boundary. The first receipt wins; later completed, cancelled,
or failed attempts return that receipt and its terminal status instead of
creating a second terminal. If the PostgreSQL result commit itself fails, the
Coordinator MUST NOT publish success or create a competing failed receipt; the
Workflow follows its retry/non-retryable policy. A worker crash between commit
and publication MUST be recoverable without a second result or terminal event.
A late progress or terminal operation from an older `run_id` MUST NOT move a
newer projection backwards.

The PostgreSQL adapter must make result/failure/cancellation commit and its
idempotency receipt transactional with the business fact. The current
SQLAlchemy adapter uses `ON CONFLICT DO NOTHING` and reads the existing row by
idempotency key or complete run identity; its required Alembic uniqueness
constraint and transaction semantics remain a live PostgreSQL qualification
gate. The in-memory authority in `reliable_task.py` is a test double and is not
a production authority.

## Decision 4: Activities, Agent Runtime, And Determinism

`TemporalResearchWorkflow` contains only deterministic validation,
Activity scheduling, retry/cancel control, and version markers. Connector,
Repository, result-commit, event publication, and all network/LLM/object-store
I/O run in Activities. Activity arguments and outputs cross the boundary as
JSON-compatible versioned contracts.

Pydantic AI V2 is the sole Agent runtime. The official `TemporalAgent` and
`PydanticAIPlugin` integration maps model requests and typed function-tool
calls to bounded Activities. A normal Pydantic AI loop, provider client,
randomness, wall-clock access, or other non-deterministic I/O MUST NOT run
directly in the Workflow sandbox. Domain Packs may declare typed tools but may
not create another Agent, queue, checkpoint, or worker runtime.

The reliable Activity policy is versioned and inspectable:

- task queue: `research`;
- Activity start-to-close timeout: 300 seconds by default;
- heartbeat timeout: 30 seconds;
- retry initial/max interval: 1/30 seconds;
- exponential backoff coefficient: 2.0;
- maximum attempts: 3;
- non-retryable types include validation, policy denial, malformed contract,
  and rejected result commit errors.

These defaults are policy fixtures, not a substitute for provider-specific
capacity review. Any change requires a versioned policy/lockfile review and
the same replay and failure-injection gates.

## Decision 5: Workload Isolation

Research uses the `research` Temporal Task Queue. `refresh` and `media` are
reserved as distinct queues with independent worker pools, quotas, and
priority controls; B4 owns their activation. A shared unprioritized broker,
ARQ, Celery, LangGraph checkpoint, or Redis job facade is prohibited. A
retry-exhausted Workflow remains queryable as a failed execution and follows
the operator recovery procedure; no broker-style second dead-letter authority
is introduced.

## Decision 6: Cancellation, Retry, And Reconciliation

Cancellation is a Temporal command. The API/policy MUST NOT fabricate a
terminal projection at request time. A cancellation Activity commits a
cancelled result receipt and only then asks the Coordinator to apply the
`cancelled` terminal transition. A cancellation racing with completion is
resolved together with failed-terminal races by the authoritative
`(task_id, workflow_id, run_id)` idempotency/CAS boundary and yields exactly one
terminal status. A retry of a failed/cancelled task reuses the stable task
identity but receives a new Temporal `run_id` and a new turn; old-run events
are ignored for current projection updates.

Cancellation is graceful at the Workflow boundary: when a signal arrives
while an Activity is running, the current Activity is allowed to finish. The
Workflow observes the signal at the next deterministic Activity boundary,
then runs the cancellation Activity and publishes the authoritative terminal
event. This bounded wait is part of the reliable cancellation contract and
does not create a request-time terminal projection.

Reconciliation is keyed by `(task_id, workflow_id, run_id)` and MUST classify
at least these cases:

| Observed state | Required action |
|---|---|
| Temporal running, no PG result | continue/retry Workflow; do not publish success |
| PG completed/cancelled/failed receipt committed, terminal event absent | finalize/reconcile and republish deterministic event |
| PG receipt absent because Workflow or commit Activity failed/exhausted | expose Workflow failure and operator retry/terminate choice; do not invent a terminal business fact |
| Old run sends progress after new run attached | ignore for current projection |
| Event stream unavailable after commit | preserve PG/Temporal state; rebuild Redis/SSE projection later |

## Decision 7: Redis And SSE Boundary

Redis is a rebuildable projection only. Reliable SSE uses the approved
`Last-Event-ID` contract: a retained cursor resumes exclusively; an unknown,
trimmed, expired, or post-restart cursor returns one `replay_expired`/`resync`
control event with the authoritative PostgreSQL task snapshot and closes the
connection. It preserves the same task/turn and never starts duplicate
research. The stream target remains one hour and `MAXLEN 1000`.

Redis outage does not invalidate a started Temporal Workflow or a committed
PostgreSQL result. A new request that needs Redis-backed live session/SSE
state returns the stable `dependency-unavailable` classification; it MUST NOT
silently fall back to process-local state in a multi-worker deployment.

## Decision 8: Rollout And Reversal

The reliable policy is enabled only when the Composition Root receives an
explicit Temporal/PostgreSQL policy adapter and
`reliable_task_lifecycle=true`. Missing adapters are a configuration error,
not permission to use an in-memory fallback. Rollback sets the flag to false,
stops new reliable admissions, preserves Temporal history and PostgreSQL
facts, and rebinds the legacy task facade. The detailed sequence and operator
checks are in [b0-reliable-task-rollback.md](../runbooks/b0-reliable-task-rollback.md).

No B0 schema migration, Evidence Bundle mutation, object deletion, or
irreversible data conversion is allowed. Temporal history and committed task
facts are retained for audit and reconciliation.

## Evidence And Open Gates

The offline contract evidence currently covers stable identity, duplicate
submission, completed and failed commit-before-publication, duplicate Activity
delivery, same-run terminal competition, cancellation command semantics,
reliable refine rejection, versioned Workflow input, and retained/unknown
Redis cursor classification:

- `tests/test_unit_b0_reliable_task.py`;
- `tests/test_unit_s3_redis_contract.py`;
- `tests/fixtures/authority/sse_v1_contract.json`;
- `tests/fixtures/authority/sse_v1_replay_expired.sse`; and
- [reliable_task_semantics_v1.json](../fixtures/reliable_task_semantics_v1.json).

The isolated SDK/application qualification now passes seven tests covering
eight observations (history replay, Pydantic AI model/tool Activities,
retry/exhaustion, clean worker restart plus replay, SDK cancellation race,
reliable cancellation receipt/event, and patched deployment replay). It does
not prove an in-flight process crash or external PG/Redis/SSE integration;
those remain explicit gates in the verification record.

The following remain qualification gates before changing this ADR to fully
accepted implementation status: live PostgreSQL transaction/uniqueness and a
durable task owner, concurrent admission and live duplicate Workflow start,
approval of any cross-turn reliable refine identity, a process-level in-flight
worker failure harness, PostgreSQL/Temporal reconciliation and snapshot wiring,
HTTP/SSE mapper/resync integration, Redis-outage behavior, and the independent
B0 revert drill. The Redis `xrange` retained, trimmed, and unknown-cursor unit
contract is covered by the S3 foundation test suite; it does not replace the
HTTP/SSE integration gate.

Rejected alternatives are Redis locks/leases, a second queue runtime, using
`task_progress_projection` as a checkpoint, publishing terminal success before
the PostgreSQL receipt, and treating Pydantic AI's ordinary loop as Workflow
code. Each creates a second authority or breaks deterministic recovery.
