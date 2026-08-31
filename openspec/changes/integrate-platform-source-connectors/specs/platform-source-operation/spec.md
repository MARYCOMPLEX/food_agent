## Purpose

Bind account-aware platform connectors into the shared SourceGateway and
Temporal execution model without contaminating public query identity, adding a
second durable runtime, or changing legacy XHS behavior while the integration
is staged.

## ADDED Requirements

### Requirement: Account selection is outside public query identity

An account-bound source invocation MUST carry an opaque account reference and
expected session version separately from `CollectRequest`, `SourceLocator`,
Query Family identity, and public Evidence. The invocation MUST resolve account
authorization before any provider call.

#### Scenario: Same public query, different account
- **WHEN** two authorized accounts request the same canonical family
- **THEN** they may share public Evidence while each activity uses only its own session and health policy

#### Scenario: Unauthorized account
- **WHEN** an invocation names an account the caller cannot use
- **THEN** no connector is called and a stable authorization error is returned

### Requirement: Upstream runtimes do not become project runtimes

The integration MUST NOT start or import the upstream FastAPI application,
SQLite task scheduler, CLI data writer, or independent retry queue. Temporal is
the only durable execution runtime and PostgreSQL/Alembic remains the only
business/schema authority.

#### Scenario: Provider package is present
- **WHEN** the platform binding is enabled
- **THEN** only the typed adapter/provider modules are loaded and no upstream API server, SQLite task table, or broker is started

#### Scenario: Provider package is absent
- **WHEN** a binding is disabled or its pinned checkout is unavailable
- **THEN** the legacy connector remains usable and the new binding reports a stable dependency-unavailable health state

### Requirement: Connector registration is feature-gated and reversible

Each platform connector MUST register a versioned source ID/capability through
the Composition Root, pass the shared source contract suite, and be disabled
without changing legacy HTTP/SSE, Query Family, or stored evidence behavior.

#### Scenario: Enable Dianping binding
- **WHEN** the operator enables the Dianping binding with a valid vault and provider checkout
- **THEN** `dianping` is discoverable through SourceGateway with its pinned connector version

#### Scenario: Roll back a binding
- **WHEN** the operator disables a platform binding after a failed canary
- **THEN** new calls use the prior connector, in-flight Temporal runs finish or fail under their pinned version, and no public pointer or legacy result is rewritten
