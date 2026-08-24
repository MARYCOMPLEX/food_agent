"""Ports for PostgreSQL-owned Personalization memory facts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .base import ContractPayload
from .memory import MemoryEvent, MemoryIsolationKey, MemoryRecord, PreferenceSnapshot


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

    async def append_memory_event(self, event: MemoryEvent) -> str: ...

    async def list_records(
        self,
        scope: MemoryIsolationKey,
        *,
        include_inactive: bool = False,
    ) -> tuple[MemoryRecord, ...]: ...

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


__all__ = ["MemoryRepositoryPort"]
