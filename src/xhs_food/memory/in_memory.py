"""Deterministic memory provider for tests and local development."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

from xhs_food.runtime.models import AgentRunContext, AgentRunResult

from .models import MemoryQuery, MemoryRecord, MemoryScope


class InMemoryMemoryProvider:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, record: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            self._records[record.id] = record
        return record

    async def search(self, query: MemoryQuery) -> Sequence[MemoryRecord]:
        query_tokens = self._tokens(query.query)
        now_records = [record for record in self._records.values() if not record.is_expired()]
        matches = []
        for record in now_records:
            if query.namespace and record.namespace != query.namespace:
                continue
            if query.scope and record.scope != query.scope:
                continue
            if any(record.metadata.get(key) != value for key, value in query.metadata.items()):
                continue
            text = self._stringify(record.content).lower()
            tokens = self._tokens(text)
            overlap = len(query_tokens & tokens)
            phrase_bonus = 1.0 if query.query.lower() in text else 0.0
            if query_tokens and overlap == 0 and phrase_bonus == 0:
                continue
            copy = record.model_copy(update={"score": overlap + phrase_bonus})
            matches.append(copy)
        matches.sort(key=lambda item: (item.score or 0, item.created_at), reverse=True)
        return matches[: query.limit]

    async def delete(self, record_id: str, namespace: str | None = None) -> bool:
        async with self._lock:
            record = self._records.get(record_id)
            if record is None or (namespace is not None and record.namespace != namespace):
                return False
            del self._records[record_id]
            return True

    async def commit_turn(self, context: AgentRunContext, result: AgentRunResult) -> None:
        await self.put(
            MemoryRecord(
                namespace=context.session_id,
                scope=MemoryScope.EPISODIC,
                content={
                    "role": "user",
                    "content": context.user_input,
                    "run_id": context.run_id,
                    "turn_id": context.turn_id,
                },
                metadata={"run_id": context.run_id, "turn_id": context.turn_id},
            )
        )
        if result.answer is not None:
            await self.put(
                MemoryRecord(
                    namespace=context.session_id,
                    scope=MemoryScope.EPISODIC,
                    content={
                        "role": "assistant",
                        "content": result.answer,
                        "run_id": context.run_id,
                        "turn_id": context.turn_id,
                    },
                    metadata={"run_id": context.run_id, "turn_id": context.turn_id},
                )
            )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        # Keep Chinese text as individual characters while treating Latin
        # words as units.  This is deliberately a fallback, not vector search.
        return {token for token in re.findall(r"[\u4e00-\u9fff]|[a-z0-9_]+", value.lower()) if token}

    @staticmethod
    def _stringify(value: object) -> str:
        if isinstance(value, str):
            return value
        return repr(value)
