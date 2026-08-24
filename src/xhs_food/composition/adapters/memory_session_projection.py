"""User-scoped Redis session projection with PostgreSQL read-through."""

from __future__ import annotations

from xhs_food.contracts import (
    ContractPayload,
    MemoryIsolationKey,
    MemoryRepositoryPort,
    MemorySessionWindowPort,
)

SESSION_WINDOW_SIZE = 20
SESSION_WINDOW_TTL_SECONDS = 86_400


class MemorySessionProjection(MemorySessionWindowPort):
    """Rebuild Redis hot state from PostgreSQL on cache miss or expiry.

    The adapter intentionally has no process-local fallback. A Redis failure
    is observable to the caller, while a miss is rebuilt from the authority.
    """

    def __init__(
        self,
        cache: MemorySessionWindowPort,
        authority: MemoryRepositoryPort,
        *,
        ttl_seconds: int = SESSION_WINDOW_TTL_SECONDS,
        window_size: int = SESSION_WINDOW_SIZE,
    ) -> None:
        if ttl_seconds != SESSION_WINDOW_TTL_SECONDS:
            raise ValueError("memory session projection TTL must be 24 hours")
        if window_size != SESSION_WINDOW_SIZE:
            raise ValueError("memory session projection window must contain 20 turns")
        self._cache = cache
        self._authority = authority
        self._ttl_seconds = ttl_seconds
        self._window_size = window_size

    async def append(
        self,
        scope: MemoryIsolationKey,
        message: ContractPayload,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds != self._ttl_seconds:
            raise ValueError("memory session projection TTL must be 24 hours")
        await self._cache.append(scope, message, ttl_seconds)

    async def recent(
        self,
        scope: MemoryIsolationKey,
        limit: int,
    ) -> tuple[ContractPayload, ...]:
        if not 1 <= limit <= self._window_size:
            raise ValueError("memory session projection read exceeds 20 turns")
        cached = await self._cache.recent(scope, self._window_size)
        if cached:
            return cached[-limit:]

        turns = await self._authority.list_conversation_turns(scope, limit=self._window_size)
        rebuilt = tuple(turn.model_dump(mode="json", by_alias=True) for turn in turns)
        for message in rebuilt:
            await self._cache.append(scope, message, self._ttl_seconds)
        return rebuilt[-limit:]

    async def clear(self, scope: MemoryIsolationKey) -> bool:
        return await self._cache.clear(scope)


__all__ = ["MemorySessionProjection", "SESSION_WINDOW_SIZE", "SESSION_WINDOW_TTL_SECONDS"]
