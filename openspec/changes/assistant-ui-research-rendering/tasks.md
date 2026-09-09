## 1. Domain adapter

- [x] 1.1 Implement the projection store and pure event reducer over `ResearchEvent v1`.
- [x] 1.2 Implement snapshot bootstrap, SSE transport, reconnect cursor, gap detection, and action boundary.
- [x] 1.3 Add adapter tests for duplicate, gap, partial, terminal, and compatibility events.

## 2. Assistant-ui island

- [x] 2.1 Add compatible React/assistant-ui dependencies and Vite integration without changing Vue routes.
- [x] 2.2 Implement an ExternalStoreRuntime bridge and typed assistant message projection.
- [x] 2.3 Implement the allow-listed renderer registry and unknown/invalid block fallback.

## 3. Research interaction surface

- [x] 3.1 Implement evidence, controversy, profile, gap, plan, and terminal-state renderers.
- [x] 3.2 Mount the island from the Vue research-session route and preserve existing follow-up actions.
- [x] 3.3 Add responsive loading, empty, partial, error, and reconnect states.

## 4. Verification

- [x] 4.1 Run focused frontend tests, typecheck, and production build.
- [x] 4.2 Validate desktop and mobile behavior with Playwright screenshots and console checks.
- [x] 4.3 Review accessibility, renderer allow-listing, and scope before commit.
