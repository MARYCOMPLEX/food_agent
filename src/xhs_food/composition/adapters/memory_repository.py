"""SQLAlchemy adapter for user-scoped Personalization authority facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
    AnonymousClaimReceipt,
    AnonymousClaimRequest,
    AnonymousIsolationKey,
    ContractPayload,
    MemoryAuthorityWrite,
    MemoryConversationTurn,
    MemoryEvent,
    MemoryIsolationKey,
    MemoryLayer,
    MemoryOutboxEvent,
    MemoryRecord,
    MemoryRepositoryPort,
    MemoryStatus,
    MemorySubject,
    MemorySubjectKind,
    PreferenceSnapshot,
    UserIsolationKey,
    isolation_key_for,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.memory_schema import (
    claim_events,
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
        statement = (
            insert(conversation_turns)
            .values(
                turn_id=turn_id,
                **values,
                role=role,
                content=content,
                metadata=metadata or {},
                source_event_id=source_event_id,
                occurred_at=occurred_at,
                idempotency_key=idempotency_key,
                created_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=[conversation_turns.c.idempotency_key])
        )
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return turn_id

    async def save_record(self, record: MemoryRecord) -> str:
        scope = isolation_key_for(record)
        payload = record.model_dump(mode="json", by_alias=True)
        statement = (
            insert(memory_records)
            .values(
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
            )
            .on_conflict_do_nothing(index_elements=[memory_records.c.record_id])
        )
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return record.record_id

    async def commit_authority_write(self, write: MemoryAuthorityWrite) -> str:
        """Commit all authority facts and the projection instruction once."""

        async with self._unit_of_work_factory() as unit:
            session = cast(Any, unit.session_for_adapter())
            if write.conversation_turn is not None:
                await session.execute(_conversation_statement(write.conversation_turn))
            if write.source_event is not None:
                await session.execute(_memory_event_statement(write.source_event))
            if write.record is not None:
                await session.execute(_record_statement(write.record))
            if write.snapshot is not None:
                await session.execute(_snapshot_statement(write.snapshot))
            await session.execute(_outbox_statement(write.outbox))
            await unit.commit()
        return write.outbox.outbox_id

    async def list_pending_outbox(
        self,
        *,
        available_at: datetime,
        limit: int,
    ) -> tuple[MemoryOutboxEvent, ...]:
        """Read committed projection work without claiming authority ownership."""

        if not 1 <= limit <= 1000:
            raise ValueError("outbox replay limit must be between 1 and 1000")
        statement = (
            select(outbox)
            .where(outbox.c.processed_at.is_(None), outbox.c.available_at <= available_at)
            .order_by(outbox.c.available_at, outbox.c.outbox_id)
            .limit(limit)
        )
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(statement)
            rows = result.mappings().all()
        return tuple(_outbox_from_row(row) for row in rows)

    async def mark_outbox_processed(
        self,
        *,
        outbox_id: str,
        processed_at: datetime,
    ) -> bool:
        """Ack one projection event only after its derived write succeeds."""

        if not outbox_id:
            raise ValueError("outbox_id must be non-empty")
        statement = (
            update(outbox)
            .where(outbox.c.outbox_id == outbox_id, outbox.c.processed_at.is_(None))
            .values(processed_at=processed_at)
        )
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(statement)
            await unit.commit()
        rowcount = getattr(result, "rowcount", None)
        return bool(rowcount if rowcount is not None else True)

    async def append_memory_event(self, event: MemoryEvent) -> str:
        statement = (
            insert(memory_events)
            .values(
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
            )
            .on_conflict_do_nothing(index_elements=[memory_events.c.idempotency_key])
        )
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

    async def claim_anonymous(self, request: AnonymousClaimRequest) -> AnonymousClaimReceipt:
        """Claim one anonymous scope in one PostgreSQL transaction."""

        source = request.source_scope
        target = UserIsolationKey(
            tenant_id=source.tenant_id,
            user_id=request.target_user_id,
            session_id=source.session_id,
        )
        source_claim = select(claim_events.c.payload).where(
            claim_events.c.tenant_id == source.tenant_id,
            claim_events.c.anonymous_subject_id == source.anonymous_subject_id,
            claim_events.c.session_id == source.session_id,
        )
        idempotent_claim = select(claim_events.c.payload).where(
            claim_events.c.idempotency_key == request.idempotency_key,
        )
        records_statement = select(memory_records.c.payload).where(
            memory_records.c.tenant_id == source.tenant_id,
            memory_records.c.subject_kind == "anonymous",
            memory_records.c.subject_id == source.anonymous_subject_id,
            memory_records.c.session_id == source.session_id,
            memory_records.c.status == "active",
            memory_records.c.valid_from <= request.requested_at,
            or_(
                memory_records.c.expires_at.is_(None),
                memory_records.c.expires_at > request.requested_at,
            ),
        )
        async with self._unit_of_work_factory() as unit:
            session = cast(Any, unit.session_for_adapter())
            existing_idempotent = (await session.execute(idempotent_claim)).mappings().first()
            if existing_idempotent is not None:
                return _receipt_from_claim_payload(existing_idempotent["payload"])
            existing_source = (await session.execute(source_claim)).mappings().first()
            if existing_source is not None:
                raise ValueError("anonymous session has already been claimed")
            rows = (await session.execute(records_statement)).mappings().all()
            records = tuple(MemoryRecord.model_validate(row["payload"]) for row in rows)
            if any(record.updated_at > request.requested_at for record in records):
                raise ValueError("claim requested_at must not precede source memory updates")

            migrated: list[MemoryRecord] = []
            claimed_ids = []
            for record in records:
                claimed_ids.append(record.record_id)
                if record.layer is MemoryLayer.INFERRED:
                    continue
                migrated.append(_claimed_record(record, target, request))
            for record in migrated:
                await session.execute(_record_statement(record))
            if claimed_ids:
                await session.execute(
                    update(memory_records)
                    .where(memory_records.c.record_id.in_(claimed_ids))
                    .values(status=MemoryStatus.CLAIMED.value, updated_at=request.requested_at)
                )

            source_outbox = _claim_outbox(
                request,
                scope=source,
                outbox_id=f"{request.claim_id}:source-invalidate",
                event_type="memory.claim.source.invalidate",
                aggregate_id=request.claim_id,
                payload={"claimId": request.claim_id, "action": "invalidate"},
            )
            target_outbox = _claim_outbox(
                request,
                scope=target,
                outbox_id=f"{request.claim_id}:target.warm",
                event_type="memory.claim.target.warm",
                aggregate_id=request.claim_id,
                payload={
                    "claimId": request.claim_id,
                    "action": "warm",
                    "recordIds": [record.record_id for record in migrated],
                },
            )
            await session.execute(_outbox_statement(source_outbox))
            await session.execute(_outbox_statement(target_outbox))
            receipt = AnonymousClaimReceipt(
                claim_id=request.claim_id,
                source_scope=source,
                target_scope=target,
                migrated_record_ids=tuple(record.record_id for record in migrated),
                claimed_record_ids=tuple(claimed_ids),
                outbox_ids=(source_outbox.outbox_id, target_outbox.outbox_id),
            )
            claim_payload = {
                "schemaVersion": request.schema_version,
                "claimId": request.claim_id,
                "sourceScope": source.model_dump(mode="json", by_alias=True),
                "targetScope": target.model_dump(mode="json", by_alias=True),
                "tokenDigest": sha256(request.one_time_token.encode("utf-8")).hexdigest(),
                "consentPolicyVersion": request.consent_policy_version,
                "receipt": receipt.model_dump(mode="json", by_alias=True),
            }
            await session.execute(
                insert(claim_events)
                .values(
                    claim_id=request.claim_id,
                    tenant_id=source.tenant_id,
                    anonymous_subject_id=source.anonymous_subject_id,
                    session_id=source.session_id,
                    target_user_id=request.target_user_id,
                    status="committed",
                    payload=claim_payload,
                    idempotency_key=request.idempotency_key,
                    created_at=request.requested_at,
                )
                .on_conflict_do_nothing(index_elements=[claim_events.c.idempotency_key])
            )
            await session.commit()
            return receipt

    async def save_preference_snapshot(self, snapshot: PreferenceSnapshot) -> str:
        scope = snapshot.isolation_key
        payload = snapshot.model_dump(mode="json", by_alias=True)
        statement = (
            insert(preference_snapshots)
            .values(
                snapshot_id=snapshot.snapshot_id,
                **_scope_values(scope),
                snapshot_version=snapshot.snapshot_version,
                policy_version=snapshot.policy_version,
                source_record_versions=snapshot.source_record_versions,
                payload=payload,
                generated_at=snapshot.generated_at,
            )
            .on_conflict_do_nothing(index_elements=[preference_snapshots.c.snapshot_id])
        )
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return snapshot.snapshot_id

    async def supersede_record(
        self,
        *,
        scope: MemoryIsolationKey,
        previous_record_id: str,
        replacement: MemoryRecord,
        source_event: MemoryEvent,
        outbox: MemoryOutboxEvent,
    ) -> str:
        """Append a correction and supersede its predecessor atomically."""

        if not previous_record_id:
            raise ValueError("previous_record_id must be non-empty")
        if replacement.supersedes_record_id != previous_record_id:
            raise ValueError("replacement must point at previous_record_id")
        write = MemoryAuthorityWrite(
            record=replacement,
            source_event=source_event,
            outbox=outbox,
        )
        _require_scope(scope, isolation_key_for(replacement))
        async with self._unit_of_work_factory() as unit:
            session = cast(Any, unit.session_for_adapter())
            existing = await session.execute(
                select(memory_records.c.record_id).where(
                    memory_records.c.record_id == replacement.record_id,
                    *_scope_clause(scope),
                )
            )
            if existing.mappings().first() is not None:
                await unit.commit()
                return replacement.record_id
            result = await session.execute(
                update(memory_records)
                .where(
                    memory_records.c.record_id == previous_record_id,
                    *_scope_clause(scope),
                    memory_records.c.status == MemoryStatus.ACTIVE.value,
                )
                .values(status=MemoryStatus.SUPERSEDED.value, updated_at=replacement.updated_at)
            )
            rowcount = getattr(result, "rowcount", None)
            if rowcount is not None and rowcount == 0:
                raise ValueError("previous memory record is missing or already inactive")
            await session.execute(_record_statement(replacement))
            await session.execute(_memory_event_statement(source_event))
            await session.execute(_outbox_statement(outbox))
            await unit.commit()
        return write.outbox.outbox_id

    async def tombstone_scope(
        self,
        *,
        scope: MemoryIsolationKey,
        source_event: MemoryEvent,
        outbox: MemoryOutboxEvent,
    ) -> int:
        """Tombstone a private scope and enqueue projection invalidation together."""

        _require_scope(
            scope,
            _scope_from_subject(
                tenant_id=source_event.tenant_id,
                subject_kind=source_event.subject.kind.value,
                subject_id=source_event.subject.id,
                session_id=source_event.session_id,
            ),
        )
        MemoryAuthorityWrite(source_event=source_event, outbox=outbox)
        statement = (
            update(memory_records)
            .where(*_scope_clause(scope), memory_records.c.status != MemoryStatus.TOMBSTONED.value)
            .values(status=MemoryStatus.TOMBSTONED.value, updated_at=source_event.occurred_at)
        )
        async with self._unit_of_work_factory() as unit:
            session = cast(Any, unit.session_for_adapter())
            result = await session.execute(statement)
            await session.execute(_memory_event_statement(source_event))
            await session.execute(_outbox_statement(outbox))
            await unit.commit()
        rowcount = getattr(result, "rowcount", None)
        return int(rowcount if rowcount is not None else 0)

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
        statement = (
            insert(outbox)
            .values(
                outbox_id=outbox_id,
                **_scope_values(scope),
                event_type=event_type,
                aggregate_id=aggregate_id,
                payload=payload,
                idempotency_key=idempotency_key,
                available_at=available_at,
                attempts=0,
                created_at=available_at,
            )
            .on_conflict_do_nothing(index_elements=[outbox.c.idempotency_key])
        )
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return outbox_id


def _scope_values(scope: MemoryIsolationKey) -> dict[str, str | None]:
    subject_id = (
        scope.user_id if isinstance(scope, UserIsolationKey) else scope.anonymous_subject_id
    )
    return _subject_scope_values(
        tenant_id=scope.tenant_id,
        subject_id=subject_id,
        subject_kind=str(scope.kind),
        session_id=scope.session_id,
    )


def _conversation_statement(turn: MemoryConversationTurn) -> Any:
    return (
        insert(conversation_turns)
        .values(
            turn_id=turn.turn_id,
            **_scope_values(turn.scope),
            role=turn.role,
            content=turn.content,
            metadata=turn.metadata,
            source_event_id=turn.source_event_id,
            occurred_at=turn.occurred_at,
            idempotency_key=turn.idempotency_key,
            created_at=turn.occurred_at,
        )
        .on_conflict_do_nothing(index_elements=[conversation_turns.c.idempotency_key])
    )


def _record_statement(record: MemoryRecord) -> Any:
    scope = isolation_key_for(record)
    return (
        insert(memory_records)
        .values(
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
        )
        .on_conflict_do_nothing(index_elements=[memory_records.c.record_id])
    )


def _snapshot_statement(snapshot: PreferenceSnapshot) -> Any:
    scope = snapshot.isolation_key
    return (
        insert(preference_snapshots)
        .values(
            snapshot_id=snapshot.snapshot_id,
            **_scope_values(scope),
            snapshot_version=snapshot.snapshot_version,
            policy_version=snapshot.policy_version,
            source_record_versions=snapshot.source_record_versions,
            payload=snapshot.model_dump(mode="json", by_alias=True),
            generated_at=snapshot.generated_at,
        )
        .on_conflict_do_nothing(index_elements=[preference_snapshots.c.snapshot_id])
    )


def _memory_event_statement(event: MemoryEvent) -> Any:
    return (
        insert(memory_events)
        .values(
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
        )
        .on_conflict_do_nothing(index_elements=[memory_events.c.idempotency_key])
    )


def _outbox_statement(event: MemoryOutboxEvent) -> Any:
    return (
        insert(outbox)
        .values(
            outbox_id=event.outbox_id,
            **_scope_values(event.scope),
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            payload=_outbox_payload(event),
            idempotency_key=event.idempotency_key,
            available_at=event.available_at,
            attempts=0,
            created_at=event.available_at,
        )
        .on_conflict_do_nothing(index_elements=[outbox.c.idempotency_key])
    )


def _claimed_record(
    record: MemoryRecord,
    target: UserIsolationKey,
    request: AnonymousClaimRequest,
) -> MemoryRecord:
    values = record.model_dump(mode="python")
    values.update(
        {
            "record_id": f"{record.record_id}:claimed:{request.claim_id}",
            "subject": MemorySubject(
                kind=MemorySubjectKind.USER,
                id=target.user_id,
                cohort=record.subject.cohort,
                locale=record.subject.locale,
            ),
            "session_id": target.session_id,
            "status": MemoryStatus.ACTIVE,
            "updated_at": request.requested_at,
        }
    )
    return MemoryRecord.model_validate(values)


def _claim_outbox(
    request: AnonymousClaimRequest,
    *,
    scope: MemoryIsolationKey,
    outbox_id: str,
    event_type: str,
    aggregate_id: str,
    payload: ContractPayload,
) -> MemoryOutboxEvent:
    return MemoryOutboxEvent(
        outbox_id=outbox_id,
        scope=scope,
        event_type=event_type,
        aggregate_id=aggregate_id,
        payload=payload,
        idempotency_key=f"{request.idempotency_key}:{outbox_id}",
        available_at=request.requested_at,
    )


def _receipt_from_claim_payload(payload: object) -> AnonymousClaimReceipt:
    if not isinstance(payload, dict) or not isinstance(payload.get("receipt"), dict):
        raise ValueError("stored claim event has an invalid receipt payload")
    return AnonymousClaimReceipt.model_validate(payload["receipt"])


def _subject_scope_values(
    *, tenant_id: str, subject_id: str, subject_kind: str, session_id: str | None
) -> dict[str, str | None]:
    return {
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "session_id": session_id,
    }


def _outbox_payload(event: MemoryOutboxEvent) -> ContractPayload:
    """Persist the projection fence in the JSON payload for old schemas."""

    if event.authority_version == 0 or "authorityVersion" in event.payload:
        return event.payload
    return {**event.payload, "authorityVersion": event.authority_version}


def _outbox_from_row(row: object) -> MemoryOutboxEvent:
    if not isinstance(row, Mapping):
        raise ValueError("stored memory outbox row must expose a public mapping interface")
    values: Mapping[str, Any] = row
    payload = values.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("stored memory outbox payload must be an object")
    scope = _scope_from_subject(
        tenant_id=str(values["tenant_id"]),
        subject_kind=str(values["subject_kind"]),
        subject_id=str(values["subject_id"]),
        session_id=values.get("session_id"),
    )
    return MemoryOutboxEvent(
        outbox_id=str(values["outbox_id"]),
        scope=scope,
        event_type=str(values["event_type"]),
        aggregate_id=str(values["aggregate_id"]),
        payload=payload,
        idempotency_key=str(values["idempotency_key"]),
        available_at=values["available_at"],
        authority_version=_payload_authority_version(payload),
    )


def _payload_authority_version(payload: ContractPayload) -> int:
    value = payload.get("authorityVersion", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("stored memory outbox authorityVersion must be a non-negative integer")
    return value


def _scope_from_subject(
    *, tenant_id: str, subject_kind: str, subject_id: str, session_id: str | None
) -> MemoryIsolationKey:
    if subject_kind == "anonymous":
        if session_id is None:
            raise ValueError("anonymous memory outbox scope requires session_id")
        return AnonymousIsolationKey(
            tenant_id=tenant_id,
            anonymous_subject_id=subject_id,
            session_id=session_id,
        )
    if subject_kind == "user":
        return UserIsolationKey(tenant_id=tenant_id, user_id=subject_id, session_id=session_id)
    raise ValueError("memory outbox scope has an unsupported subject kind")


def _require_scope(left: MemoryIsolationKey, right: MemoryIsolationKey) -> None:
    if _scope_key(left) != _scope_key(right):
        raise PermissionError("memory access is outside the authorized scope")


def _scope_key(scope: MemoryIsolationKey) -> tuple[str, str, str, str | None]:
    subject_id = (
        scope.user_id if isinstance(scope, UserIsolationKey) else scope.anonymous_subject_id
    )
    return (scope.tenant_id, str(scope.kind), subject_id, scope.session_id)


def _scope_clause(scope: MemoryIsolationKey) -> tuple[Any, ...]:
    values = _scope_values(scope)
    return tuple(memory_records.c[column] == value for column, value in values.items())


def _conversation_scope_clause(scope: MemoryIsolationKey) -> tuple[Any, ...]:
    values = _scope_values(scope)
    return tuple(conversation_turns.c[column] == value for column, value in values.items())


__all__ = ["SQLAlchemyMemoryRepository"]
