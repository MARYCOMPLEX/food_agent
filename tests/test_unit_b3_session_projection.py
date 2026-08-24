"""B3 user-scoped Redis session projection and PostgreSQL read-through tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from xhs_food.composition.adapters import MemorySessionProjection
from xhs_food.contracts import (
    MemoryConversationTurn,
    MemorySessionWindowPort,
    UserIsolationKey,
)
from xhs_food.foundation import RedisHotStateContract, RedisUserSessionWindow


def _scope(user_id: str = "user-2b4aa1b95c884d64") -> UserIsolationKey:
    return UserIsolationKey(
        tenant_id="tenant-cn-1",
        user_id=user_id,
        session_id="session-1234567890",
    )


class _Redis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key: str, value: str) -> int:
        self.calls.append(("rpush", (key, value), {}))
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> object:
        self.calls.append(("ltrim", (key, start, end), {}))
        self.lists[key] = self.lists.get(key, [])[-20:]
        return True

    async def expire(self, key: str, ttl: int) -> object:
        self.calls.append(("expire", (key, ttl), {}))
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[object]:
        self.calls.append(("lrange", (key, start, end), {}))
        return self.lists.get(key, [])

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete", keys, {}))
        deleted = 0
        for key in keys:
            deleted += int(self.lists.pop(key, None) is not None)
        return deleted


class _Authority:
    def __init__(self, turns: tuple[MemoryConversationTurn, ...]) -> None:
        self.turns = turns
        self.calls: list[tuple[object, int]] = []

    async def list_conversation_turns(self, scope: object, *, limit: int) -> tuple[MemoryConversationTurn, ...]:
        self.calls.append((scope, limit))
        return self.turns[:limit]


def _turns(scope: UserIsolationKey) -> tuple[MemoryConversationTurn, ...]:
    return tuple(
        MemoryConversationTurn(
            turn_id=f"turn-{index}",
            scope=scope,
            role="user" if index % 2 else "assistant",
            content=f"message {index}",
            source_event_id=f"event-{index}",
            occurred_at=datetime(2026, 8, 24, index, tzinfo=UTC),
            idempotency_key=f"idempotency-{index}",
        )
        for index in range(2)
    )


@pytest.mark.unit
async def test_user_session_window_uses_scoped_key_and_fixed_limits() -> None:
    client = _Redis()
    window = RedisUserSessionWindow(client, RedisHotStateContract())
    scope = _scope()

    await window.append(scope, {"role": "user", "content": "hello"}, 86_400)
    key = next(item[1][0] for item in client.calls if item[0] == "rpush")
    assert key.startswith("session:tenant_id:tenant-cn-1:user_id:user-2b4aa1b95c884d64")
    assert ":session_id:session-1234567890:namespace:window" in key
    assert isinstance(window, MemorySessionWindowPort)
    with pytest.raises(ValueError, match="TTL"):
        await window.append(scope, {}, 60)
    with pytest.raises(ValueError, match="read exceeds"):
        await window.recent(scope, 21)


@pytest.mark.unit
async def test_projection_rebuilds_cache_miss_from_postgres_without_process_fallback() -> None:
    scope = _scope()
    client = _Redis()
    cache = RedisUserSessionWindow(client)
    authority = _Authority(_turns(scope))
    projection = MemorySessionProjection(cache, authority)

    rebuilt = await projection.recent(scope, 20)
    assert [item["turnId"] for item in rebuilt] == ["turn-0", "turn-1"]
    assert len(authority.calls) == 1
    assert len([item for item in client.calls if item[0] == "rpush"]) == 2

    cached = await projection.recent(scope, 20)
    assert cached == rebuilt
    assert len(authority.calls) == 1


@pytest.mark.unit
async def test_projection_does_not_hide_redis_failure_with_local_state() -> None:
    class FailingCache:
        async def append(self, scope: object, message: dict[str, object], ttl_seconds: int) -> None:
            raise ConnectionError("redis unavailable")

        async def recent(self, scope: object, limit: int) -> tuple[dict[str, object], ...]:
            raise ConnectionError("redis unavailable")

        async def clear(self, scope: object) -> bool:
            raise ConnectionError("redis unavailable")

    authority = _Authority(_turns(_scope()))
    projection = MemorySessionProjection(FailingCache(), authority)  # type: ignore[arg-type]
    with pytest.raises(ConnectionError, match="redis unavailable"):
        await projection.recent(_scope(), 20)
    assert authority.calls == []


@pytest.mark.unit
async def test_projection_surfaces_postgres_rebuild_failure() -> None:
    class FailingAuthority(_Authority):
        async def list_conversation_turns(
            self, scope: object, *, limit: int
        ) -> tuple[MemoryConversationTurn, ...]:
            del scope, limit
            raise ConnectionError("postgres unavailable")

    projection = MemorySessionProjection(
        RedisUserSessionWindow(_Redis()),
        FailingAuthority(()),
    )
    with pytest.raises(ConnectionError, match="postgres unavailable"):
        await projection.recent(_scope(), 20)
