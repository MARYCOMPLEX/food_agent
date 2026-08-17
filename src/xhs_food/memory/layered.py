"""Layer routing and optional third-party semantic memory integration."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any

from xhs_food.runtime.models import AgentRunContext, AgentRunResult

from .in_memory import InMemoryMemoryProvider
from .models import MemoryQuery, MemoryRecord, MemoryScope
from .provider import MemoryProvider


class ThirdPartyMemoryAdapter:
    """Adapter for Mem0, Zep or another semantic SDK.

    The wrapped SDK is intentionally not imported by this project.  It only
    needs ``add`` and ``search`` methods; PostgreSQL/InMemory remains the
    authoritative record store in :class:`LayeredMemoryProvider`.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        add = self._backend.add
        value = add(record.content, user_id=record.namespace, metadata=record.metadata)
        if inspect.isawaitable(value):
            await value
        return record

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        search = self._backend.search
        value = search(query.query, user_id=query.namespace, limit=query.limit)
        if inspect.isawaitable(value):
            value = await value
        return [self._coerce(item, query) for item in (value or [])]

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        delete = getattr(self._backend, "delete", None)
        if delete is None:
            return False
        value = delete(record_id)
        if inspect.isawaitable(value):
            value = await value
        return bool(value if value is not None else True)

    async def commit_turn(self, context: AgentRunContext, result: AgentRunResult) -> None:
        return None

    @staticmethod
    def _coerce(value: Any, query: MemoryQuery) -> MemoryRecord:
        if isinstance(value, MemoryRecord):
            return value
        if isinstance(value, dict):
            content = value.get("memory", value.get("text", value.get("content", value)))
            metadata = value.get("metadata", {})
            score = value.get("score", value.get("similarity"))
        else:
            content = value
            metadata = {}
            score = None
        return MemoryRecord(
            namespace=query.namespace or "semantic",
            scope=MemoryScope.SEMANTIC,
            content=content,
            metadata=metadata,
            score=score,
        )


class LayeredMemoryProvider:
    """Route working, durable, semantic and procedural memories explicitly."""

    def __init__(
        self,
        *,
        working: MemoryProvider | None = None,
        episodic: MemoryProvider | None = None,
        semantic: MemoryProvider | None = None,
        procedural: MemoryProvider | None = None,
        semantic_adapter: ThirdPartyMemoryAdapter | None = None,
    ) -> None:
        fallback = InMemoryMemoryProvider()
        self._providers: dict[MemoryScope, MemoryProvider] = {
            MemoryScope.WORKING: working or fallback,
            MemoryScope.EPISODIC: episodic or fallback,
            MemoryScope.SEMANTIC: semantic or fallback,
            MemoryScope.PROCEDURAL: procedural or fallback,
        }
        self._semantic_adapter = semantic_adapter

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        saved = await self._providers[record.scope].put(record)
        if record.scope == MemoryScope.SEMANTIC and self._semantic_adapter is not None:
            await self._semantic_adapter.put(record)
        return saved

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        if query.scope is not None:
            records = list(await self._providers[query.scope].search(query))
        else:
            records = []
            for provider in set(self._providers.values()):
                records.extend(await provider.search(query))
            if self._semantic_adapter is not None:
                records.extend(await self._semantic_adapter.search(query))
        records.sort(key=lambda item: (item.score or 0, item.created_at), reverse=True)
        return records[: query.limit]

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        deleted = False
        for provider in set(self._providers.values()):
            deleted = await provider.delete(record_id, namespace) or deleted
        return deleted

    async def commit_turn(self, context: AgentRunContext, result: AgentRunResult) -> None:
        # Commit durable conversation facts through the episodic provider only.
        provider = self._providers[MemoryScope.EPISODIC]
        await provider.commit_turn(context, result)

    async def recall(self, query: str, session_id: str, limit: int = 8) -> list[MemoryRecord]:
        records = await self.search(
            MemoryQuery(query=query, namespace=session_id, limit=limit)
        )
        return list(records)
