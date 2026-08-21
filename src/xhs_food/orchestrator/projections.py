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

    async def put(self, projection: TaskProgressProjection) -> TaskProgressProjection:
        if projection.executable_checkpoint:
            raise ValueError("task progress projections cannot be execution checkpoints")
        async with self._lock:
            current = self._values.get(projection.task_id)
            if current is not None and projection.updated_at < current.updated_at:
                raise ValueError("task progress projections cannot move backwards in time")
            self._values[projection.task_id] = projection
            return projection

    async def delete(self, task_id: str) -> bool:
        async with self._lock:
            return self._values.pop(task_id, None) is not None


__all__ = ["InMemoryTaskProgressProjectionStore"]
