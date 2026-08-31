## Purpose

Provide a single project-owned account and session authority that keeps every
platform identity, credential version, health signal, and execution lease
isolated by tenant and account while remaining replaceable behind ports.

## ADDED Requirements

### Requirement: Account identity is explicitly scoped

The system MUST identify an external account by tenant, platform channel, and
opaque account reference.  A platform account MUST NOT be represented by an
environment-wide cookie, process-global singleton, or Query Family field.

#### Scenario: Same account reference on two platforms
- **WHEN** a tenant registers one Dianping account and one XHS PC account with the same local alias
- **THEN** the system stores and resolves two independent account identities and never reuses session material across them

#### Scenario: Cross-tenant lookup
- **WHEN** a caller requests an account or session belonging to another tenant
- **THEN** the request returns an authorization/not-found outcome without revealing account metadata or credential state

### Requirement: Session versions are encrypted and compare-and-set

The system MUST persist session material only as an authenticated encrypted
envelope with key metadata, expiry, and a non-reversible digest.  Activating a
new session MUST retire the prior active version atomically and MUST reject a
stale expected version.

#### Scenario: New session version
- **WHEN** an authenticated login completes for an account at version N
- **THEN** the authority commits version N+1 as the sole active session and stores no plaintext cookie or storage-state path

#### Scenario: Stale session writer
- **WHEN** two workers attempt to commit updates based on the same session version
- **THEN** exactly one commit succeeds and the other receives a conflict without changing the active session

### Requirement: Account leases are durable and platform-scoped

The system MUST acquire, heartbeat, and release a PostgreSQL-backed lease
keyed by tenant, platform channel, and account. Redis MUST NOT be the lease or
lock authority. At most one mutable provider client may execute for a lease
key at a time.

#### Scenario: Concurrent account activity
- **WHEN** two Temporal activities request the same account lease
- **THEN** one activity is admitted and the other receives a retryable conflict or waits according to the configured policy

#### Scenario: Different platform accounts
- **WHEN** a Dianping activity and an XHS activity run for the same tenant concurrently
- **THEN** both may proceed with independent leases and no mutable client or state is shared

### Requirement: Secrets are redacted at every project boundary

Cookies, QR payloads, signer inputs, storage-state paths, and decrypted session
material MUST NOT appear in Temporal inputs/history, SSE events, canonical
evidence, logs, metrics, or error messages. Public records MAY contain only
opaque account/session identifiers, versions, status, and digests.

#### Scenario: Provider error contains a cookie
- **WHEN** an upstream exception includes a cookie or authorization header
- **THEN** the mapped ContractError removes the secret and retains only a stable code and safe diagnostic fields

#### Scenario: Observability capture
- **WHEN** an account activity emits a trace or metric
- **THEN** labels contain bounded platform/status values and never raw account credentials or high-cardinality secret-bearing values

### Requirement: Health transitions quarantine unusable sessions

Authentication failure, challenge, expiry, or repeated transient failure MUST
update account health and prevent blind retries until the configured recovery
or re-authentication operation succeeds.

#### Scenario: Expired provider session
- **WHEN** a connector receives a provider response classified as authentication-expired
- **THEN** the session becomes expired/quarantined, the activity returns a stable retryable outcome, and a re-login is required before another provider call
