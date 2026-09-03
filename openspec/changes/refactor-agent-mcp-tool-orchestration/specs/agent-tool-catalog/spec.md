## Purpose

Define a managed, policy-controlled catalog that converts remote MCP discovery
into stable and safe Agent-callable tool definitions without exposing routing or
account authority to the model.

## ADDED Requirements

### Requirement: Discovered tools are normalized into stable public definitions

The system SHALL normalize each approved remote MCP descriptor into a unique,
model-compatible public tool name, description, input schema, output schema,
capability version, platform binding, and hidden remote route. Public names MUST
remain collision-free across platform channels and MUST NOT expose service URLs
or authentication references.

#### Scenario: Same remote name on two platforms

- **WHEN** two configured account services both discover a tool with the same remote name
- **THEN** the catalog publishes two distinct platform-namespaced public tools and retains the correct hidden route for each

#### Scenario: Invalid discovered schema

- **WHEN** a discovered tool contains an invalid JSON Schema
- **THEN** the catalog excludes that tool and reports a redacted rejection reason without disabling unrelated tools

### Requirement: Tool exposure is explicitly policy controlled

The system SHALL require the catalog feature, platform, capability, and tool to
be allowed by application-owned policy before exposing a discovered tool. The
automatic policy MUST allow only read-only side effects; an absent or empty
allow-list MUST deny every remote tool.

#### Scenario: Read-only allow-listed capability

- **WHEN** a healthy service discovers a read-only tool whose platform and capability are explicitly allowed
- **THEN** the tool appears in the Agent-callable catalog

#### Scenario: Login or publish tool

- **WHEN** discovery returns an account-login, publish, delete, or otherwise state-changing tool
- **THEN** the automatic Agent catalog excludes it even if the remote service advertises it

#### Scenario: Tool not approved by application policy

- **WHEN** a discovered tool is not present in the application-owned allow-list
- **THEN** it is not exposed to the Agent and direct execution through the managed gateway is denied

### Requirement: Each Agent run uses an immutable catalog snapshot

The system SHALL create a versioned immutable snapshot for each managed Agent
run. A remote refresh MAY create a new snapshot for later runs but MUST NOT
change definitions or routes already pinned to an in-flight run.

#### Scenario: MCP schema changes during an Agent run

- **WHEN** an account service refresh publishes a changed schema while an Agent run is in progress
- **THEN** the in-flight run continues against its pinned snapshot and a subsequent run receives the new snapshot

#### Scenario: Service is expired or unavailable

- **WHEN** the service descriptor is expired or the service has no usable MCP catalog
- **THEN** no tools from that service are included in a newly created snapshot

### Requirement: Catalog state has a redacted management projection

The system SHALL provide a projection containing public tool name, service ID,
platform, capability, capability version, side effect, policy state, and snapshot
identity. The projection MUST NOT contain tenant/account references, service
authentication material, credentials, or raw provider responses.

#### Scenario: Operator inspects the current catalog

- **WHEN** the current catalog projection is requested
- **THEN** it reports the approved public definitions and snapshot identity without secret or account-scoped values
