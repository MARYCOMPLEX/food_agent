"""Query-only task projections owned by the Research Coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import MappingProxyType

from xhs_food.contracts import TaskProgressProjection


class InMemoryTaskProgressProjectionStore:
    """Single-process S5 fixture for business query projections.

    This store deliberately has no replay or resume operation. B0 supplies the
    durable workflow history; values here only support status and recover views.
    """

    def __init__(self) -> None:
        self._values: dict[str, TaskProgressProjection] = {}
        self._lock = asyncio.Lock()

    @property
    def values(self) -> Mapping[str, TaskProgressProjection]:
        return MappingProxyType(self._values)

    async def get(self, task_id: str) -> TaskProgressProjection | None:
        async with self._lock:
            return self._values.get(task_id)

    async def get_by_session_id(self, session_id: str) -> TaskProgressProjection | None:
        async with self._lock:
            candidates = tuple(
                projection
                for projection in self._values.values()
                if projection.session_id == session_id
            )
            if not candidates:
                return None
            return max(candidates, key=lambda projection: projection.updated_at)

    async def put(self, projection: TaskProgressProjection) -> TaskProgressProjection:
        if projection.executable_checkpoint:
            raise ValueError("task progress projections cannot be execution checkpoints")
        async with self._lock:
            current = self._values.get(projection.task_id)
            if current is not None:
                turn_order = _compare_turn_ids(current.turn_id, projection.turn_id)
                if turn_order < 0:
                    return current
                if turn_order > 0:
                    # A newer refine turn is a new logical execution for the
                    # same task identity and may restart from ``running``.
                    self._values[projection.task_id] = projection
                    return projection
                if projection.updated_at < current.updated_at:
                    raise ValueError("task progress projections cannot move backwards in time")
                # A terminal projection is immutable. For non-terminal values,
                # reject same-state progress/completion regressions while still
                # allowing a legitimate transition to a terminal failure.
                if current.status.is_terminal:
                    return current
                if _status_rank(projection.status) < _status_rank(current.status):
                    return current
                if projection.status is current.status and projection.progress < current.progress:
                    return current
                if projection.status is current.status and not set(
                    current.completed_step_ids
                ).issubset(projection.completed_step_ids):
                    return current
            self._values[projection.task_id] = projection
            return projection

    async def delete(self, task_id: str) -> bool:
        async with self._lock:
            return self._values.pop(task_id, None) is not None


def _status_rank(status: object) -> int:
    value = getattr(status, "value", status)
    return {
        "created": 0,
        "planning": 1,
        "running": 2,
        "completed": 3,
        "failed": 3,
        "cancelled": 3,
    }.get(str(value), -1)


def _compare_turn_ids(current: str | None, candidate: str | None) -> int:
    """Return ``-1/0/1`` for an ordered turn transition when available."""

    if current == candidate:
        return 0
    if current is None:
        return 1 if candidate is not None else 0
    if candidate is None:
        return -1
    try:
        current_number = int(current)
        candidate_number = int(candidate)
    except (TypeError, ValueError):
        # Opaque IDs cannot establish ordering; a changed value is not safe to
        # treat as a newer turn because an old event could then overwrite it.
        return 0
    return (candidate_number > current_number) - (candidate_number < current_number)


__all__ = ["InMemoryTaskProgressProjectionStore"]
