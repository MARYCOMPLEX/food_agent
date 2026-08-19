"""Freeze legacy memory, Redis, PostgreSQL, and startup fallback semantics.

These are characterization tests for the pre-migration implementation. In
particular, process-local fallbacks intentionally do not claim the TTL or
multi-worker guarantees required by the target production architecture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from api.search import state as state_mod
from xhs_food.events import bus as bus_mod
from xhs_food.events.types import SearchEvent, SearchEventType
from xhs_food.services import postgres_storage as postgres_mod
from xhs_food.services import redis_memory as redis_memory_mod
from xhs_food.services.postgres_storage import ChatHistoryRecord, PostgresStorage
from xhs_food.services.redis_memory import RedisMemory
from xhs_food.services.session_manager import SessionManager


@dataclass
class _FixedClock:
    now: float = 1_700_000_000.0

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _clear_redis_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DATABASE",
        "REDIS_USERNAME",
        "REDIS_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


class _SyncRedisFixture:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.expirations: list[tuple[str, int]] = []
        self.trims: list[tuple[str, int, int]] = []

    def rpush(self, key: str, value: str) -> int:
        values = self.lists.setdefault(key, [])
        values.append(value)
        return len(values)

    def expire(self, key: str, ttl: int) -> bool:
        self.expirations.append((key, ttl))
        return True

    def ltrim(self, key: str, start: int, end: int) -> bool:
        self.trims.append((key, start, end))
        assert end == -1
        self.lists[key] = self.lists.get(key, [])[start:]
        return True

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        assert end == -1
        return self.lists.get(key, [])[start:]

    def delete(self, key: str) -> int:
        return int(self.lists.pop(key, None) is not None)

    def exists(self, key: str) -> int:
        return int(key in self.lists)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))


class _AsyncRedisStateFixture:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.set_calls.append((key, value, ex))

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class _AsyncRedisStreamFixture:
    def __init__(self) -> None:
        self.xadd_calls: list[dict[str, Any]] = []
        self.expirations: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.xadd_calls.append(
            {
                "key": key,
                "fields": fields,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )
        return "1700000000000-0"

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations.append((key, ttl))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


def test_redis_memory_uses_20_message_window_and_refreshes_24h_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FixedClock()
    monkeypatch.setattr(redis_memory_mod.time, "time", clock.time)
    _clear_redis_environment(monkeypatch)

    memory = RedisMemory()
    redis = _SyncRedisFixture()
    memory._redis = redis

    for index in range(21):
        memory.add_message("fixed-session", "user", f"message-{index}")

    key = "session:fixed-session:window"
    messages = memory.get_recent_messages("fixed-session")
    assert [message.content for message in messages] == [
        f"message-{index}" for index in range(1, 21)
    ]
    assert {message.timestamp for message in messages} == {clock.now}
    assert redis.expirations == [(key, RedisMemory.DEFAULT_TTL)] * 21
    assert redis.trims == [(key, -RedisMemory.DEFAULT_WINDOW_SIZE, -1)] * 21


def test_redis_memory_connection_failure_uses_process_local_window_without_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy fallback keeps the count window but does not expire by time."""
    clock = _FixedClock()
    monkeypatch.setattr(redis_memory_mod.time, "time", clock.time)
    monkeypatch.setattr(
        redis_memory_mod.redis,
        "from_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    _clear_redis_environment(monkeypatch)

    memory = RedisMemory(redis_url="redis://fixture:6379/0")
    for index in range(21):
        memory.add_message("legacy-fallback", "user", f"message-{index}")

    clock.advance(RedisMemory.DEFAULT_TTL + 1)
    messages = memory.get_recent_messages("legacy-fallback")
    assert memory._redis is None
    assert len(messages) == RedisMemory.DEFAULT_WINDOW_SIZE
    assert messages[0].content == "message-1"
    assert messages[-1].content == "message-20"


async def test_memory_and_redis_state_freeze_timestamp_key_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FixedClock()
    monkeypatch.setattr(state_mod.time, "time", clock.time)
    memory_store = state_mod._MemoryStateStore()
    monkeypatch.setattr(state_mod, "_state_store", memory_store)

    state = await state_mod.get_or_init_state("state-session", status="loading")
    assert state == {
        "id": "state-session",
        "status": "loading",
        "query": "",
        "turn_id": 0,
        "summary": "",
        "filtered_count": 0,
        "error": None,
        "restaurants": [],
        "created_at": clock.now,
        "updated_at": clock.now,
    }

    clock.advance(state_mod._STATE_TTL_SECONDS + 1)
    assert await state_mod.load_state("state-session") == state
    updated = await state_mod.update_state("state-session", query="重庆火锅", turn_id=1)
    assert updated["created_at"] == 1_700_000_000.0
    assert updated["updated_at"] == clock.now

    redis = _AsyncRedisStateFixture()
    redis_store = state_mod._RedisStateStore(redis)
    await redis_store.set("state-session", updated)

    key, payload, ttl = redis.set_calls[-1]
    assert key == "task:state-session:state"
    assert ttl == state_mod._STATE_TTL_SECONDS == 3600
    assert "重庆火锅" in payload
    assert "\\u91cd" not in payload
    assert await redis_store.get("state-session") == updated


async def test_redis_event_bus_uses_fixed_event_time_one_hour_ttl_and_maxlen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FixedClock()
    monkeypatch.setattr(bus_mod.settings, "event_stream_ttl_seconds", 3600)
    monkeypatch.setattr(bus_mod.settings, "event_stream_maxlen", 1000)
    redis = _AsyncRedisStreamFixture()
    bus = bus_mod.RedisStreamEventBus(redis)

    entry_id = await bus.publish(
        "event-session",
        SearchEvent(
            SearchEventType.PROGRESS,
            {"message": "检索中"},
            timestamp=clock.now,
        ),
    )
    await bus.reset("event-session")

    assert entry_id == "1700000000000-0"
    assert redis.xadd_calls == [
        {
            "key": "stream:event-session:events",
            "fields": {
                "payload": json.dumps(
                    {
                        "type": "progress",
                        "data": {"message": "检索中"},
                        "timestamp": clock.now,
                    },
                    ensure_ascii=False,
                ),
                "type": "progress",
            },
            "maxlen": 1000,
            "approximate": True,
        }
    ]
    assert redis.expirations == [("stream:event-session:events", 3600)]
    assert redis.deleted == ["stream:event-session:events"]


async def test_session_cache_miss_warms_memory_once_from_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FixedClock()
    monkeypatch.setattr(redis_memory_mod.time, "time", clock.time)
    _clear_redis_environment(monkeypatch)
    memory = RedisMemory(window_size=4)

    class _PostgresHistoryFixture:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def get_session_history(
            self, session_id: str, *, limit: int
        ) -> list[ChatHistoryRecord]:
            self.calls.append((session_id, limit))
            return [
                ChatHistoryRecord(role="user", content="想吃火锅", metadata={"turn": 1}),
                ChatHistoryRecord(
                    role="assistant", content="推荐重庆火锅", metadata={"turn": 1}
                ),
            ]

    postgres = _PostgresHistoryFixture()
    manager = object.__new__(SessionManager)
    manager._redis = memory
    manager._postgres = postgres
    manager._context_window = 2
    manager._pending_saves = []
    manager._initialized = True

    first = await manager.get_context("warm-session")
    second = await manager.get_context("warm-session")

    assert first == second == [
        {"role": "user", "content": "想吃火锅"},
        {"role": "assistant", "content": "推荐重庆火锅"},
    ]
    assert postgres.calls == [("warm-session", 2)]
    assert {message.timestamp for message in memory.get_recent_messages("warm-session")} == {
        clock.now
    }


async def test_postgres_absence_disables_storage_but_session_manager_still_initializes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    storage = PostgresStorage()
    assert await storage.initialize() is False
    assert storage._initialized is False
    assert storage._pool is None

    class _UnavailablePostgres:
        async def initialize(self) -> bool:
            return False

    manager = object.__new__(SessionManager)
    manager._postgres = _UnavailablePostgres()
    manager._initialized = False

    assert await manager.initialize() is True
    assert manager._initialized is True


async def test_pgvector_failure_keeps_postgres_enabled_and_skips_embedding_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmbeddingMustNotRun:
        async def embed(self, _text: str) -> list[float]:
            raise AssertionError("pgvector-disabled writes must skip embedding generation")

    class _Connection:
        def __init__(self) -> None:
            self.executed: list[str] = []
            self.insert_sql: str | None = None

        async def execute(self, sql: str) -> str:
            self.executed.append(sql)
            if sql == postgres_mod.ENABLE_PGVECTOR_SQL:
                raise RuntimeError("vector extension unavailable")
            return "OK"

        async def fetchval(self, sql: str, *_args: Any) -> int:
            self.insert_sql = sql
            return 41

    class _Acquire:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> _Connection:
            return self.connection

        async def __aexit__(self, *_args: Any) -> None:
            return None

    class _Pool:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        def acquire(self) -> _Acquire:
            return _Acquire(self.connection)

    connection = _Connection()
    pool = _Pool(connection)

    async def _create_pool(*_args: Any, **_kwargs: Any) -> _Pool:
        return pool

    monkeypatch.setattr(postgres_mod.asyncpg, "create_pool", _create_pool)
    storage = PostgresStorage(
        database_url="postgresql://fixture/db",
        embedding_service=_EmbeddingMustNotRun(),
    )

    assert await storage.initialize() is True
    assert storage._initialized is True
    assert storage._pgvector_available is False
    record_id = await storage.save_message(
        session_id="00000000-0000-0000-0000-000000000001",
        role="user",
        content="long enough to normally generate an embedding",
    )
    assert record_id == 41
    assert connection.insert_sql is not None
    assert "embedding" not in connection.insert_sql
    assert postgres_mod.ADD_EMBEDDING_COLUMN_SQL not in connection.executed


async def test_redis_startup_failures_fall_back_to_process_local_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from redis import asyncio as aioredis

    class _UnavailableRedis:
        async def ping(self) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(
        aioredis,
        "from_url",
        lambda *_args, **_kwargs: _UnavailableRedis(),
    )
    monkeypatch.setattr(bus_mod.settings, "event_bus_backend", "redis")
    monkeypatch.setattr(
        type(bus_mod.settings),
        "resolved_redis_url",
        lambda _self: "redis://fixture:6379/0",
    )

    async def _event_bus_create_failure(_cls: type, _url: str | None = None) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        bus_mod.RedisStreamEventBus,
        "create",
        classmethod(_event_bus_create_failure),
    )
    monkeypatch.setattr(bus_mod, "_bus", None)

    state_store = await state_mod._build_store()
    event_bus = await bus_mod.get_event_bus()

    assert isinstance(state_store, state_mod._MemoryStateStore)
    assert isinstance(event_bus, bus_mod.InMemoryEventBus)


async def test_application_lifespan_continues_with_legacy_degraded_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api import main as main_mod
    from xhs_food import services as services_mod
    from xhs_food.services import user_storage as user_storage_mod

    calls: list[str] = []

    class _DisabledStorage:
        _initialized = False

        async def close(self) -> None:
            calls.append("storage.close")

    class _LegacySessionManager:
        _initialized = True

        async def close(self) -> None:
            calls.append("session.close")

    storage = _DisabledStorage()
    session_manager = _LegacySessionManager()

    async def _get_storage() -> _DisabledStorage:
        calls.append("storage.get")
        return storage

    async def _get_session_manager() -> _LegacySessionManager:
        calls.append("session.get")
        return session_manager

    async def _get_event_bus() -> bus_mod.InMemoryEventBus:
        calls.append("event_bus.get")
        return bus_mod.InMemoryEventBus()

    async def _shutdown_event_bus() -> None:
        calls.append("event_bus.shutdown")

    monkeypatch.setattr(user_storage_mod, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(services_mod, "get_session_manager", _get_session_manager)
    monkeypatch.setattr(bus_mod, "get_event_bus", _get_event_bus)
    monkeypatch.setattr(bus_mod, "shutdown_event_bus", _shutdown_event_bus)

    async with main_mod.lifespan(main_mod.app):
        assert calls == ["storage.get", "session.get", "event_bus.get"]

    assert calls == [
        "storage.get",
        "session.get",
        "event_bus.get",
        "session.close",
        "event_bus.shutdown",
    ]
