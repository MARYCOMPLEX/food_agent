"""Bridge the existing SessionManager to the MemoryProvider contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from xhs_food.runtime.models import AgentRunContext, AgentRunResult

from .models import MemoryQuery, MemoryRecord, MemoryScope


class SessionManagerMemoryProvider:
    """Use SessionManager for durable messages without exposing its internals."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        role = record.metadata.get("role")
        if role == "user":
            await self._manager.add_user_message(record.namespace, str(record.content))
        elif role == "assistant":
            await self._manager.add_assistant_message(record.namespace, str(record.content))
        return record

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        if hasattr(self._manager, "search_similar_context"):
            rows = await self._manager.search_similar_context(
                query.query,
                session_id=query.namespace,
                limit=query.limit,
            )
            return [
                MemoryRecord(
                    namespace=query.namespace or "global",
                    scope=MemoryScope.EPISODIC,
                    content=row,
                    metadata={"source": "session_manager"},
                    score=row.get("similarity") if isinstance(row, dict) else None,
                )
                for row in rows
            ]
        return []

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        return False

    async def commit_turn(self, context: AgentRunContext, result: AgentRunResult) -> None:
        await self.put(
            MemoryRecord(
                namespace=context.session_id,
                scope=MemoryScope.EPISODIC,
                content=context.user_input,
                metadata={"role": "user", "run_id": context.run_id},
            )
        )
        if result.answer is not None:
            await self.put(
                MemoryRecord(
                    namespace=context.session_id,
                    scope=MemoryScope.EPISODIC,
                    content=result.answer,
                    metadata={"role": "assistant", "run_id": context.run_id},
                )
            )


class LazySessionManagerMemoryProvider:
    """Resolve the application SessionManager only when memory is accessed.

    API routes already own durable message writes.  ``read_only=True`` lets the
    Agent Loop retrieve PostgreSQL/pgvector context without duplicating those
    writes when it commits a turn.
    """

    def __init__(self, *, read_only: bool = True) -> None:
        self._read_only = read_only

    @staticmethod
    async def _get_manager() -> Any:
        from xhs_food.services import get_session_manager

        return await get_session_manager()

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        if self._read_only:
            return record
        manager = await self._get_manager()
        return await SessionManagerMemoryProvider(manager).put(record)

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        manager = await self._get_manager()
        return await SessionManagerMemoryProvider(manager).search(query)

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        if self._read_only or namespace is None:
            return False
        manager = await self._get_manager()
        await manager.clear_session(namespace)
        return True

    async def commit_turn(
        self,
        context: AgentRunContext,
        result: AgentRunResult,
    ) -> None:
        if self._read_only:
            return
        manager = await self._get_manager()
        await SessionManagerMemoryProvider(manager).commit_turn(context, result)
