## OpenSpec

- [x] Create proposal, design, tasks, and executable requirements for the
      model-driven rolling investigation Agent.
- [x] Define production supersession of deterministic planning while
      preserving the single-Agent, MCP Gateway, Food Pack, and no-data-loss
      boundaries.
- [x] Validate the change with strict, non-interactive OpenSpec checks.

## Canonical contracts

- [x] Add versioned Objective, Question, Hypothesis, PlanAction, PlanProposal,
      ObservationEnvelope, CritiqueDecision, InvestigationState, Termination,
      budget, usage, and capability-snapshot contracts.
- [x] Validate opaque JSON payloads, evidence references, plan DAGs,
      investigation identity, UTC timestamps, terminal state, and bounded
      budgets.

## Adaptive runtime

- [x] Implement the canonical immutable-state
      `InvestigationLoop` with one planner/critic Agent boundary and rolling
      Plan -> Act -> Observe -> Critique rounds.
- [x] Implement bounded concurrent `ActionScheduler` waves with dependency
      ordering, idempotency, resource limits, usage reconciliation, and typed
      rejection/gap observations.
- [x] Enforce state-revision, capability-snapshot, idempotency, Food Pack, and
      hard budget checks before executing a proposal.
- [x] Count typed policy, dependency, duplicate, and cancellation observations
      against the observation budget even when no provider call starts.
- [x] Drain cancellation safely, retain in-flight raw returns where available,
      record cancelled actions, and emit resumable typed termination metadata.

## MCP and Food integration

- [x] Capture and pin one managed MCP catalog snapshot per turn; expose only
      logical capabilities and fail closed when the account-service binding is
      unavailable.
- [x] Add the `FoodAdaptivePack` reducer for comments, profiles, claims,
      entities, controversies, coverage, pagination continuation, and typed
      retryable gaps.
- [x] Preserve raw source/provider payloads, cursors, provenance, payload refs,
      and evidence refs in state and final run projections.
- [x] Persist comment evidence through `EvidenceLedger` and profile data
      through the existing profile repository, retaining typed persistence
      gaps without discarding usable raw projections.

## Production cutover and verification

- [x] Switch the Composition Root and standalone orchestrator default to
      `AdaptiveFoodResearchWorkflow` while retaining the deterministic path as
      an injectable compatibility implementation.
- [x] Project adaptive runs into the existing Food response DTOs and expose
      adaptive strategy, coverage, observation, evidence, and gap metadata.
- [x] Synthesize terminal critic/termination conclusions and findings into the
      existing Food summary while exposing finding-level evidence references in
      auditable response metadata with a deterministic fallback.
- [x] Add focused contract, scheduler, Food reducer, MCP boundary, raw-data,
      budget, cancellation, persistence, and production-boundary tests.
- [x] Enforce discovered MCP input schemas for Food-generated follow-up
      actions, including note-ID controversy verification and Dianping
      identity resolution.
- [x] Add bounded, redacted lifecycle observations for Agent, model, MCP, and
      evidence-transform boundaries without coupling investigation outcomes to
      exporter availability.
- [x] Keep full evidence/raw payloads in state and audit projections while
      projecting each canonical observation only once into model context.

## Deferred rollout work

- [ ] Add deterministic/adaptive shadow comparison and operational rollout
      telemetry before removing the compatibility implementation.
- [ ] Add a durable restart/resume store for complete adaptive state snapshots;
      current continuation metadata is returned by the run boundary.
