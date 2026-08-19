# -*- coding: utf-8 -*-
"""Event bus — abstract publish/subscribe with two backends.

Two backends are provided:

- :class:`InMemoryEventBus`: per-process dict of asyncio queues + replay
  buffers. Used in dev/test and when Redis is unavailable.
- :class:`RedisStreamEventBus`: production backend backed by a Redis
  stream per session. Multiple workers can publish/subscribe; the SSE
  ``id`` field maps to the stream entry id, which the browser sends back
  as ``Last-Event-ID`` on reconnect — no manual index tracking required.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import AsyncGenerator, Dict, Optional, Protocol, Tuple

from loguru import logger

from xhs_food.config import settings
from xhs_food.observability.metrics import sse_active_connections

from .types import SearchEvent, SearchEventType

# Stream entry IDs in Redis follow the ``ms-seq`` form. "0" means "from
# the beginning of the stream"; "$" would mean "only new entries".
STREAM_START = "0"


class EventBus(Protocol):
    """Publish/subscribe surface used by orchestrator and SSE endpoint."""

    async def publish(self, session_id: str, event: SearchEvent) -> str:
        """Append ``event`` to the session stream. Returns the entry id."""

    def subscribe(
        self,
        session_id: str,
        last_id: str = STREAM_START,
    ) -> AsyncIterator[Tuple[str, SearchEvent]]:
        """Yield ``(entry_id, event)`` tuples until a terminal event arrives."""

    async def close(self) -> None:
        """Release any backend connections."""


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class _Channel:
    """Per-session in-memory log + fan-out queues."""

    __slots__ = ("events", "subscribers", "lock", "completed", "_counter")

    def __init__(self) -> None:
        self.events: list[tuple[str, SearchEvent]] = []
        self.subscribers: list[asyncio.Queue[tuple[str, SearchEvent]]] = []
        self.lock = asyncio.Lock()
        self.completed = False
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"mem-{self._counter}"


class InMemoryEventBus:
    """Single-process event bus suitable for tests and dev."""

    def __init__(self) -> None:
        self._channels: Dict[str, _Channel] = {}
        self._lock = asyncio.Lock()

    async def _get_channel(self, session_id: str) -> _Channel:
        async with self._lock:
            channel = self._channels.get(session_id)
            if channel is None:
                channel = _Channel()
                self._channels[session_id] = channel
            return channel

    async def publish(self, session_id: str, event: SearchEvent) -> str:
        channel = await self._get_channel(session_id)
        async with channel.lock:
            entry_id = channel.next_id()
            channel.events.append((entry_id, event))
            if event.is_terminal:
                channel.completed = True
            subscribers = list(channel.subscribers)
        for queue in subscribers:
            await queue.put((entry_id, event))
        return entry_id

    async def subscribe(
        self,
        session_id: str,
        last_id: str = STREAM_START,
    ) -> AsyncGenerator[Tuple[str, SearchEvent], None]:
        channel = await self._get_channel(session_id)
        queue: asyncio.Queue[tuple[str, SearchEvent]] = asyncio.Queue()

        async with channel.lock:
            replay = self._slice_after(channel.events, last_id)
            channel.subscribers.append(queue)
            completed = channel.completed

        sse_active_connections.inc()
        try:
            for entry_id, event in replay:
                yield entry_id, event
                if event.is_terminal:
                    return
            if completed and not replay:
                return
            while True:
                try:
                    entry_id, event = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    yield "heartbeat", SearchEvent(
                        type=SearchEventType.PROGRESS,
                        data={"heartbeat": True},
                    )
                    continue
                yield entry_id, event
                if event.is_terminal:
                    return
        finally:
            sse_active_connections.dec()
            async with channel.lock:
                if queue in channel.subscribers:
                    channel.subscribers.remove(queue)

    async def reset(self, session_id: str) -> None:
        async with self._lock:
            self._channels.pop(session_id, None)

    async def close(self) -> None:  # pragma: no cover - nothing to release
        return None

    @staticmethod
    def _slice_after(
        events: list[tuple[str, SearchEvent]],
        last_id: str,
    ) -> list[tuple[str, SearchEvent]]:
        if last_id in ("", STREAM_START, "0-0"):
            return list(events)
        for index, (entry_id, _) in enumerate(events):
            if entry_id == last_id:
                return events[index + 1:]
        return list(events)


# ---------------------------------------------------------------------------
# Redis Streams backend
# ---------------------------------------------------------------------------


class RedisStreamEventBus:
    """Redis Streams backed event bus (production).

    Uses ``redis.asyncio`` (built into ``redis>=4.2``). Each session gets a
    dedicated stream keyed ``stream:{session_id}:events``.
    """

    KEY_PREFIX = "stream"

    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        self._ttl = settings.event_stream_ttl_seconds
        self._maxlen = settings.event_stream_maxlen
        self._heartbeat = settings.sse_heartbeat_seconds

    @classmethod
    async def create(cls, url: Optional[str] = None) -> "RedisStreamEventBus":
        from redis import asyncio as aioredis  # local import to keep dev path light

        target = url or settings.resolved_redis_url()
        if not target:
            raise RuntimeError("Redis URL not configured")
        client = aioredis.from_url(target, decode_responses=True)
        await client.ping()
        safe = target.split("@")[-1]
        logger.info(f"RedisStreamEventBus connected: {safe}")
        return cls(client)

    def _key(self, session_id: str) -> str:
        return f"{self.KEY_PREFIX}:{session_id}:events"

    async def publish(self, session_id: str, event: SearchEvent) -> str:
        key = self._key(session_id)
        entry_id = await self._redis.xadd(
            key,
            {"payload": event.to_json(), "type": event.type.value},
            maxlen=self._maxlen,
            approximate=True,
        )
        await self._redis.expire(key, self._ttl)
        return entry_id

    async def subscribe(
        self,
        session_id: str,
        last_id: str = STREAM_START,
    ) -> AsyncGenerator[Tuple[str, SearchEvent], None]:
        key = self._key(session_id)
        cursor = last_id or STREAM_START
        block_ms = self._heartbeat * 1000
        while True:
            resp = await self._redis.xread({key: cursor}, count=50, block=block_ms)
            if not resp:
                yield "heartbeat", SearchEvent(
                    type=SearchEventType.PROGRESS,
                    data={"heartbeat": True},
                )
                continue
            _, entries = resp[0]
            for entry_id, fields in entries:
                event = SearchEvent.from_json(fields["payload"])
                cursor = entry_id
                yield entry_id, event
                if event.is_terminal:
                    return

    async def reset(self, session_id: str) -> None:
        await self._redis.delete(self._key(session_id))

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except AttributeError:  # pragma: no cover - older redis-py
            await self._redis.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_bus: Optional[EventBus] = None
_bus_lock = asyncio.Lock()


async def get_event_bus() -> EventBus:
    """Return the process-wide event bus (lazy init)."""
    global _bus
    if _bus is not None:
        return _bus
    async with _bus_lock:
        if _bus is not None:
            return _bus
        if settings.event_bus_backend == "redis" and settings.resolved_redis_url():
            try:
                _bus = await RedisStreamEventBus.create()
                return _bus
            except Exception as exc:
                logger.warning(
                    f"RedisStreamEventBus init failed ({exc}); falling back to in-memory"
                )
        _bus = InMemoryEventBus()
        return _bus


async def shutdown_event_bus() -> None:
    """Close the bus on application shutdown."""
    global _bus
    if _bus is not None:
        await _bus.close()
        _bus = None
