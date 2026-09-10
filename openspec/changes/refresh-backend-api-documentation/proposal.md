## Why

The repository currently splits backend API information across the root README,
`src/api/README.md`, account-service notes, a static OpenAPI YAML file, and test
fixtures. The human documentation omits active platform endpoints, links to
files that do not exist, describes identity headers as authentication, and does
not distinguish the default legacy SSE stream, opt-in reliable SSE v1, and the
unpublished `ResearchEvent v1` experience contract. The checked-in OpenAPI YAML
also trails the runtime schema.

## What Changes

- Establish `docs/backend-api.md` as the canonical human-readable guide for the
  public FastAPI surface.
- Document every registered route, request identity precedence, response and
  error conventions, search command modes, both SSE encodings, replay behavior,
  account-service control-plane APIs, and known runtime limitations.
- Replace stale API module documentation and broken links with pointers to
  version-controlled authorities.
- Generate both checked-in OpenAPI artifacts from `app.openapi()` and add a
  drift gate that also checks the endpoint inventory in the human guide.
- Correct the OpenAPI media type and examples for the SSE route without changing
  runtime request handling or business behavior.
- State explicitly that `ResearchEvent v1` and `UserResearchProjection v1` are
  frozen contracts but are not currently published by an HTTP or SSE endpoint.

## Capabilities

### New Capabilities

- `backend-api-documentation`: Accurate, generated, reviewable documentation for
  the current backend HTTP and SSE surface.

### Modified Capabilities

None.

## Impact

- Documentation: root API index, API/services module READMEs, account-service
  cross-links, corrected environment examples, and a detailed backend API guide.
- Tooling: deterministic OpenAPI export and drift tests.
- API implementation: documentation metadata only; no route, payload, storage,
  Agent, MCP, or authorization behavior changes.
