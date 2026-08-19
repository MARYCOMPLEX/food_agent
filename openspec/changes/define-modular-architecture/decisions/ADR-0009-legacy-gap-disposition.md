# ADR-0009: Legacy Gap Disposition

Status: Accepted

Date: 2026-08-20

Owners: Architecture + API + Data Platform + Platform + Frontend

Decides: OQ-19, OQ-21, OQ-24, and OQ-27; task 1.16

## Context

S0 made the repository's current contracts replayable, but it also exposed gaps
that must not be repaired incidentally while S2 introduces task facades and
compatibility mappers. This ADR classifies each gap and assigns the change that
may alter it.

The classifications have these meanings:

- **Fix first**: repair before the next structural milestone because preserving
  the condition would make that milestone unverifiable.
- **Characterize and preserve**: S2-S5 must reproduce the observed behavior,
  including the defect. A later behavior change may repair it behind its own
  contract, tests, rollout, and rollback.
- **Independent change**: the work has a separate data, deployment, or
  documentation lifecycle and must not be folded into a structural milestone.

No item below is classified **Fix first**. S0 provides enough evidence to make
S2 independently testable without changing a database, deployment topology,
or legacy task semantics.

## Evidence Limits

Repository evidence can prove the checked-in schema definitions, callers,
fixtures, and reachable Git history. It cannot prove which ad hoc migration was
run against every historical database, whether an untracked external document
copy exists, or which deployment topology is currently operated outside the
repository. Unknown fleet state is therefore handled by an explicit discovery
probe in the owning change; it is never replaced with an assumed answer.

## Disposition Ledger

| Gap | Reproducible observation | Classification | S2-S5 rule | Owning remediation and gate |
|---|---|---|---|---|
| `turn_id` migration state | Runtime table creation in `src/xhs_food/services/user_storage/schema.py` creates the pre-migration `search_results` shape with unique `session_id`; the repository already queries `turn_id` and `query`; `scripts/migrate_turn_id.py` is the only checked-in transition and no Alembic history exists. Clean, pre-, and post-script shapes are frozen in `tests/fixtures/database/*` and `tests/test_unit_search_results_schema_characterization.py`. | **Independent change** | Do not add a schema dependency or silently run the script. Preserve the characterized success/failure behavior for each fixture. | B1 task 9.1 owns an Alembic expand migration. It must inventory each target database using catalog queries, classify clean/pre/post/divergent state, back up before mutation, map a recognized state to an Alembic baseline/stamp, reject unknown shapes, and replay clean/N-1/pre/post upgrades. |
| New-search history creation | `src/api/search/routes.py` calls nonexistent `UserStorageService.create_search_history`; the implemented method is `add_history(user_id, query, ...)`. The `AttributeError` is caught and the search still starts, so the automatic history row is normally absent. | **Characterize and preserve** | The legacy task facade must make the same call at the same point, preserve the warning-and-continue outcome, and must not substitute `add_history` in S2. | A separate search-history behavior change defines identity (`user_id`/anonymous), write failure semantics, idempotency, and recovery before replacing the call. B0 reliable lifecycle must not claim authoritative history/task completion until that contract is adopted. |
| Error terminal followed by completed state | `XHSFoodOrchestrator.search_stream` catches domain and unexpected failures, emits terminal `error`, and returns normally. `run_stream_search` then unconditionally writes state `completed` before attempting persistence. The EventBus subscriber stops at the earlier terminal while status/recovery can observe a later completed projection. | **Characterize and preserve** | Keep the legacy divergence and ordering in facade tests. Do not reinterpret normal return as success, suppress the legacy error, or introduce persist-before-success semantics in S2-S5. | B0 tasks 8.1-8.9 own a versioned reliable lifecycle with one semantic owner, PostgreSQL commit barrier, and one terminal per task/turn. Rollback keeps the legacy policy selectable. |
| Refine replays an old terminal | `_kick_off_refine` resets only `SearchEventEmitter` step state; it does not reset or turn-scope the EventBus stream. A subscription from stream start sees the prior `done` and stops before new-turn events. This is frozen by `test_same_session_refine_keeps_old_done_in_event_log`. | **Characterize and preserve** | Preserve the same-session stream and stale-terminal behavior under legacy policy. Stable Event Mapper must not fabricate turn identity or delete retained events. | B0 reliable lifecycle introduces task/turn-scoped terminal identity. Canonical SSE v1 rollout remains governed by ADR-0004 and requires separate opt-in, reconnect, and rollback gates. |
| Live `search_results.restaurants` payload differs from the ADR-0005 constructed persistence fixture | The orchestrator stores `RestaurantRecommendation.to_dict()` in `ConversationContext.last_recommendations` before POI enrichment. `_persist_results` mutates that mixed snake/camel dictionary with `id` and writes it to `search_results`. `EnrichedRestaurant.to_dict()` is emitted on SSE but is not placed in that context. The existing `persistedRestaurant` fixture instead characterizes a separately constructed `Restaurant.to_dict()` camel-case view. | **Characterize and preserve** | Stable Result Mapper must preserve the live writer's recommendation-plus-`id` shape, field defaults, ordering, and mutation timing. It must not substitute the enriched/`Restaurant` view merely to satisfy the old fixture. | S2 task 4.7 adds a writer-path characterization before moving the code. A normalized persistence DTO or backfill is a separate versioned data/API change; readers must continue accepting already stored JSON without recursive case conversion. ADR-0005 is corrected to name both boundaries. |
| Frontend development origin versus CORS | Vite binds port `3000`; Settings defaults CORS to `http://localhost:5173` and FastAPI allows only `GET`, `POST`, `DELETE`, and `OPTIONS`. Both sides are frozen in `consumer_contracts.json`. | **Independent change** | Do not alter server middleware or Vite configuration in structural milestones. | A deployment/client compatibility change chooses the served origins and methods per environment, adds browser preflight tests, and supplies rollback configuration before release. |
| SSE timeout environment name | `.env.example` declares `SSE_TIMEOUT`; Settings consumes `SSE_TIMEOUT_SECONDS`. The mismatch is frozen in `configuration_deployment_contract.json`. | **Independent change** | Do not add an implicit alias or rename a setting in S2-S5. | A configuration compatibility change chooses `SSE_TIMEOUT_SECONDS` as the canonical name, defines any time-bounded legacy alias and precedence, updates deployment manifests/docs together, and tests both startup and effective timeout. |
| Container does not deliver the frontend | Docker/Compose build and run the API on port 8000 and have no frontend service or static bundle. This is explicitly recorded by `configuration_deployment_contract.json`. | **Independent change** | Treat the current image as API-only; do not copy frontend assets into it as part of a facade or mapper change. | A release-topology change decides separate static hosting versus a dedicated frontend image, origin/API routing, health checks, cache policy, and rollback. B0/B4 may develop independently, but production activation and the release gate require that decision. |
| Missing `internal-docs/*` | Five links in `src/api/README.md` and `src/xhs_food/services/README.md` point to an absent directory. `git ls-tree -r --name-only` and a reachable-history path scan find references but no tracked `internal-docs/*` blob. | **Independent change** | The missing files are not contract authority and are not reconstructed from README claims. ADR-0004, ADR-0005, specs, and committed fixtures remain authoritative. | A documentation-only change removes or replaces the five broken links with committed, reviewed documents. If an external copy is later found, it is evidence to review, not an automatic contract override. |

## Milestone Consequences

1. OQ-21 no longer blocks S2. Task 4.7 must explicitly exercise the four
   legacy task/persistence defects above; golden fixtures are not updated to
   make a structural refactor pass.
2. OQ-19 is disposition-complete but B1 remains gated on live schema discovery
   and the Alembic migration rehearsal. No historical deployment is presumed
   migrated.
3. OQ-24 is disposition-complete for this architecture change. The current
   API-only topology is characterization, while target delivery/configuration
   is a separately reviewed release change.
4. OQ-27 no longer blocks documentation or structural work. Broken links do
   not become normative merely because their former titles sound authoritative.

## Rejected Alternatives

- Repairing these defects inside the S2 facade: rejected because it combines
  behavior changes with a structural rollback unit.
- Treating the post-`turn_id` fixture as proof of fleet state: rejected because
  a replayable local fixture is not a production inventory.
- Generating replacement internal documents from README text: rejected because
  it would fabricate an authority source.
- Making ADR-0005's constructed `Restaurant` fixture overwrite the observed
  writer path: rejected because the live code persists a different payload.
