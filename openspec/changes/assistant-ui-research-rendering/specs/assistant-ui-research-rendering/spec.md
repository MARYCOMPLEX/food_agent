## Purpose

Provides a projection-driven research conversation surface that exposes the
Agent's evidence and uncertainty clearly while keeping UI rendering replaceable.

## ADDED Requirements

### Requirement: The research surface consumes the versioned public projection

The research-session UI MUST initialize from and render `UserResearchProjection
v1`; assistant-ui message types MUST remain a frontend projection and MUST NOT
be used as the backend persistence contract.

#### Scenario: Snapshot bootstraps a session

- **WHEN** a research session opens with a valid projection snapshot
- **THEN** the UI renders its plan, evidence, controversies, profiles, gaps,
  metrics, and terminal state without requiring legacy restaurant fields

### Requirement: Incremental events are deterministic and reconnectable

The frontend adapter MUST validate public events, ignore duplicate event IDs,
detect sequence gaps, and apply events in order. A reconnect MUST be able to
replace or hydrate the local projection from a snapshot and continue from the
latest accepted sequence.

#### Scenario: Duplicate and out-of-order events arrive

- **WHEN** an already applied event or a future event with a sequence gap is
  received
- **THEN** the duplicate causes no visible change and the gap enters a
  resynchronization state without corrupting the projection

### Requirement: Public research information has explicit renderers

The UI MUST provide safe, responsive renderers for comment evidence,
controversy sides, shop profile enrichment, research plan progress, and
partial/failure gaps. A renderer key or payload schema unknown to the client
MUST render a bounded fallback state and MUST NOT execute server-provided code.

#### Scenario: A shop profile and a source gap arrive incrementally

- **WHEN** the projection receives a profile upsert followed by a retryable gap
- **THEN** the profile remains visible, the affected fields show partial state,
  and the gap exposes its retryability without hiding existing evidence

### Requirement: Conversation actions cross a transport boundary

Cancel, retry, refine, expand evidence, and other interactive actions MUST be
sent through an explicit transport/action callback with a client request ID;
components MUST NOT mutate authoritative projection state locally.

#### Scenario: A user retries a failed source operation

- **WHEN** the user activates retry on a retryable gap
- **THEN** the UI emits an idempotent action command and waits for a public
  event or snapshot to update the displayed state

### Requirement: The research route remains usable across screen sizes

The research surface MUST render without horizontal overflow at desktop and
mobile viewports, expose keyboard-focusable controls, and preserve readable
evidence excerpts and failure messages in loading, empty, partial, and terminal
states.

#### Scenario: Mobile session with dense evidence

- **WHEN** a projection contains multiple evidence items and profiles at a
  narrow viewport
- **THEN** the UI stacks sections, keeps actions reachable, and does not clip or
  overlap evidence, controversy, or failure content
