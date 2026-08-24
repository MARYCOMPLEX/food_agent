# B0 Temporal And Pydantic AI Qualification

Status: Partial pass - SDK and reliable cancellation qualification passed; process-crash and external-store gates pending

Milestone: B0 (`Reliable Task Semantics`)

## Scope

This record is intentionally separate from the offline B0 contract tests. It
qualifies the locked Temporal Python SDK `1.31.0` and Pydantic AI Slim `2.5.1`
integration using the official SDK time-skipping test server and deterministic
Pydantic AI `TestModel`. It does not qualify a production Temporal deployment,
provider availability, or the PostgreSQL authority adapter.

Source suite:

- [`tests/test_temporal_qualification.py`](../../../../tests/test_temporal_qualification.py)
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
| Reliable cancellation | Reliable Research signal reaches cancellation Activity, commits a receipt, maps `task.cancelled`, and publishes one idempotent terminal event | PASS |
| Cancellation race | Cancel versus slow Activity yields exactly one terminal history event | PASS |
| Deployment patch | Old history replays under `workflow.patched()` and new execution selects the new branch | PASS |
| Application duplicate start | Temporal adapter concurrent starts resolve to the existing run; no Redis lock path | PASS (SDK adapter) |
| PG commit/reconcile | Commit receipt is idempotent; crash-after-commit republish uses the same terminal ID | PENDING |
| SSE retained cursor | `Last-Event-ID` resumes exclusively without creating a task | PENDING |
| SSE expired cursor | Trim/TTL/restart returns `replay_expired/resync` and the PG snapshot | PENDING |

The first nine observations are implemented by eight isolated SDK/application tests; retry
recovery and retry exhaustion share one test function. The worker row
intentionally does not claim an in-flight process crash: the Windows
Temporal test server's clean shutdown/restart path is the reproducible SDK
check, while a process-level crash harness remains a deployment gate. The
remaining rows require the application integration harness and a real
PostgreSQL/Redis test stack; the SDK suite alone cannot prove them.

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
| Duration | `38.12s` (current frozen-lockfile run after reliable cancellation and event-bus changes; prior runs `10.25s`-`39.42s`) |
| Failure output | `none for the eight SDK/application tests; process-crash and external PostgreSQL/Redis/SSE integration remain out of scope` |

If a future environment blocks the test server download, mark `Result` as
`blocked`, retain the command and exception, and leave unexecuted case
statuses `PENDING`. A blocked live run is evidence of an environment
prerequisite, not evidence that Temporal replay is correct.

## Acceptance Rules

The qualification passes only if:

1. every case marked `Required observation` has an explicit passing assertion;
2. no replay reports a nondeterminism failure;
3. retry counts match the configured maximum attempts;
4. the SDK worker stop/restart check and explicit history replay pass; a
   separate process-level crash harness must prove an in-flight Workflow
   resumes under the same Workflow ID before B0 is complete;
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
