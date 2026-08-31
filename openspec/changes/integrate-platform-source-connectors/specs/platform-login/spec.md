## Purpose

Offer a split-phase, account-scoped login control plane for QR, phone, and
cookie import flows without placing blocking provider interactions in the API
event loop or exposing credential material to clients.

## ADDED Requirements

### Requirement: Login attempts have a durable state machine

Every login attempt MUST have an opaque identifier, account scope, creation and
expiry time, and monotonic status transitions among `created`, `qr_ready`,
`waiting_scan`, `waiting_confirmation`, `succeeded`, `expired`, `failed`, and
`cancelled`. A terminal attempt MUST NOT transition again.

#### Scenario: QR attempt lifecycle
- **WHEN** a caller starts a QR login for a registered account
- **THEN** the API returns an opaque flow ID and short-lived QR presentation data, and subsequent polls expose status only

#### Scenario: Expired QR
- **WHEN** the QR expiry time passes before confirmation
- **THEN** the flow becomes `expired`, its QR object is no longer discoverable, and no session version is activated

### Requirement: QR bytes use the shared object boundary

QR images or equivalent binary challenges MUST be stored as short-lived
ObjectStore objects with PostgreSQL metadata and MUST be deleted or made
undiscoverable at terminal completion. Redis MAY hold only a bounded status
projection.

#### Scenario: QR retrieval
- **WHEN** a client requests the QR for an active flow
- **THEN** the service returns a time-limited presentation reference and never returns cookies, signer state, or a storage-state file

#### Scenario: Redis restart during login
- **WHEN** Redis is restarted while a QR flow is waiting for scan
- **THEN** the authoritative flow remains queryable from PostgreSQL/Temporal and the client can resume polling without creating a second flow

### Requirement: Login execution is cancellable and bounded

Provider login calls MUST execute in the account-auth Temporal boundary (or an
explicitly configured equivalent worker boundary), use bounded activity
timeouts/heartbeats, and honor cancellation. A cancelled flow MUST not commit a
session.

#### Scenario: Cancellation before confirmation
- **WHEN** the caller cancels a waiting QR flow
- **THEN** the flow becomes `cancelled`, provider polling stops at the activity boundary, and no active session changes

#### Scenario: Provider worker restart
- **WHEN** the login worker stops after a non-terminal poll
- **THEN** Temporal history resumes the same flow ID without duplicating an active session or losing the expiry deadline

### Requirement: Successful login validates and versions the session

On success the system MUST validate the returned account identity through the
provider, persist an encrypted session version with compare-and-set, and emit
only a redacted terminal receipt.

#### Scenario: Successful QR confirmation
- **WHEN** the provider confirms the QR and returns a valid external subject
- **THEN** the account is active, a new session version is committed, and the response contains status/version/subject metadata but no credential

#### Scenario: Invalid returned identity
- **WHEN** a provider reports success without a verifiable external subject
- **THEN** the flow becomes `failed`, the session is not activated, and the failure is classified as malformed or dependency-unavailable
