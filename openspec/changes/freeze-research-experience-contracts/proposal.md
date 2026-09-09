## Why

The Agent already produces a rich adaptive investigation state, but the active
HTTP/SSE boundary reduces it to legacy steps, a final summary, and restaurant
cards. Evidence, comment-level disagreement, profile enrichment, and partial
source failures are either lost at the transport boundary or remain inaccessible
to the current client. This change freezes one public, replayable experience
contract before any UI redesign so every client can consume the same incremental
research facts without exposing runtime internals or raw provider payloads.

## What Changes

- Freeze the public `ResearchEvent v1` envelope and its event-kind registry for
  run lifecycle, human-readable planning, action progress, comment evidence,
  controversy updates, shop-profile updates, recommendation updates, gaps, and
  terminal outcomes.
- Freeze the `UserResearchProjection v1` snapshot that can be rebuilt from the
  event stream and used for reconnect, refresh, and non-streaming recovery.
- Define identity, ordering, idempotency, mutation, partial-completion,
  replay-expiry, and terminal-state semantics independently of SSE or a
  particular frontend framework.
- Add a public-safe projection boundary that permits bounded evidence excerpts
  and provenance while rejecting prompts, credentials, cookies, raw provider
  payloads, and unbounded source responses.
- Add generic entity/profile/recommendation views plus namespaced extensions so
  Food can expose comment controversies today and later domains can add fields
  without changing the core event envelope.
- Add Python validation/reduction models, TypeScript mirror types, authority
  fixtures, and contract tests. Existing runtime `ResearchEvent` and legacy
  HTTP/SSE consumers remain unchanged until a follow-up transport migration.

## Capabilities

### New Capabilities

- `research-experience-contracts`: Versioned user-facing event and projection
  contracts, safe payload rules, incremental reduction, replay, and extension
  semantics.

### Modified Capabilities

None. Existing runtime and HTTP/SSE behavior is preserved in this freeze; a
separate change will wire the new projection into the active stream.

## Impact

- Adds framework-neutral Python contracts under `src/xhs_food/contracts` and a
  projection reducer under `src/xhs_food/experience`.
- Adds shared frontend TypeScript types and runtime parsing helpers without
  changing Vue components or the current route in this change.
- Adds OpenSpec authority documentation, JSON examples, and unit contract gates.
- No database migration, provider dependency, MCP protocol change, or breaking
  REST/SSE route change is introduced by the freeze.
