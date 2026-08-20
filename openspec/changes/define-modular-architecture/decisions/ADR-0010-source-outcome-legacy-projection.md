# ADR-0010: Source Outcomes And Legacy Projection

Status: Accepted

Date: 2026-08-20

Owners: Evidence + API + Architecture + QA

Decides: OQ-22; tasks 5.11 and 5.12

## Context

The legacy Food workflow collapses several source outcomes at different
boundaries. A source search returning a failed `ToolResult` and one raising an
exception both become an empty list in
`SearchExecutor.execute_4_stage_search`; later keywords still run. The
`XHSFoodOrchestrator.search_stream` path treats an aggregate with no notes as
`step_error(step2, "未找到相关笔记")` followed by a terminal `error`. The direct
`SearchExecutor.handle_new_search` path instead returns an `ok` response with
an empty recommendation list. `api.search.tasks.run_stream_search` then writes
`completed` after any normal return, including a stream that already emitted
`error`. These observations are frozen by the legacy task-facade
characterization, including
`tests/test_unit_legacy_research_task_facade.py::test_terminal_error_return_is_still_marked_completed_then_persisted`.

Analysis is item-isolated: `SearchExecutor.analyze_notes_concurrent` skips an
individual failed or throwing analyzer result and keeps other restaurants.
POI/Amap is optional enrichment: `POISearchMixin._do_poi_search` converts an API
error, exception, or empty `pois` list to no POI, and
`POIEnricherAgent._enrich_and_format` formats the original recommendation as a
basic restaurant instead of failing the task.

The target contracts already provide serializable `ContractError` values with
`ErrorCategory` and `ErrorScope`, and `CanonicalSourceBatch.errors` is the
source-owned place for errors. The target must retain these distinctions for
coverage, retry, provenance, and evidence publication even while the legacy
wire contract remains unchanged during S3.

## Decision

### 1. Internal outcome taxonomy

Every source/provider boundary reports one of these outcome meanings without
using an empty item collection as an implicit error signal:

| Outcome | Definition | Evidence and control effect |
|---|---|---|
| `success_nonempty` | The connector returned a valid batch containing one or more canonical items. | Items may proceed to normalization and analysis. |
| `success_empty` | The connector completed successfully, the payload was valid, and the batch contained zero items. | Record a successful empty attempt; do not manufacture a failure, and let the declared coverage policy evaluate the empty attempt. |
| `failure` | The connector/provider timed out, was rate limited, was unavailable, returned malformed data, or raised an unclassified boundary exception. | Emit a `ContractError` with the appropriate `ErrorCategory`; preserve retryability and source/provider scope; do not publish failure as a successful empty batch. |
| `partial` | An aggregate retained at least one eligible item while another source attempt, item analysis, or optional enrichment failed. | Preserve surviving items plus scoped errors and coverage metadata. `partial` is an aggregate outcome, not a new `TaskStatus`. |

`timeout`, `rate_limited`, `malformed_response`, `dependency_unavailable`, and
`internal` use the corresponding existing `ErrorCategory` values. A recognized
timeout, including `TimeoutError`, `SOURCE_TIMEOUT`, or `TIMEOUT`, is a
source-scoped failed attempt with `ErrorScope.SOURCE`. A malformed normalized
source payload is also source-scoped. An unclassified exception raised by the
provider before a source result envelope exists uses `ErrorScope.PROVIDER`.
Tool Gateway policy/schema/timeout failures remain `ErrorScope.TOOL`. A failure
must remain distinguishable from `success_empty` in
`CanonicalSourceBatch.errors` and downstream coverage/provenance records. The
taxonomy does not add a Redis lock, a second task runtime, or a new public
status field.

### 2. Required XHS source

XHS keyword attempts are isolated. A failed or throwing keyword call is a
source-scoped failure and the next keyword may run. If at least one keyword
produces notes, the aggregate is `partial` when another attempt or item
analysis failed; a valid empty attempt remains `success_empty` and affects
coverage only under the declared policy. Surviving notes continue through
analysis. If all attempts are empty or failed, the aggregate has no notes and
must not create a successful Evidence batch merely because the legacy
accumulator is `[]`.

The existing no-deadline behavior of a genuinely hanging XHS call remains a
characterized `loading` stream with heartbeat until a separately versioned
timeout contract is adopted. S3 does not silently add a timeout.

### 3. Optional Amap/POI enrichment

Amap/POI is optional enrichment after restaurant recommendations exist. A
valid payload with no POI is `success_empty`; a timeout, rate limit, malformed
payload, unavailable dependency, or per-item exception records a scoped
failure and partial coverage. Both outcomes keep the basic recommendation
projection, while the legacy client continues to receive restaurant data,
`result`, and `done` events.

### 4. Legacy compatibility mapping

The S3 mapper preserves the following legacy projections exactly; it does not
expose a new `partial` field or reinterpret the old `completed` defect:

| Internal situation | Legacy streaming projection | Legacy direct/recovery projection |
|---|---|---|
| All required XHS attempts are `success_empty` or `failure` and no notes exist | `step_error` for `step2`, then terminal `error` with `未找到相关笔记`; the outer background task may subsequently project `completed` after the normal return. | `SearchExecutor.handle_new_search` returns `status="ok"` with an empty recommendation list and its existing summary; background persistence retains its characterized empty-result behavior. |
| Some XHS attempts fail (and others may be empty), at least one yields notes, and item analysis leaves usable results | Existing successful six-step stream and result payload; no `partial` wire field. | Existing successful recommendation response and persistence shape. |
| Individual analyzer failures with other analyzable notes | Successful stream/result containing surviving recommendations. | Successful response containing surviving recommendations. |
| Amap/POI enrichment fails while recommendations exist | Basic restaurant projection, `result`, and `done`; no new error event. | Existing recommendation/result projection; enriched-only fields remain absent/default. |
| Refine has an earlier context/result and the new required-source run has no notes | Preserve the characterized refine persistence/recovery behavior, including any prior-result projection; do not invent a new not-found contract in S3. | Same legacy mapper and storage ordering. |

The canonical/internal path may expose the scoped errors and partial coverage to
Evidence and observability consumers, but the compatibility mapper is the only
place allowed to hide them from legacy clients. B0 remains responsible for the
separate `error` versus `completed` lifecycle correction and does not get
silently folded into this taxonomy decision.

### 5. Source-ready query projection

Canonical Query identity keeps stable public semantic identifiers; a Connector
must not be the target owner of locale-aware Food query rendering. A caller may
therefore attach a `SourceQueryProjection` for each source in `source_scope`.
An explicit projection pins `source_id`, rendered `text`, optional `locality`,
`language`, `renderer_id`, and `renderer_version`. Its source and language must
match the request partition, otherwise dispatch fails before the provider is
called.

`source_queries` remains optional in S3 because it is an additive field on the
S1 `CollectRequest` contract. Omission invokes only the characterized legacy
fallback and does not become a new failure. Target dispatch must supply the
versioned projection before later behavior milestones make the target Connector
authoritative. This preserves old payloads without treating Connector-owned
translation or domain vocabulary as the target design.

## Rejected alternatives

- Treating every empty list as a successful empty source: rejected because it
  loses source failure, retry, coverage, and provenance information.
- Adding `partial` to the existing legacy SSE or task status: rejected because
  it changes the frozen wire contract during a structural milestone.
- Making optional Amap/POI failure terminal: rejected because the current
  workflow intentionally preserves a usable basic restaurant projection.
- Adding a source timeout while introducing the taxonomy: rejected because the
  current hanging XHS behavior is separately characterized and requires its own
  versioned contract and rollback.

## Verification gate

Task 5.11 owns the mapping implementation and stable category/scope rules.
Task 5.12 must run the same consumer suite against legacy and target adapters
for true-empty, timeout, rate-limit, malformed, dependency, exception,
partial-item, all-empty/all-failed, hanging/cancel, and optional POI fallback
fixtures. The suite must assert both the internal distinction and the exact
legacy projection table above. Contract and Gateway tests must also prove that
explicit source/language projection mismatches fail before provider dispatch,
while an omitted projection retains only the S3 legacy fallback.
