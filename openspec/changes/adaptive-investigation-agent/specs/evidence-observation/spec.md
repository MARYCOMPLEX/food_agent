## Purpose

Define lossless, serializable observation envelopes and their Food reduction /
evidence persistence boundary without replacing source evidence with model
summaries.

## ADDED Requirements

### Requirement: Observations preserve raw and normalized values

Every `ObservationEnvelope` MUST separate normalized `data` from the original
JSON `raw_payload` when a source or tool returns data.  The envelope MUST
retain source/capability identity, outcome, timestamps, provenance, and
completeness metadata.  Unknown provider fields MUST remain accessible in the
raw payload rather than being dropped during normalization.

#### Scenario: A provider adds an unknown field

- **WHEN** a tool result contains a field not modeled by the current
  normalized projection
- **THEN** the observation remains valid and the field is preserved in
  `raw_payload`

#### Scenario: A source returns a partial page

- **WHEN** a result contains a continuation cursor or an incomplete page
- **THEN** the envelope records `next_cursor`, `has_more`, completeness, and
  all evidence references collected before the gap

#### Scenario: The Food reducer receives a provider envelope

- **WHEN** `FoodAdaptivePack` adapts a `SourceCall` or `SourceEnvelope`
- **THEN** it emits normalized claims, entities, profiles, coverage, and
  retryable gaps while retaining the original envelope in observations and
  `raw_provider_payloads`

### Requirement: Evidence references are explicit and unique

Observation evidence references MUST be non-empty and unique within an
envelope.  State accumulation MUST union references from observations and
MUST NOT replace them with a generated summary or a profile identifier.

#### Scenario: Analysis cites two source occurrences

- **WHEN** a critique uses two comment evidence references
- **THEN** both references remain on the decision and in the investigation
  state's accumulated evidence reference set

### Requirement: Failure is observable, not an empty success

An observation with a failure outcome MUST NOT claim complete completeness.
Unsupported shapes, policy rejection, provider challenge, and cancellation
MUST be represented by a typed non-success outcome and retained metadata.

#### Scenario: A Gateway call is rejected

- **WHEN** policy rejects a proposed capability before transport
- **THEN** the loop records a rejected observation or typed termination reason
  and does not fabricate an empty successful source result

### Requirement: Evidence and profile authorities stay separate

Observation contracts MAY carry evidence references and source payloads, but
MUST NOT encode persistence operations that merge Food evidence with stable
shop-profile authority.  Future adapters MUST write each authority through
its existing project-owned port.

#### Scenario: Profile enrichment fails after evidence succeeds

- **WHEN** a secondary profile call is challenged
- **THEN** prior evidence observations remain available and the profile gap is
  represented independently

### Requirement: Evidence persistence is idempotent and lossless

The production Food workflow MUST pass comment notes through `EvidenceLedger`
and profile projections through the existing profile repository.  Replaying
the same evidence version MUST NOT duplicate semantic delivery, while every
raw occurrence and changed version MUST remain exportable for audit.  A failed
sink or profile write MUST produce an observable typed gap without deleting
the normalized or raw projection from the run.

#### Scenario: The same comment page is replayed

- **WHEN** the workflow records the same note/comment version twice
- **THEN** the evidence reference remains stable, semantic delivery is
  idempotent, and the ledger retains the replay occurrence in its audit export

#### Scenario: Profile persistence fails after evidence succeeds

- **WHEN** the profile repository rejects one enriched profile
- **THEN** comment evidence and raw profile data remain in the run and a
  retryable `profile_persistence_failed` gap is exposed independently
