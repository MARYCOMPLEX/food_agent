## 1. Contracts and protocol

- [x] 1.1 Add versioned Pydantic contracts for service descriptors, health,
  account/login projections, source invocation envelopes, MCP tool descriptors,
  JSON-RPC messages, and stable remote error categories.
- [x] 1.2 Add central redaction/validation for remote request and response
  fields; reject credential, QR, signer, browser-path, and decrypted-session
  material at the HTTP and MCP boundaries.

## 2. Main-app adapters

- [x] 2.1 Implement an async HTTP account-service client using `httpx` with
  bounded timeouts, idempotency headers, descriptor refresh, account/login
  resources, source invocation, and redacted error mapping.
- [x] 2.2 Implement a lightweight MCP JSON-RPC client for initialize,
  tools/list, and tools/call with protocol negotiation, session headers,
  allow-listed tools, and response sanitization.
- [x] 2.3 Add the configuration-driven `AccountServiceRegistry`, lifecycle
  close, health/readiness projection, channel isolation, capability pinning,
  and explicit HTTP/MCP fallback policy.
- [x] 2.4 Wire the registry through `TargetSettings` and the Composition Root
  without changing the default legacy startup or public query contracts.

## 3. Fixtures and integration surface

- [x] 3.1 Add a deterministic local account-service fixture implementing the
  HTTP resources and MCP discovery/call surface for XHS PC, XHS Creator, and
  Dianping channels.
- [x] 3.2 Add deployment examples and documentation for two independent
  services, service authentication references, account state ownership, and
  capability refresh.
- [x] 3.3 Add API/agent integration hooks that resolve a remote service by
  channel and pass only opaque account/session/flow references.

## 4. Verification

- [x] 4.1 Add unit/contract tests for HTTP envelopes, MCP negotiation/tool
  filtering, timeout/error mapping, redaction, descriptor expiry, and registry
  lifecycle.
- [x] 4.2 Run the complete non-live suite, OpenSpec strict validation, and
  architecture/import scans; record exact results and lockfile digest.
- [x] 4.3 Add target-stack smoke and owner-approved canary tasks to the rollout
  evidence without marking local fixtures as production approval.
