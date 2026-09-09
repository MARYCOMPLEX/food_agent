## Context

The adaptive Food workflow already retains the authoritative investigation state:
normalized observations, comments, claims, entities, controversies, profiles,
gaps, evidence references, raw provider returns, and termination metadata. The
runtime `ResearchEvent` contract and reducer are intentionally rich and may
contain action results or provider envelopes. They are therefore not safe to
serialize directly to a browser.

The current experience boundary has two incompatible projections. The legacy
emitter publishes `step_*`, `restaurant`, and `result` events, while the
reliable mapper publishes only task acceptance and terminal events. The Vue
client consumes only a subset of both. A new public projection must be
transport-neutral, replayable, incremental, and independent of the runtime
implementation or frontend framework.

## Goals / Non-Goals

**Goals:**

- Define one public `ResearchEvent v1` envelope and one
  `UserResearchProjection v1` snapshot for every client.
- Deliver bounded, user-readable updates for evidence, controversies, shop
  profiles, recommendations, and partial failures as soon as they are known.
- Make event application deterministic and idempotent across reconnects,
  duplicate delivery, and snapshot recovery.
- Keep raw evidence and provider payloads authoritative in their existing
  stores while exposing enough excerpts and provenance for a user to audit a
  conclusion.
- Keep the core contract domain-neutral and provide namespaced extension points
  for Food-specific fields and future research domains.
- Preserve the existing runtime, legacy SSE, reliable task semantics, routes,
  and database behavior until an explicit migration change adopts the contract.

**Non-Goals:**

- Replacing the internal adaptive `ResearchEvent` or `ResearchState` contract.
- Exposing prompts, chain-of-thought, credentials, account routing, raw MCP
  arguments, raw provider responses, or unbounded comment pages to clients.
- Redesigning Vue components, changing visual hierarchy, or enabling a new SSE
  route in this change.
- Defining Food ranking/scoring rules in the generic experience contract.

## Decisions

### 1. Separate runtime events from public experience events

The existing runtime event remains the authority for execution and reduction.
An explicit public projector creates `ResearchEvent v1` values from allow-listed
normalized facts. This avoids treating an internal action result as a browser
payload and prevents a future runtime field from silently becoming public API.

An alternative was to reuse the runtime model directly. That was rejected
because its `result`, `raw_payload`, and provider envelope fields are too broad,
and because runtime action ordering is not the same as user-visible evidence
ordering.

### 2. One envelope, typed core kinds, namespaced extensions

Every public update uses one envelope with stable identity, session/turn scope,
monotonic public sequence, timestamp, phase, status, mutation, entity reference,
typed core payload, and an `extensions` map. The core kind registry is finite:

```text
run_started, plan_updated,
action_started, action_progress, action_completed,
evidence_added, controversy_upserted, profile_upserted,
recommendation_upserted, gap_upserted, run_progress,
run_completed, run_failed, run_cancelled
```

Future kinds are accepted only when namespaced (`x.<namespace>.<name>`). Clients
must ignore unknown namespaced kinds after advancing the cursor. This gives
Food-specific evolution without adding a second event protocol.

### 3. Snapshot plus delta, not delta-only UI state

`UserResearchProjection v1` is the authoritative client read projection for a
turn. It contains the current status, semantic plan, bounded evidence items,
controversies, profiles, recommendations, gaps, coverage, metrics, and
termination state. Events are deltas; the snapshot is used after a missed
sequence, cursor expiry, page refresh, or a new client version.

The projection stores `lastSequence` and a bounded idempotency ledger of applied
event IDs. Applying an already-seen event is a no-op. A missing sequence causes
resync instead of guessing or silently merging an incomplete investigation.

### 4. Evidence is first-class and bounded

An evidence event may carry a bounded excerpt, source/note/comment references,
stance, claim/entity references, timestamp, and confidence. It never carries a
raw provider envelope. Full comments remain in the Evidence authority and can
be fetched by reference under the existing authorization boundary. This keeps
the product's comment-disagreement insight visible without duplicating all raw
source data into SSE or browser memory.

### 5. Upsert semantics preserve data and partial truth

Evidence is append-only. Profiles, controversies, recommendations, plans, and
gaps are keyed upserts/patches. A patch cannot replace a non-empty value with an
empty value unless the mutation is explicitly `replace` or `remove`. A profile
or recommendation can be `partial` and can reference gaps; a source failure
never erases successful evidence or profile fields.

Terminal `run_completed` carries `completed` or `partial` status. `run_failed`
and `run_cancelled` carry a typed user-safe termination/error object. No later
event may mutate a terminal projection; late events remain runtime audit data.

### 6. Transport cursors remain separate from logical event identity

`eventId` and `sequence` are application identities. An SSE server may assign a
transport `id` for `Last-Event-ID` replay, but that cursor is not embedded into
domain entities and is never used as a business identifier. A future WebSocket,
polling, or mobile adapter can deliver the same envelope unchanged.

### 7. Generic core, domain data under explicit namespaces

The core projection uses generic `EntityRef`, `EvidenceItem`, `ProfileView`,
`RecommendationView`, `GapView`, and `CoverageView` values. Food-specific data
(dish names, localness, controversy kinds, price bands) lives in `domainData`
or `extensions.food`, not in the generic runtime contract. Unknown fields are
preserved only inside explicitly namespaced extension maps.

### 8. No chain-of-thought or secret-bearing observability

The public plan contains a user-readable objective, phase labels, action names,
counts, and concise rationale. It does not contain planner prompts, critic
scratch work, raw arguments, account references, credentials, trace payloads,
or provider cookies. Operational observation records remain behind the existing
redacted observation boundary.

## Risks / Trade-offs

- **[Payload growth]** Evidence excerpts and profile images can make events
  large → enforce per-field and per-event bounds, send media references rather
  than binary data, and use snapshot pagination for large collections.
- **[Two schemas during migration]** Legacy and new streams may coexist → keep
  the projector additive, test both authorities, and do not remove legacy
  mappings until a separate cutover change passes browser/replay gates.
- **[Out-of-order delivery]** Concurrent actions complete in different orders →
  use a single public sequence assigned at projection time and require resync
  on a gap; entity merge order is deterministic by ID/version.
- **[Domain extension drift]** Flexible maps can become unreviewable → require
  namespaced keys, publish a per-domain schema alongside the core contract, and
  reject unnamespaced extension keys.
- **[Evidence privacy]** Comment excerpts may contain personal data → apply the
  existing evidence redaction policy before projection and expose only bounded
  source references/labels to unauthenticated clients.

## Migration Plan

1. Land the contracts, reducer, TypeScript types, examples, and contract tests
   without changing current routes or frontend rendering.
2. Add an adapter that projects normalized runtime milestones and Food reducer
   outputs into the new envelope; dual-publish only in a separately approved
   rollout change.
3. Add a snapshot endpoint/recovery adapter backed by the projection store and
   make the Vue stream consume one `research_event` envelope.
4. Compare legacy and new projection outputs for fixed fixtures, including
   comment evidence, controversy updates, profile challenges, gaps, duplicate
   events, and replay expiry.
5. Switch the frontend after the browser/replay gates pass. Rollback disables
   the new adapter and continues serving the existing event path; it does not
   delete evidence, profiles, or projection snapshots.

## Open Questions

None. The public field boundaries, ordering semantics, terminal behavior, and
extension rules are fixed in this change. Transport route selection and visual
presentation are intentionally deferred to follow-up implementation changes.
