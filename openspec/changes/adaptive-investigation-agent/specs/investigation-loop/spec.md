## Purpose

Define the production observe/critique/propose loop while retaining one
logical Agent, one MCP Gateway boundary, and the existing Food Pack ownership
model.

## ADDED Requirements

### Requirement: The loop is one Agent with typed state

The investigation loop MUST use one logical Agent and one canonical
`InvestigationState` for a run.  Planner and critic calls MAY be separate model
roles, but runtime policy, budget, Gateway execution, Food reduction, and state
updates remain project-owned responsibilities.  The loop MUST NOT create
sub-Agents, per-tool Agents, or an alternate workflow/composition route.

#### Scenario: A food investigation needs another source

- **WHEN** critique identifies an unanswered question after a source result
- **THEN** the same Agent emits a new revisioned proposal through the existing
  Gateway boundary and the Food Pack remains the domain-policy authority

### Requirement: Critique decisions are evidence-aware

Every `CritiqueDecision` MUST identify the investigation, disposition, and
the observation/question/hypothesis or evidence references considered.  Its
disposition MUST be one of `continue`, `replan`, `request_evidence`,
`synthesize`, or `terminate`.

#### Scenario: Evidence is contradictory

- **WHEN** observations support incompatible hypotheses
- **THEN** the critique records the contradiction context and requests a
  bounded verification/replan rather than silently selecting one claim

### Requirement: The final Food synthesis is evidence-aware

When the Food workflow reaches a terminal state, its existing response summary
MUST derive the conclusion from the terminal critic/termination record and the
accumulated findings and evidence references. It MUST NOT reduce the final
result to entity or recommendation counts alone. Response metadata MUST retain
the exact finding values, finding-level evidence references, termination
reason, and state revision for audit. If the model omits a usable conclusion,
the workflow MUST use a deterministic count-based fallback while preserving the
available evidence audit and raw provider payloads.

#### Scenario: A critic returns a supported final finding

- **WHEN** the terminal critic provides a conclusion, finding, and evidence
  reference
- **THEN** the existing Food summary includes the conclusion and finding, and
  response metadata exposes the exact evidence reference without replacing the
  source observation

#### Scenario: A critic omits a usable final conclusion

- **WHEN** termination and critic text are empty or generic
- **THEN** the workflow uses its deterministic recommendation summary and still
  exposes accumulated findings, termination state, and evidence references

### Requirement: State retains rolling history

`InvestigationState` MUST retain all accepted observations and historical plan
proposals for the investigation.  State identity and nested observation,
critique, and termination IDs MUST match the investigation ID.  Repeated
observation IDs MUST be rejected so retries can be deduplicated explicitly.

#### Scenario: A provider retries the same result

- **WHEN** the same observation envelope is delivered twice
- **THEN** the state contract rejects the duplicate ID and the runtime can
  apply an idempotent deduplication policy without deleting its raw payload

### Requirement: Food reduction drives bounded follow-up work

The production Food workflow MUST feed observed source envelopes through
`FoodAdaptivePack`.  The reducer MUST derive candidate entities, claims,
profiles, coverage, controversies, and typed gaps, and MAY return bounded
semantic follow-up actions for unresolved coverage, controversy, or cursor
continuation.  It MUST NOT call providers directly.

#### Scenario: A comment page has an unresolved controversy

- **WHEN** the Food reducer sees conflicting sentiment or a retryable partial
  page
- **THEN** it emits a bounded `comments.search` or verification action carrying
  the relevant entity/cursor context, and preserves the original observation

### Requirement: Production entry uses the adaptive workflow

The Composition Root and standalone `XHSFoodOrchestrator` default MUST resolve
to `AdaptiveFoodResearchWorkflow`.  The workflow MUST project its canonical
state into the existing Food response DTOs and expose adaptive strategy,
coverage, observation, evidence, and gap metadata.  The deterministic workflow
MAY remain available only as an explicitly injected compatibility path.

#### Scenario: A production search is constructed without an override

- **WHEN** the Composition Root or orchestrator builds the research workflow
- **THEN** it uses the adaptive Food workflow, which opens one managed MCP
  session and returns the existing public Food response shape

### Requirement: Food Pack boundaries remain unchanged

Generic investigation contracts MUST NOT define food scoring, ranking,
profile persistence, or public response semantics.  Food-domain behavior MUST
continue to be supplied by the registered Food Pack, and source execution MUST
remain behind the MCP Gateway.

#### Scenario: A generic plan targets Food behavior

- **WHEN** a plan requests a food-domain operation
- **THEN** it names a logical capability and Gateway snapshot while the Food
  Pack validates domain inputs and owns the resulting public semantics

### Requirement: Model context is compact without changing evidence authority

Every planner and critic request MUST expose the canonical normalized
observation history at most once per request and MAY expose a bounded latest
wave projection for recency. Raw provider payloads, raw MCP returns, and
source payload copies MUST remain in the run/state audit boundary but MUST NOT
be duplicated into model context. Removing a duplicate model-view field MUST
NOT remove it from the canonical observation or final run projection.

#### Scenario: A later round reuses a large comment page

- **WHEN** the planner is called after a round containing full XHS comments
- **THEN** the model receives one normalized observation/history reference and
  the current wave projection, while state and the evidence ledger retain the
  complete comments and provider payload

### Requirement: Lifecycle observations are redacted and non-authoritative

The adaptive workflow MUST emit bounded project-owned observations for the
Agent run, model roles, MCP calls, and evidence transformation when an
`ObservationPort` is configured. Records MUST contain only allow-listed
status, operation, count, duration, and opaque correlation values; they MUST
NOT contain prompts, arguments, URLs, credentials, comments, or provider
payloads. Observation export failure MUST NOT change the investigation result,
state, or evidence persistence.

#### Scenario: An OTLP exporter is unavailable

- **WHEN** the observation port rejects or raises while a tool call succeeds
- **THEN** the Agent keeps the successful raw observation and returns the same
  research result, while the exporter failure is isolated to telemetry
