# Application Analysis And Boundary Map

This is the implementation-level analysis used to freeze the public
experience contract. It describes the Agent path, not the whole product.

## Current Agent data path

```text
HTTP request / conversation turn
        |
        v
ResearchTask facade and session context
        |
        v
Adaptive investigation loop
  objective/questions -> planner -> typed action plan
        |                         ^
        v                         |
  scheduler -> Tool Gateway -> XHS MCP / Dianping MCP
        |
        v
ObservationEnvelope (normalized data + evidence refs + completeness + gaps)
        |
        v
critic / evidence review / replan decision
        |
        v
Food domain adaptation
  comment evidence -> claims/entities -> controversies
  optional shop enrichment -> durable ShopProfile projection
        |
        v
recommendations + coverage + termination + raw authority refs
```

The adaptive state already contains the facts needed for an evidence-first
experience. The problem is the projection boundary, not the absence of Agent
facts.

## Current public-path losses

| Current location | What it does | Why it cannot be the v1 public contract |
| --- | --- | --- |
| `contracts/research_runtime.py` | Reduces internal action lifecycle into rich `ResearchState` and runtime `ResearchEvent`. | Contains action results, source envelopes, provider-shaped data, and raw-capable fields. It is an execution authority, not a browser DTO. |
| `research/adaptive/food_workflow.py` | Produces comments, profiles, claims, controversies, gaps, coverage, and final recommendations. | The data is available only after the workflow result is assembled. |
| `orchestrator/core.py` + `events/emitter.py` | Emits legacy step/progress/restaurant/result/done SSE events. | The legacy stream waits for the complete workflow and does not expose comment evidence or controversy deltas. |
| `experience/reliable_events.py` | Maps reliable task admission and terminal states. | A completed event only carries a message; it drops the result projection. |
| `experience/results.py` | Maps HTTP results to legacy restaurant cards. | It intentionally strips research metadata, evidence references, and source gaps. |
| `frontend/src/shared/sse/useSSEStream.ts` | Consumes progress/result/error/done. | It ignores typed restaurant/analysis/evidence-like events and cannot reconstruct a projection. |

These are compatibility surfaces and remain unchanged in this freeze. The
new contract is the seam for a later dual-publish/cutover change.

## Observability separation

There are three different kinds of records and they must not be conflated:

1. **Execution facts**: internal runtime events, planner decisions, action
   attempts, budgets, tool identifiers, and reconciliation metadata. These are
   needed for replay/debugging and may contain sensitive/provider details.
2. **Operational observation**: redacted logs, traces, metrics, latency,
   retries, and failure taxonomy. These answer whether the Agent is healthy;
   they are not user evidence.
3. **Research evidence**: normalized comment/source facts with provenance,
   stance, claims, entity refs, and controversy sides. These are the only
   records allowed into the public projection, and only in bounded form.

`ResearchEvent v1` is a fourth, deliberately narrow layer: a user-safe delta
that is projected from (1) and (3), never from raw provider responses or trace
payloads. A trace ID may be added later under a namespaced operational
extension, but it must not become a business identity or expose trace content.

## Target incremental flow

```text
internal runtime event / normalized domain fact
        |
        v
allow-listed public projector
        |
        +--> ResearchEvent v1 append log (sequence + eventId)
        |         |
        |         +--> SSE / WebSocket / polling adapter
        |
        +--> UserResearchProjection v1 reducer (authoritative snapshot)
                              |
                              +--> frontend timeline, evidence, controversy,
                                   profile, recommendation, and gap views
```

The projector owns redaction and boundedness. The reducer owns ordering,
idempotency, keyed merge, and terminal behavior. Transport owns cursors and
replay retention. UI owns layout only. No layer below the projector may infer
user-facing controversy or fill missing profile values with defaults.

## Food-specific mapping

- XHS note comments become `evidence_added` items. `noteRef` and `commentRef`
  stay attached to each excerpt so the insight can be audited.
- Conflicting comment stances become `controversy_upserted`; the two sides
  reference evidence IDs rather than copying raw comment pages.
- Dianping/place enrichment becomes `profile_upserted`. Address, coordinates,
  images, dishes, prices, opening hours, tags, source refs, and completeness
  can arrive in several upserts and are persisted by the profile authority.
- A challenge, timeout, malformed response, or exhausted retry becomes
  `gap_upserted`. Existing evidence and candidate entities remain untouched.
- A candidate can be published as `recommendation_upserted` with `partial`
  status before all optional enrichment is available.
- The terminal event is `run_completed` with `succeeded` or `partial`, or
  `run_failed`/`run_cancelled` with a typed termination view.

## Why this is extensible

The core vocabulary describes research mechanics, not Food ranking rules. A
future domain can add `x.travel.*` or `x.retail.*` events and put domain data
under its namespace without changing sequence, replay, evidence, gap, or
terminal semantics. A v1 client can skip unknown namespaced events while still
advancing the cursor; a domain-aware client can layer a second reducer over the
same event stream.
