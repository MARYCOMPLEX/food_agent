## Why

The current platform connector work owns provider adapters inside the main
application and leaves real account login behind deployment-specific seams.
That makes account lifecycle, browser state, signer state, and provider
upgrades harder to operate independently.  A microservice-first boundary lets
each upstream project own its account/session implementation while the main
application remains stable and discovers the latest approved capabilities.

## What Changes

- Define a versioned, provider-neutral HTTP contract for account registration,
  QR/credential login, flow status, QR presentation, cancellation, health, and
  source invocation.
- Define an MCP tool-discovery/call contract over the same service boundary so
  the main application can refresh approved upstream capabilities without
  importing provider packages or starting provider workers in-process.
- Add a configuration-driven account-service registry in the main application;
  each service is identified by a stable service ID, base URL, protocol, and
  allowed channels/capabilities.
- Add HTTP and MCP client adapters with timeouts, redacted errors, capability
  version pinning, and fail-closed behavior when a service is missing or drifts.
- Preserve the existing in-process platform bindings as a compatibility path;
  remote services are opt-in and selected explicitly by configuration.
- Add a local deterministic fixture service and contract tests that exercise
  XHS PC, XHS Creator, and Dianping account namespaces without credentials.

## Capabilities

### New Capabilities

- `account-service-http-contract`: stable account/login/source HTTP resources,
  envelopes, health, and redaction rules.
- `account-service-mcp-discovery`: MCP initialize, tools/list, tools/call,
  capability versioning, and tool safety policy.
- `account-service-registry`: configuration, lifecycle, routing, health
  refresh, and explicit service/channel isolation in the main application.

### Modified Capabilities

None. Existing in-process connector contracts remain available and are not
silently replaced.

## Impact

- Affected code: `contracts`, `gateways`, `composition`, `foundation/config`,
  API readiness wiring, and new local service fixtures/tests.
- Runtime dependencies: existing `httpx` is used for HTTP and MCP transport;
  no provider SDK or second durable workflow runtime is added to the main app.
- Deployment: each provider can run as its own FastAPI/ASGI service or another
  HTTP server implementing the contract; account databases, browser profiles,
  QR bytes, and signer state stay inside that service.
- Security: the main app stores only opaque service/account/flow references;
  credentials and provider response bodies are rejected from envelopes and
  redacted from logs, events, and MCP results.
