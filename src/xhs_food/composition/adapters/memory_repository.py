"""SQLAlchemy adapter for user-scoped Personalization authority facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
    ContractPayload,
    MemoryIsolationKey,
    MemoryRecord,
    MemoryRepositoryPort,
    PreferenceSnapshot,
    UserIsolationKey,
    isolation_key_for,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.memory_schema import (
    conversation_turns,
    memory_records,
    outbox,
    preference_snapshots,
)

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyMemoryRepository(MemoryRepositoryPort):
    """Persist private memory with every query constrained by full scope."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

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
    ) -> str:
        if not turn_id or not source_event_id or not idempotency_key:
            raise ValueError("turn and event identities must be non-empty")
        if role not in {"user", "assistant", "system"}:
            raise ValueError("conversation role is not supported")
        if not content:
            raise ValueError("conversation content must be non-empty")
        values = _scope_values(scope)
        statement = insert(conversation_turns).values(
            turn_id=turn_id,
            **values,
            role=role,
            content=content,
            metadata=metadata or {},
            source_event_id=source_event_id,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            created_at=occurred_at,
        ).on_conflict_do_nothing(index_elements=[conversation_turns.c.idempotency_key])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return turn_id

    async def save_record(self, record: MemoryRecord) -> str:
        scope = isolation_key_for(record)
        payload = record.model_dump(mode="json", by_alias=True)
        statement = insert(memory_records).values(
            record_id=record.record_id,
            **_scope_values(scope),
            layer=record.layer.value,
            memory_key=record.key,
            value=record.value,
            confidence=record.confidence,
            source_event_ids=list(record.source_event_ids),
            consent=record.consent.model_dump(mode="json", by_alias=True),
            valid_from=record.valid_from,
            expires_at=record.expires_at,
            status=record.status.value,
            supersedes_record_id=record.supersedes_record_id,
            policy_version=record.policy_version,
            payload=payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        ).on_conflict_do_nothing(index_elements=[memory_records.c.record_id])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return record.record_id

    async def list_records(
        self,
        scope: MemoryIsolationKey,
        *,
        include_inactive: bool = False,
    ) -> tuple[MemoryRecord, ...]:
        statement = select(memory_records.c.payload).where(
            *(_scope_clause(scope)),
        )
        if not include_inactive:
            statement = statement.where(memory_records.c.status == "active")
        statement = statement.order_by(memory_records.c.updated_at.desc())
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(statement)
            rows = result.mappings().all()
        return tuple(MemoryRecord.model_validate(row["payload"]) for row in rows)

    async def save_preference_snapshot(self, snapshot: PreferenceSnapshot) -> str:
        scope = snapshot.isolation_key
        payload = snapshot.model_dump(mode="json", by_alias=True)
        statement = insert(preference_snapshots).values(
            snapshot_id=snapshot.snapshot_id,
            **_scope_values(scope),
            snapshot_version=snapshot.snapshot_version,
            policy_version=snapshot.policy_version,
            source_record_versions=snapshot.source_record_versions,
            payload=payload,
            generated_at=snapshot.generated_at,
        ).on_conflict_do_nothing(index_elements=[preference_snapshots.c.snapshot_id])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return snapshot.snapshot_id

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
    ) -> str:
        if not event_type or not aggregate_id or not idempotency_key:
            raise ValueError("outbox identities must be non-empty")
        statement = insert(outbox).values(
            outbox_id=outbox_id,
            **_scope_values(scope),
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
            idempotency_key=idempotency_key,
            available_at=available_at,
            attempts=0,
            created_at=available_at,
        ).on_conflict_do_nothing(index_elements=[outbox.c.idempotency_key])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return outbox_id


def _scope_values(scope: MemoryIsolationKey) -> dict[str, str | None]:
    subject_id = scope.user_id if isinstance(scope, UserIsolationKey) else scope.anonymous_subject_id
    return {
        "tenant_id": scope.tenant_id,
        "subject_kind": str(scope.kind),
        "subject_id": subject_id,
        "session_id": scope.session_id,
    }


def _scope_clause(scope: MemoryIsolationKey) -> tuple[object, ...]:
    values = _scope_values(scope)
    return tuple(
        memory_records.c[column] == value
        for column, value in values.items()
    )


__all__ = ["SQLAlchemyMemoryRepository"]
