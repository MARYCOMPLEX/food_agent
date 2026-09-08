## Purpose

Define bounded progress, cancellation, and explicit termination for the
production rolling investigation, including partial continuation without data
loss.

## ADDED Requirements

### Requirement: Investigations have hard budget metadata

An `InvestigationBudget` MUST expose at least one finite ceiling and MAY bound
iterations, actions, tool calls, cost units, model tokens, observations, wall
time, and an absolute UTC deadline.  `BudgetUsage` MUST record actual
consumption and MUST remain serializable even when a provider call causes a
small measured overshoot.

#### Scenario: A token ceiling is reached

- **WHEN** usage reaches the configured token ceiling while evidence remains
- **THEN** the loop stops scheduling new model work, retains collected
  observations, and can terminate as partial with continuation metadata

#### Scenario: Concurrent actions compete for a hard budget

- **WHEN** two ready actions reserve estimated calls, tokens, or cost and only
  one reservation fits
- **THEN** the scheduler executes the admitted action, rejects the other with
  a typed `budget_exhausted` observation, and records actual usage

#### Scenario: An unbounded budget is requested

- **WHEN** every budget ceiling and deadline is omitted
- **THEN** contract validation rejects the budget before an investigation can
  start

### Requirement: Termination states a machine-readable reason

Every terminal decision MUST use a versioned `Termination` with an explicit
reason such as evidence sufficiency, budget exhaustion, deadline exceeded, no
progress, cancellation, failure, or policy denial.  A resumable termination
MUST carry continuation metadata.

#### Scenario: Evidence is sufficient

- **WHEN** critique determines that the objective is supported by adequate
  evidence
- **THEN** termination records `evidence_sufficient`, cited evidence
  references, and a concise summary

#### Scenario: A deadline expires

- **WHEN** the investigation reaches its deadline before all questions are
  answered
- **THEN** termination records `deadline_exceeded`, preserves successful raw
  observations, and includes a cursor or other continuation data when resume
  is possible

#### Scenario: A running investigation is cancelled

- **WHEN** the caller cancels an active run while an action is in flight
- **THEN** the scheduler drains or marks the action with a typed cancellation
  observation, the state becomes terminal `cancelled`, and termination keeps
  the collected raw payloads and resumable continuation metadata

### Requirement: Termination cannot hide active work

An `InvestigationState` with a termination value MUST use a terminal status,
and all nested termination/observation/critique identities MUST match the
investigation.  A non-terminal state MUST remain resumable through a future
critique/proposal rather than being treated as complete.

#### Scenario: A caller marks a running state terminated

- **WHEN** a termination is attached while state status is `running`
- **THEN** state validation rejects the contradictory snapshot

### Requirement: Budget exhaustion never discards evidence

Budget, cancellation, and policy termination MUST stop further work without
deleting raw payloads, evidence references, cursors, or prior plan history.

#### Scenario: Collection stops at an action limit

- **WHEN** the action budget is exhausted after several successful pages
- **THEN** all successful observations remain in state and the result exposes
  the exhaustion reason as partial or resumable termination

### Requirement: Rejected work consumes observation budget

Policy, dependency, duplicate, and cancellation outcomes MUST be recorded as
typed observations and MUST count toward `max_observations`, even when no
provider call was started.  The scheduler MAY overshoot the ceiling only to
retain the terminal rejection record that explains why work stopped.

#### Scenario: An action is rejected before provider execution

- **WHEN** an action is rejected for an unavailable capability or failed
  dependency
- **THEN** the scheduler records the typed rejection and increments observed
  usage before the next budget decision
