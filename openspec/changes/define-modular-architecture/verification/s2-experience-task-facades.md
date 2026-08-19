# S2 Experience And Task Facades Verification

Date: 2026-08-20

## Scope

S2 routes new/refine/recover/status/results through `ResearchTaskPort`, binds
`modular_core` to the legacy facade, adds detached context snapshots and stable
event/result mappers, and separates the six-step presentation projection from
orchestrator execution. It does not enable canonical SSE v1, explicit refresh,
reliable task semantics, a new runtime, or any data/schema migration.

The S1 base revision is `b610dde`. The implementation tip and detached-worktree
revert evidence are recorded after the S2 implementation commit exists.

## Compatibility And Policy Gates

The focused S2 boundary, facade, mapper, architecture, HTTP, and SSE suite ran
with warnings promoted to errors:

```text
129 passed in 5.77s
```

It proves:

- Every non-streaming search operation depends only on `ResearchTaskPort`.
- New and refine start the legacy background runner exactly once.
- API code no longer reads `orchestrator._context` directly.
- Context snapshot/restore is detached in both directions and preserves order.
- Stable result projections preserve empty/default/Unicode/order/ID behavior.
- Stable task events map only to the approved 11 legacy event names and six
  numeric step IDs; EventBus IDs remain the sole legacy SSE cursors.
- Explicit refresh is a public unbound port and OpenAPI exposes no refresh route.
- The legacy history-method gap, error-then-completed projection, completed
  before persistence, swallowed persistence failure, and old terminal replay
  remain characterized rather than repaired.
- The live writer persists `RestaurantRecommendation.to_dict() + id`, preserves
  an existing empty/`null` ID, and mutates context before the restaurant upsert await.

The full offline non-live backend suite produced:

```text
518 passed, 5 deselected, 2 warnings in 25.81s
```

The five deselected tests are explicitly marked `live`. The two warnings are
the pre-existing `PytestReturnNotNoneWarning` cases in `tests/test_session.py`.
No HTTP, SSE, DTO, consumer, or authority golden fixture was updated.

## Architecture And Binding

The dependency policy now exactly matches the current scan:

```text
89/89 reviewed legacy import violations
21/21 reviewed legacy private-access violations
0 additions and 0 stale allowances
```

The three eliminated API `_context` accesses and twelve reclassified/removed
imports were deleted from the shrink-only baseline. The default logical binding
is:

```text
modular_core -> use_cases.research_task -> LegacyResearchTaskFacade (legacy/v1)
```

The operational rollback is documented in
`runbooks/s2-modular-core-rollback.md`.

## Browser And Frontend

Frontend ESLint and the TypeScript/Vite production build passed; Vite built
2,264 modules. A local API plus Vite preview was exercised with installed
Chromium at desktop `1440x900` and mobile `390x844` viewports. `/`,
`/favorites`, `/history`, and `/profile` each returned 200, rendered non-empty
content, and produced no page, console, or HTTP errors across eight navigations.

The existing Vite `__dirname` forward-compatibility notice remains non-blocking
and unchanged. S2 does not alter the separately characterized frontend/server
contract discrepancies.

## Tooling Gates

- Python 3.12.0 on Windows x86_64.
- Scoped Pyright for contracts/composition/experience/search boundary: zero errors.
- Ruff check and format check for S2-added files and target boundary slices:
  passed. Legacy EventBus/Orchestrator files retain their pre-existing
  repository-wide modernization findings; S2 introduces no new finding there.
- `uv lock --check --offline`: 89 packages resolved.
- Frontend ESLint: passed.
- Frontend TypeScript and Vite production build: passed.
- `openspec validate define-modular-architecture --strict --json`: passed with
  zero issues.
- `git diff --check`: passed.

## Failure Injection

Facade tests inject missing legacy history API, orchestrator error return,
uncaught runner exception, persistence failure, empty/`null` legacy IDs,
missing sessions, adapter `KeyError`, malformed mapping aliases, and unbound
refresh. Failures remain isolated at the same compatibility boundaries and do
not create a new terminal policy or persistence authority.

## Revert Drill

Pending until the S2 implementation commit exists. The drill will revert the
S2 range in a detached worktree, run the S1 baseline, confirm the tree matches
`b610dde`, and record all commit/tree hashes here before task 4.10 is checked.
