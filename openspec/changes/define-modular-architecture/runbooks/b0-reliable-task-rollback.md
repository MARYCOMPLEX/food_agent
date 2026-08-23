# B0 Reliable Task Rollback Runbook

## Purpose

Return Research admission and API/task handling to the S5 legacy policy while
preserving Temporal history, PostgreSQL business facts, task projections,
Redis streams, and all existing HTTP/SSE compatibility behavior. B0 is an
opt-in behavior milestone; rollback must not delete durable evidence or
silently replace it with process-local state.

This runbook applies to a B0 candidate selected by
`reliable_task_lifecycle=true`. It does not roll back B1 schema changes, B2
Query Family behavior, or B4 Refresh/Media workers.

## Rollback Invariants

1. No new reliable Workflow is admitted after the rollback gate is closed.
2. A Workflow that already has a PostgreSQL result receipt is never rewritten
   as an uncommitted legacy success.
3. A Workflow without a result receipt is not marked successful in Redis or a
   legacy in-memory projection.
4. Temporal history and PostgreSQL task/result facts remain available for
   reconciliation and audit.
5. Existing legacy HTTP/SSE routes, envelopes, event IDs, and known legacy
   characterization behavior remain unchanged.
6. No Redis lock, lease, Redlock, queue replacement, database downgrade, or
   object/Evidence deletion is performed as part of B0 rollback.

## Bindings

| Concern | B0 candidate | Rollback binding |
|---|---|---|
| Reliable flag | `MODULAR_RELIABLE_TASK_LIFECYCLE=true` | `false` |
| Research core | shared Coordinator with reliable policy | `MODULAR_RESEARCH_CORE_VERSION=legacy/v1` |
| New task admission | Temporal `research` Workflow | legacy task facade only |
| Existing Temporal history | retained and reconciled | retained, no new admission |
| Business authority | PostgreSQL result/task repository | retained; legacy readers continue |
| Hot replay | Redis target EventBus | existing legacy stream/state adapter |

The Composition Root must be restarted with an explicit legacy binding. It
must not be made to work by omitting a required reliable adapter while leaving
the flag true: the missing adapter is a configuration error.

## Preconditions

Record the following before changing configuration:

- deployed revision and B0 implementation/qualification commit SHAs;
- `MODULAR_RELIABLE_TASK_LIFECYCLE`,
  `MODULAR_RESEARCH_CORE_VERSION`, and target-adapter settings;
- Temporal namespace, `research` Task Queue, active Workflow IDs and their
  `run_id`/status;
- PostgreSQL task/projection/result receipt counts for the active Workflow set;
- Redis stream keys and the latest event IDs, if available; and
- the last known-good S5/legacy artifact and its verification record.

Drain new Research requests at the ingress or deployment layer before the
configuration flip. Keep the B0 worker image available until the active set
has been reconciled; stopping it first can leave a committed result without a
published hot event.

Confirm that the B0 range contains no Alembic revision, runtime DDL,
backfill, object deletion, or irreversible Evidence migration. If any such
change is found, stop and use that change's rollback procedure instead.

## Procedure

### 1. Freeze reliable admissions

Stop routing new requests to the B0 candidate and apply the following staged
configuration to every API instance:

```powershell
$env:MODULAR_RELIABLE_TASK_LIFECYCLE = "false"
$env:MODULAR_RESEARCH_CORE_VERSION = "legacy/v1"
```

Do not claim the rollback is active until every instance reports the same
configuration and no admission request can still call
`TemporalReliableResearchPolicy.submit`.

### 2. Reconcile active Workflows

Use the deployment's approved Temporal and PostgreSQL operator tooling. The
following placeholders describe the required queries without introducing a
second runtime:

```powershell
TEMPORAL_CLI workflow list --namespace NAMESPACE --query "TaskQueue='research'"
PG_QUERY "select task_id, workflow_id, run_id, status from task_progress_projection where workflow_id in (...)"
```

For each active `(task_id, workflow_id, run_id)`:

| Observation | Action |
|---|---|
| PostgreSQL result receipt committed, terminal event missing | Run the approved reconciler to finalize the Coordinator projection and republish the deterministic terminal event ID. |
| Workflow running, no PostgreSQL receipt | Keep the B0 worker available long enough to finish or retry under its recorded policy; do not synthesize success in the legacy facade. |
| Workflow failed/exhausted, no receipt | Preserve the failed execution and error. Operator may retry or terminate using the recorded Workflow ID; a later retry must be explicit. |
| Cancellation requested but no cancellation receipt | Let the cancellation Activity reconcile, or issue the approved Temporal cancel again. Do not mark `cancelled` only in Redis. |
| Old run sends late progress | Ignore it when the current projection is attached to a newer run. |

If the worker must be stopped immediately, record the stop reason and leave
the Temporal history intact. Reconciliation is required before exposing a
terminal result through a legacy read path.

### 3. Rebind and restart

Deploy the legacy configuration and restart API workers in a rolling manner.
The first instance must pass the binding check before draining the remaining
B0 instances:

```powershell
uv run --frozen python -c "import asyncio; from xhs_food.composition import build_legacy_composition_root; r=build_legacy_composition_root(); print(r.logical_bindings['modular_core']); print(r.logical_bindings.get('reliable_task_lifecycle')); asyncio.run(r.close())"
```

The output must show `legacy/v1`/`LegacyResearchTaskFacade` and a disabled
reliable binding. If the installed root does not expose the second logical
binding, verify the effective settings and the absence of an injected
`TemporalReliableResearchPolicy` instead of treating a missing print as
success.

Do not change route paths, DTO mappings, session keys, event retention, or
database schema during this restart.

### 4. Verify no new reliable admission

Run a fixed legacy request and inspect the Temporal namespace at the same
time. The request must use the existing legacy path and must not create a new
`research:<task_id>` Workflow. Existing committed results and legacy history
rows must remain readable.

```powershell
uv run --frozen pytest -q `
  tests/test_unit_s5_research_skeleton.py `
  tests/test_unit_s5_plan_contracts.py `
  tests/test_unit_composition_root.py `
  tests/test_unit_b0_reliable_task.py
```

The B0 unit tests are retained as contract evidence; they do not imply that
the reliable policy is enabled during this verification. Also run the
non-live HTTP/SSE characterization suite and confirm the legacy six-step
stream and known legacy terminal projection remain unchanged.

### 5. Close the rollback

Record:

- the final active Workflow list and reconciliation outcomes;
- PostgreSQL receipt/projection counts before and after the flip;
- the first legacy request and its HTTP/SSE fixture comparison;
- absence of new Temporal `research` starts after the gate;
- Redis stream/event observations (including any expected expiry); and
- operator, timestamp, artifact SHA, and test output.

Keep Temporal history, PostgreSQL rows, Redis keys that have not naturally
expired, object-store content, and credentials. No cleanup command in this
runbook deletes them.

## Restore B0

Restore only after the failure cause is understood, the production
PostgreSQL authority adapter and reconciler are healthy, and the B0
qualification record is complete. Revert the bindings in a staged deployment:

```powershell
$env:MODULAR_RESEARCH_CORE_VERSION = "shared/v1"
$env:MODULAR_RELIABLE_TASK_LIFECYCLE = "true"
```

The Composition Root must receive the explicit Temporal/PostgreSQL policy
adapter before the first instance starts. Re-run the focused B0, live
qualification, Redis replay, HTTP/SSE, and dependency gate before reopening
admission.

## Independent Git Revert Drill

Run this drill after the B0 implementation, qualification, and documentation
commits are pushed. Replace placeholders; do not use `git reset --hard` or
revert unrelated `.agents/` files.

```powershell
$B0_BASE = "<last verified S5 commit>"
$B0_HEAD = "<pushed B0 head>"
$B0_COMMITS_NEWEST_FIRST = @(
    "<B0 documentation/qualification commit>",
    "<B0 verification commit>",
    "<B0 implementation commit>"
)
$repo = (git -c core.autocrlf=false rev-parse --show-toplevel).Trim()
$drill = Join-Path (Split-Path $repo -Parent) "food-agent-b0-revert-drill"
if (Test-Path -LiteralPath $drill) { throw "revert drill path already exists: $drill" }
git -c core.autocrlf=false merge-base --is-ancestor $B0_BASE $B0_HEAD
if ($LASTEXITCODE -ne 0) { throw "B0 base is not an ancestor of B0 head" }
git -c core.autocrlf=false worktree add --detach $drill $B0_HEAD
if ($LASTEXITCODE -ne 0) { throw "cannot create detached drill worktree" }
foreach ($commit in $B0_COMMITS_NEWEST_FIRST) {
    git -c core.autocrlf=false -C $drill revert --no-edit $commit
    if ($LASTEXITCODE -ne 0) {
        throw "B0 revert failed for $commit; preserve worktree for diagnosis"
    }
}
$baseTree = (git -c core.autocrlf=false rev-parse "$B0_BASE^{tree}").Trim()
$revertedTree = (git -c core.autocrlf=false -C $drill rev-parse "HEAD^{tree}").Trim()
if ($baseTree -ne $revertedTree) { throw "reverted tree differs from B0 base" }
uv --directory $drill sync --frozen --python 3.12
if ($LASTEXITCODE -ne 0) { throw "base dependency sync failed" }
uv --directory $drill run --frozen pytest -q -m "unit or integration"
if ($LASTEXITCODE -ne 0) { throw "reverted base regression failed" }
git -c core.autocrlf=false -C $drill diff --exit-code --no-ext-diff $B0_BASE HEAD --
if ($LASTEXITCODE -ne 0) { throw "reverted content differs from base" }
$status = @(git -c core.autocrlf=false -C $drill status --short)
if ($status.Count -ne 0) { throw "drill worktree is dirty" }
git -c core.autocrlf=false worktree remove $drill
git -c core.autocrlf=false worktree prune
```

Record the B0 commit list, generated revert commits, base/reverted tree
hashes, test count/duration, empty diff, clean status, and cleanup result in
the final section below. If any revert or tree check fails, preserve the
isolated worktree for diagnosis and keep serving the last verified legacy
artifact.

| Revert evidence | Value |
|---|---|
| Base commit/tree | `<SHA> / <tree>` |
| B0 head/tree | `<SHA> / <tree>` |
| Generated revert commits | `<newest-to-oldest list>` |
| Reverted tree equals base | `pass/fail` |
| Reverted test count/duration | `<exact output>` |
| Empty diff and clean status | `pass/fail` |
| Worktree cleanup/prune | `pass/fail` |

## Recovery If Rollback Verification Fails

Keep the candidate out of service and continue serving the last verified
legacy artifact. Preserve any failed drill worktree and all Temporal/
PostgreSQL evidence. Do not flush Redis, reset Temporal, downgrade the
database, delete objects, or rewrite task status by hand. Escalate unresolved
receipt/projection mismatches to the Platform Runtime and Data Platform
owners; resume only after the reconciliation table above has a recorded
outcome for every active Workflow.
