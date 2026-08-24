"""Offline contracts for rebuildable target Redis state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from redis import exceptions as redis_errors

from xhs_food.contracts import ErrorCategory, ErrorScope, EventEnvelope
from xhs_food.events import bus as event_bus_module
from xhs_food.events.bus import EventBusDependencyError
from xhs_food.foundation import (
    FoundationAdapterError,
    RateLimitDecision,
    RedisEventBusAdapter,
    RedisFixedWindowRateLimiter,
    RedisHotStateContract,
    RedisIdempotencyWindow,
    RedisReplayExpiredError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.now = 0
        self.values: dict[str, str] = {}
        self.expires_at: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def advance(self, seconds: int) -> None:
        self.now += seconds

    def _expire(self, key: str) -> None:
        deadline = self.expires_at.get(key)
        if deadline is not None and deadline <= self.now:
            self.values.pop(key, None)
            self.expires_at.pop(key, None)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> object:
        self.calls.append(("set", (key, value), {"ex": ex, "nx": nx}))
        self._expire(key)
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expires_at[key] = self.now + ex
        return True

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object:
        self.calls.append(("eval", (script, numkeys, *keys_and_args), {}))
        assert numkeys == 1
        key = str(keys_and_args[0])
        window_seconds = int(keys_and_args[1])
        limit = int(keys_and_args[2])
        self._expire(key)
        count = int(self.values.get(key, "0")) + 1
        self.values[key] = str(count)
        if count == 1 or key not in self.expires_at:
            self.expires_at[key] = self.now + window_seconds
        allowed = count <= limit
        return [
            int(allowed),
            max(limit - count, 0),
            0 if allowed else self.expires_at[key] - self.now,
        ]

    async def get(self, key: str) -> object:
        raise NotImplementedError

    async def delete(self, *keys: str) -> int:
        raise NotImplementedError

    async def rpush(self, key: str, value: str) -> int:
        raise NotImplementedError

    async def ltrim(self, key: str, start: int, end: int) -> object:
        raise NotImplementedError

    async def lrange(self, key: str, start: int, end: int) -> list[object]:
        raise NotImplementedError

    async def expire(self, key: str, ttl: int) -> object:
        raise NotImplementedError

    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        raise NotImplementedError

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[object]:
        raise NotImplementedError


@pytest.mark.unit
async def test_idempotency_claim_is_atomic_and_expires() -> None:
    client = FakeRedis()
    contract = RedisHotStateContract(idempotency_ttl_seconds=5)
    claims = RedisIdempotencyWindow(client, contract)

    assert await claims.claim("request-1", 5) is True
    assert await claims.claim("request-1", 5) is False
    client.advance(5)
    assert await claims.claim("request-1", 5) is True

    assert client.calls == [
        ("set", ("idempotency:request-1", "1"), {"ex": 5, "nx": True}),
        ("set", ("idempotency:request-1", "1"), {"ex": 5, "nx": True}),
        ("set", ("idempotency:request-1", "1"), {"ex": 5, "nx": True}),
    ]
    public = {
        name
        for name in dir(RedisIdempotencyWindow)
        if not name.startswith("_") and callable(getattr(RedisIdempotencyWindow, name))
    }
    assert public == {"claim"}


@pytest.mark.unit
async def test_fixed_window_rate_limit_allows_rejects_and_resets() -> None:
    client = FakeRedis()
    contract = RedisHotStateContract(rate_limit_window_seconds=10)
    limiter = RedisFixedWindowRateLimiter(client, contract)

    assert await limiter.consume("provider-1", limit=2, window_seconds=10) == RateLimitDecision(
        allowed=True,
        remaining=1,
        retry_after_seconds=0,
    )
    assert await limiter.consume("provider-1", limit=2, window_seconds=10) == RateLimitDecision(
        allowed=True,
        remaining=0,
        retry_after_seconds=0,
    )
    assert await limiter.consume("provider-1", limit=2, window_seconds=10) == RateLimitDecision(
        allowed=False,
        remaining=0,
        retry_after_seconds=10,
    )

    client.advance(10)
    assert await limiter.consume("provider-1", limit=2, window_seconds=10) == RateLimitDecision(
        allowed=True,
        remaining=1,
        retry_after_seconds=0,
    )
    eval_calls = [call for call in client.calls if call[0] == "eval"]
    assert all(call[1][1:] == (1, "rate_limit:provider-1", 10, 2) for call in eval_calls)


@pytest.mark.unit
async def test_redis_contract_rejects_unbounded_windows() -> None:
    client = FakeRedis()
    contract = RedisHotStateContract(
        idempotency_ttl_seconds=5,
        rate_limit_window_seconds=10,
    )

    with pytest.raises(ValueError, match="idempotency TTL"):
        await RedisIdempotencyWindow(client, contract).claim("request-1", 6)
    with pytest.raises(ValueError, match="rate-limit window"):
        await RedisFixedWindowRateLimiter(client, contract).consume(
            "provider-1",
            limit=2,
            window_seconds=11,
        )


class FailingRedis(FakeRedis):
    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object:
        del script, numkeys, keys_and_args
        raise redis_errors.ConnectionError("fixture unavailable")

    async def ping(self) -> object:
        raise redis_errors.ConnectionError("fixture unavailable")


@pytest.mark.unit
async def test_rate_limit_dependency_failure_propagates_as_stable_contract_error() -> None:
    limiter = RedisFixedWindowRateLimiter(FailingRedis())

    with pytest.raises(FoundationAdapterError) as caught:
        await limiter.consume("provider-1", limit=2, window_seconds=60)

    assert caught.value.error.scope is ErrorScope.CACHE
    assert caught.value.error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert caught.value.error.boundary_ref == "cache.rate_limit.consume"
    assert isinstance(caught.value.__cause__, redis_errors.ConnectionError)


@pytest.mark.unit
async def test_event_bus_health_dependency_failure_is_stable() -> None:
    with pytest.raises(FoundationAdapterError) as caught:
        await RedisEventBusAdapter(FailingRedis()).ensure_available()

    assert caught.value.error.scope is ErrorScope.EVENT_BUS
    assert caught.value.error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert caught.value.error.boundary_ref == "event_bus.health"


class BytesEventRedis(FakeRedis):
    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> object:
        del key, fields, maxlen, approximate
        return b"1-0"

    async def expire(self, key: str, ttl: int) -> object:
        del key, ttl
        return True


@pytest.mark.unit
async def test_event_publish_normalizes_bytes_entry_id() -> None:
    events = RedisEventBusAdapter(BytesEventRedis())

    entry_id = await events.publish(
        EventEnvelope(
            event_id="event-1",
            topic="search",
            payload={"status": "running"},
            published_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert entry_id == "1-0"
    assert isinstance(entry_id, str)


class ReplayEventRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str, dict[str, str]]] = []

    async def xrange(
        self,
        key: str,
        min: str = "-",
        max: str = "+",
        count: int | None = None,
    ) -> list[object]:
        del key, max
        minimum = (0, 0) if min == "-" else tuple(int(part) for part in min.split("-"))
        values = [
            item
            for item in self.entries
            if tuple(int(part) for part in item[0].split("-")) >= minimum
        ]
        if count is not None:
            values = values[:count]
        return list(values)

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[object]:
        del count, block
        key, cursor = next(iter(streams.items()))
        entries = [
            item
            for item in self.entries
            if tuple(int(part) for part in item[0].split("-"))
            > tuple(int(part) for part in cursor.split("-"))
        ]
        return [(key, entries)] if entries else []


@pytest.mark.unit
async def test_sse_cursor_inside_window_replays_exclusively() -> None:
    client = ReplayEventRedis()
    first = EventEnvelope(
        event_id="event-1",
        topic="search",
        payload={"status": "running"},
        published_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    second = first.model_copy(update={"event_id": "event-2", "payload": {"status": "done"}})
    client.entries = [
        ("10-0", {"payload": first.model_dump_json()}),
        ("11-0", {"payload": second.model_dump_json()}),
    ]

    iterator = RedisEventBusAdapter(client).subscribe("search", after="10-0")
    event = await anext(iterator)
    assert event.event_id == "event-2"
    await iterator.aclose()


@pytest.mark.unit
async def test_sse_cursor_outside_window_is_replay_expired() -> None:
    client = ReplayEventRedis()
    event = EventEnvelope(
        event_id="event-2",
        topic="search",
        payload={"status": "done"},
        published_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    client.entries = [("11-0", {"payload": event.model_dump_json()})]

    iterator = RedisEventBusAdapter(client).subscribe("search", after="9-0")
    with pytest.raises(RedisReplayExpiredError) as caught:
        await anext(iterator)
    assert caught.value.error.code == "SSE_REPLAY_EXPIRED"
    assert caught.value.error.details["recovery"] == "resync"


@pytest.mark.unit
async def test_sse_unknown_cursor_inside_window_is_replay_expired() -> None:
    client = ReplayEventRedis()
    event = EventEnvelope(
        event_id="event-2",
        topic="search",
        payload={"status": "done"},
        published_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    client.entries = [("11-0", {"payload": event.model_dump_json()})]

    iterator = RedisEventBusAdapter(client).subscribe("search", after="10-0")
    with pytest.raises(RedisReplayExpiredError):
        await anext(iterator)


@pytest.mark.unit
async def test_reliable_event_bus_requires_redis_instead_of_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_module, "_bus", None)
    monkeypatch.setattr(event_bus_module.settings, "event_bus_backend", "memory")
    monkeypatch.setattr(
        type(event_bus_module.settings),
        "resolved_redis_url",
        lambda self: None,
    )

    with pytest.raises(EventBusDependencyError) as caught:
        await event_bus_module.get_event_bus(require_redis=True)

    assert caught.value.error.code == "EVENT_BUS_DEPENDENCY_UNAVAILABLE"
    assert caught.value.error.details["fallback"] == "disabled"


@pytest.mark.unit
async def test_reliable_event_bus_wraps_redis_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(event_bus_module, "_bus", None)
    monkeypatch.setattr(event_bus_module.settings, "event_bus_backend", "redis")
    monkeypatch.setattr(
        type(event_bus_module.settings),
        "resolved_redis_url",
        lambda self: "redis://fixture.invalid/0",
    )

    async def failing_create(cls: type[object], url: str | None = None) -> object:
        del cls, url
        raise ConnectionError("fixture unavailable")

    monkeypatch.setattr(event_bus_module.RedisStreamEventBus, "create", classmethod(failing_create))

    with pytest.raises(EventBusDependencyError) as caught:
        await event_bus_module.get_event_bus(require_redis=True)

    assert caught.value.error.code == "EVENT_BUS_DEPENDENCY_UNAVAILABLE"
    assert caught.value.error.boundary_ref == "event_bus.redis_connect"
