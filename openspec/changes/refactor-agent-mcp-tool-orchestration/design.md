## Context

See `proposal.md` for motivation. The account-service registry already owns MCP
initialization, `tools/list`, descriptor expiry, allow-listed `tools/call`, and
redaction. The PydanticAI adapter validates declared Agent tool schemas but
currently exposes only `gateway_execute(tool_name, arguments)`. The active food
search executor reaches into the legacy `MCPToolRegistry` and resolves
`xhs_search` itself.

The project-owned Agent runtime and Tool Gateway remain the sole execution
authorities. Remote MCP servers advertise capabilities; they do not grant
permission, choose tenants/accounts, or become a workflow runtime.

## Goals / Non-Goals

**Goals:**

- Create a framework-neutral catalog and policy boundary between MCP discovery
  and Agent model exposure.
- Pin definitions and routes for one run, with deterministic public identities
  and local input/output validation.
- Preserve opaque tenant/account routing outside model-visible schemas.
- Make both the PydanticAI runtime and deterministic food search consume the
  same managed catalog/executor rather than a provider-specific registry.
- Remove the legacy XHS MCP-like protocol, local providers, compatibility
  source connector, and their DI/Composition Root bindings.
- Preserve disabled-by-default rollout and existing behavior when no policy is
  configured.

**Non-Goals:**

- Enabling login, publish, delete, upload, or other state-changing tools for
  autonomous Agent use.
- Creating a second Agent runtime, MCP SDK dependency, workflow engine, or
  durable policy database.
- Changing public Query Family/Evidence identity.
- Implementing model/provider governance; that remains a separate control-plane
  change.

## Decisions

### 1. Introduce project-owned catalog contracts and two narrow ports

An immutable catalog snapshot contains public `AgentToolDefinition` values and
an opaque snapshot reference. A catalog port creates snapshots from request
context; a contextual execution port resolves a selected public name against
the pinned snapshot. The account-service adapter implements these ports over the
existing registry while keeping remote routes in private snapshot state.

This separates discovery/policy from PydanticAI and from food-domain code.
Passing raw `McpToolDescriptor` objects directly into the Agent was rejected
because it would make the remote server the policy authority and leak routing
concerns into the runtime.

### 2. Use platform-namespaced, model-compatible public names

Public names use `<platform>__<normalized_remote_name>`, with unsupported
characters converted to underscores and collisions rejected. For example,
`notes.search` on XHS PC becomes `xhs_pc__notes_search`. The snapshot privately
retains service ID, platform, remote name, capability, version, schema digests,
and side effect.

Service-ID-only names were rejected because one XHS service may own both PC and
Creator channels. Dot-separated names were rejected because common model tool
protocols restrict function names to letters, numbers, underscores, and hyphens.

### 3. Apply two independent allow-lists and a hard read-only ceiling

Remote service configuration continues filtering advertised capabilities at
the MCP client. The new application policy then independently requires an
enabled feature, an allowed platform, and an allowed capability/public name.
Empty policy lists deny all tools. Automatic exposure has a hard ceiling of
`read_only`; account-login and mutating tools cannot be enabled by this policy.

The initial policy is loaded from validated target configuration and exposed as
a redacted projection. The port permits a later durable admin policy provider
without changing the catalog or Agent runtime. Treating all discovered tools as
trusted was rejected because discovery is provider-controlled input.

### 4. Strip and inject system-owned arguments

The catalog removes declared `tenant_ref`, `account_ref`,
`expected_session_version`, and `correlation_id` properties from the
model-visible schema, including its `required` list. At execution it rejects any
model argument using a hidden or secret-shaped key, then injects only hidden
fields declared by the pinned remote schema. Missing required context fails
before transport.

The owning request carries opaque execution context separately from prompts and
tool definitions. Raw credentials, cookies, service auth, browser state, and
provider responses are never valid context fields.

### 5. Build native tools from the pinned definitions for each run

The PydanticAI adapter builds one `Tool.from_schema` definition per effective
tool and passes a per-run `FunctionToolset` to `Agent.run`. Each closure delegates
to the same budgeted validation path, which selects either the existing static
Tool Gateway or the managed contextual executor. The fixed `gateway_execute`
model surface is removed.

Local request tools remain supported and are merged with managed tools only
when names are unique. Embedding the full catalog in instructions while keeping
the meta-tool was rejected because it weakens provider-side schema enforcement
and adds avoidable prompt tokens.

### 6. Keep snapshots immutable and bounded

The account-service catalog atomically replaces its current snapshot after a
successful build and retains a bounded set of older snapshots for in-flight
runs. A digest over sorted public definitions and private route versions forms
the snapshot identity; unchanged discovery reuses the identity. New runs only
use healthy, unexpired registry state. Execution requires the exact retained
snapshot reference and never resolves against "latest".

Unbounded history was rejected because refresh is periodic. A small bounded
retention window plus active-run references is sufficient for the in-process
runtime; durable cross-process snapshot storage belongs to the future Temporal
activation change.

### 7. Cut food search over to the managed MCP catalog

`SearchExecutor` receives one project-owned search port implemented by a
managed adapter over `AgentToolCatalogPort` and `ContextualToolExecutorPort`.
The adapter selects an approved `notes.search` capability from the pinned
snapshot and uses the same context injection, policy, route, and output
validation as native Agent calls.

The local `MCPToolRegistry`, `XHSSearchProvider`, `XHSNoteProvider`,
`XHSBatchProvider`, `XHSSourceConnector`, and their DI/Composition Root bindings
are removed. Missing managed policy, discovery, tenant/account context, or an
unambiguous search capability is an explicit dependency/policy failure. There
is no local Spider fallback and no implicit global account.

## Risks / Trade-offs

- [Remote schemas are incomplete or overly permissive] -> Validate schema
  syntax locally, strip hidden fields deterministically, exclude invalid tools,
  and use a JSON-value fallback output schema only when MCP omits one.
- [A refresh removes a snapshot still in use] -> Retain bounded prior snapshots
  and release active references after the run; fail explicitly if the exact
  snapshot is unavailable.
- [Dynamic names collide after normalization] -> Reject both colliding entries
  for that snapshot and report redacted diagnostics.
- [PydanticAI changes its dynamic-tool API] -> Keep all framework usage inside
  the Agent adapter and preserve catalog/runtime contract tests.
- [Managed MCP search is unavailable] -> Fail closed with a stable dependency
  error and require operators to restore the account service or policy; do not
  route to the removed local provider.

## Migration Plan

1. Add contracts, policy parsing, catalog snapshot tests, and the account-service
   adapter while the feature remains disabled.
2. Change the Agent adapter to native per-run tools and pass all existing Agent
   contract tests with scripted models.
3. Bind food search to a managed MCP search adapter and delete the legacy
   registry/provider/connector dependency graph.
4. Bind the managed catalog in the Composition Root only when an account-service
   registry and explicit non-empty policy are configured. Expose its redacted
   projection for inspection.
5. Roll back application code as one release if the direct cutover is rejected.
   Disabling managed policy is not a traffic fallback: subsequent search calls
   fail closed, while in-flight runs either finish against retained snapshots or
   fail with the stable unavailable error.
