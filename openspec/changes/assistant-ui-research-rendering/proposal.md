## Why

The current research session page renders legacy `steps`, `restaurants`, and `summary` fields, so comment evidence, controversy reasoning, shop enrichment, and partial failures cannot arrive as first-class incremental UI state. The application needs a maintainable conversation/rendering base that can evolve with the Agent while keeping the domain event contract independent from any UI library.

## What Changes

- Add a typed frontend domain store and transport adapter for `ResearchEvent v1` and `UserResearchProjection v1`.
- Use assistant-ui as a React rendering island backed by an external store, while keeping Vue as the application shell and router.
- Add a renderer registry with safe fallbacks for evidence, controversy, shop profile, research gap, plan progress, and ordinary text.
- Replace the research-session page's direct legacy SSE state consumption with the projection-backed conversation surface.
- Add responsive, accessible layouts for dense research evidence on desktop and mobile.
- Preserve the existing backend transport as a compatibility input until the new public event stream is available; do not make assistant-ui types a backend contract.

## Capabilities

### New Capabilities

- `assistant-ui-research-rendering`: A projection-driven, extensible conversation surface for Agent research evidence and state.

### Modified Capabilities

None.

## Impact

- Frontend dependencies: assistant-ui React runtime and React/Vite support may be added alongside the existing Vue stack.
- Frontend code: research-session domain adapter, React island, renderer registry, and Vue integration boundary.
- Backend APIs remain unchanged in this phase; the adapter accepts the versioned public projection and can switch transport implementations later.
- Browser behavior changes only on the research session route; operations, account, favorites, and history views remain Vue-native.
