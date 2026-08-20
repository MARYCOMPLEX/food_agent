# S4 Food Pack And Decision Extraction Verification

Date: 2026-08-21

Evidence status: complete; implementation gates and detached revert evidence
were verified against the pushed S4 implementation commit.

## Scope

S4 packages the approved `food@1.0.0` Domain Contract and schema bundle as
production resources, moves Food intent, prompts, workflow, preprocessing,
scoring, POI interpretation, and decision behavior behind the Food Pack, and
retains the old Python/DTO surfaces as compatibility facades.

This milestone does not change HTTP/SSE routes or payloads, add a database
migration, enable Query Family/Evidence behavior, activate Temporal, change
Redis authority, or create object-store data. The S3 base revision is
`9519e2fbbfd74477db9cc84967c7f3283ff0fc6c`.

## Contract And Binding Inventory

| Boundary | S4 structural result |
|---|---|
| Manifest | Packaged `domain-pack-manifest/v1`, `food@1.0.0`, and the exact approved schema bundle/digests |
| Domain methods | `describe`, `classify_constraints`, `validate_evidence`, `compute_features`, `score_public`, `build_final_output`, and `map_error` |
| Allowed tools | `place.lookup@1.0.0` and `evidence.search_reviews@1.0.0`, validated before provider dispatch and after provider output |
| Required sources | `place.lookup` and `reviews.search`, both version constrained by the manifest |
| Final output | Schema validation occurs before legacy Restaurant/XHSFoodResponse mapping |
| Discovery | Composition Root loads exactly one deployment-allow-listed `food` entry-point factory at startup |
| Default selection | `food_pack -> domain_packs.food_1_0_0` |
| Rollback selection | `MODULAR_FOOD_PACK_VERSION=legacy/v1` selects `domain_packs.food_legacy` |
| Shared core | `modular_core -> use_cases.research_task` remains unchanged |

Freshness and coverage remain versioned profile IDs only. S4 does not promote
review examples or unresolved operational values into production thresholds.

## Compatibility Evidence

The S4 differential suite freezes:

- `FoodSearchIntent`, prompt, preprocessing, and scoring public exports.
- Four-stage keyword order and fast/deep stopping behavior.
- Note merge, invalid-name removal, wanghong/locality decision, exclusion,
  confidence adjustment, sorting, and Top-K inputs.
- POI search variants, matching, address projection, and cost bands while all
  network access remains in the Place owner boundary.
- Legacy Restaurant/XHSFoodResponse defaults and frontend serialization.
- Legacy version rebinding without changing `modular_core` or S3 facades.

## Failure And Isolation Evidence

| Injection | Required assertion |
|---|---|
| Incomplete/invalid manifest or schema bundle | Registration fails atomically and the published snapshot is unchanged |
| Duplicate Pack version or incompatible core/source/tool version | Candidate is rejected without replacing a valid Pack |
| Malformed tool input | Gateway returns `TOOL_INPUT_INVALID`; provider call count remains zero |
| Unauthorized tool | Gateway returns `TOOL_POLICY_DENIED`; provider call count remains zero |
| Malformed tool output | Gateway returns `TOOL_OUTPUT_INVALID`; value is not passed downstream |
| Malformed final output | Registry/adapter validation fails before DTO mapping or success publication |
| Invalid unregister restore | Restore revalidates and cannot pollute the registry snapshot |
| Non-allow-listed entry point | Discovery does not import or load it |
| Missing, duplicate, or non-callable Food entry point | Composition Root startup fails before Pack activation |
| Coexisting `1.0.0` and `legacy/v1` roots | Each orchestrator retains its root-owned Pack; no process-global selection leaks between roots |
| Forbidden Pack dependency | Static architecture gate fails |

## Gate Commands

```powershell
uv sync --frozen --extra dev --python 3.12
uv lock --check
uv run --frozen pytest -q -W error `
  tests/test_unit_s4_food_pack_resources.py `
  tests/test_unit_s4_domain_pack_registry.py `
  tests/test_unit_s4_food_pack_compatibility.py `
  tests/test_unit_composition_root.py `
  tests/test_unit_architecture_boundaries.py `
  tests/test_unit_python_contract_characterization.py
uv run --frozen pytest -q -m "unit or integration"
openspec validate define-modular-architecture --strict --json
git -c core.autocrlf=false diff --check
```

## Final Gate Record

Do not replace a pending value until the exact command has run on the final S4
implementation tree.

| Gate | Final result |
|---|---|
| Python/uv sync | Passed; `uv sync --frozen --extra dev --python 3.12`, 115 packages checked |
| `uv lock --check` | Passed; 117 packages resolved |
| Focused S4 suite | Passed; 51 tests in 15.81s with `-W error` |
| Complete non-live S0-S4 suite | Passed; 684 passed, 5 deselected, 2 pre-existing warnings in 44.08s |
| Ruff check/format | Passed; scoped S4 files clean and formatted |
| Blocking S4 Pyright scope | Passed; 0 errors, 0 warnings, 0 informations |
| Architecture gate | Passed; 12 tests in 5.68s |
| HTTP/SSE/DTO/Python characterization | Passed; 23 tests in 6.46s with `-W error` |
| Strict OpenSpec validation | Passed; change valid with no issues |
| Diff/line-ending integrity | Passed; `git -c core.autocrlf=false diff --check` |
| Packaged wheel resource check | Passed; manifest and schema bundle resources present in wheel |

## Revert Drill

The procedure is defined in `runbooks/s4-food-pack-rollback.md`.

| Revert evidence | Final value |
|---|---|
| S4 implementation commit | `6abca19ae71473696a62c7a8b446e5e1ecfad5ec` (pushed) |
| Detached revert commit | `9273fd48cb7ce5a1796bf09b119580503fb69741` |
| S3 base tree hash | `efed2dd3b1d0fccd497497162d52573d2be6c9f4` |
| Reverted tree hash | `efed2dd3b1d0fccd497497162d52573d2be6c9f4` |
| Reverted S3 regression | `uv --directory $drill run --frozen pytest -q -m "unit or integration"`: 657 passed, 5 deselected, 2 pre-existing warnings in 52.03s (after `uv sync --frozen --extra dev --python 3.12`) |
| Diff and clean-worktree result | Passed; `git diff --exit-code 9519e2f..HEAD --` returned 0 and detached worktree status was clean |
| Authority SSE LF check | Passed; 2/2 fixtures contain no CR bytes |
| Worktree cleanup/prune result | Passed; temporary detached worktree removed and metadata pruned |
