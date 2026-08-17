# Session Log

## 2026-08-17

### Session Goal

Analyze `MARYCOMPLEX/food_agent` in detail.

### What Was Done

- Cloned commit `fa19e984287a9ca376b497e2fcc05c650e210c68` into a temporary read-only analysis copy.
- Read README, packaging, Docker, configuration, API, orchestrator, spider, auth, storage, event bus, frontend, tests, and CI.
- Installed backend/frontend dependencies in the temporary copy.
- Ran tests and quality checks.

### Confirmed Facts

- `pytest -q`: 106 passed, 5 warnings.
- Ruff: 962 findings.
- Pyright: 229 errors and 5 warnings.
- ESLint: 3 errors.
- Frontend build: blocked by missing `frontend/tsconfig.json`.
- API health and route registration work in a no-database TestClient smoke test.

### Key Problems

- Frontend/backend DTO and SSE event contracts are inconsistent.
- Search result schema and persistence code require an unapplied turn migration.
- Automatic history creation calls a nonexistent service method.
- Background task marks a search completed after `search_stream` emits an error because `search_stream` catches exceptions internally.
- Comment scoring never increments positive/negative counters used by wanghong classification.

### Recommended Next Step

Create a contract test fixture with one fake search, one fake LLM response, one fake POI, and a real SSE client; fix DTO/event/schema boundaries until that test passes.

### Backend Refactor Follow-up

- Limited the refactor analysis to FastAPI, application orchestration, agents,
  provider adapters, task state, SSE, Redis, and PostgreSQL; GUI work is excluded.
- Confirmed remote `HEAD` is still `fa19e984287a9ca376b497e2fcc05c650e210c68`.
- Identified split ownership across orchestrator context, task state, event streams,
  chat memory, and search-result persistence as the primary architectural issue.
- Recorded the tested custom-provider/OpenAI Agents SDK compatibility matrix in
  `AGENT.MD`, with `AGENTS.md` as the automatic discovery entry point.
- Recommended extracting a durable `SearchApplicationService` and typed ports
  before migrating LangChain call sites to an `AgentRuntime` adapter.

### Agentic Architecture Revision

- Reframed the target from workflow-centric orchestration to a constrained
  Agent Loop: observe, plan, execute, review, and replan.
- Added the recommended V2 diagram at
  `D:/codex-group/visualizations/2026/08/16/01a00b98-63f6-70b0-8fd2-fac3ac75df74/food-agent-backend-agentic-v2.drawio`.
- Introduced four runtime boundaries: `AgentRuntime`, `MemoryProvider`,
  `CapabilityGateway`, and `Plan DAG Executor`.
- Fixed workflows are modeled as versioned Skill Packs; exploratory search is
  performed through typed search capabilities rather than direct network access.
- Third-party memory SDKs are allowed through adapters, but PostgreSQL remains
  the durable source of truth and Redis remains working/runtime memory.

## 2026-08-18

### Session Goal

Implement the backend Agentic architecture on `codex/agentic-runtime-v2`, keep
existing API/SSE/persistence behavior, verify it, and publish the branch.

### What Was Done

- Added the provider-neutral Agent Loop with typed, resumable Plan DAGs and
  bounded observe/plan/execute/review/replan phases.
- Added concurrent capability execution with retry, timeout, cancellation,
  per-capability limits, and stable turn-level idempotency.
- Added a policy-enforced Capability Gateway for Local tools, versioned Skills,
  legacy providers, and paginated MCP tool discovery.
- Added layered working/episodic/semantic/procedural memory plus optional
  Mem0/Zep-style semantic adapters; PostgreSQL remains authoritative.
- Moved new and follow-up turns behind the Agent Loop while preserving the
  deterministic search/scoring/POI pipeline as callable capabilities.
- Added a per-session task reservation/supervisor so rejected concurrent
  refines cannot reset an active turn's state or event stream.
- Fixed search history creation, multi-turn result schema/persistence, stale
  terminal events, failure completion status, and private storage access.
- Locked `openai-agents==0.21.0` and `openai==3.1.0` to the tested provider
  contract in `AGENT.MD`.

### Verification

```powershell
uv lock
uv sync --extra dev
uv lock --check
uv run pytest -q
uv run pytest -q tests/test_search_task_supervisor.py tests/test_integration_search_routes.py tests/test_agent_runtime.py tests/test_agentic_search.py tests/test_capabilities_memory.py
uv run ruff check src/api/search/routes.py src/api/search/tasks.py src/xhs_food/agentic src/xhs_food/capabilities src/xhs_food/memory src/xhs_food/runtime src/xhs_food/skills
uv run pyright src/api/search/routes.py src/api/search/tasks.py src/xhs_food/agentic src/xhs_food/capabilities src/xhs_food/memory src/xhs_food/runtime src/xhs_food/skills
```

- Complete backend suite: 125 passed, 5 historical warnings.
- Targeted Agentic/API tests: 22 passed.
- Targeted Ruff: passed.
- Targeted Pyright: 0 errors, 0 warnings.

### Publish State

- Full verification, staged diff validation, and secret audit completed. The
  branch is prepared for commit and remote publication.
