## Context

FastAPI's route registry is the executable source of truth, while
`tests/fixtures/http/openapi.json` protects its generated schema. The existing
`contracts/openapi.yaml` was generated earlier and is missing newer request
fields and the Agent tool catalog route. Human documentation independently
drifted and still contains broken `internal-docs/*` links.

Three event contracts must remain visibly separate:

1. The default legacy SSE stream selected by an omitted or `legacy`
   `sseVersion`.
2. The reliable task SSE v1 stream selected explicitly with
   `sseVersion=v1` and available only when its durable runtime is enabled.
3. `ResearchEvent v1` / `UserResearchProjection v1`, which are frozen public
   experience models but are not wired to a backend transport yet.

## Goals / Non-Goals

**Goals:**

- Give frontend, backend, and operations readers one accurate entry point.
- Make every registered route discoverable and explain dynamic response shapes
  that the generated OpenAPI cannot express precisely today.
- Keep YAML and JSON OpenAPI artifacts deterministic and checked against
  `app.openapi()`.
- Record current limitations plainly instead of presenting planned contracts as
  deployed behavior.

**Non-Goals:**

- No endpoint additions, removals, aliases, or payload migrations.
- No activation of the reliable runtime or Research Experience projector.
- No replacement of the current identity mechanism with real authentication.
- No runtime correction of deployment or frontend contract gaps; discovered
  integration gaps are documented as current limitations.

## Decisions

### FastAPI is the route and schema authority

`scripts/export_openapi.py` imports `api.main:app`, serializes
`app.openapi()` to deterministic YAML and JSON, and supports a read-only
`--check` mode. Hand-edited OpenAPI fields are not authoritative.

### One human guide, small local indexes

`docs/backend-api.md` owns request flows, examples, caveats, and the complete
route inventory. The root README keeps only a short entry point and
`src/api/README.md` explains module ownership. This avoids maintaining three
copies of endpoint details.

### Document current wire behavior, not desired behavior

The guide labels default/optional feature states and names the exact source or
fixture behind each claim. Planned `ResearchEvent v1` transport work is linked
as a contract, not shown as an available endpoint. Dynamic response bodies are
documented with characterized examples instead of invented strict schemas.

### OpenAPI SSE metadata is documentation-only

The search stream decorator declares `EventSourceResponse` and a
`text/event-stream` response with legacy and reliable examples. The handler
already returns `EventSourceResponse`, so this changes generated documentation
without changing runtime serialization.

## Verification

- Strict OpenSpec validation.
- Deterministic OpenAPI export followed by `--check`.
- A documentation test proving both generated artifacts equal `app.openapi()`
  and every runtime path appears in the canonical guide.
- Existing HTTP/SSE characterization and reliable-stream tests.
- Link and stale-reference scans plus `git diff --check`.
