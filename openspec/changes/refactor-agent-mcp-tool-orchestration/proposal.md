## Why

The account-service boundary can already discover and call MCP tools, but the
Agent runtime still exposes one fixed meta-tool and the active food search path
depends directly on a legacy registry. This prevents the model from seeing the
approved tool schemas and forces orchestration code to change when remote MCP
services evolve.

## What Changes

- Add a managed Agent tool catalog that normalizes discovered MCP descriptors,
  assigns collision-free public names, applies explicit policy, and publishes
  immutable per-run snapshots.
- Map approved read-only account-service MCP tools to native Agent tool
  definitions while retaining service, channel, tenant, and account routing as
  hidden execution context.
- Replace the fixed `gateway_execute` model surface with per-run native tools so
  the model receives each tool's name, description, and JSON input schema.
- Route selected tools through one validating gateway to the configured account
  service and validate both inputs and outputs at the application boundary.
- Route food search through the same policy-controlled account-service MCP
  catalog/executor used by the Agent and remove the legacy `xhs_search`
  registry, providers, connector, and dependency-injection factories.
- Keep remote MCP discovery additive and fail closed: refreshes affect subsequent
  runs, never mutate an in-flight run, and state-changing tools are not
  automatically exposed.

## Capabilities

### New Capabilities

- `agent-tool-catalog`: Managed discovery, normalization, namespacing, policy
  filtering, snapshotting, and administrative projection of Agent-callable tools.
- `agent-tool-orchestration`: Native per-run Agent tool exposure, validated
  execution routing, hidden context injection, and a single managed MCP search
  route with no local-provider fallback.

### Modified Capabilities

None. The existing account-service MCP transport and platform source contracts
remain unchanged.

## Impact

- Affected code: Agent/tool contracts, account-service composition adapters,
  tool gateways, PydanticAI runtime, food search execution, Composition Root,
  control-plane tool projections, and focused tests.
- Public query and evidence result contracts remain unchanged. Search now fails
  closed when managed MCP policy, discovery, or request account context is
  unavailable; no local Spider/provider fallback remains.
- No new runtime dependency or durable state authority is introduced. Initial
  policy is configuration owned; a later administrative persistence change can
  implement the same catalog policy port.
- Account credentials, service authentication, tenant references, and account
  references remain outside model-visible tool schemas and outputs.
