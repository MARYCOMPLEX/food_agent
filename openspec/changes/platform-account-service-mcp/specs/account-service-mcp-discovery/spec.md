# Account Service MCP Discovery

## ADDED Requirements

### Requirement: MCP transport is an additive adapter
Each account service MAY expose an MCP endpoint at a configured URL.  The main
application MUST use the MCP protocol only through a project-owned client and
MUST keep the existing HTTP contract as the authoritative fallback boundary.
The client MUST support JSON-RPC `initialize`, `tools/list`, and `tools/call`
with a negotiated protocol version and optional `Mcp-Session-Id`.

#### Scenario: Discover tools
- **WHEN** the registry refreshes an MCP service
- **THEN** it stores only tool name, description, input schema, output schema,
  capability version, and declared side-effect class.

#### Scenario: MCP endpoint unavailable
- **WHEN** MCP is unavailable but HTTP is healthy
- **THEN** HTTP account/source calls remain usable and readiness marks only MCP
  discovery degraded.

### Requirement: Tool calls are allow-listed
The registry MUST allow calls only to tools declared by the accepted service
descriptor and configured capability allow-list.  Unknown tools, tools with an
unapproved side-effect class, and calls containing secret-bearing fields MUST
be rejected before transport.

#### Scenario: Upstream adds a tool
- **WHEN** a refreshed `tools/list` contains a new read-only tool within an
  approved capability namespace
- **THEN** the agent can see it after refresh without a main-app code release.

#### Scenario: Upstream adds an unsafe tool
- **WHEN** a tool declares publishing, upload, arbitrary shell, or credential
  export side effects
- **THEN** it is omitted from the registry and cannot be called.

### Requirement: MCP results stay canonical and redacted
MCP `tools/call` results MUST be normalized to canonical source envelopes or a
stable error envelope.  Text and structured content MUST be scanned for
cookies, authorization values, QR bytes, signer input, storage-state paths,
and decrypted session material before entering agent context, logs, or SSE.

#### Scenario: Credential-bearing result is blocked
- **WHEN** an MCP tool returns text containing a cookie, authorization value,
  QR payload, or storage-state path
- **THEN** the client returns a redacted protocol error and does not publish
  the content to the agent or event bus.
