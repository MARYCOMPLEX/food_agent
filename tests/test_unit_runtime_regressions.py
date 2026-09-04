"""Regression tests for single-agent runtime lifecycle guarantees.

These tests deliberately exercise the public runtime, resource-pool, and
event-reducer contracts.  They protect evidence preservation and lifecycle
semantics while provider adapters evolve independently.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_food.contracts import (
    AnalyzeCommentBatch,
    ResearchActionResult,
    ResearchEvent,
    ResearchEventType,
    ResearchState,
    SearchNotes,
    XhsNoteLead,
    reduce_research_event,
)
from xhs_food.research.resource_limits import (
    CircuitBreaker,
    CircuitState,
    ResourcePool,
    ResourcePoolConfig,
    RetryableResourceError,
    RuntimeBudget,
)
from xhs_food.research.runtime import ResearchRuntime, ResearchRuntimeConfig


@pytest.mark.unit
async def test_aclose_waits_for_shielded_finish_task_before_returning() -> None:
    finish_started = asyncio.Event()
    finish_release = asyncio.Event()

    class SlowFinisherRuntime(ResearchRuntime):
        async def _finish_impl(self, tasks: tuple[asyncio.Task[Any], ...]) -> ResearchState:
            finish_started.set()
            await finish_release.wait()
            return await super()._finish_impl(tasks)

    runtime = SlowFinisherRuntime(
        lambda _: ResearchActionResult(action_id="unused"),
        capabilities={"notes.search"},
    )
    runtime.begin("close-finisher")
    finisher = asyncio.create_task(runtime.finish())
    await asyncio.wait_for(finish_started.wait(), timeout=1)

    close_task = asyncio.create_task(runtime.aclose())
    await asyncio.sleep(0)
    assert close_task.done() is False
    assert runtime._finish_task is not None
    assert runtime._finish_task.done() is False

    finish_release.set()
    final = await asyncio.wait_for(finisher, timeout=1)
    await asyncio.wait_for(close_task, timeout=1)

    assert final.outcome.value == "failed"
    assert runtime._finish_task is not None
    assert runtime._finish_task.done() is True
    assert sum(
        event.event_type is ResearchEventType.RUN_CANCELLED for event in runtime.events
    ) == 1


@pytest.mark.unit
async def test_aclose_drains_finisher_when_cancel_itself_is_interrupted() -> None:
    finish_started = asyncio.Event()
    finish_release = asyncio.Event()

    class InterruptibleCancelRuntime(ResearchRuntime):
        async def _finish_impl(self, tasks: tuple[asyncio.Task[Any], ...]) -> ResearchState:
            finish_started.set()
            await finish_release.wait()
            return await super()._finish_impl(tasks)

        async def cancel(self) -> ResearchState | None:
            self._cancel_requested = True
            raise asyncio.CancelledError

    runtime = InterruptibleCancelRuntime(
        lambda _: ResearchActionResult(action_id="unused"),
        capabilities={"notes.search"},
    )
    runtime.begin("interrupted-cancel")
    finisher = asyncio.create_task(runtime.finish())
    await asyncio.wait_for(finish_started.wait(), timeout=1)

    close_task = asyncio.create_task(runtime.aclose())
    await asyncio.sleep(0)
    assert close_task.done() is False
    finish_release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(close_task, timeout=1)
    final = await asyncio.wait_for(finisher, timeout=1)

    assert final.outcome.value == "failed"
    assert runtime._finish_task is not None
    assert runtime._finish_task.done() is True
    assert sum(
        event.event_type is ResearchEventType.RUN_CANCELLED for event in runtime.events
    ) == 1


@pytest.mark.unit
async def test_actual_token_overage_keeps_partial_result_and_typed_gap() -> None:
    async def handler(action: Any) -> ResearchActionResult:
        return ResearchActionResult(
            action_id=action.action_id,
            notes=(XhsNoteLead(note_id="note-preserved", title="火锅线索"),),
            tokens_used=3,
        )

    action = AnalyzeCommentBatch(
        action_id="analyze-overage",
        idempotency_key="run:analyze-overage",
        note_id="note-preserved",
        batch_index=0,
        comment_ids=("comment-1",),
        token_estimate=1,
    )
    runtime = ResearchRuntime(
        handler,
        capabilities={"comments.analyze"},
        config=ResearchRuntimeConfig(budget=RuntimeBudget(max_tokens=1)),
    )

    state = await runtime.run((action,), run_id="token-overage")

    assert state.notes == (XhsNoteLead(note_id="note-preserved", title="火锅线索"),)
    assert state.completed_action_ids == ("analyze-overage",)
    assert state.outcome.value == "partial"
    gap = next(gap for gap in state.gaps if gap.code == "budget_tokens_exhausted")
    assert gap.details["action_id"] == "analyze-overage"
    completion = next(
        event
        for event in state.events
        if event.event_type is ResearchEventType.ACTION_COMPLETED
    )
    assert completion.result is not None
    assert completion.result.completeness == "partial"
    assert completion.result.notes == state.notes
    assert completion.result.continuation["budget_exhausted"] is True


@pytest.mark.unit
async def test_resumed_state_restores_action_call_and_token_budget_usage() -> None:
    calls: list[str] = []

    async def handler(action: Any) -> ResearchActionResult:
        calls.append(action.action_id)
        return ResearchActionResult(action_id=action.action_id, tokens_used=2)

    config = ResearchRuntimeConfig(
        budget=RuntimeBudget(max_actions=1, max_calls=1, max_tokens=2)
    )
    first_runtime = ResearchRuntime(handler, config=config, capabilities={"comments.analyze"})
    first_runtime.begin("resume-budget")
    first_action = AnalyzeCommentBatch(
        action_id="first",
        idempotency_key="run:first",
        note_id="note-1",
        batch_index=0,
        comment_ids=("comment-1",),
        token_estimate=2,
    )
    await first_runtime.dispatch(first_action)
    persisted = first_runtime.state
    assert persisted is not None
    assert first_runtime.budget.usage.actions == 1
    assert first_runtime.budget.usage.calls == 1
    assert first_runtime.budget.usage.tokens == 2

    resumed = ResearchRuntime(
        handler,
        config=config,
        capabilities={"comments.analyze"},
        initial_state=persisted,
    )
    assert resumed.budget.usage.actions == 1
    assert resumed.budget.usage.calls == 1
    assert resumed.budget.usage.tokens == 2

    second_action = AnalyzeCommentBatch(
        action_id="second",
        idempotency_key="run:second",
        note_id="note-2",
        batch_index=0,
        comment_ids=("comment-2",),
        token_estimate=1,
    )
    state = await resumed.run((second_action,), state=persisted)

    assert calls == ["first"]
    assert state.failed_action_ids == ("second",)
    assert any(gap.code == "budget_actions_exhausted" for gap in state.gaps)
    assert resumed.budget.usage.actions == 1
    assert resumed.budget.usage.calls == 1
    assert resumed.budget.usage.tokens == 2


@pytest.mark.unit
async def test_total_duration_budget_cancels_blocking_provider_call() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(
        handler,
        capabilities={"notes.search"},
        config=ResearchRuntimeConfig(
            budget=RuntimeBudget(max_duration_seconds=0.03),
            resource_pools={
                "xhs.search": ResourcePoolConfig(
                    resource_class="xhs.search",
                    max_concurrency=1,
                )
            },
        ),
    )
    action = SearchNotes(
        action_id="duration-bound",
        idempotency_key="run:duration-bound",
        query="成都 火锅",
    )

    state = await asyncio.wait_for(runtime.run((action,), run_id="duration-run"), timeout=1)

    assert entered.is_set()
    assert cancelled.is_set()
    assert state.failed_action_ids == ("duration-bound",)
    assert any(gap.code == "resource_timeout" for gap in state.gaps)


@pytest.mark.unit
async def test_cancelled_half_open_probe_is_available_to_the_next_request() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        failure_threshold=1,
        reset_timeout_seconds=1.0,
        clock=lambda: now[0],
    )
    pool = ResourcePool(
        ResourcePoolConfig(resource_class="xhs.search", max_retries=0),
        circuit_breaker=breaker,
        clock=lambda: now[0],
    )

    async def fail() -> None:
        raise RetryableResourceError("provider unavailable")

    with pytest.raises(RetryableResourceError):
        await pool.execute(fail)
    assert breaker.state is CircuitState.OPEN

    now[0] = 2.0
    entered = asyncio.Event()

    async def blocked() -> None:
        entered.set()
        await asyncio.Event().wait()

    cancelled_probe = asyncio.create_task(pool.execute(blocked))
    await entered.wait()
    assert breaker.state is CircuitState.HALF_OPEN
    cancelled_probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_probe

    async def succeeds() -> str:
        return "ok"

    assert await pool.execute(succeeds) == "ok"
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.unit
def test_late_completion_after_run_cancelled_cannot_revive_terminal_state() -> None:
    run_id = "late-cancelled"
    state = ResearchState(run_id=run_id)
    started = ResearchEvent(
        event_id="action:start",
        run_id=run_id,
        sequence=1,
        event_type=ResearchEventType.ACTION_STARTED,
        action_id="slow-action",
    )
    cancelled = ResearchEvent(
        event_id="run:cancelled",
        run_id=run_id,
        sequence=2,
        event_type=ResearchEventType.RUN_CANCELLED,
    )
    late = ResearchEvent(
        event_id="action:late-complete",
        run_id=run_id,
        sequence=3,
        event_type=ResearchEventType.ACTION_COMPLETED,
        action_id="slow-action",
        result=ResearchActionResult(
            action_id="slow-action",
            notes=(XhsNoteLead(note_id="late-note"),),
            tokens_used=9,
        ),
    )

    cancelled_state = reduce_research_event(
        reduce_research_event(state, started), cancelled
    )
    reduced = reduce_research_event(cancelled_state, late)

    assert reduced.outcome == cancelled_state.outcome
    assert reduced.outcome.value != "complete"
    assert reduced.in_flight_action_ids == ()
    assert reduced.failed_action_ids == ("slow-action",)
    assert reduced.completed_action_ids == ()
    assert reduced.notes == ()
    assert reduced.tokens_used == 0
    assert reduced.events[-1].event_id == "action:late-complete"


@pytest.mark.unit
def test_duplicate_completion_event_ids_do_not_double_count_tokens() -> None:
    run_id = "duplicate-completion"
    state = ResearchState(run_id=run_id)

    def completed(event_id: str, sequence: int) -> ResearchEvent:
        return ResearchEvent(
            event_id=event_id,
            run_id=run_id,
            sequence=sequence,
            event_type=ResearchEventType.ACTION_COMPLETED,
            action_id="same-action",
            result=ResearchActionResult(
                action_id="same-action",
                notes=(XhsNoteLead(note_id="same-note"),),
                tokens_used=7,
            ),
        )

    state = reduce_research_event(state, completed("complete:one", 1))
    state = reduce_research_event(state, completed("complete:replay", 2))

    assert state.tokens_used == 7
    assert state.completed_action_ids == ("same-action",)
    assert state.notes == (XhsNoteLead(note_id="same-note"),)
    assert state.applied_event_ids == ("complete:one", "complete:replay")


@pytest.mark.unit
async def test_cancelling_one_duplicate_incremental_waiter_keeps_shared_execution() -> None:
    calls: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        calls.append(action.action_id)
        started.set()
        await release.wait()
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capabilities={"notes.search"})
    runtime.begin("shared-dispatch")
    action = SearchNotes(
        action_id="shared-action",
        idempotency_key="run:shared-action",
        query="成都",
    )
    owner = asyncio.create_task(runtime.dispatch(action))
    await started.wait()
    waiter = asyncio.create_task(runtime.dispatch(action))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    release.set()
    result = await owner
    final = await runtime.finish()

    assert result.success is True
    assert calls == ["shared-action"]
    assert final.completed_action_ids == ("shared-action",)
    assert not any(gap.code == "action_cancelled" for gap in final.gaps)


@pytest.mark.unit
async def test_event_sink_receives_events_in_runtime_sequence_order() -> None:
    delivered: list[int] = []

    async def sink(event: ResearchEvent) -> None:
        if event.event_type is ResearchEventType.ACTION_STARTED:
            await asyncio.sleep(0.01 if event.action_id == "a" else 0)
        delivered.append(event.sequence)

    async def handler(action: Any) -> ResearchActionResult:
        await asyncio.sleep(0 if action.action_id == "b" else 0.002)
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(
        handler,
        capabilities={"notes.search"},
        config=ResearchRuntimeConfig(max_parallel_actions=2),
        event_sink=sink,
    )
    actions = (
        SearchNotes(action_id="a", idempotency_key="run:a", query="成都"),
        SearchNotes(action_id="b", idempotency_key="run:b", query="重庆"),
    )
    runtime.begin("ordered-sink")
    await asyncio.gather(*(runtime.dispatch(action) for action in actions))
    await runtime.finish()

    assert delivered == sorted(delivered)
    assert delivered == [event.sequence for event in runtime.events]
