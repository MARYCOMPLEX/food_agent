## Purpose

Define the single-Agent research runtime that parallelizes independent work
without changing evidence authority or losing provider data.

## ADDED Requirements

### Requirement: Collection gaps permit one bounded research expansion

The active workflow MUST evaluate the typed result of its initial collection
wave before closing the note stream. It MAY dispatch at most one
`ExpandResearch` action only when the runtime and Planner both have a positive
`max_replans` budget and the initial wave contains a retryable `ResearchGap`.
Expansion MUST preserve stable note order and retain the raw payload from every
collection wave.

#### Scenario: One retryable collection gap opens one expansion wave

- **WHEN** the initial note search returns a typed retryable gap and both the
  runtime and Planner have a positive replan budget
- **THEN** the active workflow may dispatch exactly one `ExpandResearch` action,
  merges its notes after the initial notes in stable sequence order, and keeps
  both source waves' raw payloads; a non-retryable gap or a zero budget MUST
  not dispatch an expansion

### Requirement: The food route has one logical Agent and one runtime

The active food route MUST instantiate exactly one conversation-aware research
Agent and one bounded research runtime. It MUST NOT instantiate multi-Agent
handoffs, per-tool LLM agents, or a parallel legacy workflow.

#### Scenario: Composition root resolves food research

- **WHEN** the application resolves the food research use case
- **THEN** it resolves one Agent with one runtime, one pinned MCP snapshot, and
  injected source/evidence/profile ports

### Requirement: Independent actions execute with bounded structured concurrency

The runtime MUST execute independent actions concurrently and MUST enforce
per-resource concurrency, rate, timeout, retry, and total run budgets. Cursor
pages within one provider pagination chain MUST remain ordered.

#### Scenario: Multiple notes are available

- **WHEN** two notes have independent evidence requests
- **THEN** their requests may overlap, but the configured resource limit is
  never exceeded and each note's page order is preserved

#### Scenario: A downstream queue is full

- **WHEN** analysis cannot accept another item
- **THEN** collection applies backpressure instead of discarding or silently
  truncating the note

### Requirement: Collection and analysis form a streaming pipeline

The runtime MUST enqueue a note for analysis after that note's available
comment evidence is complete, without waiting for every search result. A
failed note MUST NOT prevent independent notes from being analyzed.

#### Scenario: One note finishes before another

- **WHEN** note A has complete comments while note B is still paginating
- **THEN** note A enters analysis immediately and its result is merged before
  the run's final synthesis barrier

### Requirement: Comment analysis is bounded and deterministic

Comment batches MAY execute concurrently under a token-aware limiter. The
merged result MUST be ordered by stable batch index and retain an evidence
reference for every extracted claim.

#### Scenario: One analysis batch fails

- **WHEN** a retryable LLM failure occurs for batch 2
- **THEN** other batches remain available, batch 2 produces a typed gap, and
  the result is partial rather than silently omitting its comments

### Requirement: Raw evidence and provider envelopes are lossless

Every successful note, comment page, comment, and profile response MUST retain
its raw provider payload, identifiers, cursor/provenance, and completeness
metadata. Summaries or insight records MUST NOT replace raw evidence.

#### Scenario: Provider returns an unknown field

- **WHEN** a source response contains a field not present in the normalized
  contract
- **THEN** the field remains accessible in the raw payload/extra map and the
  normalized item remains valid

### Requirement: Evidence and profile authorities remain separate

The runtime MUST write XHS comment evidence only through the evidence port and
stable Dianping shop data only through the profile port. Profile refresh MUST
NOT mutate or delete evidence.

#### Scenario: Profile enrichment is challenged

- **WHEN** Dianping detail or review calls require interactive verification
- **THEN** successful fields remain persisted, the profile is marked partial
  with a typed gap, and XHS evidence remains publishable

### Requirement: Semantic actions are policy-bound

The Planner MUST emit only the versioned semantic action set. The executor
MUST validate dependencies, capability allow-lists, schemas, idempotency keys,
and budgets before mapping an action to MCP.

#### Scenario: Planner proposes an unavailable capability

- **WHEN** an action maps to a capability absent from the pinned catalog
- **THEN** the action is rejected with a typed policy gap and no provider call
  is made

### Requirement: State transitions and writes are idempotent

Applying the same source event or commit more than once MUST produce the same
logical result and MUST NOT duplicate evidence or shop rows. Independent event
completion order MUST NOT change the final ordered result.

#### Scenario: A task is retried

- **WHEN** the same action result is delivered twice
- **THEN** the reducer and persistence layer keep one logical item and retain
  one provenance record for the source occurrence

### Requirement: Completion status explains incompleteness

The runtime MUST return `complete`, `partial`, `empty`, or `failed` according
to collected evidence and typed gaps. Budget exhaustion, cancellation, source
challenge, and unsupported shapes MUST be observable in gaps and continuation
metadata.

#### Scenario: Comment budget is reached

- **WHEN** pagination stops because a configured budget is exhausted
- **THEN** successful comments remain in the result, the continuation cursor is
  recorded, and the outcome is `partial`

### Requirement: Progress events represent actual work

The runtime MUST emit action start, progress, gap, and completion events as
work occurs. The event stream MUST preserve a stable sequence number per run
and MUST NOT claim a phase is complete before its dependent actions finish.

#### Scenario: Analysis overlaps collection

- **WHEN** a note begins analysis while another note is being collected
- **THEN** the stream exposes both action lifecycles with accurate counts and
  durations
