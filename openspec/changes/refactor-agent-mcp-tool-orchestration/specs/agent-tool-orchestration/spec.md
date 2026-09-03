## Purpose

Define how each Agent run receives native dynamic tools and executes selected
tools through validated, tenant-bound routes, with managed MCP as the sole
platform-search implementation behind a framework-neutral port.

## ADDED Requirements

### Requirement: Agent receives native per-tool definitions

For each run, the system SHALL expose every approved tool as an individual
native model tool using its public name, description, and JSON input schema. The
model-visible surface MUST NOT require a generic tool-name argument or expose
hidden routing and account context.

#### Scenario: Agent starts with two approved tools

- **WHEN** the pinned snapshot contains two approved tools
- **THEN** the model receives two native tool definitions and can select either from its declared schema

#### Scenario: No tools are approved

- **WHEN** no local or managed tools are approved for the request
- **THEN** the model receives no callable tools and cannot reach the managed gateway by inventing a name

### Requirement: Managed calls are validated and context bound

The system SHALL validate tool input against the pinned public schema before
dispatch, resolve the hidden route from the same snapshot, inject only declared
tenant/account/session context from the owning request, call the configured MCP
service, normalize the result, and validate it against the pinned output schema.
Model-supplied values MUST NOT override hidden context.

#### Scenario: Valid read-only call

- **WHEN** the model supplies arguments valid for an approved tool and the request contains its required account context
- **THEN** the gateway invokes the pinned remote tool with system-owned context and returns a schema-valid normalized result

#### Scenario: Missing required account context

- **WHEN** a remote tool requires an account reference that the owning request does not provide
- **THEN** execution fails with a stable policy or validation error before the remote call

#### Scenario: Model attempts to supply hidden context

- **WHEN** model arguments contain a tenant reference, account reference, session version, credential, cookie, or token field
- **THEN** the gateway rejects the call before transport and does not echo the supplied value

#### Scenario: Remote output violates the descriptor schema

- **WHEN** a remote MCP result cannot be normalized to a value accepted by the pinned output schema
- **THEN** execution returns a stable malformed-response tool failure and the invalid value is not returned to the model

### Requirement: Budgets and failures remain stable across dynamic tools

Dynamic tool calls SHALL use the existing per-run call, cost, timeout, and
deadline budgets. An unavailable, denied, or malformed managed tool MUST fail
within its own boundary and MUST NOT silently fall back to another service or a
legacy provider.

#### Scenario: Tool call budget is exhausted

- **WHEN** a dynamic call would exceed the request's tool-call or cost budget
- **THEN** the runtime rejects it without invoking an MCP service

#### Scenario: Selected MCP service is unavailable

- **WHEN** the pinned route cannot be called because its service is unavailable
- **THEN** the tool result carries a stable dependency failure and no alternate platform or account is selected

### Requirement: Food search has one managed MCP tool route

The food search executor SHALL invoke search through an adapter over the same
managed catalog snapshot and contextual executor used by native Agent tools.
The legacy MCP-like registry, local XHS providers, compatibility connector, and
Spider-backed search fallback MUST NOT remain in the production dependency
graph.

#### Scenario: Managed MCP search is unavailable

- **WHEN** managed MCP policy, discovery, or request execution context is unavailable
- **THEN** food search fails with a stable dependency or policy error and does not call a local XHS provider

#### Scenario: Managed provider is supplied

- **WHEN** composition supplies an approved managed search-tool implementation
- **THEN** the search executor uses its pinned `notes.search` route without changing the four-stage search strategy

#### Scenario: Removed legacy dependency is referenced

- **WHEN** production source or Composition Root code is scanned for `MCPToolRegistry`, `xhs_search`, or `xhs_compat`
- **THEN** no executable legacy search registration or fallback remains
