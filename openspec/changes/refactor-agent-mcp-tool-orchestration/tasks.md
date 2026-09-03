## 1. Catalog Contracts And Policy

- [x] 1.1 Add immutable Agent tool context, catalog snapshot, projection, and catalog/executor port contracts with validation and export coverage.
- [x] 1.2 Add fail-closed target configuration and policy parsing for enabled platforms, capabilities, and public tool names.
- [x] 1.3 Add contract tests for empty-policy denial, read-only enforcement, namespacing, schema rejection, and redacted projections.

## 2. Account-Service MCP Catalog Adapter

- [x] 2.1 Implement descriptor normalization, hidden-field stripping, stable public names, schema digests, collision handling, and bounded immutable snapshot retention.
- [x] 2.2 Implement pinned-route execution with hidden context injection, local input/output validation, MCP result normalization, and stable error mapping.
- [x] 2.3 Add adapter tests for two-service discovery, refresh isolation, context override denial, missing context, malformed output, and unavailable snapshots.

## 3. Native Agent Tool Runtime

- [x] 3.1 Replace the fixed gateway meta-tool with per-run native tools generated from effective local and managed definitions.
- [x] 3.2 Route managed tools through their pinned contextual executor while preserving existing budgets, local Tool Gateway behavior, result recording, and disabled runtime behavior.
- [x] 3.3 Update Agent runtime tests to prove model-visible schemas, name selection, duplicate rejection, budget enforcement, and no undeclared gateway access.

## 4. Search And Composition Migration

- [x] 4.1 Refactor `SearchExecutor` to receive a search-tool port and bind it directly to managed MCP search composition.
- [x] 4.2 Bind the managed catalog and contextual executor only when the account-service registry and explicit policy are configured; retain disabled-by-default behavior.
- [x] 4.3 Expose a redacted catalog projection and update configuration/deployment examples without credentials.
- [x] 4.4 Run search characterization tests to confirm the four-stage strategy and public output remain unchanged.

## 5. Verification And Rollback

- [x] 5.1 Run focused contract, account-service, Agent runtime, API, and search suites plus targeted static checks.
- [x] 5.2 Run the complete non-live unit/integration suite or record any pre-existing unrelated failure with a narrower passing gate.
- [x] 5.3 Run `openspec validate refactor-agent-mcp-tool-orchestration --strict` and record exact verification and rollback evidence.

## 6. Direct Managed-Search Cutover

- [x] 6.1 Add the managed MCP search adapter and request-scoped tool-context binding over the existing catalog/executor contracts.
- [x] 6.2 Remove the legacy MCP protocol, XHS providers, compatibility connector, DI factories, local account/login authority, Spider/auth implementation, and all production Composition Root registrations/references.
- [x] 6.3 Rewire food search and food tool composition to fail closed on the managed route, then remove obsolete compatibility tests and fixtures.
- [x] 6.4 Run dependency scans, focused search/Agent/API suites, the non-live gate, and strict OpenSpec validation; replace the superseded rollback evidence.
