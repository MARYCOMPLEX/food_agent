# B0 Temporal And Pydantic AI Qualification

Status: Partial pass - SDK, application, local process-crash, and PG/Temporal crash-reconciliation qualification passed; target-service and restart gates remain pending

Milestone: B0 (`Reliable Task Semantics`)

## Scope

This record is intentionally separate from the offline B0 contract tests. It
qualifies the locked Temporal Python SDK `1.31.0` and Pydantic AI Slim `2.5.1`
integration using the official SDK time-skipping test server and deterministic
Pydantic AI `TestModel`. It does not qualify a production Temporal deployment,
provider availability, or the PostgreSQL authority adapter. The process-crash
case uses a real local Temporal dev server and two OS worker processes; it does
not qualify a production Temporal service rollout.

Source suite:

- [`tests/test_temporal_qualification.py`](../../../../tests/test_temporal_qualification.py)
- [`tests/test_live_b0_process_crash.py`](../../../../tests/test_live_b0_process_crash.py)
- [`tests/test_live_b0_process_crash_reconciliation.py`](../../../../tests/test_live_b0_process_crash_reconciliation.py)
- [Temporal Python SDK documentation](https://docs.temporal.io/develop/python)
- [Pydantic AI Temporal durable execution documentation](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/)

## Environment And Command

Run with Python 3.12 and the committed lockfile:

```powershell
uv sync --frozen --python 3.12
uv run --frozen pytest -q -m live tests/test_temporal_qualification.py
```

The `live` marker is deliberate. Do not include this suite in the offline
`unit or integration` gate, and do not claim qualification if the ephemeral
Temporal server cannot start or download. Record the exact error and the
runtime environment in the table below.

## Qualification Cases

| Case | Required observation | Status |
|---|---|---|
| Determinism/replay | Persisted history replays with `replay_failure is None`; one echo Activity is scheduled/completed | PASS |
| Model/tool Activity mapping | Official `TemporalAgent` emits model-request and function-tool Activities, then completes structured output | PASS |
| Retry recovery | Transient Activity succeeds on the third bounded attempt | PASS |
| Retry exhaustion | Exhausted Activity produces one failed Workflow and the configured attempt count | PASS |
| Worker stop/restart | Clean worker stop, fresh worker execution, and explicit history replay pass; this is not a process-level crash test | PASS (limited) |
| Process-level worker crash | First OS worker exits with code 71 after Activity start; replacement worker completes the same Workflow and persisted history | PASS (local Temporal dev server) |
| PG/Temporal crash-after-commit | PostgreSQL receipt/projection survive an OS worker exit with code 72 before publish; replacement completes the same Workflow and Redis has one terminal event | PASS (live PostgreSQL/Redis + local Temporal dev server) |
| Reliable cancellation | Reliable Research signal reaches cancellation Activity, commits a receipt, maps `task.cancelled`, and publishes one idempotent terminal event | PASS |
| Cancellation race | Cancel versus slow Activity yields exactly one terminal history event | PASS |
| Deployment patch | Old history replays under `workflow.patched()` and new execution selects the new branch | PASS |
| Application duplicate start | Temporal adapter concurrent starts resolve to the existing run; no Redis lock path | PASS (SDK adapter) |
| PG commit/reconcile | Commit receipt is idempotent; application failure injection after commit republishes the same terminal ID | PASS (application live) |
| SSE retained cursor | Live FastAPI/Redis route resumes exclusively from `Last-Event-ID` without creating a task | PASS (application live) |
| SSE expired cursor | Live FastAPI/Redis route maps stream loss to `replay_expired/resync` with the PostgreSQL snapshot | PASS (application live) |
| Redis service restart | Redis restart either preserves a retained cursor or returns `replay_expired`; no duplicate event is delivered | PASS (live Redis service) |

The fifteen observations listed here are covered by sixteen isolated
SDK/application tests in the combined live command; retry recovery and retry
exhaustion share one test function, and the Redis retention/TTL/restart
coverage uses three tests. The process-crash test proves that a replacement OS worker resumes
the same Workflow ID after the first worker exits with code 71. Temporal may
reassign an in-flight Activity task without appending a second
`ACTIVITY_TASK_STARTED` event; the test therefore requires an Activity start
and completion plus `WORKFLOW_EXECUTION_COMPLETED`, rather than assuming a
retry-event shape. The PG/Temporal crash-after-commit test verifies the
committed receipt and projection before replacement, then asserts one terminal
Redis event after recovery. The application rows are qualified separately by
the B0 live PostgreSQL, Redis, and HTTP/SSE suites. A real deployed Temporal
service, restart smoke, and production lifespan binding remain outside this
record.

The reliable cancellation case uses graceful signal handling: a signal that
arrives during an Activity waits for that Activity to finish, then the
Workflow invokes the cancellation Activity at the next deterministic boundary.
Only the committed cancellation receipt can produce the `task.cancelled`
terminal event; the request path never fabricates one.

## Evidence Capture

Fill this section from the command output, preserving failures verbatim:

| Field | Value |
|---|---|
| Date/time (UTC) | `2026-08-24` |
| Host/OS | `DESKTOP-OVTL170 / Windows-11-10.0.22631-SP0` |
| Python | `3.12.0` |
| Temporal SDK | `1.31.0` |
| Pydantic AI | `2.5.1` |
| Test server mode | `time-skipping` |
| Command | `uv run --frozen pytest -q -m live tests/test_temporal_qualification.py -ra` |
| Result | `8 passed` |
| Duration | `36.54s` (current frozen-lockfile run) |
| Failure output | `none for the eight SDK tests or the sixteen-test combined B0 live gate; real Temporal service qualification remains out of scope` |

If a future environment blocks the test server download, mark `Result` as
`blocked`, retain the command and exception, and leave unexecuted case
statuses `PENDING`. A blocked live run is evidence of an environment
prerequisite, not evidence that Temporal replay is correct.

## Acceptance Rules

The qualification passes only if:

1. every case marked `Required observation` has an explicit passing assertion;
2. no replay reports a nondeterminism failure;
3. retry counts match the configured maximum attempts;
4. the SDK worker stop/restart check and explicit history replay pass, and the
   local process-level crash harness proves an in-flight Workflow resumes under
   the same Workflow ID; target Temporal service restart qualification remains
   a separate deployment gate;
5. exactly one terminal history event is observed in the cancellation race;
6. the reliable application cancellation test commits the authoritative
   cancellation receipt and emits one `task.cancelled` event;
7. the patched deployment replays old history before taking the new branch;
8. application integration proves PostgreSQL commit-before-terminal and Redis
   replay-expiry behavior; and
9. no test uses an in-memory authority as a production binding or introduces a
   second task runtime.

When these conditions are met, copy the exact result and commit SHA into
[b0-reliable-task-semantics.md](./b0-reliable-task-semantics.md), then update
ADR-0011's status and the decision index. Until then, B0 remains an opt-in
implementation candidate.
