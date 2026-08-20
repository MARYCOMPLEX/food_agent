# S4 Food Pack Rollback

## Purpose

Restore Food behavior selection to the frozen legacy adapter without changing
HTTP/SSE contracts, Food DTOs, database schema, stored data, task state, or any
Foundation binding. S4 is a structural milestone: it extracts Food semantics,
registers `food@1.0.0`, and keeps the pre-registration behavior selectable.

## Binding Inventory

The default S4 deployment selects:

```text
MODULAR_FOOD_PACK_VERSION=1.0.0
food_pack -> domain_packs.food_1_0_0 -> food@1.0.0
modular_core -> use_cases.research_task -> LegacyResearchTaskFacade
```

The operational rollback selects:

```text
MODULAR_FOOD_PACK_VERSION=legacy/v1
food_pack -> domain_packs.food_legacy -> LegacyFoodPackAdapter
modular_core -> use_cases.research_task -> LegacyResearchTaskFacade
```

The Food Pack registry, schema-validated Food Tool Gateway, and source
capability declarations may remain registered. The legacy Food workflow does
not dispatch through those new bindings in S4. All S3 target Foundation
adapters remain disabled.

## Preconditions

1. Record the deployed revision, selected Food Pack version, registry snapshot,
   and logical binding inventory.
2. Confirm the candidate contains no Alembic revision, DDL, backfill, dual
   write, target runtime activation, or persistent object write.
3. Stop routing new Food tasks to the candidate process before restarting it.
   Existing in-process requests may complete on their pinned process version.
4. Preserve PostgreSQL rows, Redis keys/streams/windows, Temporal service state,
   object-store buckets, and credentials. None is an S4 rollback target.

## Operational Rebinding

Set the deployment environment and restart the application process:

```powershell
$env:MODULAR_FOOD_PACK_VERSION = "legacy/v1"
```

Do not change `MODULAR_TARGET_ADAPTERS_ENABLED`, source credentials, model
selection, routes, event mappers, or DTO configuration. A process restart is
required because Composition Root validates and selects the Pack during
construction and new `SearchExecutor` instances capture that selection.

Verify the selected root:

```powershell
uv run --frozen python -c "import asyncio; from xhs_food.composition import build_legacy_composition_root; r=build_legacy_composition_root(); print(r.logical_bindings['food_pack']); print(r.logical_bindings['modular_core']); asyncio.run(r.close())"
```

The first binding must be `domain_packs.food_legacy`; the second must remain
`use_cases.research_task`. Restore the default only after approval:

```powershell
$env:MODULAR_FOOD_PACK_VERSION = "1.0.0"
```

## Registry Unregister And Restore Drill

Unregistering a Pack version only removes it from future registry selection.
An already copied `DomainContractPin` remains immutable. The drill must prove:

1. `unregister("food", "1.0.0")` removes only that snapshot entry.
2. Existing pins retain the original manifest, method, tool, and final-output
   schema digests.
3. `restore(registered_food)` revalidates the candidate before publication.
4. A malformed restore is rejected without changing the published snapshot.
5. `modular_core`, S3 source/repository/state bindings, and legacy DTO exports
   remain unchanged throughout the drill.

These assertions are automated in
`tests/test_unit_s4_domain_pack_registry.py` and
`tests/test_unit_s4_food_pack_compatibility.py`.

## Verification

Run the focused S4 gates after any rebind:

```powershell
uv run --frozen pytest -q -W error `
  tests/test_unit_s4_food_pack_resources.py `
  tests/test_unit_s4_domain_pack_registry.py `
  tests/test_unit_s4_food_pack_compatibility.py `
  tests/test_unit_composition_root.py `
  tests/test_unit_architecture_boundaries.py
```

Then run the non-live compatibility and integrity gates:

```powershell
uv run --frozen pytest -q -m "unit or integration"
uv run --frozen ruff check src/xhs_food/domain_packs `
  src/xhs_food/composition/domain_packs.py `
  src/xhs_food/composition/adapters/food_output.py `
  src/xhs_food/composition/adapters/food_tools.py `
  src/xhs_food/composition/adapters/legacy_food.py `
  tests/test_unit_s4_*.py
uv run --frozen pyright src/xhs_food/domain_packs `
  src/xhs_food/composition/domain_packs.py `
  src/xhs_food/composition/adapters/food_output.py `
  src/xhs_food/composition/adapters/food_tools.py `
  src/xhs_food/composition/adapters/legacy_food.py
uv lock --check
openspec validate define-modular-architecture --strict --json
git -c core.autocrlf=false diff --check
```

Confirm that keyword order, fast/deep stopping, merge/filter/rank results,
prompts, public Python exports, Food HTTP/SSE/DTO fixtures, and optional POI
fallback remain equivalent. No Pack may import an Agent, Gateway, database,
Redis, Temporal, object-store client, platform SDK, or another Pack.

## Independent Git Revert Drill

After pushing the single S4 implementation commit, create an isolated detached
worktree at that commit and revert only that commit. Use
`core.autocrlf=false`, with S3 verification revision
`9519e2fbbfd74477db9cc84967c7f3283ff0fc6c` as the base.

The drill passes only when:

1. The implementation range contains no merge commit.
2. The revert applies without conflict.
3. The reverted `HEAD^{tree}` equals the S3 base tree exactly.
4. `uv --directory $drill run --frozen pytest -q -m "unit or integration"`
   passes on the reverted tree.
5. `git diff --exit-code $S3_BASE HEAD --` is empty and the worktree is clean.
6. Authority SSE fixtures remain LF-only.
7. The temporary worktree is removed and pruned after evidence is recorded.

Record the implementation commit, generated revert commit, both tree hashes,
test count/duration, diff result, LF check, and cleanup result in
`verification/s4-food-pack.md`. Do not mark task 6.10 complete before this
evidence exists.

## Recovery If Verification Fails

Keep the candidate artifact out of service. If the failure is limited to the
operational binding, redeploy the last known S4 artifact with
`MODULAR_FOOD_PACK_VERSION=legacy/v1`. If the code-level revert fails, preserve
the isolated worktree for diagnosis and keep serving the last verified S3 or
legacy-bound S4 artifact.

S4 has no schema migration or new durable authority. Database restore, Redis
flush, Temporal reset, object deletion, and credential rotation are neither
required nor permitted by this runbook.
