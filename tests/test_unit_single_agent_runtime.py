"""Focused contracts and bounded-concurrency tests for the research runtime."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    AnalyzeCommentBatch,
    ResearchActionResult,
    ResearchEvent,
    ResearchEventType,
    ResearchGap,
    ResearchPlan,
    ResearchPlanStep,
    ResearchState,
    ResourceClass,
    SearchNotes,
    SemanticAction,
    ShopProfile,
    SourceEnvelope,
    ToolResult,
    XhsNoteLead,
    parse_semantic_action,
    reduce_research_event,
)
from xhs_food.orchestrator.scheduler import StepScheduler
from xhs_food.research.resource_limits import (
    BoundedAsyncQueue,
    BudgetController,
    CircuitBreaker,
    QueueClosedError,
    ResourceCircuitOpenError,
    ResourcePool,
    ResourcePoolConfig,
    RetryableResourceError,
    RuntimeBudget,
)
from xhs_food.research.runtime import ResearchRuntime, ResearchRuntimeConfig


@pytest.mark.unit
def test_runtime_contracts_keep_unknown_provider_fields_and_validate_pagination() -> None:
    envelope = SourceEnvelope(
        source="xhs",
        operation="comments.search",
        items=({"comment_id": "c1"},),
        raw={"provider_field": "kept"},
        provider_extra={"nested": True},
    )

    assert envelope.items == ({"comment_id": "c1"},)
    assert envelope.raw_payload == {"provider_field": "kept"}
    assert envelope.extra["provider_extra"] == {"nested": True}
    with pytest.raises(ValidationError, match="has_more requires next_cursor"):
        SourceEnvelope(source="xhs", operation="comments.search", has_more=True)


@pytest.mark.unit
def test_semantic_actions_are_discriminated_and_policy_fields_are_validated() -> None:
    action = parse_semantic_action(
        {
            "kind": "SearchNotes",
            "id": "search-1",
            "idempotency_key": "run:search-1",
            "query": "成都 火锅",
        }
    )
    assert isinstance(action, SearchNotes)
    assert action.resource is ResourceClass.XHS_SEARCH
    assert isinstance(
        SemanticAction.model_validate_json(
            '{"kind":"search_notes","action_id":"json-1",'
            '"idempotency_key":"json-key","query":"成都"}'
        ),
        SearchNotes,
    )

    with pytest.raises(ValidationError, match="requires query or queries"):
        SearchNotes(action_id="search-1", idempotency_key="key")
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AnalyzeCommentBatch(
            action_id="batch-1",
            idempotency_key="key",
            note_id="note-1",
            batch_index=0,
            comment_ids=("c1", "c1"),
        )


@pytest.mark.unit
def test_research_reducer_is_idempotent_and_orders_independent_items() -> None:
    state = ResearchState(run_id="run-1")
    first = SourceEnvelope(
        source="xhs",
        operation="notes.search",
        normalized_items=({"note_id": "b"},),
        raw_payload={"page": 2},
    )
    second = SourceEnvelope(
        source="xhs",
        operation="notes.search",
        normalized_items=({"note_id": "a"},),
        raw_payload={"page": 1},
    )
    result_a = ResearchActionResult(action_id="a", source_envelopes=(first,))
    result_b = ResearchActionResult(action_id="b", source_envelopes=(second,))
    event_a = ResearchEvent(
        event_id="event-a",
        run_id="run-1",
        sequence=2,
        event_type=ResearchEventType.ACTION_COMPLETED,
        action_id="a",
        result=result_a,
    )
    event_b = ResearchEvent(
        event_id="event-b",
        run_id="run-1",
        sequence=1,
        event_type=ResearchEventType.ACTION_COMPLETED,
        action_id="b",
        result=result_b,
    )

    left = reduce_research_event(reduce_research_event(state, event_a), event_b)
    right = reduce_research_event(reduce_research_event(state, event_b), event_a)
    duplicate = reduce_research_event(left, event_a)
    assert left.source_envelopes == right.source_envelopes
    assert left.applied_event_ids == ("event-a", "event-b")
    assert duplicate == left
    assert [item.normalized_items[0]["note_id"] for item in left.source_envelopes] == ["a", "b"]


@pytest.mark.unit
def test_research_reducer_chooses_duplicate_payload_deterministically() -> None:
    state = ResearchState(run_id="run-duplicate")
    sparse = XhsNoteLead(note_id="same-note")
    rich = XhsNoteLead(note_id="same-note", title="成都火锅", summary="评论很多")

    def completed(event_id: str, note: XhsNoteLead, sequence: int) -> ResearchEvent:
        return ResearchEvent(
            event_id=event_id,
            run_id="run-duplicate",
            sequence=sequence,
            event_type=ResearchEventType.ACTION_COMPLETED,
            action_id=event_id,
            result=ResearchActionResult(action_id=event_id, notes=(note,)),
            occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
        )

    left = reduce_research_event(
        reduce_research_event(state, completed("sparse", sparse, 1)),
        completed("rich", rich, 2),
    )
    right = reduce_research_event(
        reduce_research_event(state, completed("rich", rich, 2)),
        completed("sparse", sparse, 1),
    )

    assert left == right
    assert left.notes == (rich,)


@pytest.mark.unit
def test_research_reducer_profiles_prefer_provider_identity_over_renamed_name() -> None:
    state = ResearchState(run_id="run-profile-identity")

    def completed(event_id: str, profile: ShopProfile, sequence: int) -> ResearchEvent:
        return ResearchEvent(
            event_id=event_id,
            run_id="run-profile-identity",
            sequence=sequence,
            event_type=ResearchEventType.ACTION_COMPLETED,
            action_id=event_id,
            result=ResearchActionResult(action_id=event_id, profiles=(profile,)),
            occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
        )

    old_name = ShopProfile(provider_refs={"dianping": "dp-1"}, name="老店", address="旧地址")
    renamed = ShopProfile(
        provider_refs={"dianping": "dp-1"},
        name="老店焕新",
        address="新地址",
        recommended_dishes=("招牌菜",),
    )

    left = reduce_research_event(
        reduce_research_event(state, completed("old", old_name, 1)),
        completed("renamed", renamed, 2),
    )
    right = reduce_research_event(
        reduce_research_event(state, completed("renamed", renamed, 2)),
        completed("old", old_name, 1),
    )

    assert left == right
    assert len(left.profiles) == 1
    assert left.profiles[0].provider_refs == {"dianping": "dp-1"}


@pytest.mark.unit
def test_research_reducer_merges_duplicate_profile_fields_losslessly() -> None:
    state = ResearchState(run_id="run-profile-fields")

    def completed(event_id: str, profile: ShopProfile, sequence: int) -> ResearchEvent:
        return ResearchEvent(
            event_id=event_id,
            run_id="run-profile-fields",
            sequence=sequence,
            event_type=ResearchEventType.ACTION_COMPLETED,
            action_id=event_id,
            result=ResearchActionResult(action_id=event_id, profiles=(profile,)),
        )

    address_only = ShopProfile(
        provider_refs={"dianping": "dp-fields"},
        name="字段店",
        address="成都春熙路",
        images=({"url": "https://img.example/a"},),
        attributes={"brand": "老字号"},
    )
    dishes_only = ShopProfile(
        provider_refs={"dianping": "dp-fields"},
        name="字段店",
        phone="028-123456",
        recommended_dishes=("招牌牛肉",),
        promotions=({"title": "双人套餐"},),
        tags=("本地人推荐",),
        attributes={"parking": True},
    )

    left = reduce_research_event(
        reduce_research_event(state, completed("address", address_only, 1)),
        completed("dishes", dishes_only, 2),
    )
    right = reduce_research_event(
        reduce_research_event(state, completed("dishes", dishes_only, 2)),
        completed("address", address_only, 1),
    )

    assert left.profiles == right.profiles
    assert len(left.profiles) == 1
    profile = left.profiles[0]
    assert profile.address == "成都春熙路"
    assert profile.phone == "028-123456"
    assert profile.images == ({"url": "https://img.example/a"},)
    assert profile.recommended_dishes == ("招牌牛肉",)
    assert profile.promotions == ({"title": "双人套餐"},)
    assert profile.tags == ("本地人推荐",)
    assert profile.attributes == {"brand": "老字号", "parking": True}


@pytest.mark.unit
def test_research_reducer_name_fallback_is_normalized_only_without_provider_ids() -> None:
    state = ResearchState(run_id="run-profile-name-fallback")

    def completed(event_id: str, profile: ShopProfile) -> ResearchEvent:
        return ResearchEvent(
            event_id=event_id,
            run_id="run-profile-name-fallback",
            sequence=1 if event_id == "spaced" else 2,
            event_type=ResearchEventType.ACTION_COMPLETED,
            action_id=event_id,
            result=ResearchActionResult(action_id=event_id, profiles=(profile,)),
        )

    no_id_spaced = ShopProfile(name="老 店")
    no_id_compact = ShopProfile(name="老店", address="成都")
    identified = ShopProfile(provider_refs={"dianping": "dp-1"}, name="老店")

    name_only = reduce_research_event(
        reduce_research_event(state, completed("spaced", no_id_spaced)),
        completed("compact", no_id_compact),
    )
    mixed = reduce_research_event(
        reduce_research_event(state, completed("spaced", no_id_spaced)),
        completed("identified", identified),
    )

    assert len(name_only.profiles) == 1
    assert len(mixed.profiles) == 2


@pytest.mark.unit
async def test_resource_pool_bounds_concurrency_and_retries() -> None:
    pool = ResourcePool(
        ResourcePoolConfig(
            resource_class="xhs.search",
            max_concurrency=2,
            max_retries=1,
        )
    )
    active = 0
    maximum = 0
    attempts: dict[int, int] = {}

    async def call(identifier: int) -> int:
        nonlocal active, maximum
        attempts[identifier] = attempts.get(identifier, 0) + 1
        if identifier == 0 and attempts[identifier] == 1:
            raise RetryableResourceError("temporary")
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.005)
        active -= 1
        return identifier

    assert await asyncio.gather(*(pool.execute(call, index) for index in range(4))) == [0, 1, 2, 3]
    assert maximum == 2
    assert attempts[0] == 2
    assert pool.max_in_flight == 2


@pytest.mark.unit
async def test_resource_pool_circuit_breaker_is_scoped_and_blocks_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=60)
    pool = ResourcePool(
        ResourcePoolConfig(resource_class="dianping.detail", max_retries=0),
        circuit_breaker=breaker,
    )

    async def fail() -> None:
        raise RetryableResourceError("provider challenge")

    for _ in range(2):
        with pytest.raises(RetryableResourceError):
            await pool.execute(fail)
    with pytest.raises(ResourceCircuitOpenError):
        await pool.execute(fail)
    assert breaker.is_open


@pytest.mark.unit
async def test_budget_controller_reserves_concurrent_calls_atomically() -> None:
    controller = BudgetController(RuntimeBudget(max_calls=1))

    async def reserve_call() -> bool:
        try:
            await controller.reserve(calls=1)
        except Exception as exc:  # noqa: BLE001 - assert one budget loser below
            assert getattr(exc, "dimension", None) == "calls"
            return False
        return True

    results = await asyncio.gather(reserve_call(), reserve_call())
    assert sorted(results) == [False, True]
    assert controller.usage.calls == 1


@pytest.mark.unit
async def test_bounded_queue_close_wakes_all_waiters_and_preserves_accepted_items() -> None:
    queue: BoundedAsyncQueue[int] = BoundedAsyncQueue(maxsize=1)
    queue.put_nowait(1)
    blocked_put = asyncio.create_task(queue.put(2))
    assert await queue.get() == 1
    assert await blocked_put is None
    assert await queue.get() == 2
    waiters = (asyncio.create_task(queue.get()), asyncio.create_task(queue.get()))
    await asyncio.sleep(0)
    await queue.close()
    for waiter in waiters:
        with pytest.raises(QueueClosedError):
            await waiter


@pytest.mark.unit
async def test_runtime_runs_independent_actions_and_allows_partial_dependents() -> None:
    started: set[str] = set()
    started_event = asyncio.Event()
    released = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        started.add(action.action_id)
        if len(started) >= 2:
            started_event.set()
        if action.action_id == "partial":
            return ResearchActionResult(
                action_id=action.action_id,
                completeness="partial",
                gaps=(
                    ResearchGap(
                        source="xhs",
                        operation="comments.search",
                        code="budget_exhausted",
                    ),
                ),
            )
        if action.action_id == "independent":
            await released.wait()
        return ResearchActionResult(action_id=action.action_id)

    actions = (
        SearchNotes(
            action_id="partial",
            idempotency_key="partial-key",
            query="成都",
        ),
        SearchNotes(
            action_id="dependent",
            idempotency_key="dependent-key",
            query="成都 火锅",
            dependencies=("partial",),
        ),
        SearchNotes(
            action_id="independent",
            idempotency_key="independent-key",
            query="成都 串串",
        ),
    )

    runtime = ResearchRuntime(
        handler,
        capabilities={"notes.search"},
        config=ResearchRuntimeConfig(
            max_parallel_actions=2,
            resource_pools={
                "xhs.search": ResourcePoolConfig(
                    resource_class="xhs.search",
                    max_concurrency=2,
                ),
            },
        ),
    )
    task = asyncio.create_task(runtime.run(actions, run_id="run-1"))
    await asyncio.wait_for(started_event.wait(), timeout=1)
    assert {"partial", "independent"}.issubset(started)
    released.set()
    state = await task
    assert "dependent" in state.completed_action_ids
    assert state.outcome.value == "partial"
    assert any(gap.code == "budget_exhausted" for gap in state.gaps)
    assert any(event.event_type is ResearchEventType.ACTION_PROGRESS for event in runtime.events)
    assert all("calls" in event.budget_usage for event in runtime.events)
    assert [event.sequence for event in state.events] == list(range(1, state.sequence + 1))


@pytest.mark.unit
async def test_runtime_reconciles_actual_tokens_without_exceeding_budget() -> None:
    async def handler(action: Any) -> ResearchActionResult:
        return ResearchActionResult(action_id=action.action_id, tokens_used=3)

    action = AnalyzeCommentBatch(
        action_id="batch",
        idempotency_key="batch-key",
        note_id="note-1",
        batch_index=0,
        token_estimate=1,
    )
    runtime = ResearchRuntime(
        handler,
        capabilities={"comments.analyze"},
        config=ResearchRuntimeConfig(budget=RuntimeBudget(max_tokens=3)),
    )
    state = await runtime.run((action,), run_id="token-run")
    assert state.tokens_used == 3
    assert runtime.budget.usage.tokens == 3
    assert state.completed_action_ids == ("batch",)


@pytest.mark.unit
def test_reducer_cancellation_terminal_event_closes_replayed_in_flight_state() -> None:
    state = ResearchState(run_id="cancel-replay")
    started = ResearchEvent(
        event_id="started",
        run_id="cancel-replay",
        sequence=1,
        event_type=ResearchEventType.ACTION_STARTED,
        action_id="action-1",
    )
    cancelled = ResearchEvent(
        event_id="cancelled",
        run_id="cancel-replay",
        sequence=2,
        event_type=ResearchEventType.RUN_CANCELLED,
    )
    reduced = reduce_research_event(reduce_research_event(state, started), cancelled)
    assert reduced.in_flight_action_ids == ()
    assert reduced.failed_action_ids == ("action-1",)


@pytest.mark.unit
async def test_runtime_empty_run_and_duplicate_idempotency_are_validated() -> None:
    runtime = ResearchRuntime()
    empty = await runtime.run((), run_id="empty")
    assert empty.outcome.value == "empty"

    runtime.begin("duplicate-keys")
    first = SearchNotes(action_id="first", idempotency_key="same", query="成都")
    second = SearchNotes(action_id="second", idempotency_key="same", query="重庆")
    with pytest.raises(ValueError, match="idempotency_key"):
        await runtime.run((first, second), run_id="duplicate-keys")


@pytest.mark.unit
async def test_runtime_rejects_full_run_or_dispatch_overlap() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        started.set()
        await release.wait()
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capabilities={"notes.search"})
    runtime.begin("overlap")
    incremental = SearchNotes(action_id="incremental", idempotency_key="i", query="成都")
    full = SearchNotes(action_id="full", idempotency_key="f", query="重庆")
    dispatch_task = asyncio.create_task(runtime.dispatch(incremental))
    await started.wait()
    with pytest.raises(RuntimeError, match="incremental actions are active"):
        await runtime.run((full,), run_id="overlap")
    release.set()
    await dispatch_task


@pytest.mark.unit
async def test_runtime_rejects_unavailable_capability_without_provider_call() -> None:
    calls: list[str] = []

    async def handler(action: Any) -> ResearchActionResult:
        calls.append(action.action_id)
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capability_allow_list=("places.detail",))
    action = SearchNotes(action_id="search", idempotency_key="key", query="成都")
    state = await runtime.run((action,), run_id="run-1")
    assert calls == []
    assert state.failed_action_ids == ("search",)
    assert state.gaps[0].code == "capability_unavailable"


@pytest.mark.unit
async def test_runtime_incremental_dispatch_defers_terminal_and_begin_resets_run() -> None:
    calls: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        calls.append(action.action_id)
        started.set()
        await release.wait()
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime()
    initial = runtime.begin("incremental-1", handler=handler)
    action = SearchNotes(action_id="batch-1", idempotency_key="key-1", query="成都")
    dispatch_task = asyncio.create_task(runtime.dispatch(action))
    await started.wait()
    duplicate_task = asyncio.create_task(runtime.dispatch(action))
    finish_task = asyncio.create_task(runtime.finish())
    await asyncio.sleep(0)
    assert not finish_task.done()
    assert not any(event.event_type is ResearchEventType.RUN_COMPLETED for event in runtime.events)
    release.set()
    first = await dispatch_task
    duplicate = await duplicate_task
    final = await finish_task

    assert initial.run_id == "incremental-1"
    assert first == duplicate
    assert calls == ["batch-1"]
    assert "batch-1" in final.completed_action_ids
    assert any(event.event_type is ResearchEventType.RUN_COMPLETED for event in final.events)
    assert await runtime.finish() == final

    runtime.begin("incremental-2")
    assert runtime.state is not None
    assert runtime.state.run_id == "incremental-2"
    assert runtime.state.sequence == 0
    assert runtime.events == ()


@pytest.mark.unit
async def test_runtime_incremental_dispatch_accepts_completed_external_dependency() -> None:
    calls: list[str] = []

    async def handler(action: Any) -> ResearchActionResult:
        calls.append(action.action_id)
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capabilities={"notes.search"})
    runtime.begin("incremental-dependency")
    parent = SearchNotes(action_id="parent", idempotency_key="parent-key", query="成都")
    child = SearchNotes(
        action_id="child",
        idempotency_key="child-key",
        query="成都 火锅",
        dependencies=("parent",),
    )

    await runtime.dispatch(parent)
    result = await runtime.dispatch(child)
    final = await runtime.finish()

    assert result.success
    assert calls == ["parent", "child"]
    assert final.completed_action_ids == ("child", "parent")


@pytest.mark.unit
async def test_runtime_incremental_cancellation_records_gap_and_can_finish() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        started.set()
        await release.wait()
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capabilities={"notes.search"})
    runtime.begin("cancel-incremental")
    action = SearchNotes(action_id="slow", idempotency_key="slow-key", query="成都")
    task = asyncio.create_task(runtime.dispatch(action))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert runtime.state.gaps[0].code == "action_cancelled"
    final = await runtime.finish()
    assert any(event.event_type is ResearchEventType.RUN_COMPLETED for event in final.events)


@pytest.mark.unit
async def test_runtime_run_cancellation_clears_in_flight_actions() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(action: Any) -> ResearchActionResult:
        started.set()
        await release.wait()
        return ResearchActionResult(action_id=action.action_id)

    runtime = ResearchRuntime(handler, capabilities={"notes.search"})
    action = SearchNotes(action_id="slow", idempotency_key="slow-key", query="成都")
    task = asyncio.create_task(runtime.run((action,), run_id="cancel-run"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert runtime.state.failed_action_ids == ("slow",)
    assert runtime.state.gaps[0].code == "action_cancelled"
    assert any(event.event_type is ResearchEventType.RUN_CANCELLED for event in runtime.events)


@pytest.mark.unit
async def test_scheduler_executes_ready_wave_with_configured_bound() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0

        async def execute(self, call: Any) -> Any:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.005)
            self.active -= 1
            return ToolResult(call_id=call.call_id, success=True, output={})

        async def health(self, tool_name: str) -> bool:
            return True

    gateway = Gateway()
    plan = ResearchPlan(
        plan_id="plan",
        task_id="task",
        goal="parallel",
        steps=tuple(
            ResearchPlanStep(step_id=f"s{index}", capability=f"tool.{index}")
            for index in range(4)
        ),
    )
    result = await StepScheduler(gateway, max_concurrency=2).execute(plan)
    assert result.error is None
    assert gateway.maximum == 2
    assert len(result.completed) == 4


@pytest.mark.unit
async def test_scheduler_continues_independent_ready_actions_after_failure() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def execute(self, call: Any) -> ToolResult:
            self.calls.append(call.tool_name)
            if call.tool_name == "tool.fail":
                return ToolResult(
                    call_id=call.call_id,
                    success=False,
                    error=None,
                )
            return ToolResult(call_id=call.call_id, success=True, output={})

        async def health(self, tool_name: str) -> bool:
            return True

    gateway = Gateway()
    plan = ResearchPlan(
        plan_id="failure-isolation-plan",
        task_id="failure-isolation-task",
        goal="continue independent work",
        steps=(
            ResearchPlanStep(step_id="fail", capability="tool.fail"),
            ResearchPlanStep(step_id="independent", capability="tool.independent"),
            ResearchPlanStep(
                step_id="dependent",
                capability="tool.dependent",
                dependencies=("fail",),
            ),
        ),
    )
    result = await StepScheduler(gateway, max_concurrency=2).execute(plan)
    assert gateway.calls == ["tool.fail", "tool.independent"]
    assert result.plan.status.value == "failed"
    assert [step.step_id for step in result.completed] == ["independent"]
    assert result.error is not None
    assert result.error.code == "TOOL_EXECUTION_FAILED"
