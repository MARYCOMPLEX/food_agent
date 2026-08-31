## Purpose

Integrate the pinned Spider_XHS PC and Creator protocol clients behind a
replaceable canonical connector, adding the missing project-owned account
state and QR control without duplicating its signer or running its CLI data
writer.

## ADDED Requirements

### Requirement: PC and Creator channels are isolated

The system MUST model `xhs_pc` and `xhs_creator` as separate account channels
with independent encrypted session versions, device/signer state, health, and
leases. A PC session MUST never be supplied to a Creator client or vice versa.

#### Scenario: Same human account, two channels
- **WHEN** one user registers PC and Creator identities for the same tenant
- **THEN** the system creates two channel-scoped sessions and can re-authenticate either one independently

#### Scenario: Channel mismatch
- **WHEN** a Creator activity is given a PC session reference
- **THEN** it fails validation before calling Spider_XHS

### Requirement: PC read data is canonicalized

The connector MUST support bounded PC note search, note detail, comments, and
stable media references. It MUST normalize tuple/envelope provider results,
strip access-bearing URL parameters from canonical URLs, preserve opaque
watermark/cursor data, and keep raw payloads outside canonical attributes or in
the shared ObjectStore under policy.

#### Scenario: Note search with pagination
- **WHEN** Spider_XHS returns notes and a `has_more` cursor
- **THEN** the connector returns unique canonical documents and a resumable next cursor without leaking cookies or xsec tokens

#### Scenario: Malformed note
- **WHEN** an item lacks a stable note ID or URL cannot be normalized
- **THEN** that item is isolated as a non-retryable malformed error while eligible items remain represented as partial coverage

### Requirement: QR, phone, and cookie factories are wrapped, not reimplemented

The adapter MUST use the pinned upstream auth factories and lower-level split
phase methods, execute synchronous calls off the API event loop, and persist
returned mutable state through the project vault. It MUST NOT invoke
`Data_Spider`, CLI input, Excel/media filesystem writers, or a process-global
`.env` cookie.

#### Scenario: QR login
- **WHEN** an XHS PC or Creator login flow requests a QR challenge
- **THEN** the adapter returns an opaque challenge and polls it through the shared login state machine, committing only the account's encrypted session on success

#### Scenario: Provider risk response
- **WHEN** Spider_XHS returns a 406/429/risk-control response
- **THEN** the account is quarantined or rate-limited according to policy and blind retry is stopped

### Requirement: Creator publishing is a separate capability

The source connector MUST expose Creator read/health operations only in this
change. Publishing, uploads, scheduling, and business-platform APIs MUST remain
disabled until a separately versioned capability and idempotency contract is
approved.

#### Scenario: Publish method requested
- **WHEN** a caller attempts to publish through the source connector
- **THEN** the request is rejected as an unregistered capability without invoking Spider_XHS upload code
