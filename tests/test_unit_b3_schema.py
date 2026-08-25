"""B3 additive memory schema and repository scope contracts."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from xhs_food.composition.adapters import (
    MemoryAuthorityWriter,
    MemoryOutboxProjector,
    SQLAlchemyMemoryRepository,
)
from xhs_food.contracts import (
    MemoryAuthorityWrite,
    MemoryConversationTurn,
    MemoryEvent,
    MemoryOutboxEvent,
    MemoryRecord,
    UserIsolationKey,
)

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20260824_0007_b3_personalization_memory.py"
MEMORY_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"


def _migration() -> Any:
    spec = importlib.util.spec_from_file_location("b3_memory_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql_for(operation: Any) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        operation()
    return output.getvalue()


@pytest.mark.unit
def test_b3_migration_is_additive_and_scoped_to_memory_authority() -> None:
    migration = _migration()
    upgrade = _sql_for(migration.upgrade)
    downgrade = _sql_for(migration.downgrade)

    for table in (
        "conversation_turns",
        "session_state",
        "memory_records",
        "memory_events",
        "preference_snapshots",
        "memory_summaries",
        "consent_events",
        "claim_events",
        "outbox",
    ):
        assert f"CREATE TABLE {table}" in upgrade
        assert f"DROP TABLE {table}" in downgrade
    assert "CREATE TABLE IF NOT EXISTS" not in upgrade
    assert "ALTER TABLE alembic_version" in upgrade
    assert "chat_history" not in upgrade
    assert "DROP TABLE chat_history" not in downgrade
    assert "ix_memory_records_scope_status" in upgrade
    assert "uq_preference_snapshot_scope_version" in upgrade
    assert "uq_memory_summary_scope_version" in upgrade


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> _Rows:
        return _Rows(self._rows)


class _Session:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self.rows)


class _UnitOfWork:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.commits = 0

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args

    def session_for_adapter(self) -> _Session:
        return self.session

    async def commit(self) -> None:
        self.commits += 1


def _record() -> MemoryRecord:
    return _records()[1]


def _records() -> tuple[MemoryRecord, ...]:
    value = json.loads(MEMORY_FIXTURE.read_text(encoding="utf-8"))
    return tuple(MemoryRecord.model_validate(item) for item in value["exampleRecords"])


@pytest.mark.unit
async def test_memory_repository_commits_and_filters_by_full_user_scope() -> None:
    record = _record()
    scope = UserIsolationKey(
        tenant_id=record.tenant_id,
        user_id=record.subject.id,
    )
    session = _Session([{"payload": record.model_dump(mode="json", by_alias=True)}])
    unit = _UnitOfWork(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)

    assert await repository.save_record(record) == record.record_id
    listed = await repository.list_records(scope)

    assert listed == (record,)
    assert unit.commits == 1
    assert len(session.statements) == 2
    query = session.statements[-1]
    compiled = query.compile(dialect=postgresql.dialect())
    assert "memory_records.tenant_id" in str(query)
    assert "memory_records.subject_kind" in str(query)
    assert "memory_records.subject_id" in str(query)
    assert compiled.params["tenant_id_1"] == record.tenant_id
    assert compiled.params["subject_id_1"] == record.subject.id
    assert "memory_records.session_id IS NULL" in str(query)


@pytest.mark.unit
async def test_memory_repository_writes_conversation_and_outbox_with_scope() -> None:
    scope = UserIsolationKey(tenant_id="tenant-1", user_id="user-1234567890abcd")
    session = _Session()
    unit = _UnitOfWork(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)
    now = datetime(2026, 8, 24, tzinfo=UTC)

    assert (
        await repository.append_conversation_turn(
            turn_id="turn-1",
            scope=scope,
            role="user",
            content="不要辣",
            source_event_id="event-1",
            occurred_at=now,
            idempotency_key="turn-1",
        )
        == "turn-1"
    )
    assert (
        await repository.enqueue_outbox(
            outbox_id="outbox-1",
            scope=scope,
            event_type="memory.invalidate",
            aggregate_id="record-1",
            payload={"recordId": "record-1"},
            idempotency_key="event-1",
            available_at=now,
        )
        == "outbox-1"
    )
    assert unit.commits == 2
    assert "conversation_turns" in str(session.statements[0])
    assert "outbox" in str(session.statements[1])
    for statement in session.statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert scope.tenant_id in compiled.params.values()
        assert scope.user_id in compiled.params.values()


@pytest.mark.unit
async def test_memory_repository_persists_versioned_source_event_scope() -> None:
    record = _record()
    event = MemoryEvent(
        event_id=record.source_event_ids[0],
        tenant_id=record.tenant_id,
        subject=record.subject,
        session_id=record.session_id,
        event_type=f"memory.{record.layer.value}",
        payload={"recordId": record.record_id, "confidence": record.confidence},
        idempotency_key=f"source:{record.source_event_ids[0]}",
        occurred_at=record.valid_from,
        policy_version=record.policy_version,
        created_at=record.created_at,
    )
    session = _Session()
    unit = _UnitOfWork(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)

    assert await repository.append_memory_event(event) == event.event_id
    assert unit.commits == 1
    statement = session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "memory_events" in str(statement)
    assert event.tenant_id in compiled.params.values()
    assert event.subject.id in compiled.params.values()
    payload = compiled.params["payload"]
    assert payload["schemaVersion"] == "memory-event/v1"
    assert payload["policyVersion"] == record.policy_version


@pytest.mark.unit
@pytest.mark.parametrize("record_index", range(4))
async def test_memory_repository_accepts_each_authoritative_layer(record_index: int) -> None:
    record = _records()[record_index]
    session = _Session()
    unit = _UnitOfWork(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)

    assert await repository.save_record(record) == record.record_id
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert compiled.params["layer"] == record.layer.value
    assert compiled.params["policy_version"] == record.policy_version
    assert compiled.params["source_event_ids"] == list(record.source_event_ids)


@pytest.mark.unit
async def test_memory_authority_write_commits_facts_and_outbox_once() -> None:
    record = _record()
    scope = UserIsolationKey(
        tenant_id=record.tenant_id,
        user_id=record.subject.id,
        session_id="session-user-0001",
    )
    record = record.model_copy(update={"session_id": scope.session_id})
    now = datetime(2026, 8, 24, tzinfo=UTC)
    turn = MemoryConversationTurn(
        turn_id="turn-batch-1",
        scope=scope,
        role="user",
        content="不要辣",
        source_event_id="turn-batch-1",
        occurred_at=now,
        idempotency_key="turn-batch-1",
    )
    source_event = MemoryEvent(
        event_id="event-batch-1",
        tenant_id=record.tenant_id,
        subject=record.subject,
        session_id=scope.session_id,
        event_type="memory.explicit",
        payload={"recordId": record.record_id},
        idempotency_key="event-batch-1",
        occurred_at=now,
        policy_version=record.policy_version,
        created_at=now,
    )
    outbox_event = MemoryOutboxEvent(
        outbox_id="outbox-batch-1",
        scope=scope,
        event_type="memory.session.warm",
        aggregate_id=turn.turn_id,
        payload={"message": {"role": "user", "content": turn.content}},
        idempotency_key="outbox-batch-1",
        available_at=now,
    )
    write = MemoryAuthorityWrite(
        conversation_turn=turn,
        record=record,
        source_event=source_event,
        outbox=outbox_event,
    )
    session = _Session()
    unit = _UnitOfWork(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)

    assert await repository.commit_authority_write(write) == outbox_event.outbox_id
    assert unit.commits == 1
    assert [statement.table.name for statement in session.statements] == [
        "conversation_turns",
        "memory_events",
        "memory_records",
        "outbox",
    ]


@pytest.mark.unit
def test_memory_authority_write_rejects_cross_scope_facts() -> None:
    record = _record()
    scope = UserIsolationKey(
        tenant_id=record.tenant_id,
        user_id=record.subject.id,
        session_id="session-user-0001",
    )
    outbox_event = MemoryOutboxEvent(
        outbox_id="outbox-cross-scope",
        scope=scope,
        event_type="memory.session.invalidate",
        aggregate_id="record-1",
        payload={},
        idempotency_key="outbox-cross-scope",
        available_at=record.created_at,
    )
    with pytest.raises(ValueError, match="share one tenant/subject/session scope"):
        MemoryAuthorityWrite(record=record, outbox=outbox_event)


class _SessionWindow:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, object]] = []

    async def append(self, session_id: str, message: dict[str, object], ttl_seconds: int) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.calls.append(("append", session_id, (message, ttl_seconds)))

    async def recent(self, session_id: str, limit: int) -> tuple[dict[str, object], ...]:
        del session_id, limit
        return ()

    async def clear(self, session_id: str) -> bool:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.calls.append(("clear", session_id, True))
        return True


class _AuthorityRepository:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.batches: list[MemoryAuthorityWrite] = []

    async def commit_authority_write(self, batch: MemoryAuthorityWrite) -> str:
        self.order.append("commit")
        self.batches.append(batch)
        return batch.outbox.outbox_id


class _OutboxProjector:
    def __init__(self, order: list[str], *, fail: bool = False) -> None:
        self.order = order
        self.fail = fail

    async def project(self, event: MemoryOutboxEvent) -> bool:
        del event
        self.order.append("project")
        if self.fail:
            raise RuntimeError("redis unavailable")
        return True


def _event_only_write() -> MemoryAuthorityWrite:
    record = _record()
    scope = UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)
    event = MemoryEvent(
        event_id="event-writer-1",
        tenant_id=record.tenant_id,
        subject=record.subject,
        event_type="memory.explicit",
        payload={"recordId": record.record_id},
        idempotency_key="event-writer-1",
        occurred_at=record.valid_from,
        policy_version=record.policy_version,
        created_at=record.created_at,
    )
    return MemoryAuthorityWrite(
        source_event=event,
        outbox=MemoryOutboxEvent(
            outbox_id="outbox-writer-1",
            scope=scope,
            event_type="memory.session.invalidate",
            aggregate_id=event.event_id,
            payload={},
            idempotency_key="outbox-writer-1",
            available_at=record.created_at,
        ),
    )


@pytest.mark.unit
async def test_memory_outbox_projector_runs_after_commit_and_is_retryable() -> None:
    scope = UserIsolationKey(
        tenant_id="tenant-1",
        user_id="user-1234567890abcd",
        session_id="session-1234567890",
    )
    event = MemoryOutboxEvent(
        outbox_id="outbox-project-1",
        scope=scope,
        event_type="memory.session.warm",
        aggregate_id="turn-1",
        payload={"message": {"role": "user", "content": "不要辣"}},
        idempotency_key="outbox-project-1",
        available_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    window = _SessionWindow()
    assert await MemoryOutboxProjector(window).project(event) is True
    assert window.calls == [("append", scope.session_id, ({"role": "user", "content": "不要辣"}, 86_400))]

    failed_window = _SessionWindow(fail=True)
    assert await MemoryOutboxProjector(failed_window).project(event) is False


@pytest.mark.unit
async def test_memory_authority_writer_projects_only_after_commit() -> None:
    order: list[str] = []
    repository = _AuthorityRepository(order)
    projector = _OutboxProjector(order)

    receipt = await MemoryAuthorityWriter(repository, projector).write(_event_only_write())

    assert receipt.committed is True
    assert receipt.projected is True
    assert receipt.outbox_id == "outbox-writer-1"
    assert order == ["commit", "project"]


@pytest.mark.unit
async def test_memory_authority_writer_keeps_commit_when_projection_fails() -> None:
    order: list[str] = []
    repository = _AuthorityRepository(order)
    projector = _OutboxProjector(order, fail=True)

    receipt = await MemoryAuthorityWriter(repository, projector).write(_event_only_write())

    assert receipt.committed is True
    assert receipt.projected is False
    assert order == ["commit", "project"]
    assert len(repository.batches) == 1
