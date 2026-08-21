# S5 Shared Research Skeleton Rollback

## Purpose

Return the Research experience to the S4 legacy task facade while preserving
all existing HTTP/SSE payloads, Food behavior, session/turn/event identity,
database rows, Redis streams and windows, Temporal service state, and object
store content. S5 is a structural milestone: it introduces typed research
contracts and disabled shared orchestration components, but it does not add a
durable workflow, migration, dual write, or executable checkpoint.

## Default And Rollback Bindings

The S5 candidate is assembled with one shared Coordinator and one Agent
runtime registration:

```text
modular_core -> use_cases.research_task -> ResearchCoordinator
ResearchCoordinator -> LegacyResearchTaskFacade (legacy policy)
agent runtime     -> PydanticAIAgentRuntime (registered, disabled)
step scheduler    -> StepScheduler (registered, disabled)
reliable policy   -> DisabledReliableResearchPolicy
```

The rollback selection is:

```text
MODULAR_RESEARCH_CORE_VERSION=legacy/v1
modular_core -> use_cases.research_task -> LegacyResearchTaskFacade
```

Keep the following S5 bindings disabled during rollback: Agent runtime,
StepScheduler execution, reliable policy, Temporal integration metadata,
target Redis state, target repositories, and object-store adapters. Do not
replace a disabled target with a process-local production fallback.

## Preconditions

1. Record the deployed revision, `MODULAR_RESEARCH_CORE_VERSION`, registry
   snapshot, and logical binding inventory.
2. Confirm the candidate range contains no Alembic revision, DDL, backfill,
   object write, Temporal workflow start, or new authoritative state store.
3. Drain new requests from the candidate before restarting the process.
4. Preserve PostgreSQL rows, Redis keys/streams/windows, Temporal history,
   object-store buckets, and credentials. None is an S5 rollback target.

## Operational Rebind

Set the legacy binding and restart the application process:

```powershell
$env:MODULAR_RESEARCH_CORE_VERSION = "legacy/v1"
```

Verify the selected binding and disabled execution flags:

```powershell
uv run --frozen python -c "import asyncio; from xhs_food.composition import build_legacy_composition_root; r=build_legacy_composition_root(); print(r.logical_bindings['modular_core']); asyncio.run(r.close())"
```

The logical binding must resolve to `LegacyResearchTaskFacade`. Restore the
S5 structural selection only after the candidate is re-approved:

```powershell
$env:MODULAR_RESEARCH_CORE_VERSION = "shared/v1"
```

No route, mapper, DTO, session key, event stream, or legacy orchestrator
configuration should be changed as part of this rebind.

## Verification After Rebind

Run the focused compatibility and architecture checks:

```powershell
uv run --frozen pytest -q -W error `
  tests/test_unit_s5_plan_contracts.py `
  tests/test_unit_s5_research_skeleton.py `
  tests/test_unit_composition_root.py `
  tests/test_unit_s4_food_pack_compatibility.py `
  tests/test_unit_architecture_boundaries.py
```

Then run the non-live regression and repository gates:

```powershell
uv run --frozen pytest -q -m "unit or integration"
uv run --frozen ruff check <S5 changed files>
uv run --frozen ruff format --check <S5 changed files>
uv run --frozen pyright <S5 changed files>
uv lock --check
openspec validate define-modular-architecture --strict --json
git -c core.autocrlf=false diff --check
```

The checks must show unchanged legacy Food output, six-step SSE ordering,
error mapping, recovery identity, and persistence ordering. The Agent fake
must not contact a live provider; the disabled runtime must fail closed;
malformed plans, tools, outputs, budgets, and provider failures must remain
classified at the contract boundary.

## Independent Git Revert Drill

Run this drill after every commit in the recorded S5 rollback set is pushed.
The evidence-only commit that records the completed drill is created afterward
and is not part of that already-verified set. Use a clean detached worktree,
preserve LF line endings, and revert newest-to-oldest:

```powershell
$S4_BASE = "67e2e71b9836886215f66f3c7bb338443b9dd423"
$S5_HEAD = "<record pushed final S5 commit>"
$S5_COMMITS_NEWEST_FIRST = @(
    "<S5 correction commit>",
    "<S5 verification commit>",
    "<S5 implementation commit>"
)
$repo = (git -c core.autocrlf=false rev-parse --show-toplevel).Trim()
$drill = Join-Path (Split-Path $repo -Parent) "food-agent-s5-revert-drill"
if (Test-Path -LiteralPath $drill) { throw "revert drill path already exists: $drill" }
git -c core.autocrlf=false merge-base --is-ancestor $S4_BASE $S5_HEAD
if ($LASTEXITCODE -ne 0) { throw "S4 is not an ancestor of the final S5 revision" }
$merges = @(git -c core.autocrlf=false rev-list --merges "$S4_BASE..$S5_HEAD")
if ($merges.Count -ne 0) { throw "S5 range contains a merge commit" }
git -c core.autocrlf=false worktree add --detach $drill $S5_HEAD
if ($LASTEXITCODE -ne 0) { throw "cannot create detached drill worktree" }
foreach ($commit in $S5_COMMITS_NEWEST_FIRST) {
    git -c core.autocrlf=false -C $drill revert --no-edit $commit
    if ($LASTEXITCODE -ne 0) {
        throw "S5 revert failed for $commit; preserve the worktree for diagnosis"
    }
}
$revertHead = (git -c core.autocrlf=false -C $drill rev-parse HEAD).Trim()
$s4Tree = (git -c core.autocrlf=false rev-parse "$S4_BASE^{tree}").Trim()
$revertedTree = (git -c core.autocrlf=false -C $drill rev-parse "HEAD^{tree}").Trim()
if ($s4Tree -ne $revertedTree) { throw "reverted tree does not equal S4 tree" }
uv --directory $drill sync --frozen --extra dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw "S4 dependency sync failed" }
uv --directory $drill run --frozen pytest -q -m "unit or integration"
if ($LASTEXITCODE -ne 0) { throw "reverted S4 baseline failed" }
git -c core.autocrlf=false -C $drill diff --exit-code --no-ext-diff $S4_BASE HEAD --
if ($LASTEXITCODE -ne 0) { throw "reverted content differs from S4" }
$status = @(git -c core.autocrlf=false -C $drill status --short)
if ($status.Count -ne 0) { throw "drill worktree is dirty" }
git -c core.autocrlf=false worktree remove $drill
git -c core.autocrlf=false worktree prune
```

Record the S5 commit list, generated revert commits and final revert head, both
tree hashes, test count/duration, empty diff, clean status, and cleanup result
in the S5 verification record. Do not mark the revert task complete without
those exact values.

## Recovery If Verification Fails

Keep the candidate out of service and redeploy the last verified S4 artifact
with `MODULAR_RESEARCH_CORE_VERSION=legacy/v1`. Preserve the isolated drill
worktree when a revert or tree comparison fails. Recreate it with
`core.autocrlf=false` only for checkout or environment faults. Do not restore
the database, flush Redis, reset Temporal, delete objects, or rotate
credentials: S5 created no authoritative durable data requiring those actions.
