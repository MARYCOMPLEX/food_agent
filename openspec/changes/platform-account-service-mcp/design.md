## Context

The main application already has canonical source contracts, account-bound
invocation models, redaction policies, and feature-gated platform bindings.
This change adds a remote boundary around those contracts.  The upstream
microservice owns Playwright/Node/provider details and its own durable account
store.  The main app owns routing, authorization context, canonical evidence,
and durable research execution.

## Decisions

### 1. HTTP is the operational contract; MCP is capability discovery

HTTP resources provide predictable account/login/source operations and health
checks.  MCP is an additive tool surface used for `initialize`, `tools/list`,
and `tools/call`; it does not become a second state authority or workflow
runtime.  If MCP discovery is unavailable, explicitly configured HTTP calls can
continue.  The registry never imports an upstream Python package.

### 2. One service, one account-state owner

Deploy `xhs-account-service` and `dianping-account-service` independently.
Each service may use its own PostgreSQL schema/database, browser profiles,
signer process, QR ObjectStore, and provider SDK.  The main app receives only
opaque identifiers.  `xhs_pc`, `xhs_creator`, and `dianping` remain distinct
channels even when a service hosts more than one channel.

### 3. Explicit configuration and capability pinning

Use a JSON configuration variable or mounted file containing service ID, base
URL, protocol, descriptor version, channels, capabilities, and timeout.  The
registry accepts only configured capability prefixes and descriptor versions.
An upstream can publish a new read-only tool and the agent can discover it on
refresh; state-changing tools require an explicit capability and side-effect
approval.

### 4. Security boundary

Request models reject secret-shaped keys.  HTTP/MCP result text is redacted
before logs, events, SSE, Evidence, or agent context.  No remote URL is copied
into query identity.  Service authentication is represented by a deployment
provided header/token reference and is never included in OpenSpec fixtures.

### 5. Compatibility and migration

The current in-process platform connectors remain available.  The registry is
disabled by default and may be introduced per platform through a feature flag.
Once a remote service passes target-stack, dependency/license, and canary gates,
the Composition Root can route that channel to it without changing public
`CollectRequest`, Query Family, or Evidence contracts.

## Component flow

`Agent/Temporal activity -> AccountServiceRegistry -> HTTP/MCP client ->
upstream account service -> provider runtime`

`upstream account service -> its DB/ObjectStore/browser/signer`

`AccountServiceRegistry -> redacted capability/readiness -> Composition Root`

## Failure handling

- Connection and read timeouts map to `dependency-unavailable` within the
  configured budget.
- HTTP 401/403/409/429 and provider risk/auth errors retain stable source scope
  and never trigger an unbounded retry.
- MCP protocol/version/tool-schema drift disables only the affected service.
- Health expiry disables the service; no alternate service is selected silently.
- Client close is idempotent and owned by the Composition Root.

## Testing strategy

- Contract tests use `httpx.MockTransport` and an in-memory MCP JSON-RPC fixture.
- Registry tests cover duplicate service IDs, channel collisions, descriptor
  expiry, HTTP fallback, MCP tool allow-listing, redaction, and lifecycle.
- A local fixture service is deterministic and never creates credentials,
  browser profiles, SQLite authority, or external provider calls.
