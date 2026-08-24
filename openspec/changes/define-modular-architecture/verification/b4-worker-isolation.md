# B4 Worker Isolation Contract

Status: PASS for task 12.1; Refresh and Media execution behavior remains
disabled until later B4 tasks register their workflows and activities.

## Implemented Boundary

- Temporal owns the `research`, `refresh`, and `media` Task Queues.
- Each queue has an independent `TemporalWorkerQuota` with activity capacity,
  workflow-task capacity, priority, and an explicit enabled flag.
- Research remains enabled by default. Refresh and Media require an explicit
  enabled quota and use separate Composition Root factories.
- `TemporalExecutionPolicy` is the shared contract for Activity timeout,
  heartbeat, retry intervals, backoff, maximum attempts, and non-retryable
  failures. `ReliableTaskConfig` specializes it only with Research identity.
- `WorkflowOperatorPort` exposes failed-execution inspection, explicit retry
  with the original deterministic `WorkflowStart`, and termination. It keeps
  the Workflow ID/idempotency key and does not introduce a broker queue.

## Verification

```powershell
uv run --frozen pytest -q tests/test_unit_b4_worker_contracts.py
uv run --frozen pytest -q tests/test_unit_b0_worker_binding.py tests/test_unit_b0_reliable_task.py
uv run --frozen pytest -q tests/test_unit_architecture_boundaries.py
uv run --frozen ruff check src/xhs_food tests/test_unit_b4_worker_contracts.py
```

The unit and architecture gates assert queue isolation, default-off
activation, quota ordering, shared policy inheritance, visibility filtering,
same-identity retry, and Temporal termination. No production worker is started
by this contract test; live Temporal qualification belongs to the later B4
failure-injection gate.
