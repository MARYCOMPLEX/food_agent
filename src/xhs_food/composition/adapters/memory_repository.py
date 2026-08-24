"""SQLAlchemy adapter for user-scoped Personalization authority facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
    ContractPayload,
    MemoryAuthorityWrite,
    MemoryConversationTurn,
    MemoryEvent,
    MemoryIsolationKey,
    MemoryOutboxEvent,
    MemoryRecord,
    MemoryRepositoryPort,
    PreferenceSnapshot,
    UserIsolationKey,
    isolation_key_for,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.memory_schema import (
    conversation_turns,
    memory_events,
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

    async def commit_authority_write(self, write: MemoryAuthorityWrite) -> str:
        """Commit all authority facts and the projection instruction once."""

        async with self._unit_of_work_factory() as unit:
            if write.conversation_turn is not None:
                await unit.session_for_adapter().execute(
                    _conversation_statement(write.conversation_turn)
                )
            if write.source_event is not None:
                await unit.session_for_adapter().execute(_memory_event_statement(write.source_event))
            if write.record is not None:
                await unit.session_for_adapter().execute(_record_statement(write.record))
            await unit.session_for_adapter().execute(_outbox_statement(write.outbox))
            await unit.commit()
        return write.outbox.outbox_id

    async def append_memory_event(self, event: MemoryEvent) -> str:
        statement = insert(memory_events).values(
            event_id=event.event_id,
            **_subject_scope_values(
                tenant_id=event.tenant_id,
                subject_id=event.subject.id,
                subject_kind=event.subject.kind.value,
                session_id=event.session_id,
            ),
            event_type=event.event_type,
            payload=event.model_dump(mode="json", by_alias=True),
            idempotency_key=event.idempotency_key,
            occurred_at=event.occurred_at,
            created_at=event.created_at,
        ).on_conflict_do_nothing(index_elements=[memory_events.c.idempotency_key])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return event.event_id

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

    async def list_conversation_turns(
        self,
        scope: MemoryIsolationKey,
        *,
        limit: int,
    ) -> tuple[MemoryConversationTurn, ...]:
        if not 1 <= limit <= 20:
            raise ValueError("conversation window limit must be between 1 and 20")
        statement = (
            select(conversation_turns)
            .where(*_conversation_scope_clause(scope))
            .order_by(conversation_turns.c.occurred_at.desc(), conversation_turns.c.turn_id.desc())
            .limit(limit)
        )
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(statement)
            rows = result.mappings().all()
        return tuple(
            MemoryConversationTurn(
                turn_id=row["turn_id"],
                scope=scope,
                role=row["role"],
                content=row["content"],
                source_event_id=row["source_event_id"],
                occurred_at=row["occurred_at"],
                idempotency_key=row["idempotency_key"],
                metadata=row["metadata"] or {},
            )
            for row in reversed(rows)
        )

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
    return _subject_scope_values(
        tenant_id=scope.tenant_id,
        subject_id=subject_id,
        subject_kind=str(scope.kind),
        session_id=scope.session_id,
    )


def _conversation_statement(turn: MemoryConversationTurn) -> object:
    return insert(conversation_turns).values(
        turn_id=turn.turn_id,
        **_scope_values(turn.scope),
        role=turn.role,
        content=turn.content,
        metadata=turn.metadata,
        source_event_id=turn.source_event_id,
        occurred_at=turn.occurred_at,
        idempotency_key=turn.idempotency_key,
        created_at=turn.occurred_at,
    ).on_conflict_do_nothing(index_elements=[conversation_turns.c.idempotency_key])


def _record_statement(record: MemoryRecord) -> object:
    scope = isolation_key_for(record)
    return insert(memory_records).values(
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
        payload=record.model_dump(mode="json", by_alias=True),
        created_at=record.created_at,
        updated_at=record.updated_at,
    ).on_conflict_do_nothing(index_elements=[memory_records.c.record_id])


def _memory_event_statement(event: MemoryEvent) -> object:
    return insert(memory_events).values(
        event_id=event.event_id,
        **_subject_scope_values(
            tenant_id=event.tenant_id,
            subject_id=event.subject.id,
            subject_kind=str(event.subject.kind),
            session_id=event.session_id,
        ),
        event_type=event.event_type,
        payload=event.model_dump(mode="json", by_alias=True),
        idempotency_key=event.idempotency_key,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
    ).on_conflict_do_nothing(index_elements=[memory_events.c.idempotency_key])


def _outbox_statement(event: MemoryOutboxEvent) -> object:
    return insert(outbox).values(
        outbox_id=event.outbox_id,
        **_scope_values(event.scope),
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        payload=event.payload,
        idempotency_key=event.idempotency_key,
        available_at=event.available_at,
        attempts=0,
        created_at=event.available_at,
    ).on_conflict_do_nothing(index_elements=[outbox.c.idempotency_key])


def _subject_scope_values(
    *, tenant_id: str, subject_id: str, subject_kind: str, session_id: str | None
) -> dict[str, str | None]:
    return {
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "session_id": session_id,
    }


def _scope_clause(scope: MemoryIsolationKey) -> tuple[object, ...]:
    values = _scope_values(scope)
    return tuple(
        memory_records.c[column] == value
        for column, value in values.items()
    )


def _conversation_scope_clause(scope: MemoryIsolationKey) -> tuple[object, ...]:
    values = _scope_values(scope)
    return tuple(
        conversation_turns.c[column] == value
        for column, value in values.items()
    )


__all__ = ["SQLAlchemyMemoryRepository"]
