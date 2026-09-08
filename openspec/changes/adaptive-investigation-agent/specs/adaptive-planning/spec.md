## Purpose

Define typed, revisioned planning contracts for the production adaptive
investigation loop.  The contracts roll bounded actions forward from evidence
without becoming an unbounded or provider-coupled workflow.

## ADDED Requirements

### Requirement: Plans are typed semantic proposals

The Agent MAY propose work only through a versioned `PlanProposal` containing
typed `PlanAction` values.  Each action MUST identify a logical capability,
validated JSON arguments, an idempotency key, and its dependencies.  A plan
MUST NOT encode provider credentials, client objects, or executable raw MCP
requests.

#### Scenario: A model proposes a search and verification

- **WHEN** the model emits two independent actions for the current objective
- **THEN** the proposal preserves both typed actions, their capabilities,
  arguments, rationale, and idempotency keys for runtime validation

#### Scenario: A proposal contains an unknown dependency

- **WHEN** an action depends on an action ID absent from the proposal
- **THEN** contract validation rejects the proposal before any Gateway call

### Requirement: Proposal revisions are state-bound

Every proposal MUST carry an investigation ID, objective ID, revision, and
base revision.  A proposal MUST be immutable after validation.  The adaptive
runtime MUST reject a proposal whose base revision is stale or whose
capability snapshot is unavailable rather than applying it to a different
state.

#### Scenario: A later observation supersedes a proposal

- **WHEN** state revision 3 has already produced a new observation and a
  proposal based on revision 2 is submitted
- **THEN** the proposal is treated as stale and no action is dispatched

### Requirement: Plan graphs are finite and acyclic

Plan action IDs MUST be unique.  Dependencies MUST refer to actions in the
same proposal, MUST be unique, and MUST NOT contain self-dependencies or
cycles.  Empty proposals MAY be represented when the critique chooses
termination, but they MUST NOT imply an implicit unbounded retry.

#### Scenario: A model emits a dependency cycle

- **WHEN** action A depends on B and action B depends on A
- **THEN** validation rejects the proposal with no partial execution

### Requirement: Capability metadata is Gateway-bound

Model-visible capability metadata MUST identify the project-owned
`mcp_gateway`, input/output schemas, side-effect class, timeout, and cost.  A
capability snapshot MUST have a stable opaque reference and unique public
capability names.  Unsafe side effects MUST remain visible as metadata and
MUST NOT be silently treated as read-only.  The production MCP session MUST
pin one such snapshot for the turn and release it when the turn closes.

#### Scenario: A snapshot contains a mutating capability

- **WHEN** a capability declares account mutation or publish side effects
- **THEN** the metadata preserves that declaration and policy can deny it
  before a model action reaches the Gateway

#### Scenario: A turn calls a capability after the catalog changes

- **WHEN** the active catalog has a different current projection after the
  turn's snapshot was captured
- **THEN** the action still resolves against the pinned snapshot or is
  rejected with a typed capability gap; it MUST NOT silently switch snapshots

### Requirement: Domain follow-ups use discovered input contracts

Food-generated follow-up actions MUST use only fields accepted by the pinned
MCP capability schema. `comments.search` MUST carry a note identity (or be
replaced by a schema-valid `notes.search` discovery action), and Dianping
detail/review actions MUST carry a provider shop identity. Domain context such
as controversy IDs, entity IDs, and evidence references MUST remain in the
action metadata rather than being sent as undeclared provider arguments.

#### Scenario: A controversy has a cited XHS note

- **WHEN** the Food reducer requests controversy verification
- **THEN** it emits `comments.search(note_id, max_comments, include_replies)`
  and keeps the controversy/evidence context in metadata

#### Scenario: A comment-only candidate has no provider identity

- **WHEN** the Food reducer needs structured Dianping data for a named shop
- **THEN** it emits `places.search(keyword)` first and does not invent a
  `places.detail` ID
