"""Memory provider protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from xhs_food.runtime.models import AgentRunContext, AgentRunResult

from .models import MemoryQuery, MemoryRecord


class MemoryProvider(Protocol):
    async def put(self, record: MemoryRecord) -> MemoryRecord:
        ...

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        ...

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        ...

    async def commit_turn(
        self,
        context: AgentRunContext,
        result: AgentRunResult,
    ) -> None:
        ...
