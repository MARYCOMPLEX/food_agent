# Backend Agent Integration Contract

## Tested Provider

- Base URL: `https://tokenrhythm.studio/v1`
- Model: `deepseek-v4-flash-0731`
- Credentials: read from `OPENAI_API_KEY`; never commit a token.
- Test versions: `openai-agents==0.21.0`, `openai==3.1.0`.
- Test date: 2026-08-17.
- Current repository state: `openai-agents==0.21.0` and `openai==3.1.0` are
  locked in `pyproject.toml`/`uv.lock`. The provider adapter lives in
  `src/xhs_food/runtime/model_runtime.py`; legacy LangChain call sites remain
  during staged migration.

## Confirmed Compatibility

`OpenAIResponsesModel` passed:

- Basic `Agent` execution.
- Function tool calling.
- Strict Pydantic `output_type` structured output.
- Streaming through the Agents SDK event stream.

`OpenAIChatCompletionsModel` passed:

- Basic execution.
- Function tool calling when tool choice remains automatic.
- Agent handoff.
- Streaming.

## Provider Constraints

- Prefer `OpenAIResponsesModel` for this provider.
- Do not assume Chat Completions strict `json_schema` support; the tested request
  failed. Use Responses plus a Pydantic `output_type` for typed results.
- Do not force a named tool on Chat Completions; the tested provider rejected
  that request. Leave tool selection as `auto` unless a new compatibility test
  proves otherwise.
- Disable OpenAI tracing for provider-only credentials. Agents SDK tracing uses
  OpenAI's tracing endpoint and needs a separate valid OpenAI credential.
- Treat streaming as an internal SDK event source. Map it into the project's
  typed search events instead of forwarding provider event payloads to SSE.
- Handoffs passed on Chat Completions, but application workflow state must not
  live only inside an in-process handoff.

## Required Construction Pattern

```python
import os

from agents import Agent, RunConfig, Runner
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url=os.environ.get(
        "OPENAI_API_BASE",
        "https://tokenrhythm.studio/v1",
    ),
    api_key=os.environ["OPENAI_API_KEY"],
)

model = OpenAIResponsesModel(
    model=os.environ.get("DEFAULT_LLM_MODEL", "deepseek-v4-flash-0731"),
    openai_client=client,
)

agent = Agent(name="food-agent", model=model, instructions="...")
result = await Runner.run(
    agent,
    input="...",
    run_config=RunConfig(tracing_disabled=True),
)
```

## Migration Rules

1. Put the Agents SDK behind a local `AgentRuntime` protocol; API routes and
   domain services must not import SDK classes directly.
2. Keep the tested SDK versions pinned when migrating call sites; verify the
   resolved FastAPI, Starlette, Pydantic, and MCP versions after any upgrade.
3. Migrate intent parsing first, then comment analysis, then follow-up handling.
4. Keep the four-stage XHS search, deterministic scoring, POI enrichment,
   persistence, and SSE event protocol in application/infrastructure services.
5. Use Pydantic models at every LLM boundary. Remove manual JSON extraction only
   after the corresponding compatibility and contract tests pass.
6. Keep LangChain until all existing call sites have migrated; do not retain it
   merely as an extra provider wrapper after that point.
7. Re-run basic, tool, structured-output, streaming, handoff, and tracing tests
   whenever provider, model, `openai-agents`, or `openai` versions change.

## Agentic Runtime Rules

- Follow-up handling uses an Agent Loop with explicit `observe`, `plan`,
  `execute`, `review`, and `replan` phases. The loop supervisor owns budgets,
  cancellation, retries, idempotency, and stop conditions.
- Complex requests use a typed Plan DAG. The model may add or revise pending
  steps, but it cannot bypass capability policy or mutate completed steps.
- Independent read-only steps may execute concurrently through the runtime
  executor. The model never creates raw asyncio tasks and never controls
  provider concurrency directly.
- Fixed workflows are exposed as versioned Skill Packs. The agent may invoke a
  Skill Pack as a high-level capability or compose lower-level tools when the
  task requires exploration.
- Local tools, Skills, and MCP tools are normalized behind a
  `CapabilityGateway`. Every capability declares input/output schemas, version,
  timeout, cost, concurrency limit, side-effect level, auth scope, and trust.
- Memory is accessed through `MemoryProvider`. Working memory belongs in Redis;
  durable sessions, messages, evidence, and user facts belong in PostgreSQL.
  A third-party memory SDK such as Mem0 or Zep may be an optional semantic
  retrieval/extraction adapter, never the authoritative store.
- Search tools should return typed evidence with source IDs and provenance;
  final answers must be produced from evidence rather than untracked model
  text.

## Implemented Backend Boundaries

- `src/xhs_food/runtime/`: provider-neutral Agent Loop, typed Plan DAG,
  bounded replan policy, concurrent executor, retry/timeout/cancellation, and
  stable `session_id:turn_id:step_id` idempotency keys.
- `src/xhs_food/capabilities/`: policy-enforced catalog/gateway for local tools,
  Skills, legacy providers, and MCP. `MCPToolSource` discovers paginated
  `list_tools` results and keeps planner-visible names separate from remote
  tool names.
- `src/xhs_food/skills/`: versioned deterministic workflows exposed as agent
  capabilities. `food.search.fixed` is the stable food-search workflow.
- `src/xhs_food/memory/`: working, episodic, semantic, and procedural layers.
  PostgreSQL remains authoritative; Redis/in-memory owns working state;
  Mem0/Zep-style SDKs are optional semantic adapters only.
- `src/xhs_food/agentic/search.py`: food-domain composition root. It exposes
  fixed and low-level capabilities but leaves task creation, provider calls,
  storage, and SSE transport outside model control.
- `src/api/search/tasks.py`: one active task per session, route-time
  reservation before state mutation, and a global cross-session concurrency
  limit. API routes must not create unmanaged background tasks.
- Agents SDK events are never sent directly to clients. Internal loop events
  are mapped into the existing typed SSE event contract.

The rule-based planner is the default rollback-safe path.
`AGENT_MODEL_PLANNER_ENABLED=true` enables the typed Responses-based planner;
the Capability Gateway remains authoritative in both modes.

## Repository Verification Baseline

Verified on 2026-08-18 after the Agentic backend integration:

- `uv lock --check`: passed (`111` resolved packages).
- `uv run pytest -q`: `125 passed`, `5 warnings`.
- The five warnings are pre-existing tests that return booleans instead of
  asserting (`tests/test_config.py` and `tests/test_session.py`).
- Ruff on the API/Agentic runtime change surface: passed.
- Pyright on the API/Agentic runtime change surface: `0 errors`, `0 warnings`.

Re-run this baseline whenever Plan semantics, capability policy, task
supervision, memory routing, SDK versions, or provider configuration changes.
