"""Legacy hot-state compatibility adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import TypeAdapter

from xhs_food.contracts import ContractPayload, EventEnvelope
from xhs_food.events.bus import STREAM_START
from xhs_food.events.types import SearchEvent, SearchEventType


class LegacyStateStore(Protocol):
    async def get(self, sid: str) -> dict[str, Any] | None: ...

    async def set(self, sid: str, value: dict[str, Any]) -> None: ...

    async def delete(self, sid: str) -> None: ...


class LegacyEventBus(Protocol):
    async def publish(self, session_id: str, event: SearchEvent) -> str: ...

    def subscribe(
        self, session_id: str, last_id: str = STREAM_START
    ) -> AsyncIterator[tuple[str, SearchEvent]]: ...

    async def close(self) -> None: ...


class LegacyMemory(Protocol):
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> None: ...

    def get_recent_messages(self, session_id: str, count: int | None) -> list[Any]: ...

    def session_exists(self, session_id: str) -> bool: ...

    def clear_session(self, session_id: str) -> None: ...


class LegacyStateStoreAdapter:
    """Expose the existing task state backend without changing its policy."""

    KEY_PATTERN = "task:{session_id}:state"
    TTL_SECONDS = 3_600
    FALLBACK_POLICY = "redis_init_failure_to_in_memory"

    def __init__(
        self,
        store: LegacyStateStore,
        *,
        ttl_seconds: int = TTL_SECONDS,
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds

    async def get(self, key: str) -> ContractPayload | None:
        value = await self._store.get(key)
        if value is None:
            return None
        return TypeAdapter(ContractPayload).validate_python(value)

    async def set(self, key: str, value: ContractPayload, ttl_seconds: int) -> None:
        if ttl_seconds != self._ttl_seconds:
            raise ValueError("legacy task-state TTL changed at the compatibility boundary")
        await self._store.set(key, dict(value))

    async def delete(self, key: str) -> bool:
        existed = await self._store.get(key) is not None
        await self._store.delete(key)
        return existed


class LegacyEventBusAdapter:
    """Map contract envelopes to the existing SearchEvent bus and replay rules."""

    REDIS_KEY_PATTERN = "stream:{session_id}:events"
    FALLBACK_POLICY = "redis_init_failure_to_in_memory"

    def __init__(self, event_bus: LegacyEventBus) -> None:
        self._event_bus = event_bus

    async def publish(self, event: EventEnvelope) -> str:
        event_type, data = _legacy_event_payload(event.payload)
        legacy_event = SearchEvent(
            type=event_type,
            data=data,
            timestamp=event.published_at.timestamp(),
        )
        return await self._event_bus.publish(event.topic, legacy_event)

    def subscribe(self, topic: str, after: str | None = None) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, after)

    async def _subscribe(self, topic: str, after: str | None) -> AsyncIterator[EventEnvelope]:
        async for entry_id, event in self._event_bus.subscribe(
            topic,
            last_id=after or STREAM_START,
        ):
            yield EventEnvelope(
                event_id=entry_id,
                topic=topic,
                payload={"type": event.type.value, "data": dict(event.data)},
                published_at=datetime.fromtimestamp(event.timestamp, tz=UTC),
            )

    async def close(self) -> None:
        await self._event_bus.close()


class LegacySessionWindowAdapter:
    KEY_PATTERN = "session:{session_id}:window"
    WINDOW_SIZE = 20
    TTL_SECONDS = 86_400
    FALLBACK_POLICY = "redis_operation_failure_to_in_memory"

    def __init__(
        self,
        memory: LegacyMemory,
        *,
        ttl_seconds: int = TTL_SECONDS,
    ) -> None:
        self._memory = memory
        self._ttl_seconds = ttl_seconds

    async def append(self, session_id: str, message: ContractPayload, ttl_seconds: int) -> None:
        if ttl_seconds != self._ttl_seconds:
            raise ValueError("legacy session TTL changed at the compatibility boundary")
        raw_metadata = message.get("metadata")
        if raw_metadata is not None and not isinstance(raw_metadata, Mapping):
            raise TypeError("legacy session metadata must be an object")
        metadata = (
            {str(key): value for key, value in raw_metadata.items()}
            if raw_metadata is not None
            else None
        )
        self._memory.add_message(
            session_id,
            str(message.get("role", "user")),
            str(message.get("content", "")),
            metadata,
        )

    async def recent(self, session_id: str, limit: int) -> tuple[ContractPayload, ...]:
        return tuple(
            _message_payload(message)
            for message in self._memory.get_recent_messages(session_id, limit)
        )

    async def clear(self, session_id: str) -> bool:
        existed = bool(self._memory.session_exists(session_id))
        self._memory.clear_session(session_id)
        return existed


def _legacy_event_payload(
    payload: ContractPayload,
) -> tuple[SearchEventType, dict[str, object]]:
    raw_type = payload.get("type")
    raw_data = payload.get("data", {})
    if not isinstance(raw_type, str):
        raise ValueError("legacy event payload requires a string type")
    if not isinstance(raw_data, Mapping):
        raise TypeError("legacy event payload data must be an object")
    return SearchEventType(raw_type), {str(key): value for key, value in raw_data.items()}


def _message_payload(message: object) -> ContractPayload:
    to_dict = getattr(message, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("legacy session message must expose to_dict()")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("legacy session message to_dict() must return an object")
    return {str(key): item for key, item in value.items()}


__all__ = [
    "LegacyEventBusAdapter",
    "LegacySessionWindowAdapter",
    "LegacyStateStoreAdapter",
]
