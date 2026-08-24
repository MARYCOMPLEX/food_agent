# B4 Worker Isolation Rollback Runbook

## Purpose

Stop background Refresh or Media execution independently while preserving
Research capacity, Temporal history, and already published evidence versions.

## Invariants

1. The `research`, `refresh`, and `media` queue names remain distinct.
2. Disabling a queue changes admission only; it does not delete Temporal
   history or rewrite PostgreSQL task/evidence facts.
3. A retry is an explicit operator action using the same stable Workflow ID and
   idempotency key. It is never moved into a cache or a broker dead-letter
   queue.
4. Failed candidate work does not activate a Bundle pointer. Existing Bundle
   versions remain readable.

## Procedure

1. Set `MODULAR_REFRESH_ENABLED=false` or `MODULAR_MEDIA_ENABLED=false` for the
   affected workload and roll the worker process. Keep the Research quota
   unchanged.
2. Stop the corresponding worker pool after its current Activity reaches a
   deterministic boundary. For an urgent stop, terminate only the selected
   Workflow IDs through `WorkflowOperatorPort` and record the reason.
3. Inspect retry-exhausted executions with `list_failed_workflows` filtered by
   the affected queue. Retry only with the original deterministic
   `WorkflowRetryRequest`, or terminate with an explicit
   `WorkflowTerminateRequest`.
4. Verify Research admission and capacity are unchanged, and that old Bundle
   reads continue to serve the last committed pointer.
5. Re-enable the queue only after its workflow/activity registrations and B4
   failure gates pass. Do not delete retained history or orphan audit records
   as part of rollback. Cleanup must re-check PostgreSQL references, retention,
   and legal holds.

## Verification

```powershell
uv run --frozen pytest -q tests/test_unit_b4_worker_contracts.py tests/test_unit_b0_worker_binding.py
```
