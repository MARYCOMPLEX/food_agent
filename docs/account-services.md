# Account Service Deployment

> This document defines the upstream contract and deployment boundary between
> the main application and the independent XHS/Dianping account services. For
> browser-facing `/v1/platform/*`, search, SSE, identity, and error behavior,
> see the [backend API guide](backend-api.md). The two URL surfaces are not
> interchangeable.
> 
> 💡 **对外集成与开发接入指南（中文）**：如需接入新的外部爬虫或数据源，请参阅 [外部 MCP 服务接入规范与接口指南](mcp-service-integration-guide.md)。

The main application uses a provider-neutral account-service boundary. The
upstream service owns provider SDKs, Playwright/browser profiles, signer state,
QR bytes, credentials, leases, and its account database. The main application
stores only `service_id`, `platform`, `account_ref`, `flow_id`, capability
version, and audit metadata.

## Two independent services

Run the services independently so an XHS outage or upgrade cannot share state
with Dianping:

```text
xhs-account-service       channels: xhs_pc, xhs_creator   port: PORT_XHS
dianping-account-service  channels: dianping               port: PORT_DIANPING
```

Each service may use its own PostgreSQL database, object store bucket, browser
profile root, signer process, and provider dependency versions. The XHS service
should expose separate `xhs_pc` and `xhs_creator` account namespaces. Creator
publishing remains unavailable unless a future capability is explicitly
approved.

The upstream implementations can be FastAPI, Go, Node, or another HTTP server.
They must implement the versioned resources in the
[account-service HTTP contract](../openspec/changes/platform-account-service-mcp/specs/account-service-http-contract/spec.md):

```text
GET  /v1/capabilities
POST /v1/accounts
GET  /v1/accounts/{platform}/{account_ref}?tenant_ref=...
POST /v1/accounts/{platform}/{account_ref}/login
POST /v1/accounts/{platform}/{account_ref}/login/qr
GET  /v1/login/{flow_id}/status?tenant_ref=...
GET  /v1/login/{flow_id}/qr?tenant_ref=...
POST /v1/login/{flow_id}/poll
POST /v1/login/{flow_id}/cancel
POST /v1/source/invoke
POST /mcp                       # optional MCP JSON-RPC endpoint
```

All provider material stays behind the service. Requests and responses use
opaque references such as `credential_ref` and `object_ref`; raw cookies,
authorization values, QR payloads, storage-state paths, signer state, and
decrypted sessions are invalid at this boundary.

## Main-app configuration

Set `MODULAR_ACCOUNT_SERVICES_FILE` to a deployment-managed JSON file, or use
`MODULAR_ACCOUNT_SERVICES_JSON` for a small local setup. The example below
keeps the two providers isolated and enables MCP discovery for both:

```json
[
  {
    "service_id": "xhs-account",
    "base_url": "http://HOST:PORT_XHS",
    "mcp_url": "http://HOST:PORT_XHS/mcp",
    "protocol": "http+mcp",
    "channels": ["xhs_pc", "xhs_creator"],
    "capabilities": ["account.register", "account.read", "account.login", "notes.search", "notes.detail", "comments.search"],
    "descriptor_version": "account-service/v1",
    "timeout_seconds": 10
  },
  {
    "service_id": "dianping-account",
    "base_url": "http://HOST:PORT_DIANPING",
    "mcp_url": "http://HOST:PORT_DIANPING/mcp",
    "protocol": "http+mcp",
    "channels": ["dianping"],
    "capabilities": ["account.register", "account.read", "account.login", "places.search", "places.detail", "reviews.search"],
    "descriptor_version": "account-service/v1",
    "timeout_seconds": 10
  }
]
```

`auth_ref` is a deployment reference; never replace it with the token itself in
this file, the repository, query identity, Temporal history, Redis, or MCP
arguments. The gateway clients accept an injected `AuthHeaderProvider`, but the
default `AccountServiceRegistry` currently constructs them without one and does
not resolve `auth_ref`. A protected upstream therefore needs a deployment-owned
client factory/secret resolver that is not yet included in the stock
Composition Root. Without that extension, use only a trusted internal upstream
that does not require the missing header.

On startup the Composition Root creates one HTTP/MCP client pair per service,
refreshes `/v1/capabilities` and `tools/list`, and exposes redacted status at
`GET /v1/platform/readiness`. Descriptor expiry disables only the affected
service. MCP discovery may be degraded while healthy HTTP operations continue.

## Agent/MCP use

The raw account-service discovery and diagnostic boundary remains available at:

```text
GET  /v1/platform/account-services/{platform}/tools
POST /v1/platform/account-services/{platform}/tools/{tool_name}
```

This is not the model-visible catalog. Configure a second, application-owned
policy before any discovered tool can be exposed natively to the Agent:

```bash
MODULAR_AGENT_MCP_TOOL_POLICY_JSON='{"enabled":true,"allowed_platforms":["xhs_pc","dianping"],"allowed_capabilities":["notes.search","notes.detail","comments.search","places.search","places.detail","reviews.search"]}'
```

The final policy-filtered projection is available at:

```text
GET /v1/platform/agent-tools/catalog
```

The Agent catalog uses names such as `xhs_pc__notes_search`, publishes each
tool's own input schema to the model, and accepts only `read_only` tools. Login,
publish, upload, mutation, shell, and credential-export tools are never exposed
for automatic selection. Declared tenant/account/session fields are removed
from the model schema and injected from the owning request at execution time.
An empty or absent policy exposes no remote tools.

For Agent search, MCP is the sole execution route: discovery uses `tools/list`
and each selected read-only capability executes through `tools/call`. There is
no local XHS provider, registry, connector, or Spider fallback. HTTP account and
login resources remain the operational and durable authority.

## Local fixture

The deterministic fixture is intended for contract tests and local wiring only:

```python
from food_agent.account_services.fixture import create_fixture_app
from food_agent.contracts import PlatformChannel

app = create_fixture_app(
    service_id="xhs-fixture",
    channels=(PlatformChannel.XHS_PC, PlatformChannel.XHS_CREATOR),
)
```

It never calls an external platform, creates credentials, writes browser
profiles, or becomes a production account authority. Replace it with the
upstream XHS and Dianping services after their own target-stack and canary
evidence is approved.
