## Purpose

Define one versioned, replayable user-facing research contract so a client can
observe evidence, disagreements, profile enrichment, recommendations, and
partial failures incrementally without receiving runtime internals or raw
provider payloads.

## ADDED Requirements

### Requirement: Public research events use one versioned envelope

Every user-facing research update MUST use the `ResearchEvent v1` envelope with
`schemaVersion`, `eventId`, `sessionId`, `taskId`, `turnId`, `sequence`,
`occurredAt`, `kind`, and a JSON-safe payload. `eventId` MUST be a stable
logical identity and `sequence` MUST be a positive, monotonically increasing
number within one session turn. Transport-assigned SSE cursors MUST remain
separate from these fields.

The core event kinds MUST include run start/progress/terminal states, plan and
action lifecycle, evidence addition, controversy upsert, profile upsert,
recommendation upsert, and gap upsert. An extension kind MUST use an explicit
namespace and MUST NOT replace the meaning of a core kind.

#### Scenario: Client receives an evidence update

- **WHEN** a normalized comment evidence item becomes publishable
- **THEN** the client receives one `ResearchEvent v1` envelope with a unique
  event ID, the same session/turn identity as the run, a new sequence, and an
  `evidence_added` payload containing only bounded public fields and provenance

#### Scenario: A future domain adds an event

- **WHEN** a domain publishes `x.travel.itinerary_item_added`
- **THEN** a v1 client that does not know the kind can ignore its payload after
  advancing the cursor, while the event remains valid and replayable

### Requirement: Public payloads are safe and bounded

The public event and projection contracts MUST reject or omit prompts, model
scratch text, credentials, cookies, account/session secrets, raw MCP arguments,
raw provider responses, and unbounded binary or text payloads. Evidence MAY
contain a bounded excerpt, source/note/comment references, stance, confidence,
timestamps, and claim/entity references. Full raw evidence MUST remain behind
the existing evidence authority.

#### Scenario: Provider response contains an unknown field

- **WHEN** an internal source envelope has a provider-specific field that is not
  part of the public projection
- **THEN** the public event omits that field while the authoritative evidence
  store retains it for audit

#### Scenario: A caller tries to publish a credential-shaped field

- **WHEN** an event payload includes a cookie, token, authorization value, raw
  provider payload, or planner prompt
- **THEN** contract validation rejects the event before it reaches a client

### Requirement: User projection is a complete snapshot of the public state

`UserResearchProjection v1` MUST identify the session, task, turn, and run and
MUST expose the current status, semantic phase, user-readable plan, summary,
bounded evidence items, controversy views, shop profile views,
recommendations, gaps, coverage, metrics, and terminal/continuation metadata.
Fields that are unavailable MUST be represented as unknown or absent; the
projection MUST NOT fabricate scores, counts, prices, or evidence.

#### Scenario: A client refreshes after the run completes

- **WHEN** the client requests the projection without an active SSE stream
- **THEN** it receives the same logically ordered evidence, controversy,
  profile, recommendation, gap, coverage, and terminal state that would result
  from applying the retained public events

#### Scenario: A profile is not available

- **WHEN** the secondary profile source is challenged or returns a typed gap
- **THEN** the projection retains the candidate and all comment evidence,
  marks the profile partial/unavailable, and exposes the gap instead of filling
  default address, price, rating, or review counts

### Requirement: Incremental entities use explicit mutation semantics

Evidence events MUST be append-only. Plan steps, controversies, profiles,
recommendations, and gaps MUST support keyed `upsert`/`patch` semantics and
MAY use explicit `replace` or `remove` mutations. A patch MUST NOT overwrite a
known non-empty value with an empty value unless the mutation explicitly allows
replacement. Each entity MUST have a stable reference independent of display
name or array position.

#### Scenario: Profile fields arrive in separate waves

- **WHEN** an address arrives first and dishes/images arrive later
- **THEN** the projection merges the later profile event into the same profile
  identity without deleting the address or previously known fields

#### Scenario: Duplicate evidence is delivered after reconnect

- **WHEN** the same evidence event is delivered twice with the same event ID
- **THEN** the projection contains one logical evidence item and the reducer
  reports no additional user-visible change

### Requirement: Comment evidence and controversy are first-class updates

The contract MUST represent comment evidence separately from the final
recommendation. An evidence item MUST be able to reference its source note and
comment, a bounded quote/excerpt, stance, entities, and claims. A controversy
MUST be able to reference an entity, topic, opposing evidence/claim references,
status (`unresolved`, `partially_resolved`, or `resolved`), and a concise
user-readable resolution or remaining question.

#### Scenario: Conflicting comments trigger a follow-up

- **WHEN** positive and negative comment evidence for the same shop conflicts
- **THEN** the client receives evidence additions followed by a controversy
  upsert showing both sides and `unresolved` status; later verification may
  upsert the same controversy to `resolved` without removing its evidence

#### Scenario: A recommendation is published before all comments finish

- **WHEN** a candidate meets the minimum evidence threshold while another note
  is still being collected
- **THEN** the client may render the candidate with its current evidence and a
  partial coverage/gap state, and later events may enrich it

### Requirement: Partial failures preserve usable work

A source, action, profile, or evidence failure MUST be represented by a typed
gap event with source, operation, stable code, user-safe message, retryability,
affected entity references, and continuation information when available. A
partial run MUST remain distinguishable from a complete run, and a failed
optional source MUST NOT erase successful evidence or profiles from the
projection.

#### Scenario: Dianping detail is challenged

- **WHEN** a shop profile call requires interactive verification after XHS
  comments have produced valid evidence
- **THEN** the projection keeps the evidence and candidate, emits a profile
  gap, marks the profile/candidate as partial where applicable, and allows the
  run to complete with `partial` status

#### Scenario: All required evidence fails

- **WHEN** no usable evidence is collected and the required source attempts
  fail
- **THEN** the run terminates as `failed` with a terminal error/gap and does not
  publish an apparently successful empty recommendation set

### Requirement: Projection application is ordered and idempotent

The public reducer MUST verify session/task/turn identity, reject a missing
sequence, ignore an already-applied event ID, and require snapshot resync when
an event arrives outside the retained contiguous sequence. Applying the same
ordered event list more than once MUST produce the same projection. A terminal
projection MUST reject later user-visible mutations.

#### Scenario: Replay cursor skips an event

- **WHEN** the client receives sequence 12 after its last applied sequence is 10
- **THEN** it does not guess the missing state; it requests or applies a
  `UserResearchProjection v1` snapshot before continuing

#### Scenario: Late provider completion arrives after cancellation

- **WHEN** an action completion is delivered after `run_cancelled`
- **THEN** the event may remain in audit storage but cannot mutate the public
  terminal projection

### Requirement: Reconnect and replay have explicit snapshot semantics

The event stream MUST support an exclusive transport cursor and MUST expose a
stable resync signal when that cursor is outside the retained window. The
resync signal MUST identify the session/task/turn and provide either an
authoritative projection snapshot or an unambiguous snapshot reference. A
client MUST NOT create a new research task solely because replay expired.

#### Scenario: Retained cursor reconnects

- **WHEN** a client reconnects with a retained cursor
- **THEN** the server replays events strictly after that cursor, preserving
  logical event sequence and terminal semantics

#### Scenario: Cursor retention expires

- **WHEN** a client reconnects with an expired cursor
- **THEN** the server returns a resync control event and the current
  `UserResearchProjection v1`; it does not fabricate missing events or create a
  duplicate task

### Requirement: Contract evolution is additive and namespaced

Adding an optional field, entity attribute, or namespaced extension MUST remain
backward compatible. Existing field meanings and core event kinds MUST NOT be
reused for a different semantic. Removing a required field, changing enum
meaning, or changing ordering/terminal semantics MUST require a new major
contract version and an explicit migration.

#### Scenario: Food adds a controversy classifier

- **WHEN** Food adds `extensions.food.controversyKind`
- **THEN** v1 clients continue to parse the core event and projection while
  Food-aware clients can consume the additional field

#### Scenario: A core field changes meaning

- **WHEN** a producer wants `confidence` to mean a different statistical value
- **THEN** it must introduce a new version or namespaced field rather than
  silently changing the v1 meaning
