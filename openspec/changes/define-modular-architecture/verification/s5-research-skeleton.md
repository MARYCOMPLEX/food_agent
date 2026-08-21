# S5 Shared Research Skeleton Verification

Date: 2026-08-21

Evidence status: complete; implementation gates, post-audit corrections, and
detached S4 revert evidence were verified against the final pushed S5 range.

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
| Unknown plan ID or plan/task mismatch | Coordinator rejects before Agent runtime dispatch |
| Projection/admission bookkeeping failure | Legacy payload, status, and recovery behavior remain unchanged |
| Late failed/cancelled schedule after completed | Same-turn terminal projection, task, and plan remain completed |
| New refine turn after terminal | Higher numeric turn starts a new running projection; old-turn writes are rejected |
| Duplicate/concurrent submit | Stable task identity; no duplicate legacy admission |

## Gate Record

| Gate | Result |
|---|---|
| Focused S5 correction suite | Passed: 54 tests in 13.23s with `-W error` |
| `uv run --frozen pytest -q -m "unit or integration"` | Passed: 728 passed, 5 deselected, 2 pre-existing warnings, 58.57s |
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
| S5 implementation revision | `359a72f2982435f15993671ea478715c6f5ce679` |
| S5 verification revision | `405b1e648a0f82d5203877e8a5af990580d4a65e` |
| Final S5 correction/head | `0f331feb2e1c356fd2819b6cf677d60178485524` |
| Detached revert revisions | `26ee527cff7f00c0da481b1bb7f6811f249d41b9`, `7eceab1fcacce8ba73899119eec2f2d79c661302`, `9a4bc447df06769d92a65040abdb526cc3f1bc47` |
| Final detached revert head | `9a4bc447df06769d92a65040abdb526cc3f1bc47` |
| S4 base tree | `3b170489c3f3d1215d544e9e8b58fd052ad8ec2b` |
| Reverted tree | `3b170489c3f3d1215d544e9e8b58fd052ad8ec2b` |
| Reverted S4 regression | `684 passed, 5 deselected, 2 warnings in 64.87s` |
| Diff and clean-worktree result | Passed; `git diff --exit-code 67e2e71..HEAD --` returned 0 and status was empty |
| Authority SSE LF check | Passed; `sse_v1_replay_expired.sse` and `sse_v1_window_replay.sse` contain no CR bytes |
| Worktree cleanup/prune result | Passed; temporary detached worktree removed and metadata pruned |

The tested rollback set ends at the final S5 code revision `0f331fe`; this
evidence-only update records that completed drill and does not alter runtime
behavior.
