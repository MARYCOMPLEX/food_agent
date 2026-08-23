"""Target Redis adapters for rebuildable state only."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from pydantic import TypeAdapter

from xhs_food.contracts import (
    ContractError,
    ContractPayload,
    ErrorCategory,
    ErrorScope,
    EventEnvelope,
)

from .failures import FoundationAdapterError, foundation_failure_boundary


class AsyncRedisClient(Protocol):
    async def get(self, key: str) -> object: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> object: ...

    async def delete(self, *keys: str) -> int: ...

    async def rpush(self, key: str, value: str) -> int: ...

    async def ltrim(self, key: str, start: int, end: int) -> object: ...

    async def lrange(self, key: str, start: int, end: int) -> list[object]: ...

    async def expire(self, key: str, ttl: int) -> object: ...

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object: ...

    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> object: ...

    async def xread(
        self, streams: Mapping[str, str], *, count: int, block: int
    ) -> list[object]: ...

    async def xrange(
        self, key: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[object]: ...


class RedisReplayExpiredError(FoundationAdapterError):
    """The requested SSE cursor is outside Redis' bounded replay window."""

    def __init__(self, *, topic: str, cursor: str) -> None:
        super().__init__(
            ContractError(
                code="SSE_REPLAY_EXPIRED",
                category=ErrorCategory.REPLAY_EXPIRED,
                scope=ErrorScope.EVENT_BUS,
                retryable=False,
                terminal=False,
                message="the requested event cursor is outside the Redis replay window",
                boundary_ref="event_bus.subscribe.replay_window",
                details={"topic": topic, "cursor": cursor, "recovery": "resync"},
            )
        )


@dataclass(frozen=True, slots=True)
class RedisHotStateContract:
    session_window_size: int = 20
    session_ttl_seconds: int = 86_400
    event_stream_ttl_seconds: int = 3_600
    event_stream_maxlen: int = 1_000
    event_read_block_ms: int = 30_000
    idempotency_ttl_seconds: int = 300
    rate_limit_window_seconds: int = 60

    def __post_init__(self) -> None:
        values = (
            self.session_window_size,
            self.session_ttl_seconds,
            self.event_stream_ttl_seconds,
            self.event_stream_maxlen,
            self.event_read_block_ms,
            self.idempotency_ttl_seconds,
            self.rate_limit_window_seconds,
        )
        if any(value < 1 for value in values):
            raise ValueError("Redis hot-state limits must be positive")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int

    def __post_init__(self) -> None:
        if self.remaining < 0 or self.retry_after_seconds < 0:
            raise ValueError("rate-limit decision values must not be negative")


class RedisIdempotencyWindow:
    """Single-use claims that expire and may be safely lost or rebuilt."""

    KEY_PREFIX = "idempotency"

    def __init__(
        self,
        client: AsyncRedisClient,
        contract: RedisHotStateContract | None = None,
    ) -> None:
        self._client = client
        self._contract = contract or RedisHotStateContract()

    async def claim(self, identity: str, ttl_seconds: int) -> bool:
        if ttl_seconds != self._contract.idempotency_ttl_seconds:
            raise ValueError("idempotency TTL must match the target Redis contract")
        key = self._key(identity)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.idempotency.claim",
        ):
            return bool(await self._client.set(key, "1", ex=ttl_seconds, nx=True))

    def _key(self, identity: str) -> str:
        _validate_identity(identity)
        return f"{self.KEY_PREFIX}:{identity}"


class RedisFixedWindowRateLimiter:
    """Atomic, expiring fixed-window counters for non-authoritative throttling."""

    KEY_PREFIX = "rate_limit"
    _CONSUME_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl_ms = redis.call('PTTL', KEYS[1])
if count == 1 or ttl_ms < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl_ms = tonumber(ARGV[1]) * 1000
end
local limit = tonumber(ARGV[2])
local allowed = 0
if count <= limit then
    allowed = 1
end
local remaining = math.max(limit - count, 0)
local retry_after = 0
if allowed == 0 then
    retry_after = math.max(math.floor((ttl_ms + 999) / 1000), 1)
end
return {allowed, remaining, retry_after}
""".strip()

    def __init__(
        self,
        client: AsyncRedisClient,
        contract: RedisHotStateContract | None = None,
    ) -> None:
        self._client = client
        self._contract = contract or RedisHotStateContract()

    async def consume(
        self,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit < 1:
            raise ValueError("rate-limit request limit must be positive")
        if window_seconds != self._contract.rate_limit_window_seconds:
            raise ValueError("rate-limit window must match the target Redis contract")
        key = self._key(identity)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.rate_limit.consume",
        ):
            raw = await self._client.eval(
                self._CONSUME_SCRIPT,
                1,
                key,
                window_seconds,
                limit,
            )
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                raise TypeError("rate-limit response must contain decision values")
            allowed_value = int(_text(raw[0]))
            remaining = int(_text(raw[1]))
            retry_after_seconds = int(_text(raw[2]))
            if allowed_value not in {0, 1} or remaining < 0 or retry_after_seconds < 0:
                raise TypeError("rate-limit response contains invalid values")
            return RateLimitDecision(
                allowed=bool(allowed_value),
                remaining=remaining,
                retry_after_seconds=retry_after_seconds,
            )

    def _key(self, identity: str) -> str:
        _validate_identity(identity)
        return f"{self.KEY_PREFIX}:{identity}"


class RedisStateStore:
    """JSON state with a mandatory TTL; no durable-state or lock surface."""

    KEY_PREFIX = "state"

    def __init__(self, client: AsyncRedisClient) -> None:
        self._client = client

    async def get(self, key: str) -> ContractPayload | None:
        redis_key = self._key(key)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.state.get",
        ):
            raw = await self._client.get(redis_key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(str(raw))
            return TypeAdapter(ContractPayload).validate_python(value)

    async def set(self, key: str, value: ContractPayload, ttl_seconds: int) -> None:
        if ttl_seconds < 1:
            raise ValueError("state TTL must be positive")
        redis_key = self._key(key)
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.state.set",
        ):
            await self._client.set(redis_key, payload, ex=ttl_seconds)

    async def delete(self, key: str) -> bool:
        redis_key = self._key(key)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.state.delete",
        ):
            return bool(await self._client.delete(redis_key))

    def _key(self, identity: str) -> str:
        _validate_identity(identity)
        return f"{self.KEY_PREFIX}:{identity}"


class RedisSessionWindow:
    KEY_PREFIX = "session"

    def __init__(
        self,
        client: AsyncRedisClient,
        contract: RedisHotStateContract | None = None,
    ) -> None:
        self._client = client
        self._contract = contract or RedisHotStateContract()

    async def append(self, session_id: str, message: ContractPayload, ttl_seconds: int) -> None:
        if ttl_seconds != self._contract.session_ttl_seconds:
            raise ValueError("session window TTL must match the target Redis contract")
        key = self._key(session_id)
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.session_window.append",
        ):
            await self._client.rpush(key, payload)
            await self._client.ltrim(key, -self._contract.session_window_size, -1)
            await self._client.expire(key, ttl_seconds)

    async def recent(self, session_id: str, limit: int) -> tuple[ContractPayload, ...]:
        if not 1 <= limit <= self._contract.session_window_size:
            raise ValueError("session window read exceeds the target limit")
        redis_key = self._key(session_id)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.session_window.recent",
        ):
            values = await self._client.lrange(redis_key, -limit, -1)
            return tuple(_payload(value) for value in values)

    async def clear(self, session_id: str) -> bool:
        redis_key = self._key(session_id)
        with foundation_failure_boundary(
            scope=ErrorScope.CACHE,
            operation="cache.session_window.clear",
        ):
            return bool(await self._client.delete(redis_key))

    def _key(self, session_id: str) -> str:
        _validate_identity(session_id)
        return f"{self.KEY_PREFIX}:{session_id}:window"


class RedisEventBusAdapter:
    """Contract EventBus over Redis Streams with exclusive cursor reads."""

    KEY_PREFIX = "events"

    def __init__(
        self,
        client: AsyncRedisClient,
        contract: RedisHotStateContract | None = None,
    ) -> None:
        self._client = client
        self._contract = contract or RedisHotStateContract()

    async def publish(self, event: EventEnvelope) -> str:
        key = self._key(event.topic)
        payload = event.model_dump_json()
        with foundation_failure_boundary(
            scope=ErrorScope.EVENT_BUS,
            operation="event_bus.publish",
        ):
            entry_id = await self._client.xadd(
                key,
                {"payload": payload},
                maxlen=self._contract.event_stream_maxlen,
                approximate=True,
            )
            await self._client.expire(key, self._contract.event_stream_ttl_seconds)
            return _text(entry_id)

    async def subscribe(self, topic: str, after: str | None = None) -> AsyncIterator[EventEnvelope]:
        key = self._key(topic)
        cursor = after or "0"
        await self._assert_cursor_replayable(topic, key, cursor)
        while True:
            with foundation_failure_boundary(
                scope=ErrorScope.EVENT_BUS,
                operation="event_bus.subscribe",
            ):
                response = await self._client.xread(
                    {key: cursor}, count=50, block=self._contract.event_read_block_ms
                )
                if response:
                    _, entries = response[0]  # type: ignore[misc]
                else:
                    entries = ()
            for entry_id, fields in entries:
                with foundation_failure_boundary(
                    scope=ErrorScope.EVENT_BUS,
                    operation="event_bus.subscribe.response",
                ):
                    entry_cursor = _text(entry_id)
                    event = EventEnvelope.model_validate_json(
                        _text(fields.get("payload") or fields.get(b"payload"))
                    )
                cursor = entry_cursor
                yield event

    async def _assert_cursor_replayable(self, topic: str, key: str, cursor: str) -> None:
        """Detect a trimmed cursor before ``XREAD`` silently starts later.

        ``xrange`` is optional on the narrow test double used by the S3
        contract suite.  Production redis-py exposes it, so the target path
        gets explicit replay-expiry semantics without changing the legacy bus.
        """

        if cursor in {"", "0", "0-0"}:
            return
        range_reader = getattr(self._client, "xrange", None)
        if not callable(range_reader):
            return
        typed_range_reader = cast(
            Callable[..., Awaitable[list[object]]],
            range_reader,
        )
        with foundation_failure_boundary(
            scope=ErrorScope.EVENT_BUS,
            operation="event_bus.subscribe.replay_window",
        ):
            first = await typed_range_reader(key, min="-", max="+", count=1)
        if not first:
            raise RedisReplayExpiredError(topic=topic, cursor=cursor)
        first_item = cast(tuple[object, object], first[0])
        first_id = _text(first_item[0])  # redis-py returns (entry_id, fields)
        if _stream_id_is_after(first_id, cursor):
            raise RedisReplayExpiredError(topic=topic, cursor=cursor)

    async def delete_topic(self, topic: str) -> bool:
        redis_key = self._key(topic)
        with foundation_failure_boundary(
            scope=ErrorScope.EVENT_BUS,
            operation="event_bus.delete_topic",
        ):
            return bool(await self._client.delete(redis_key))

    def _key(self, topic: str) -> str:
        _validate_identity(topic)
        return f"{self.KEY_PREFIX}:{topic}:stream"


def _payload(value: object) -> ContractPayload:
    parsed = json.loads(_text(value))
    return TypeAdapter(ContractPayload).validate_python(parsed)


def _text(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _validate_identity(value: str) -> None:
    if not value or any(character.isspace() or character in ":\\/" for character in value):
        raise ValueError("Redis identity must be a non-empty opaque segment")


__all__ = [
    "AsyncRedisClient",
    "RateLimitDecision",
    "RedisEventBusAdapter",
    "RedisFixedWindowRateLimiter",
    "RedisHotStateContract",
    "RedisIdempotencyWindow",
    "RedisReplayExpiredError",
    "RedisSessionWindow",
    "RedisStateStore",
]


def _stream_id_is_after(candidate: str, cursor: str) -> bool:
    """Compare Redis ``milliseconds-sequence`` IDs without string surprises."""

    try:
        candidate_parts = tuple(int(part) for part in candidate.split("-", 1))
        cursor_parts = tuple(int(part) for part in cursor.split("-", 1))
    except (TypeError, ValueError):
        raise ValueError("Redis stream cursor must use the ms-sequence format") from None
    if len(candidate_parts) != 2 or len(cursor_parts) != 2:
        raise ValueError("Redis stream cursor must use the ms-sequence format")
    return candidate_parts > cursor_parts
