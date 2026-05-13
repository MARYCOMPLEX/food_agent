"""Unit tests for :class:`xhs_food.events.bus.InMemoryEventBus`."""

from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest

from xhs_food.events.bus import STREAM_START, InMemoryEventBus
from xhs_food.events.types import SearchEvent, SearchEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evt(kind: SearchEventType, **data) -> SearchEvent:
    """Tiny helper to build :class:`SearchEvent` in tests."""
    return SearchEvent(type=kind, data=dict(data))


async def _collect(
    bus: InMemoryEventBus,
    session_id: str,
    last_id: str = STREAM_START,
    *,
    max_items: int | None = None,
    timeout: float = 1.0,
) -> List[Tuple[str, SearchEvent]]:
    """Drain the subscribe generator until terminal or ``max_items``/timeout."""
    out: List[Tuple[str, SearchEvent]] = []

    async def runner() -> None:
        async for entry_id, evt in bus.subscribe(session_id, last_id):
            out.append((entry_id, evt))
            if max_items is not None and len(out) >= max_items:
                return

    try:
        await asyncio.wait_for(runner(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return out


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def test_publish_assigns_sequential_ids(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"

    # Act
    id1 = await event_bus.publish(sid, _evt(SearchEventType.PROGRESS))
    id2 = await event_bus.publish(sid, _evt(SearchEventType.PROGRESS))

    # Assert
    assert id1 == "mem-1"
    assert id2 == "mem-2"


async def test_publish_appends_to_channel(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"

    # Act
    await event_bus.publish(sid, _evt(SearchEventType.STEP_START, step="step1"))
    await event_bus.publish(sid, _evt(SearchEventType.STEP_DONE, step="step1"))
    channel = await event_bus._get_channel(sid)  # noqa: SLF001 - white-box check

    # Assert
    assert len(channel.events) == 2
    assert channel.events[0][1].type == SearchEventType.STEP_START
    assert channel.events[1][1].type == SearchEventType.STEP_DONE


# ---------------------------------------------------------------------------
# Subscribe replay
# ---------------------------------------------------------------------------


async def test_subscribe_from_stream_start_replays_all(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, n=1))
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, n=2))
    await event_bus.publish(sid, _evt(SearchEventType.DONE))

    # Act
    collected = await _collect(event_bus, sid)

    # Assert
    assert len(collected) == 3
    assert [e.data.get("n") for _, e in collected[:2]] == [1, 2]
    assert collected[-1][1].type == SearchEventType.DONE


async def test_subscribe_from_last_id_returns_only_newer(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    first_id = await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, n=1))
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, n=2))
    await event_bus.publish(sid, _evt(SearchEventType.DONE))

    # Act — subscribe from after the first event
    collected = await _collect(event_bus, sid, last_id=first_id)

    # Assert — only events after ``first_id``
    assert len(collected) == 2
    assert collected[0][1].data == {"n": 2}
    assert collected[-1][1].type == SearchEventType.DONE


async def test_subscribe_stops_at_terminal_done(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS))
    await event_bus.publish(sid, _evt(SearchEventType.DONE))

    # Act — push more events after terminal; subscribers should still stop
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, after_done=True))
    collected = await _collect(event_bus, sid)

    # Assert — terminal stops the stream during replay
    types = [e.type for _, e in collected]
    assert SearchEventType.DONE in types
    # Anything after DONE in replay must not be yielded.
    done_index = types.index(SearchEventType.DONE)
    assert done_index == len(types) - 1


async def test_subscribe_stops_at_terminal_error(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    await event_bus.publish(sid, _evt(SearchEventType.ERROR, error="boom"))

    # Act
    collected = await _collect(event_bus, sid)

    # Assert
    assert len(collected) == 1
    assert collected[0][1].type == SearchEventType.ERROR


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------


async def test_multiple_subscribers_receive_all_events(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    results_a: List[Tuple[str, SearchEvent]] = []
    results_b: List[Tuple[str, SearchEvent]] = []

    async def consumer(store: List[Tuple[str, SearchEvent]]) -> None:
        async for entry_id, event in event_bus.subscribe(sid):
            store.append((entry_id, event))

    # Start subscribers before publishing so they receive live events.
    task_a = asyncio.create_task(consumer(results_a))
    task_b = asyncio.create_task(consumer(results_b))
    await asyncio.sleep(0.01)  # let subscribers register

    # Act
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS, n=1))
    await event_bus.publish(sid, _evt(SearchEventType.DONE))

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)

    # Assert — both subscribers saw both events
    assert [e.type for _, e in results_a] == [
        SearchEventType.PROGRESS,
        SearchEventType.DONE,
    ]
    assert [e.type for _, e in results_b] == [
        SearchEventType.PROGRESS,
        SearchEventType.DONE,
    ]


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_emitted_when_idle(
    event_bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — force a fast heartbeat
    from xhs_food.events import bus as bus_module

    monkeypatch.setattr(bus_module.settings, "sse_heartbeat_seconds", 0.1, raising=False)

    sid = "s1"

    async def runner() -> List[Tuple[str, SearchEvent]]:
        out: List[Tuple[str, SearchEvent]] = []
        async for entry_id, evt in event_bus.subscribe(sid):
            out.append((entry_id, evt))
            # First heartbeat is enough; publish DONE to terminate.
            if entry_id == "heartbeat":
                await event_bus.publish(sid, _evt(SearchEventType.DONE))
            if evt.type == SearchEventType.DONE:
                return out
        return out

    # Act
    collected = await asyncio.wait_for(runner(), timeout=2.0)

    # Assert
    heartbeat_ids = [eid for eid, _ in collected if eid == "heartbeat"]
    assert heartbeat_ids, "expected at least one heartbeat event"


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


async def test_reset_drops_channel(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    await event_bus.publish(sid, _evt(SearchEventType.PROGRESS))

    # Act
    await event_bus.reset(sid)

    # Assert — new channel starts fresh
    channel = await event_bus._get_channel(sid)  # noqa: SLF001
    assert channel.events == []
    assert channel._counter == 0  # noqa: SLF001
