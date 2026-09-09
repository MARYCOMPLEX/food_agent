## 1. Contract Authority

- [x] 1.1 Add the versioned, browser-safe `ResearchEvent v1` and `UserResearchProjection v1` Pydantic contracts without changing the internal runtime `ResearchEvent`.
- [x] 1.2 Define stable entity references, mutation semantics, bounded evidence/provenance, typed gaps, terminal state, and namespaced extensions.
- [x] 1.3 Add an allow-list sanitizer that rejects secrets, prompts, raw provider payloads, raw MCP arguments, and unbounded public values.

## 2. Deterministic Projection

- [x] 2.1 Implement an ordered, idempotent projection reducer with duplicate-event no-op, sequence-gap resync, identity validation, and terminal immutability.
- [x] 2.2 Preserve comment evidence and controversies independently from profiles and recommendations, including partial profile/source failures.
- [x] 2.3 Add snapshot and replay-control semantics without coupling the contract to SSE.

## 3. Client Contract

- [x] 3.1 Add framework-neutral TypeScript/Zod mirrors for the event envelope, projection snapshot, and core public entity views.
- [x] 3.2 Keep the current Vue components and routes unchanged; export the new contract for a later UI migration.

## 4. Verification

- [x] 4.1 Add Python contract tests for JSON round trips, bounds, forbidden fields, event ordering, duplicate delivery, patch/upsert behavior, partial failures, and terminal runs.
- [x] 4.2 Add representative fixtures for comment evidence, controversy, shop enrichment, and Dianping verification gaps.
- [x] 4.3 Run focused Python tests, lint/type checks for the new modules, OpenSpec validation, and frontend type checking.

### Verification notes

- Focused contract/reducer/architecture checks pass.
- The repository-wide suite remains blocked by pre-existing missing fixtures
  under `openspec/changes/enable-evidence-reuse-memory-phoenix/`; the new
  contract does not add or modify those fixtures.
