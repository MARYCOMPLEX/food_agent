# ADR-0013: Explicit Refresh Contract And Mapping Authority

Status: Accepted

Date: 2026-08-24

Owners: API + Evidence

Decides: OQ-28 and task 1.17; supplies the B2 contract for tasks 10.6 and 10.11

## Context

B2 now has an explicit refresh use-case, but it is intentionally not bound to
the current HTTP surface. The use-case must be reviewable without making the
legacy search route or six-step SSE stream an accidental refresh API. It also
needs one durable identity for concurrent callers so a refresh cannot be
duplicated by a cache or process-local lock.

Evidence is the implementation and contract suite in
`tests/test_unit_b2_explicit_refresh.py` and
`tests/test_unit_b2_explicit_refresh_contract.py`. The B2 verification and
rollback runbook record that the binding remains disabled and that no external
refresh route is present.

## Decision 1: Versioned request contract

The authority name is `explicit-refresh/v1`. A refresh command is a
`ResearchRequest` with:

- `operation = refresh`;
- a non-empty `queryFamilyId` identifying the existing public Family;
- a non-empty, canonical `refreshScope` array;
- explicit `policyVersion` and `compatibilityVersion` values; and
- a boolean `force` flag, defaulting to `false`.

The wire mapper accepts the versioned camelCase fields and produces the
domain-neutral request contract. `RequestIdentity` remains separate from
`publicInputs`; subject, session, tenant, and authorization references never
enter the public refresh identity.

## Decision 2: Ordinary and forced refresh

Ordinary refresh uses the approved Freshness Gate policy and may refresh only
the requested scope. Forced refresh explicitly bypasses the ordinary freshness
decision and requires the `refresh:force` authorization reference. The policy
check MUST happen before the durable claim and before any Connector call.

Both modes use the Research Orchestrator and Evidence ports. The refresh
use-case MUST NOT call a platform Connector directly, edit the current Bundle
in place, or create a user-specific public Bundle.

## Decision 3: Stable identity and in-flight merge

The single-flight preimage is exactly:

```text
refresh-single-flight/v1 + family_id + canonical scope + policy_version
```

The PostgreSQL claim key and Temporal Workflow ID are deterministic SHA-256
derivations of that preimage. The task ID is a deterministic derivation of the
Workflow ID. A compatible request (same Family, scope, and policy version)
reuses the existing claim, Workflow ID, task ID, and event identity; it may
describe the existing Workflow but MUST NOT start another one. A request with
a different scope or policy version is not compatible and receives its own
identity.

The claim and current-pointer activation are authoritative PostgreSQL
operations. Redis, process memory, or an EventBus value cannot decide refresh
ownership or publication. A late refresh writer can publish only through the
conditional current-pointer update, so an older base cannot replace a newer
Bundle.

## Decision 4: Bundle and event semantics

Refresh produces an immutable candidate Evidence Bundle. The current pointer
changes only after provenance, schema, feature, score, and index validation and
a successful PostgreSQL CAS. Failure leaves the previous Bundle readable.

The accepted event has stable internal identity:

```text
event_id   = {task_id}:refresh:accepted
event_type = task.refresh.accepted
```

Its payload contains `familyId`, `workflowId`, `reused`, and `force`. Both a
newly acquired and a reused request publish the same event ID, allowing event
consumers to apply the admission exactly once.

If a future, separately approved refresh route exposes this task stream, its
mapper MUST preserve the task/turn/workflow identity and use the existing
versioned SSE boundary and replay rules. It MUST NOT add refresh-specific
legacy step IDs or change the current six-step compatibility stream. The
current B2 binding has no external SSE route and therefore does not alter the
legacy HTTP/OpenAPI snapshot.

## Decision 5: New behavior boundary and rollback

Explicit refresh is new target behavior, not a legacy compatibility contract.
The existing `/v1/search/` command and current legacy SSE stream do not gain a
refresh operation through this ADR. Exposing refresh externally requires a
separate API/version authority fixture and an explicit composition binding.

The B2 rollback disables the explicit-refresh/read-reuse binding, restores the
previous Bundle/profile pointer through conditional CAS, and keeps immutable
Bundles, claims, and Temporal history for audit. It does not delete evidence,
workflow history, or database rows.
