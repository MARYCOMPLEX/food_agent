# Verification: Agent MCP Tool Orchestration

Date: 2026-09-02

## Acceptance Evidence

- Focused account-service, MCP catalog, managed search, Agent, API lifespan,
  composition, OpenAPI, dependency-ledger, and release-manifest suites:
  `56 passed in 26.82s`.
- Complete non-live suite with the six documented unrelated baseline cases
  excluded: `953 passed, 31 deselected, 2 warnings in 130.60s`.
- The same complete suite without exclusions had no additional cutover failure;
  its remaining failures are the six baseline cases listed below.
- Targeted Pyright over the changed Agent, MCP, account-service, API startup,
  and search modules: `0 errors, 0 warnings`.
- Ruff over the changed production and contract-test modules: `All checks passed`.
- Dependency scan found no production reference to the deleted Spider/auth,
  local provider/registry/DI, local account/login authority, account-auth queue,
  Node signer, `pycryptodome`, `qrcode`, or production Python `playwright`
  route. Playwright remains a dev-only frontend qualification tool.
- `uv lock --check`, the dependency ledger, `git diff --check`, and JSON fixture
  validation passed.
- `openspec validate refactor-agent-mcp-tool-orchestration --strict --json` is
  valid with zero issues.

The two warnings are existing `PytestReturnNotNoneWarning` results in
`tests/test_session.py`.

## Existing Unrelated Baseline Failures

- One architecture-baseline failure for the pre-existing
  `xhs_food.services.llm_service -> xhs_food.config.settings` import.
- Three documented-provider characterization cases and one constructor-model
  precedence case affected by the branch's local `.env` settings and existing
  extra LLM adapter parameters.
- One frontend characterization case expecting Vite port 3000, which is absent
  from the current branch source.

## Security Evidence

- Managed discovery is fail-closed unless
  `MODULAR_AGENT_MCP_TOOL_POLICY_JSON` explicitly enables platforms and an
  allow-list.
- Only `read_only` descriptors enter the Agent catalog.
- Tenant, account, session version, correlation, and secret-shaped arguments
  are rejected or removed from the model-visible schema and injected locally.
- In-flight calls prefer their approved pinned descriptor over refreshed MCP
  catalog state.
- The local `.env` and `.venv` are ignored by Git, and the configured API key is
  absent from tracked files.

## Rollback

1. Remove or disable `MODULAR_AGENT_MCP_TOOL_POLICY_JSON` and restart the API
   and worker processes.
2. New Agent runs receive no managed MCP tools and platform search fails closed;
   there is no local provider, Spider, account authority, or compatibility route.
3. In-flight runs may finish against retained snapshots; unavailable snapshots
   fail with `TOOL_SNAPSHOT_UNAVAILABLE` and never fall back to another account
   or service.
