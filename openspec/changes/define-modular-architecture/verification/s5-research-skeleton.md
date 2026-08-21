# S5 Shared Research Skeleton Verification

Date: 2026-08-21

Evidence status: implementation gates passed; detached S4 revert evidence is
recorded below after the pushed implementation commit.

## Scope

S5 adds the shared, domain-neutral research skeleton: a versioned typed DAG
plan, the Research Coordinator lifecycle facade, one Pydantic AI V2 runtime
adapter, a Gateway-only step scheduler, evidence review/replan and stopping
shells, and query-only progress/recovery projections. The default Coordinator
continues to delegate admission, execution, cancellation, retry, terminal
status, and wire mapping to the legacy task policy. Agent execution,
StepScheduler execution, reliable policy, and Temporal integration remain
disabled.

S5 does not add an Alembic revision, create a table, write a durable
checkpoint, start a Temporal workflow, change Redis authority, add an object,
or change HTTP/SSE/DTO behavior. B0 owns executable checkpoint/replay and
persist-before-terminal semantics.

## Contract And Binding Inventory

| Boundary | S5 result |
|---|---|
| Plan schema | New `research-plan/v1`; legacy generic `1.0` plans remain readable |
| DAG validation | Unique step IDs, known acyclic dependencies, status invariants, budgets, and non-empty unique evidence refs |
| Coordinator | Shared lifecycle owner with legacy admission/execution delegation and monotonic status/projection updates |
| Agent runtime | Exactly one `PydanticAIAgentRuntime`, typed dependencies/tools/output, Gateway-only dispatch |
| Temporal binding | `pydantic-ai-temporal/v1` metadata registered but disabled; no workflow execution in S5 |
| Scheduler | Deterministic dependency order, tool/deadline/step/plan budgets, stable failure categories |
| Review/replan | Evidence review, replanning, and stopping-condition ports are shells delegating to legacy behavior by default |
| Projection | `task_progress_projection` and `RecoverView` are query-only and rebuildable; never executable checkpoints |
| Default selection | `modular_core -> ResearchCoordinator -> LegacyResearchTaskFacade` |
| Rollback selection | `MODULAR_RESEARCH_CORE_VERSION=legacy/v1 -> LegacyResearchTaskFacade` |

## Compatibility Evidence

The S5 differential tests cover duplicate admission, concurrent submit,
legacy success/error/terminal states, cancel/retry delegation, session/turn
identity, event identity, recover views, projection failure isolation, and
resumed-plan progress accounting. Existing Food keyword order, stopping,
ranking, DTO defaults, HTTP envelopes, SSE events, and persistence behavior
remain covered by the S0-S4 regression suite.

Agent contract tests use `ScriptedAgentRuntime` and provider fakes only. They
verify disabled fail-closed behavior, typed tool schema validation before
Gateway dispatch, malformed output rejection, allowed plan/evidence scope,
budget/deadline enforcement, and separate provider-failure classification.

## Failure And Isolation Matrix

| Injection | Required assertion |
|---|---|
| Invalid DAG, duplicate/unknown dependency, cycle | Plan construction rejects atomically |
| Illegal dependency status or evidence ref | Contract validation fails before scheduling |
| Tool timeout/failure or exhausted plan/step budget | Stable terminal error; failed step and descendants are not executed |
| Agent disabled | `AGENT_RUNTIME_DISABLED`; no model/provider call |
| Malformed tool input/output | `TOOL_INPUT_INVALID`/`TOOL_OUTPUT_INVALID`; Gateway/provider boundary stops |
| Malformed final output or out-of-scope step/evidence refs | `AGENT_OUTPUT_INVALID`/scope error before result publication |
| Provider `ValueError` or runtime exception | `AGENT_PROVIDER_FAILURE`, retryable dependency category |
| Projection/admission bookkeeping failure | Legacy payload, status, and recovery behavior remain unchanged |
| Duplicate/concurrent submit | Stable task identity; no duplicate legacy admission |

## Gate Record

| Gate | Result |
|---|---|
| `uv run --frozen pytest -q -m "unit or integration"` | Passed: 724 passed, 5 deselected, 2 pre-existing warnings, 45.69s |
| Scoped Ruff check | Passed |
| Scoped Ruff format check | Passed after normalizing `orchestrator/__init__.py` to LF |
| Scoped Pyright | Passed: 0 errors, 0 warnings, 0 informations |
| `uv lock --check` | Passed; 117 packages resolved |
| Strict OpenSpec validation | Passed; no issues |
| `git -c core.autocrlf=false diff --check` | Passed |

## Revert Drill

Procedure: `runbooks/s5-research-skeleton-rollback.md`.

| Revert evidence | Final value |
|---|---|
| S4 base revision | `67e2e71b9836886215f66f3c7bb338443b9dd423` |
| S5 implementation revision | `<fill after pushed implementation commit>` |
| Detached revert revision | `<fill after detached drill>` |
| S4 base tree | `<fill after detached drill>` |
| Reverted tree | `<fill after detached drill>` |
| Reverted S4 regression | `<fill exact test count/duration after detached drill>` |
| Diff and clean-worktree result | `<fill after detached drill>` |
| Worktree cleanup/prune result | `<fill after detached drill>` |

The placeholders above are release blockers and must be replaced with command
evidence before task 7.11 is checked.
