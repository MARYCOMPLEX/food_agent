"""Unit tests for :class:`xhs_food.events.emitter.SearchEventEmitter`."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from xhs_food.events.bus import InMemoryEventBus
from xhs_food.events.emitter import SearchEventEmitter
from xhs_food.events.types import SearchEvent, SearchEventType


# ---------------------------------------------------------------------------
# init_steps
# ---------------------------------------------------------------------------


async def test_init_steps_creates_six_pending_steps(event_bus: InMemoryEventBus) -> None:
    # Arrange
    emitter = SearchEventEmitter("s1", event_bus)

    # Act
    emitter.init_steps("成都火锅")

    # Assert
    assert len(emitter.steps) == 6
    for idx, step in enumerate(emitter.steps, start=1):
        assert step["id"] == f"step{idx}"
        assert step["status"] == "pending"
        assert step["label"]  # non-empty label


# ---------------------------------------------------------------------------
# step_start
# ---------------------------------------------------------------------------


async def _drain_recent(
    bus: InMemoryEventBus, sid: str
) -> List[Tuple[str, SearchEvent]]:
    """Return a snapshot of currently buffered events for ``sid``."""
    channel = await bus._get_channel(sid)  # noqa: SLF001 - white-box for asserts
    return list(channel.events)


async def test_step_start_emits_event_and_marks_loading(
    event_bus: InMemoryEventBus,
) -> None:
    # Arrange
    sid = "s1"
    emitter = SearchEventEmitter(sid, event_bus)
    emitter.init_steps("q")

    # Act
    await emitter.step_start("step1", "解析意图中")

    # Assert — status updated and event published
    step1 = next(s for s in emitter.steps if s["id"] == "step1")
    assert step1["status"] == "loading"
    assert step1["label"] == "解析意图中"

    events = await _drain_recent(event_bus, sid)
    assert len(events) == 1
    _, evt = events[0]
    assert evt.type == SearchEventType.STEP_START
    assert evt.data["step"] == "step1"


# ---------------------------------------------------------------------------
# step_done
# ---------------------------------------------------------------------------


async def test_step_done_increments_progress(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    emitter = SearchEventEmitter(sid, event_bus)
    emitter.init_steps("q")

    # Act — finish two of six steps
    await emitter.step_done("step1", "意图已解析")
    await emitter.step_done("step2", "笔记搜索完成")

    # Assert — progress = 2/6 ≈ 33%
    step1 = next(s for s in emitter.steps if s["id"] == "step1")
    step2 = next(s for s in emitter.steps if s["id"] == "step2")
    assert step1["status"] == "done"
    assert step2["status"] == "done"

    events = await _drain_recent(event_bus, sid)
    assert len(events) == 2
    assert all(e.type == SearchEventType.STEP_DONE for _, e in events)
    # Last emit should report progress ~ 33
    assert events[-1][1].data["progress"] == int(2 / 6 * 100)


async def test_step_done_includes_extra_payload(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    emitter = SearchEventEmitter(sid, event_bus)
    emitter.init_steps("q")

    # Act
    await emitter.step_done("step1", "done", extra={"count": 7})

    # Assert
    events = await _drain_recent(event_bus, sid)
    assert events[-1][1].data["count"] == 7


# ---------------------------------------------------------------------------
# emit_done
# ---------------------------------------------------------------------------


async def test_emit_done_marks_completed(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    emitter = SearchEventEmitter(sid, event_bus)

    # Act
    await emitter.emit_done()

    # Assert
    assert emitter.is_completed is True
    events = await _drain_recent(event_bus, sid)
    assert events[-1][1].type == SearchEventType.DONE


# ---------------------------------------------------------------------------
# step_error
# ---------------------------------------------------------------------------


async def test_step_error_marks_step_error(event_bus: InMemoryEventBus) -> None:
    # Arrange
    sid = "s1"
    emitter = SearchEventEmitter(sid, event_bus)
    emitter.init_steps("q")

    # Act
    await emitter.step_error("step3", "搜索失败")

    # Assert
    step3 = next(s for s in emitter.steps if s["id"] == "step3")
    assert step3["status"] == "error"
    events = await _drain_recent(event_bus, sid)
    assert events[-1][1].type == SearchEventType.STEP_ERROR
    assert events[-1][1].data["error"] == "搜索失败"


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


async def test_reset_clears_steps_and_completion_flag(
    event_bus: InMemoryEventBus,
) -> None:
    # Arrange
    emitter = SearchEventEmitter("s1", event_bus)
    emitter.init_steps("q")
    await emitter.emit_done()

    # Act
    emitter.reset()

    # Assert
    assert emitter.steps == []
    assert emitter.is_completed is False
