"""Agent Loop contracts: DAG validation, parallel execution and replanning."""

from __future__ import annotations

import asyncio
import time

import pytest

from xhs_food.runtime import (
    AgentLoop,
    AgentLoopConfig,
    AgentRunContext,
    Plan,
    PlanExecutor,
    PlanStep,
    RuleBasedPlanner,
    RuleBasedReviewer,
)


def _context() -> AgentRunContext:
    return AgentRunContext(run_id="run-1", session_id="session-1", user_input="test")


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        Plan(
            id="cycle",
            goal="bad",
            steps=[
                PlanStep(id="a", capability="noop", depends_on=["b"]),
                PlanStep(id="b", capability="noop", depends_on=["a"]),
            ],
        )


@pytest.mark.asyncio
async def test_executor_runs_independent_steps_in_parallel() -> None:
    started: list[str] = []

    async def invoke(name, args, context):
        started.append(name)
        await asyncio.sleep(0.05)
        return args.get("value", name)

    plan = Plan(
        id="parallel",
        goal="parallel",
        steps=[
            PlanStep(id="a", capability="slow", args={"value": "a"}),
            PlanStep(id="b", capability="slow", args={"value": "b"}),
            PlanStep(
                id="c",
                capability="slow",
                args={"value": "c"},
                depends_on=["a", "b"],
            ),
        ],
    )
    start = time.perf_counter()
    report = await PlanExecutor(invoke, max_concurrency=2).execute(plan, _context())
    elapsed = time.perf_counter() - start

    assert report.succeeded
    assert started[:2] == ["slow", "slow"]
    assert elapsed < 0.14
    assert report.outputs["c"] == "c"


@pytest.mark.asyncio
async def test_executor_retries_and_resolves_step_references() -> None:
    attempts = 0

    async def invoke(name, args, context):
        nonlocal attempts
        if name == "flaky" and attempts == 0:
            attempts += 1
            raise RuntimeError("transient")
        return args.get("value")

    plan = Plan(
        id="retry",
        goal="retry",
        steps=[
            PlanStep(id="first", capability="flaky", args={"value": "ready"}),
            PlanStep(
                id="second",
                capability="echo",
                args={"value": {"$ref": "first"}},
                depends_on=["first"],
            ),
        ],
    )
    report = await PlanExecutor(invoke).execute(plan, _context())
    assert report.succeeded
    assert attempts == 1
    assert report.outputs["second"] == "ready"


@pytest.mark.asyncio
async def test_executor_reuses_idempotent_result_across_runs_of_same_turn() -> None:
    calls = 0
    store = {}

    async def invoke(name, args, context):
        nonlocal calls
        calls += 1
        return f"result-{calls}"

    first_context = _context()
    second_context = first_context.model_copy(update={"run_id": "run-2"})
    first = Plan(
        id="first-run",
        goal="resume",
        steps=[PlanStep(id="stable-step", capability="lookup", output_key="answer")],
    )
    second = Plan(
        id="second-run",
        goal="resume",
        steps=[PlanStep(id="stable-step", capability="lookup", output_key="answer")],
    )

    first_report = await PlanExecutor(invoke, idempotency_store=store).execute(first, first_context)
    second_report = await PlanExecutor(invoke, idempotency_store=store).execute(
        second, second_context
    )

    assert calls == 1
    assert first_report.outputs["answer"] == "result-1"
    assert second_report.outputs["answer"] == "result-1"
    assert second_report.executions[0].attempts == 0
    assert second_report.executions[0].idempotency_key == "session-1:1:stable-step"


@pytest.mark.asyncio
async def test_executor_does_not_cache_non_idempotent_steps() -> None:
    calls = 0
    store = {}

    async def invoke(name, args, context):
        nonlocal calls
        calls += 1
        return calls

    executor = PlanExecutor(invoke, idempotency_store=store)
    for run_id in ("run-1", "run-2"):
        plan = Plan(
            id=run_id,
            goal="write twice",
            steps=[
                PlanStep(
                    id="write",
                    capability="write",
                    idempotent=False,
                )
            ],
        )
        await executor.execute(
            plan,
            _context().model_copy(update={"run_id": run_id}),
        )

    assert calls == 2
    assert store == {}


@pytest.mark.asyncio
async def test_executor_honors_capability_idempotency_manifest() -> None:
    calls = 0
    store = {}

    async def invoke(name, args, context):
        nonlocal calls
        calls += 1
        return calls

    executor = PlanExecutor(
        invoke,
        idempotency_store=store,
        capability_idempotency={"external.write": False},
    )
    for run_id in ("run-1", "run-2"):
        await executor.execute(
            Plan(
                id=run_id,
                goal="manifest controls caching",
                steps=[PlanStep(id="write", capability="external.write")],
            ),
            _context().model_copy(update={"run_id": run_id}),
        )

    assert calls == 2
    assert store == {}


@pytest.mark.asyncio
async def test_executor_caps_step_timeout_at_run_deadline() -> None:
    async def invoke(name, args, context):
        await asyncio.sleep(1)

    context = _context()
    context.deadline_at = time.time() + 0.02
    plan = Plan(
        id="deadline",
        goal="stop on time",
        steps=[
            PlanStep(
                id="slow",
                capability="slow",
                timeout_seconds=10,
                max_attempts=1,
            )
        ],
    )

    start = time.perf_counter()
    report = await PlanExecutor(invoke).execute(plan, context)

    assert report.failed
    assert time.perf_counter() - start < 0.2
    assert "timed out" in (report.executions[0].error or "")


@pytest.mark.asyncio
async def test_agent_loop_replans_after_failed_capability() -> None:
    calls: list[str] = []

    async def invoke(name, args, context):
        calls.append(name)
        if name == "bad":
            raise RuntimeError("provider unavailable")
        return "answer"

    first = Plan(id="first", goal="goal", steps=[PlanStep(id="s", capability="bad")])
    replacement = Plan(
        id="replacement",
        goal="goal",
        steps=[PlanStep(id="s2", capability="good", output_key="answer")],
    )
    planner = RuleBasedPlanner(
        lambda _ctx, _caps: first, lambda _ctx, _old, _reason, _caps: replacement
    )
    loop = AgentLoop(
        planner=planner,
        executor=PlanExecutor(invoke),
        reviewer=RuleBasedReviewer(),
        config=AgentLoopConfig(max_replans=1),
    )
    result = await loop.run(_context())

    assert result.status == "completed"
    assert result.answer == "answer"
    assert calls == ["bad", "bad", "good"]
