## Context

The repository has a Vue 3 application shell and an existing SSE client that
translates task events into legacy `steps`, `restaurants`, and `summary`
state. The previous contract freeze added browser-safe TypeScript schemas for
`ResearchEvent v1` and `UserResearchProjection v1`, plus a transport-neutral
Python reducer, but no frontend runtime is consuming those contracts yet.

The requested assistant-ui approach is React-based. A full Vue-to-React
migration would widen the change unnecessarily, so the research session will
host a small React island. The island receives domain state through an
external-store runtime; Vue remains responsible for routing, authentication,
and the rest of the application.

## Goals / Non-Goals

**Goals:**

- Make the versioned research projection the single UI state source.
- Render comment evidence, controversy sides, shop profiles, gaps, plan
  progress, and terminal states as incremental, inspectable UI blocks.
- Keep event transport and domain state independent from assistant-ui.
- Provide deterministic replay, idempotency, and unknown-renderer fallbacks.
- Verify the actual research route in a browser at desktop and mobile sizes.

**Non-Goals:**

- No backend Agent planning or MCP behavior changes.
- No replacement of the existing Vue application shell.
- No exposure of raw provider payloads, private account fields, prompts, or
  hidden reasoning to the browser.
- No hard dependency on AG-UI in this phase.

## Decisions

### React island instead of full migration

Use Vite's built-in TSX transform and mount one assistant-ui React root inside
a Vue component. This keeps the existing Vue routes stable while allowing the
research surface to use assistant-ui primitives without adding a second Vite
plugin to the existing Vue build. Alternatives considered:

- Full migration to React: rejected because it expands the blast radius to
  every route and existing Vue component.
- A Vue-only imitation of assistant-ui: rejected because it would not provide
  the requested runtime and primitive ecosystem.

### Domain store before UI runtime

The store owns `UserResearchProjection v1`, ordered event application,
snapshot bootstrap, reconnect cursors, and transport errors. The assistant-ui
runtime receives a projected message list and UI blocks from that store. This
keeps assistant-ui's `ThreadMessageLike` as a presentation type only.

### Renderer registry with explicit schemas

Each public block has a stable renderer key and schema. The registry maps keys
to local React components; unknown or invalid blocks render a bounded fallback
instead of dynamically importing or executing server-provided code.

Initial renderers are:

- `research.summary@1`
- `research.plan@1`
- `research.evidence@1`
- `research.controversy@1`
- `research.profile@1`
- `research.recommendation@1`
- `research.gap@1`
- `research.coverage@1`

### Vue/React boundary

The Vue wrapper passes a serializable projection, session identity, and action
callbacks into the React island. The island emits user actions through those
callbacks; it does not reach into Pinia or Vue internals. A later transport
change only replaces the adapter/store input.

### Compatibility input

Until the backend emits public `ResearchEvent v1`, the adapter may normalize
the existing stable SSE events into a clearly marked compatibility projection.
The compatibility path must not masquerade as complete evidence: missing
evidence, controversy, or profile data remains visibly partial.

## Risks / Trade-offs

- [Risk] Two UI frameworks increase bundle and maintenance cost.
  -> Limit React to the research island and keep shared domain/store code
  framework-neutral.
- [Risk] Existing legacy SSE data is less rich than the new projection.
  -> Render explicit partial/gap states and keep the new schemas strict.
- [Risk] React dependency/plugin drift can break the Vue build.
  -> Pin compatible versions, run frontend typecheck/build, and verify the
  route in Playwright.
- [Risk] Dense evidence can overwhelm mobile users.
  -> Use progressive disclosure, stable sections, and a compact mobile order;
  preserve full evidence in expandable panels rather than truncating it.

## Migration Plan

1. Add the domain store/transport adapter and renderer components.
2. Add the React island and mount it behind a Vue research-session wrapper.
3. Keep the existing route entry and backend endpoints; switch only the
   research-session rendering source.
4. Verify projection replay, partial/error states, and responsive browser
   rendering.
5. Remove the legacy session-page state wiring only after the new surface is
   proven against the public projection contract.

Rollback is a route-level revert to the existing Vue session page; no backend
or database rollback is required.

## Open Questions

None for this implementation slice. The exact backend endpoint that emits
public events remains behind the transport interface.
