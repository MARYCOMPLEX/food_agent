# Account Service HTTP Contract

## ADDED Requirements

### Requirement: Service discovery is versioned
Each account service MUST expose `GET /v1/capabilities` with a stable
`service_id`, `service_version`, supported `platform_channels`, source
capabilities, login modes, and an expiry/refresh timestamp.  The response MUST
be JSON-safe and MUST NOT contain cookies, storage paths, QR bytes, signer
inputs, or provider response bodies.

#### Scenario: Main app accepts a compatible descriptor
- **WHEN** the descriptor has a supported protocol version and an explicitly
  configured service ID
- **THEN** the registry records the descriptor and routes only its declared
  channels/capabilities to that service.

#### Scenario: Descriptor drift fails closed
- **WHEN** the service version, channel, or capability contract is outside the
  configured allow-list
- **THEN** readiness reports `dependency-unavailable` and no provider call is
  attempted.

### Requirement: Account and login resources use opaque references
The service MUST implement account registration and login resources under
`/v1/accounts` and `/v1/login`.  Requests and responses MUST use
`tenant_ref`, `account_ref`, `flow_id`, `credential_ref`, and `object_ref` as
opaque references.  Raw cookies, authorization headers, QR payloads, signer
state, browser profile paths, and decrypted envelopes MUST be rejected.

#### Scenario: Start QR login
- **WHEN** an authorized caller posts to
  `/v1/accounts/{platform}/{account_ref}/login/qr`
- **THEN** the service returns a flow projection containing `flow_id`, state,
  expiry, and a redacted QR presentation reference.

#### Scenario: Poll and cancel a flow
- **WHEN** the caller polls or cancels `/v1/login/{flow_id}` with the same
  tenant and idempotency context
- **THEN** the service returns a monotonic state projection and never returns
  provider credentials or raw response bodies.

### Requirement: Source invocation is account-bound
The service MUST expose a versioned source invocation endpoint or equivalent
tool that accepts a query, opaque account reference, expected session version,
correlation ID, capability, and bounded timeout.  Canonical documents,
comments, and media references MUST use the existing public evidence shape.

#### Scenario: Account isolation
- **WHEN** two tenants or two platform channels use the same alias
- **THEN** their service-side sessions, leases, browser contexts, and health
  records remain independent and cross-scope access returns the same denied or
  not-found envelope.

### Requirement: Transport errors are stable and redacted
The client and service MUST map timeout, unavailable, authentication,
rate-limit, malformed, and provider-risk outcomes to stable error codes.  A
transport error MUST NOT include request headers, credential values, storage
paths, or raw provider payloads.

#### Scenario: Service outage
- **WHEN** the configured service cannot be reached within the request budget
- **THEN** the main app returns `dependency-unavailable` with the service ID
  and capability version only.
