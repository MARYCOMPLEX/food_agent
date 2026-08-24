"""Search event domain — types, bus abstraction, and emitter facade.

Public surface preserved for backwards compatibility:
- :class:`SearchEvent`, :class:`SearchEventType`
- :func:`get_emitter`, :func:`remove_emitter`
- :class:`SearchEventEmitter` (now a thin facade over :class:`EventBus`)
"""
from .bus import (
    EventBus,
    InMemoryEventBus,
    RedisStreamEventBus,
    get_event_bus,
)
from .emitter import SearchEventEmitter, get_emitter, remove_emitter
from .types import SearchEvent, SearchEventType

__all__ = [
    "SearchEvent",
    "SearchEventType",
    "EventBus",
    "InMemoryEventBus",
    "RedisStreamEventBus",
    "get_event_bus",
    "SearchEventEmitter",
    "get_emitter",
    "remove_emitter",
]
