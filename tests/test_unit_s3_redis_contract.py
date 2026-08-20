"""Offline contracts for rebuildable target Redis state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from redis import exceptions as redis_errors

from xhs_food.contracts import ErrorCategory, ErrorScope, EventEnvelope
from xhs_food.foundation import (
    FoundationAdapterError,
    RateLimitDecision,
    RedisEventBusAdapter,
    RedisFixedWindowRateLimiter,
    RedisHotStateContract,
    RedisIdempotencyWindow,
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


@pytest.mark.unit
async def test_rate_limit_dependency_failure_propagates_as_stable_contract_error() -> None:
    limiter = RedisFixedWindowRateLimiter(FailingRedis())

    with pytest.raises(FoundationAdapterError) as caught:
        await limiter.consume("provider-1", limit=2, window_seconds=60)

    assert caught.value.error.scope is ErrorScope.CACHE
    assert caught.value.error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert caught.value.error.boundary_ref == "cache.rate_limit.consume"
    assert isinstance(caught.value.__cause__, redis_errors.ConnectionError)


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
