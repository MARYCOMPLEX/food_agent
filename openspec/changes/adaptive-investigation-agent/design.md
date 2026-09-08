## Context

The repository has a project-owned MCP Gateway/catalog, canonical evidence
contracts, and a registered Food Pack.  The adaptive implementation now sits
on the production research path: one logical Agent is represented by separate
planner and critic model roles, while runtime code remains the authority for
policy, budgets, execution, reduction, and evidence/profile ownership.

The deterministic comment-first workflow is still importable for compatibility,
but it is no longer the production planning authority.

## Decision

Use one immutable, versioned state snapshot per investigation and an
append-only observation history:

```text
XHSFoodOrchestrator / Composition Root
                  |
                  v
      AdaptiveFoodResearchWorkflow
       |       |       |        |
       |       |       |        +--> EvidenceLedger / profile repository
       |       |       +-----------> FoodAdaptivePack reducer
       |       +-------------------> InvestigationLoop (canonical state)
       +---------------------------> ManagedMcpToolSession (one snapshot)
                                      |
                                      v
                                  MCP Gateway

InvestigationLoop:
  Objective + state -> AdaptivePlanner -> PlanProposal
  PlanProposal -> ActionScheduler -> semantic Gateway calls
  raw returns -> ObservationEnvelope -> Food reducer -> AdaptiveCritic
  CritiqueDecision -> next proposal or typed Termination
```

The model may propose a plan and critique evidence, but it never receives
credentials, account routing, provider clients, or an authority to execute a
raw MCP method.  The current runtime validates every proposal against the
current state revision, hard budget, Food Pack policy, and pinned capability
snapshot before dispatching it.

## Contract Boundaries

### Objective, Question, and Hypothesis

`Objective` is the stable user/use-case goal.  `Question` records an open or
answered sub-question.  `Hypothesis` is a falsifiable working explanation;
supported or refuted hypotheses must cite evidence references.  These values
are immutable and use opaque IDs so a model cannot silently change identity.

### Rolling planning and execution

`PlanProposal` is revisioned and contains only typed `PlanAction` values.  An
action has a semantic kind, logical capability, validated JSON arguments,
dependencies, idempotency key, evidence/question/hypothesis references, and a
bounded action budget.  Proposal validation rejects duplicate IDs, unknown
dependencies, self-dependencies, and cycles.  `base_revision` makes stale
proposals detectable before `InvestigationLoop` applies them.  The scheduler
executes independent actions in bounded waves and records a typed observation
for success, failure, rejection, dependency errors, and cancellation.

### Observation and critique

`ObservationEnvelope` separates normalized `data` from the untouched JSON
`raw_payload`.  It retains source/capability identity, cursor and
completeness, provenance, and evidence references.  It never coerces an
unsupported or failed result into a successful empty result.  A
`CritiqueDecision` records what observations were considered, the disposition
(`continue`, `replan`, `request_evidence`, `synthesize`, or `terminate`), and
the evidence used for that decision.  `FoodAdaptivePack` reduces all observed
Food envelopes into deduplicated claims/entities/profiles and emits follow-up
actions for unresolved coverage or pagination gaps.

### Final evidence synthesis

The Food adapter performs the final user-facing synthesis after the canonical
loop has terminated. It prefers the terminal `Termination` summary and the
latest round's critic conclusion, then renders accumulated findings and their
evidence references into the existing `summary` string. A structured
`evidenceSynthesis` projection in `research_metadata` retains the exact finding
values, finding-level references, terminal reason, and state revision. This is
an adapter projection rather than a new Agent or a new DTO: canonical state and
raw observation payloads remain authoritative. If model text is absent or
generic, the adapter falls back to the deterministic recommendation/count
summary and still exposes the audit projection.

### State and termination

`InvestigationState` is the canonical state authority used by the engine.  It
keeps the objective, question/hypothesis set, current and historical
proposals, all observations, latest critique, budget usage, tool snapshot
reference, findings, gaps, and accumulated evidence references.  IDs and
investigation scope are checked at construction; observed evidence references
are unioned into the state rather than discarded.  `Termination` makes the
reason explicit and can carry a cursor, next round, budget usage, or other
continuation metadata for a partial, resumable result.  State updates use
immutable model copies, so the returned run retains the complete audit trail.

### Budget, cancellation, and capabilities

`InvestigationBudget` requires at least one finite ceiling and covers
iterations, actions, tool calls, cost units, tokens, observations, wall time,
and an optional UTC deadline.  `BudgetUsage` records actual consumption,
including reservation overshoot needed for auditability.  `ActionScheduler`
reserves estimated calls/tokens/cost before concurrent work, reconciles actual
usage afterward, and emits a typed `budget_exhausted` observation when a
reservation is denied.  Cancellation drains in-flight work, records terminal
cancelled observations, and lets the engine produce a resumable
`Termination`.

`ToolCapabilityMetadata` and `ToolCapabilitySnapshot` describe only
capabilities exposed through the project-owned `mcp_gateway`; side effects,
schemas, cost, timeout, and evidence/pagination support are explicit.
`ManagedMcpToolSession.open()` captures one catalog snapshot for the turn,
`ManagedMcpToolPort` exposes only its logical capabilities, and `close()`
releases the snapshot.  The no-configuration path uses a fail-closed session.

### Model view and operational observations

The canonical state is intentionally richer than the model request. Planner
and critic context contains one normalized observation history index plus the
latest wave; raw provider returns, comments, and source payloads remain in the
state/run audit projection and are never copied into telemetry or repeated in
the model prompt. This keeps the comment evidence authoritative while
preventing serialized payload duplication from consuming the planning budget.

When the Composition Root provides the project-owned `ObservationPort`, the
workflow records bounded `agent.run`, `model.call`, `mcp.tool_call`, and
`evidence.transform` records. The recorder allow-lists scalar status/count/
duration fields and opaque correlation IDs. It is best effort: an exporter
failure cannot alter scheduling, evidence reduction, profile persistence, or
the returned Food response.

Food follow-up actions are built against the discovered MCP input contracts.
For example, a cited XHS note produces `comments.search` with `note_id`, while
a candidate without a Dianping identity produces `places.search(keyword)`;
domain identifiers and controversy context stay in action metadata.

## Invariants

- Contract models are immutable, JSON-serializable, and reject undeclared
  fields.  Opaque payloads are JSON-only and reject non-finite numbers.
- Evidence and profile ownership remains separate.  The workflow invokes
  `EvidenceLedger.record_many()` and the profile repository port; the generic
  state contract never embeds persistence operations.
- `EvidenceLedger` is idempotent by evidence reference/version for delivery,
  while retaining all raw occurrences and changed versions for audit.
- The registered Food Pack remains the only owner of food-domain policy and
  final output semantics.  Generic investigation contracts do not import Food
  workflow/composition code.
- Every production run has one logical Agent loop, one Gateway boundary, one
  pinned capability snapshot, bounded budgets, and lossless evidence behavior.

## Delivery and Rollback

1. The additive contracts, scheduler, canonical loop, MCP snapshot adapter,
   Food reducer, and focused tests are implemented and validated.
2. The Composition Root and standalone orchestrator now select the adaptive
   workflow; direct model calls are still mediated by `ProviderModelGateway`.
3. Each run projects its state into the existing Food DTOs, records evidence
   through `EvidenceLedger`, and writes profiles through the existing port.
4. Rollback remains at the workflow authority boundary: a caller may inject
   the compatibility deterministic workflow without deleting evidence,
   profiles, history, or raw payloads.
5. A future change may add deterministic/adaptive shadow comparison and remove
   the compatibility implementation only after an explicit rollout review.
