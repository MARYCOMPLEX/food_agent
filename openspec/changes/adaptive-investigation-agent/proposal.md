## Why

The bounded Food route used to choose a deterministic action set before the
runtime had seen enough evidence.  New facts, contradictions, pagination gaps,
and failed providers therefore could not influence the next bounded question.
The repository now has a canonical adaptive runtime, so the OpenSpec change
must describe the shipped behavior rather than a contract-only milestone.

## What Changes

- Define versioned contracts for objectives, questions, hypotheses, rolling
  plans, semantic actions, observations, critique decisions, immutable state,
  budgets, capability snapshots, and explicit termination.
- Execute one bounded `Plan -> Act -> Observe -> Critique` loop through
  `InvestigationLoop` and `ActionScheduler`.  Planner and critic model calls
  return typed semantic actions; the scheduler enforces dependency,
  idempotency, capability, resource, and budget checks.
- Pin each turn to one policy-approved `ManagedMcpToolSession` snapshot.
  `ManagedMcpToolPort` routes logical capabilities through the project-owned
  MCP Gateway, while an unavailable account-service binding fails closed.
- Use `FoodAdaptivePack` as the Food reducer.  It converts source envelopes
  into claims, entities, profiles, coverage, controversies, retryable gaps, and
  dynamically requested follow-up actions without replacing raw source data.
- Preserve raw provider returns, cursors, provenance, payload references, and
  evidence references in canonical state and the final `ResearchRunResult`.
  `EvidenceLedger` records comment evidence through its lifecycle/sink bridge;
  profile projections are written through the existing profile repository.
- Apply hard iteration, action, tool-call, token, cost, observation, wall-time,
  and deadline limits.  Actual usage, reservation overshoot, cancellation
  observations, typed gaps, and resumable termination metadata remain visible.
- Project one normalized observation history into each model request while
  retaining complete comments/provider envelopes in the audit state, and emit
  only bounded redacted lifecycle observations through the optional
  project-owned ObservationPort.
- Switch the Composition Root and direct orchestrator default to the adaptive
  Food workflow while retaining the deterministic workflow only as a
  compatibility implementation.  The public Food response shape remains
  unchanged and identifies the strategy as `adaptive_investigation/v1`.

## Supersession

This change supersedes the deterministic `ResearchPlanner` as the production
decision authority.  The existing deterministic workflow remains available to
compatibility callers and rollback tooling, but the Composition Root and
standalone orchestrator now construct `AdaptiveFoodResearchWorkflow`.

## Goals

- Let one logical Agent adapt a bounded investigation to evidence, gaps, and
  explicit critique without creating sub-Agents or an untyped tool loop.
- Keep actions typed, dependency-checked, idempotent, serializable, and bound
  to the active state revision and MCP capability snapshot.
- Preserve every raw provider envelope and evidence reference so normalized
  summaries are never the sole source of truth.
- Keep source execution behind the MCP Gateway, Food semantics in the
  registered Food Pack, and evidence/profile writes behind their owning ports.
- Make budget exhaustion and cancellation observable, partial, and resumable
  instead of silently dropping collected evidence.

## Non-Goals

- No second Agent, Agent handoff, per-tool Agent, arbitrary browser worker, or
  new orchestration framework.
- No direct MCP client, provider credential, account session, or persistence
  implementation in the generic contract module.
- No change to the public Food response schema or transfer of evidence/profile
  authority into the generic investigation engine.
- No dual-run shadow comparison or deletion of the deterministic compatibility
  path in this change.

## Impact

The additive adaptive contracts are consumed by the canonical runtime and
Food adapter.  Production composition now injects the existing model gateway,
managed MCP session, evidence ledger, and profile repository into the adaptive
workflow.  Successful and partial runs expose the same transport DTOs together
with adaptive state, raw observations, coverage, gaps, and evidence counts;
provider failures and policy denials remain typed rather than becoming empty
successes.
