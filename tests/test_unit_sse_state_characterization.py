"""Characterization of current SSE replay and per-session state semantics."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from xhs_food.events.bus import (
    STREAM_START,
    InMemoryEventBus,
    RedisStreamEventBus,
)
from xhs_food.events.emitter import SearchEventEmitter
from xhs_food.events.types import SearchEvent, SearchEventType


async def _collect(
    bus: InMemoryEventBus | RedisStreamEventBus,
    session_id: str,
    last_id: str = STREAM_START,
) -> list[tuple[str, SearchEvent]]:
    return [item async for item in bus.subscribe(session_id, last_id)]


async def test_six_step_event_order_progress_and_payload_are_frozen() -> None:
    bus = InMemoryEventBus()
    emitter = SearchEventEmitter("six-step-session", bus)
    emitter.init_steps("成都火锅")

    for number in range(1, 7):
        await emitter.step_start(f"step{number}", f"start-{number}")
        await emitter.step_done(f"step{number}", f"done-{number}")
    await emitter.emit_result("推荐完成", total=2, filtered=1)
    await emitter.emit_done()

    events = await _collect(bus, "six-step-session")
    assert [event.type for _, event in events] == [
        event_type
        for _ in range(6)
        for event_type in (SearchEventType.STEP_START, SearchEventType.STEP_DONE)
    ] + [SearchEventType.RESULT, SearchEventType.DONE]
    assert [event.data.get("step") for _, event in events[:12]] == [
        step_id for number in range(1, 7) for step_id in (f"step{number}", f"step{number}")
    ]
    assert [event.data["progress"] for _, event in events[:12]] == [
        0,
        16,
        16,
        33,
        33,
        50,
        50,
        66,
        66,
        83,
        83,
        100,
    ]
    assert [event.data["message"] for _, event in events[:12]] == [
        message for number in range(1, 7) for message in (f"start-{number}", f"done-{number}")
    ]
    assert all(
        set(event.data) == {"step", "message", "steps", "progress"} for _, event in events[:12]
    )
    assert events[-2][1].data == {
        "summary": "推荐完成",
        "total": 2,
        "filtered": 1,
        "steps": emitter.steps,
    }
    assert events[-1][1].data == {"message": "搜索完成"}
    assert [entry_id for entry_id, _ in events] == [f"mem-{number}" for number in range(1, 15)]


async def test_disconnect_then_resume_replays_only_events_after_seen_id() -> None:
    bus = InMemoryEventBus()
    first_id = await bus.publish(
        "disconnect-session",
        SearchEvent(SearchEventType.PROGRESS, {"sequence": 1}),
    )
    subscription: AsyncGenerator[tuple[str, SearchEvent], None] = bus.subscribe(
        "disconnect-session"
    )
    received_id, received_event = await anext(subscription)
    assert received_id == first_id
    assert received_event.type == SearchEventType.PROGRESS
    assert received_event.data == {"sequence": 1}
    await subscription.aclose()

    await bus.publish(
        "disconnect-session",
        SearchEvent(SearchEventType.PROGRESS, {"sequence": 2}),
    )
    await bus.publish(
        "disconnect-session",
        SearchEvent(SearchEventType.DONE, {"message": "搜索完成"}),
    )

    resumed = await _collect(bus, "disconnect-session", first_id)
    assert [event.data for _, event in resumed] == [
        {"sequence": 2},
        {"message": "搜索完成"},
    ]


async def test_old_terminal_cursor_has_no_replay_and_pre_terminal_cursor_gets_terminal() -> None:
    bus = InMemoryEventBus()
    before_terminal = await bus.publish(
        "old-terminal",
        SearchEvent(SearchEventType.PROGRESS, {"sequence": 1}),
    )
    terminal_id = await bus.publish(
        "old-terminal",
        SearchEvent(SearchEventType.DONE, {"message": "搜索完成"}),
    )

    from_before_terminal = await _collect(bus, "old-terminal", before_terminal)
    from_terminal = await _collect(bus, "old-terminal", terminal_id)

    assert [(entry_id, event.type) for entry_id, event in from_before_terminal] == [
        (terminal_id, SearchEventType.DONE)
    ]
    assert from_terminal == []


async def test_repeated_subscriptions_replay_the_same_completed_stream() -> None:
    bus = InMemoryEventBus()
    await bus.publish(
        "repeated-subscription",
        SearchEvent(SearchEventType.PROGRESS, {"sequence": 1}),
    )
    await bus.publish(
        "repeated-subscription",
        SearchEvent(SearchEventType.DONE, {"message": "搜索完成"}),
    )

    first, second = await asyncio.gather(
        _collect(bus, "repeated-subscription"),
        _collect(bus, "repeated-subscription"),
    )

    assert first == second
    assert [event.type for _, event in first] == [
        SearchEventType.PROGRESS,
        SearchEventType.DONE,
    ]


async def test_same_session_refine_keeps_old_done_in_event_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freeze stale-DONE replay: refine resets the emitter, not its bus stream."""
    from xhs_food.composition import research_task
    from xhs_food.composition.research_task import ResearchTaskFacade

    bus = InMemoryEventBus()
    emitter = SearchEventEmitter("refine-session", bus)
    emitter.init_steps("first query")
    old_done_id = await emitter.emit(
        SearchEvent(SearchEventType.DONE, {"message": "first turn done"})
    )
    state = {"turn_id": 1, "status": "completed"}

    async def _load_state(session_id: str) -> dict[str, Any]:
        assert session_id == "refine-session"
        return state

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        assert session_id == "refine-session"
        state.update(changes)
        return state

    class _SessionManager:
        async def add_user_message(self, session_id: str, query: str) -> None:
            assert (session_id, query) == ("refine-session", "less spicy")

    async def _get_session_manager() -> _SessionManager:
        return _SessionManager()

    async def _get_emitter(session_id: str) -> SearchEventEmitter:
        assert session_id == "refine-session"
        return emitter

    async def _noop_search(
        session_id: str,
        query: str,
        tool_context: object | None,
    ) -> None:
        return None

    def _discard_task(coro: Any) -> object:
        coro.close()
        return object()

    monkeypatch.setattr(research_task.search_state, "load_state", _load_state)
    monkeypatch.setattr(research_task.search_state, "update_state", _update_state)
    monkeypatch.setattr(research_task, "get_session_manager", _get_session_manager)
    monkeypatch.setattr(research_task, "get_emitter", _get_emitter)

    facade = ResearchTaskFacade(
        task_runner=_noop_search,
        task_spawner=_discard_task,
    )
    admission = await facade.refine("refine-session", "less spicy")
    await emitter.step_start("step1", "refine start")
    await emitter.emit_done()

    replay_without_cursor = await _collect(bus, "refine-session")
    replay_after_old_done = await _collect(bus, "refine-session", old_done_id)

    assert admission.turn_id == 2
    assert state == {
        "turn_id": 2,
        "status": "loading",
        "query": "less spicy",
    }
    assert [(entry_id, event.data) for entry_id, event in replay_without_cursor] == [
        (old_done_id, {"message": "first turn done"})
    ]
    assert [event.type for _, event in replay_after_old_done] == [
        SearchEventType.STEP_START,
        SearchEventType.DONE,
    ]


class _SharedRedisFixture:
    """Small Redis Streams fixture shared by simulated worker adapters."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.counter = 0
        self.expirations: list[tuple[str, int]] = []
        self.maxlens: list[int] = []

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        assert approximate is True
        self.counter += 1
        entry_id = f"{self.counter}-0"
        self.streams.setdefault(key, []).append((entry_id, fields))
        self.maxlens.append(maxlen)
        return entry_id

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations.append((key, ttl))

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        assert count == 50
        assert block > 0
        key, cursor = next(iter(streams.items()))
        entries = [entry for entry in self.streams.get(key, []) if entry[0] > cursor]
        return [(key, entries)] if entries else []


async def test_redis_stream_is_shared_across_simulated_workers() -> None:
    redis = _SharedRedisFixture()
    worker_a = RedisStreamEventBus(redis)
    worker_b = RedisStreamEventBus(redis)

    first_id = await worker_a.publish(
        "multi-worker-session",
        SearchEvent(SearchEventType.PROGRESS, {"worker": "a"}),
    )
    terminal_id = await worker_b.publish(
        "multi-worker-session",
        SearchEvent(SearchEventType.DONE, {"worker": "b"}),
    )

    received_by_worker_b = await _collect(worker_b, "multi-worker-session")

    assert [first_id, terminal_id] == ["1-0", "2-0"]
    assert [(entry_id, event.data) for entry_id, event in received_by_worker_b] == [
        ("1-0", {"worker": "a"}),
        ("2-0", {"worker": "b"}),
    ]
    assert len(redis.expirations) == 2
    assert redis.maxlens == [worker_a._maxlen, worker_b._maxlen]
