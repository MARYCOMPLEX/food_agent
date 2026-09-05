## Purpose

Provide a default-off, privacy-preserving Evidence shadow path that records
candidate public evidence and provenance for qualification without changing
the existing research response or its source side effects.

## ADDED Requirements

### Requirement: Shadow activation is isolated and default-off

The system MUST keep Evidence shadow writes disabled unless an explicit
configuration enables them. The configuration MUST include a deterministic
sample rate and a bounded write budget, and changing the shadow setting MUST
not change the legacy response path, request status, or source connector
contract.

#### Scenario: Default deployment
- **WHEN** no Evidence shadow configuration is supplied
- **THEN** the system MUST perform no shadow writes and MUST return the legacy result unchanged

#### Scenario: Budget is exhausted
- **WHEN** the configured shadow write budget would be exceeded by a sampled batch
- **THEN** the system MUST skip that batch, record a bounded skipped outcome, and MUST NOT partially write it

### Requirement: Shadow input contains only public canonical semantics

The system MUST derive shadow identity and candidate Evidence only from the
versioned public canonical query and public source batch. User identifiers,
session identifiers, preferences, clicks, favorites, credentials, cookies,
tokens, QR data, and private account state MUST be rejected from public
Evidence rather than redacted into an apparently valid claim.

#### Scenario: Private field appears in a source batch
- **WHEN** a source batch contains a private field or private nested value
- **THEN** the system MUST reject the candidate shadow record, leave the legacy connector result intact, and record a privacy failure without persisting the value

#### Scenario: Two users share public semantics
- **WHEN** two requests have the same public canonical semantics but different private context
- **THEN** their eligible shadow records MUST use the same public identity and MUST contain no private-context field

### Requirement: Candidate Evidence has complete provenance

Every shadow candidate MUST carry a stable source locator, connector identity and
version, capture time, source update watermark when available, schema and
extractor versions, visibility, license, retention, content hash, and a link to
its originating source batch. A candidate missing any required provenance MUST
not be accepted by the shadow sink.

#### Scenario: Complete source record
- **WHEN** a sampled connector batch has valid public source items and provenance
- **THEN** the system MUST produce candidate Evidence records with stable identifiers and all required provenance fields

#### Scenario: Missing locator or schema version
- **WHEN** a candidate cannot be linked to its source locator or expected schema version
- **THEN** the system MUST reject the candidate and MUST NOT expose it as reusable Evidence

### Requirement: Shadow records are immutable candidates

Shadow output MUST be represented as candidate records and MUST NOT become the
current published Evidence Bundle. Repeated delivery of the same source item
with the same content hash MUST be idempotent, while a corrected item MUST
produce a distinct candidate version linked to its predecessor.

#### Scenario: Duplicate delivery
- **WHEN** the same sampled source item is delivered more than once with the same content hash
- **THEN** the sink MUST retain one logical candidate and MUST NOT inflate Evidence counts

#### Scenario: Corrected source item
- **WHEN** a source item changes and receives a new content hash
- **THEN** the system MUST retain the old candidate for audit and write a new candidate linked to the old one

### Requirement: Shadow failure cannot alter the legacy path

Failures in sampling, normalization, provenance validation, persistence,
telemetry, or shutdown handling MUST be isolated from the legacy connector and
research result. The system MUST classify failures as bounded outcomes and MUST
not report a successful shadow write until the candidate transaction has
committed.

#### Scenario: Shadow sink is unavailable
- **WHEN** the shadow sink times out or is unavailable after a connector succeeds
- **THEN** the system MUST return the connector's original result, record a dependency-unavailable observation, and leave the candidate unpublished

#### Scenario: Candidate transaction aborts
- **WHEN** candidate persistence aborts after validation
- **THEN** the system MUST report shadow failure only through bounded telemetry and MUST leave any existing published Bundle unchanged

### Requirement: B1 exit gate is measurable and reversible

The system MUST expose aggregate shadow counts, sampled/skipped counts, privacy
rejections, provenance failures, write failures, and legacy-versus-shadow
comparison digests without exposing raw query, prompt, output, account, or
private-memory content. B1 MUST remain non-serving until its migration,
provenance, failure-injection, and parity gates pass; disabling the B1 flag
MUST stop new writes without deleting candidate history.

#### Scenario: B1 gate passes
- **WHEN** the configured qualification window meets the declared parity, privacy, and persistence thresholds
- **THEN** an operator MAY enable the B1 shadow flag while legacy responses continue to be served

#### Scenario: B1 rollback
- **WHEN** an operator disables the B1 shadow flag
- **THEN** new shadow writes MUST stop promptly, legacy reads MUST continue, and prior candidates MUST remain available for investigation
