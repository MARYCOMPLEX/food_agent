# Account Service Registry

## ADDED Requirements

### Requirement: Configuration selects isolated services
The main application MUST load a list of account services from configuration.
Each entry MUST contain a unique service ID, base URL, protocol mode (`http`,
`mcp`, or `http+mcp`), allowed channels, capability allow-list, timeout, and
descriptor version.  A service entry MUST NOT contain raw credentials.

#### Scenario: XHS and Dianping are separate services
- **WHEN** configuration declares `xhs-account` and `dianping-account`
- **THEN** the registry creates independent clients and never shares cookies,
  browser profiles, signer state, sessions, or leases between them.

#### Scenario: Duplicate or overlapping service identity
- **WHEN** two entries claim the same service ID or the same channel/version
  without an explicit priority and collision policy
- **THEN** configuration validation fails before application readiness.

### Requirement: Health refresh is explicit and bounded
The registry MUST refresh service descriptors and health with bounded timeouts,
low-cardinality status, and no provider invocation.  A failed refresh MUST
preserve the previous accepted descriptor only until its configured expiry;
after expiry the service is disabled.

#### Scenario: Expired descriptor disables a service
- **WHEN** refresh fails and the previously accepted descriptor passes its expiry
- **THEN** readiness reports the service as dependency-unavailable and routing
  rejects new calls.

### Requirement: Lifecycle is owned by the Composition Root
The Composition Root MUST create and close registry clients.  API handlers and
agents MUST depend on the registry/ports, not instantiate `httpx` clients or
provider-specific SDKs directly.

#### Scenario: Application shutdown closes clients
- **WHEN** the Composition Root shuts down
- **THEN** all HTTP/MCP clients are closed exactly once and no background task
  remains owned by the registry.

### Requirement: Remote service is opt-in
With no service configuration the legacy application startup MUST remain unchanged.
When a configured service is unavailable or fails validation, the registry
reports a redacted disabled/dependency-unavailable status and does not silently
fall back to a different platform service.

#### Scenario: Empty configuration preserves legacy startup
- **WHEN** no account-service configuration is present
- **THEN** the registry is disabled and the existing in-process/legacy startup
  path is selected unchanged.

### Requirement: Account state remains upstream-owned
The main application MUST persist only service ID, platform channel, opaque
account reference, flow reference, capability version, and audit metadata.
Provider cookies, browser profiles, QR bytes, signer state, and account
database rows remain in the upstream microservice.

#### Scenario: Main app stores only references
- **WHEN** a remote login succeeds
- **THEN** the main app records the service/account/flow references and
  capability version while the provider session remains in the upstream
  service.
