"""Ports for PostgreSQL-owned Personalization memory facts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .base import ContractPayload
from .memory import (
    MemoryAuthorityWrite,
    MemoryConversationTurn,
    MemoryEvent,
    MemoryIsolationKey,
    MemoryOutboxEvent,
    MemoryRecord,
    PreferenceSnapshot,
)


@runtime_checkable
class MemoryRepositoryPort(Protocol):
    """User-scoped repository operations; adapters own transaction sessions."""

    async def append_conversation_turn(
        self,
        *,
        turn_id: str,
        scope: MemoryIsolationKey,
        role: str,
        content: str,
        source_event_id: str,
        occurred_at: datetime,
        idempotency_key: str,
        metadata: ContractPayload | None = None,
    ) -> str: ...

    async def save_record(self, record: MemoryRecord) -> str: ...

    async def commit_authority_write(self, write: MemoryAuthorityWrite) -> str: ...

    async def append_memory_event(self, event: MemoryEvent) -> str: ...

    async def list_records(
        self,
        scope: MemoryIsolationKey,
        *,
        include_inactive: bool = False,
    ) -> tuple[MemoryRecord, ...]: ...

    async def list_conversation_turns(
        self,
        scope: MemoryIsolationKey,
        *,
        limit: int,
    ) -> tuple[MemoryConversationTurn, ...]: ...

    async def save_preference_snapshot(self, snapshot: PreferenceSnapshot) -> str: ...

    async def enqueue_outbox(
        self,
        *,
        outbox_id: str,
        scope: MemoryIsolationKey,
        event_type: str,
        aggregate_id: str,
        payload: ContractPayload,
        idempotency_key: str,
        available_at: datetime,
    ) -> str: ...


@runtime_checkable
class MemoryOutboxProjectorPort(Protocol):
    async def project(self, event: MemoryOutboxEvent) -> bool: ...


@runtime_checkable
class MemorySessionWindowPort(Protocol):
    """User-scoped, rebuildable session projection; never an authority."""

    async def append(
        self,
        scope: MemoryIsolationKey,
        message: ContractPayload,
        ttl_seconds: int,
    ) -> None: ...

    async def recent(
        self,
        scope: MemoryIsolationKey,
        limit: int,
    ) -> tuple[ContractPayload, ...]: ...

    async def clear(self, scope: MemoryIsolationKey) -> bool: ...


__all__ = [
    "MemoryOutboxProjectorPort",
    "MemoryRepositoryPort",
    "MemorySessionWindowPort",
]
