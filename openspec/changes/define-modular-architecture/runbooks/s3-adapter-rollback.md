# S3 Adapter Binding Rollback

## Purpose

Restore the S3 gateway/foundation boundary to the S2 legacy implementation by
rebinding or reverting adapters independently. The rollback preserves the
frozen HTTP/SSE/Food behavior and does not migrate schema, restore data, delete
Redis keys, start or terminate Temporal workflows, or inspect/remove object
storage content.

S3 is a structural milestone. Its target bindings are disabled before and
after rollback, so the operational rollback is a code/binding deployment, not
a data rollback.

## Required Default State

Before rollback, record the deployed revision and assert all of the following:

```text
modular_core -> use_cases.research_task -> LegacyResearchTaskFacade (legacy/v1)

tools.schema_tool_gateway            enabled = false
target_foundation.sqlalchemy         enabled = false
target_foundation.temporal           enabled = false
target_foundation.temporal_activities enabled = false
target_foundation.object_store       enabled = false
target_foundation.redis_contract     enabled = false
target_foundation.observability      enabled = false
```

No target Foundation binding may be enabled as part of rollback. If a later
milestone has enabled one, stop and use that milestone's migration/runbook
first; this S3 procedure does not reverse later behavior or schema changes.

## Preconditions

1. Record `S3_IMPLEMENTATION_COMMIT`, the deployed artifact identifier, and the
   current binding inventory.
2. Confirm the S2 base revision is
   `82bce06932a6689d61f7d64c054f84acbc57f7ad` and is an ancestor of the S3
   implementation commit.
3. Confirm the candidate range contains no Alembic revision, DDL, backfill,
   target runtime activation, or merge commit.
4. Drain the candidate deployment from new traffic before replacing its
   artifact. Existing requests use the same legacy policy and may finish.
5. Preserve PostgreSQL rows, Redis state/streams/windows, credentials, Temporal
   service state, and object-store buckets. None is a rollback target for S3.

## Adapter-By-Adapter Rebinding

Apply the smallest affected binding rollback first. Restart the FastAPI process
after changing Composition Root bindings so lifecycle resolution runs again.

| Capability | S3 facade/binding to remove or deselect | Legacy binding to retain/restore | Data action |
|---|---|---|---|
| XHS source | `sources.xhs_compat` | Existing `foundation.xhs_service` and `tools.xhs_tool_registry`; direct legacy XHS provider path | None |
| Place source/tool | `sources.place_compat`, `sources.place_tool_compat` | Existing `AmapAPI`/POI enrichment path | None |
| Tool Gateway | Disabled `tools.schema_tool_gateway` | `tools.xhs_tool_registry` (`legacy/v1`) | None |
| Model provider | `models.legacy_llm_provider` facade | Existing `LLMService` construction and provider settings | None |
| Session repository | `repositories.session_legacy` facade | Existing session manager | None |
| User/history/favorites/result repositories | Corresponding `repositories.*_legacy` facades | Existing `UserStorageService` public methods | None |
| Place cache repository | `repositories.place_cache_legacy` facade | Existing public `get_cached_restaurant_by_name()` behavior | None |
| Public Evidence | `repositories.public_evidence_disabled` sentinel | No public Evidence repository in S2 | None; do not create a table |
| Task state | `state.task_state_legacy` facade | Existing `api.search.state` Redis/in-memory selector | Preserve `task:{session_id}:state` |
| EventBus | `state.event_bus_legacy` facade | Existing Redis Streams/in-memory EventBus selector | Preserve `stream:{session_id}:events` and cursors |
| Session window | `state.session_window_legacy` facade | Existing `RedisMemory` | Preserve `session:{session_id}:window` |
| SQLAlchemy target | Disabled `target_foundation.sqlalchemy` | Existing legacy storage/pool owner | None; do not run Alembic or DDL |
| Temporal target | Disabled `target_foundation.temporal` | Existing S2 in-process legacy task policy | None; no S3 workflow exists |
| Temporal Activities target | Disabled `target_foundation.temporal_activities` | Existing synchronous/async legacy model, tool, and service calls | None; no S3 Activity is dispatched |
| ObjectStore target | Disabled `target_foundation.object_store` | No S2 object-store binding | None; no S3 object was authoritative |
| Target Redis contract | Disabled `target_foundation.redis_contract` | Existing legacy hot-state implementations | None |
| OTel target bootstrap | Disabled `target_foundation.observability` | Existing Prometheus metrics and logging | None; keep metric names unchanged |
| Modular use case | Do not change `use_cases.research_task` | `LegacyResearchTaskFacade`, `contract_version="legacy/v1"` | None |

The per-adapter operation is complete only when the selected path reaches the
same legacy concrete service and the target binding remains unresolvable. Do
not substitute an in-memory implementation as a production rollback for a
target runtime; S3 only preserves the already-characterized legacy fallback.

## Binding Verification

Run the focused binding and compatibility checks after any operational rebind:

```powershell
uv sync --frozen --extra dev --python 3.12
uv run --frozen pytest -q -W error `
  tests/test_unit_composition_root.py `
  tests/test_unit_s3_composition_adapters.py `
  tests/test_unit_s3_legacy_adapters.py `
  tests/test_unit_s3_legacy_projection_matrix.py `
  tests/test_integration_search_http_characterization.py `
  tests/test_integration_sse_characterization.py `
  tests/test_unit_sse_state_characterization.py
```

Confirm:

- `resolve_logical("modular_core")` returns `LegacyResearchTaskFacade`.
- Every `target_foundation` binding and `tools.schema_tool_gateway` rejects
  resolution with `DisabledBindingError`.
- XHS provider names, order, arguments, and no-deadline cancellation behavior
  remain unchanged.
- Task state, EventBus, and session-window keys, TTLs, replay, heartbeat, and
  characterized fallback policies remain unchanged.
- ADR-0010 still separates direct no-note `ok`, streaming no-note `error` plus
  the known outer `completed`, and optional POI basic-result success.
- No new engine, Temporal client/workflow, Redis target client, S3 client, or
  OTel instrumentation is created while disabled.

Then run the complete S2/S3 non-live regression and policy gates:

```powershell
uv run --frozen pytest -q -m "unit or integration"
uv run --frozen pytest -q tests/test_unit_architecture_boundaries.py
uv lock --check
openspec validate define-modular-architecture --strict --json
git -c core.autocrlf=false diff --check
```

## Independent Git Revert Drill

Run the release drill only after the S3 implementation commit is pushed. Use an
isolated detached worktree with LF-preserving checkout settings:

```powershell
$S2_BASE = "82bce06932a6689d61f7d64c054f84acbc57f7ad"
$S3_IMPLEMENTATION_COMMIT = "65c9cc978b9a3225e2f48c4587820ebb52a8edfb"
$repo = (git -c core.autocrlf=false rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot resolve repository root" }
$drill = Join-Path (Split-Path $repo -Parent) "food-agent-s3-revert-drill"

if (Test-Path -LiteralPath $drill) {
    throw "revert drill path already exists: $drill"
}

git -c core.autocrlf=false merge-base --is-ancestor $S2_BASE $S3_IMPLEMENTATION_COMMIT
if ($LASTEXITCODE -ne 0) { throw "S2 is not an ancestor of the S3 implementation" }

$merges = @(git -c core.autocrlf=false rev-list --merges "$S2_BASE..$S3_IMPLEMENTATION_COMMIT")
if ($LASTEXITCODE -ne 0) { throw "cannot inspect the S3 commit range" }
if ($merges.Count -ne 0) { throw "S3 implementation range contains a merge commit" }

git -c core.autocrlf=false worktree add --detach $drill $S3_IMPLEMENTATION_COMMIT
if ($LASTEXITCODE -ne 0) { throw "cannot create detached drill worktree" }

git -c core.autocrlf=false -C $drill revert --no-edit $S3_IMPLEMENTATION_COMMIT
if ($LASTEXITCODE -ne 0) { throw "S3 revert failed; preserve the worktree for inspection" }
$revertCommit = (git -c core.autocrlf=false -C $drill rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot resolve the generated revert commit" }

$s2Tree = (git -c core.autocrlf=false rev-parse "$S2_BASE^{tree}").Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot resolve the S2 tree" }
$revertedTree = (git -c core.autocrlf=false -C $drill rev-parse "HEAD^{tree}").Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot resolve the reverted tree" }
if ($s2Tree -ne $revertedTree) {
    throw "reverted tree $revertedTree does not equal S2 tree $s2Tree"
}

uv --directory $drill sync --frozen --extra dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw "S2 dependency sync failed" }
uv --directory $drill run --frozen pytest -q -m "unit or integration"
if ($LASTEXITCODE -ne 0) { throw "reverted S2 baseline failed" }

git -c core.autocrlf=false -C $drill diff --exit-code --no-ext-diff $S2_BASE HEAD --
if ($LASTEXITCODE -ne 0) { throw "reverted content differs from S2" }
$authoritySse = Get-ChildItem -LiteralPath (Join-Path $drill "tests/fixtures/authority") -Filter *.sse
foreach ($fixture in $authoritySse) {
    if ([System.IO.File]::ReadAllBytes($fixture.FullName) -contains 13) {
        throw "authority SSE fixture is not LF-only: $($fixture.FullName)"
    }
}
$drillStatus = @(git -c core.autocrlf=false -C $drill status --short)
if ($LASTEXITCODE -ne 0) { throw "cannot read drill worktree status" }
if ($drillStatus.Count -ne 0) {
    throw "drill worktree is dirty; preserve it for inspection"
}

git -c core.autocrlf=false worktree remove $drill
if ($LASTEXITCODE -ne 0) { throw "clean drill worktree removal failed" }
git -c core.autocrlf=false worktree prune
if ($LASTEXITCODE -ne 0) { throw "worktree prune failed" }

[pscustomobject]@{
    ImplementationCommit = $S3_IMPLEMENTATION_COMMIT
    RevertCommit = $revertCommit
    S2Tree = $s2Tree
    RevertedTree = $revertedTree
    AuthoritySseLfOnly = $true
    WorktreeRemoved = -not (Test-Path -LiteralPath $drill)
}
```

Before accepting the drill, record:

1. The S3 implementation and generated revert commit hashes.
2. `git rev-parse "$S2_BASE^{tree}"` and the reverted `HEAD^{tree}`; they must
   be identical.
3. The exact S2 baseline test count, deselections, warnings, and duration.
4. An empty `git diff --exit-code` and clean worktree status after the test.
5. Confirmation that both authority `.sse` fixtures remain LF-only.
6. Confirmation that the temporary worktree was removed and pruned.

Record those values in
`verification/s3-gateways-foundation.md`; do not invent placeholders as passing
evidence.

## Recovery If Rollback Verification Fails

Keep the reverted artifact out of service. Determine whether the failure is a
fixture checkout issue, dependency-environment contamination, an incomplete
commit range, or a real S2 regression.

For a checkout/environment issue, discard only the isolated worktree, recreate
it with `core.autocrlf=false`, install the locked `dev` extra, and repeat the
same commands. For a real regression, redeploy the last known S3 artifact while
the repair is prepared; do not alter data to make tests pass.

Because S3 has no schema migration, target runtime history, target hot-state
authority, or authoritative object write, restoration consists only of
redeploying the chosen code artifact and restarting its process. Database
restore, Redis flush, Temporal reset, object deletion, and credential rotation
are neither required nor permitted by this runbook.
