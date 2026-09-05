"""B3 authority, projection fencing, and outbox replay failure gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from xhs_food.composition.adapters import (
    MemoryAuthorityWriter,
    MemoryOutboxProjector,
    MemoryOutboxReplayer,
    SQLAlchemyMemoryRepository,
)
from xhs_food.contracts import (
    MemoryAuthorityWrite,
    MemoryEvent,
    MemoryOutboxEvent,
    MemoryRecord,
    PreferenceSnapshot,
    UserIsolationKey,
)

ROOT = Path(__file__).parents[1]
MEMORY_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"


def _record() -> MemoryRecord:
    values = json.loads(MEMORY_FIXTURE.read_text(encoding="utf-8"))
    return MemoryRecord.model_validate(values["exampleRecords"][1])


def _scope() -> UserIsolationKey:
    record = _record()
    return UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)


def _event(
    *,
    outbox_id: str,
    event_type: str = "memory.session.warm",
    authority_version: int = 0,
    scope: UserIsolationKey | None = None,
    payload: dict[str, Any] | None = None,
) -> MemoryOutboxEvent:
    return MemoryOutboxEvent(
        outbox_id=outbox_id,
        scope=scope or UserIsolationKey(
            tenant_id="tenant-1",
            user_id="user-1234567890abcd",
            session_id="session-1234567890",
        ),
        event_type=event_type,
        aggregate_id=outbox_id,
        payload=payload or {"message": {"turnId": outbox_id}},
        idempotency_key=outbox_id,
        available_at=datetime(2026, 8, 24, tzinfo=UTC),
        authority_version=authority_version,
    )


class _LegacyWindow:
    def __init__(self) -> None:
        self.appended: list[tuple[str, dict[str, Any], int]] = []
        self.cleared: list[str] = []

    async def append(self, session_id: str, message: dict[str, Any], ttl_seconds: int) -> None:
        self.appended.append((session_id, message, ttl_seconds))

    async def recent(self, session_id: str, limit: int) -> tuple[dict[str, Any], ...]:
        del session_id, limit
        return ()

    async def clear(self, session_id: str) -> bool:
        self.cleared.append(session_id)
        return True


@pytest.mark.unit
async def test_authority_writer_does_not_project_when_authority_commit_aborts() -> None:
    class FailingRepository:
        async def commit_authority_write(self, write: MemoryAuthorityWrite) -> str:
            del write
            raise RuntimeError("postgres transaction aborted")

    class Projector:
        called = False

        async def project(self, event: MemoryOutboxEvent) -> bool:
            del event
            self.called = True
            return True

    projector = Projector()
    scope = _scope()
    with pytest.raises(RuntimeError, match="transaction aborted"):
        await MemoryAuthorityWriter(FailingRepository(), projector).write(
            MemoryAuthorityWrite(
                source_event=_source_event(),
                outbox=_event(outbox_id="abort", scope=scope),
            )
        )
    assert projector.called is False


@pytest.mark.unit
async def test_projection_fences_older_versions_and_duplicate_outbox_replay() -> None:
    window = _LegacyWindow()
    projector = MemoryOutboxProjector(window)

    newer = _event(outbox_id="newer", authority_version=2)
    older = _event(outbox_id="older", authority_version=1)
    assert await projector.project(newer) is True
    assert await projector.project(older) is True
    assert await projector.project(newer) is True
    assert [item[1]["turnId"] for item in window.appended] == ["newer"]


@pytest.mark.unit
async def test_outbox_replay_acks_only_success_and_is_safe_after_process_exit() -> None:
    class Repository:
        def __init__(self) -> None:
            self.pending = [_event(outbox_id="replay-failed"), _event(outbox_id="replay-ok")]
            self.processed: list[str] = []

        async def list_pending_outbox(
            self, *, available_at: datetime, limit: int
        ) -> tuple[MemoryOutboxEvent, ...]:
            del available_at
            return tuple(self.pending[:limit])

        async def mark_outbox_processed(self, *, outbox_id: str, processed_at: datetime) -> bool:
            del processed_at
            self.processed.append(outbox_id)
            return True

    class Projector:
        async def project(self, event: MemoryOutboxEvent) -> bool:
            return event.outbox_id == "replay-ok"

    repository = Repository()
    replayed = await MemoryOutboxReplayer(repository, Projector()).replay(
        available_at=datetime(2026, 8, 24, tzinfo=UTC)
    )
    assert replayed == 1
    assert repository.processed == ["replay-ok"]


@pytest.mark.unit
async def test_summary_projection_without_derived_adapter_is_explicitly_unavailable() -> None:
    event = _event(
        outbox_id="summary-lost",
        event_type="memory.summary.project",
        scope=_scope(),
        payload={"summaryVersion": 2},
    )
    assert await MemoryOutboxProjector(_LegacyWindow()).project(event) is False


@pytest.mark.unit
async def test_derived_summary_projection_runs_after_authority_commit() -> None:
    class Derived:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def project(self, event: MemoryOutboxEvent) -> bool:
            self.events.append(event.outbox_id)
            return True

    derived = Derived()
    event = _event(
        outbox_id="summary-after-commit",
        event_type="memory.summary.project",
        scope=_scope(),
        payload={"summaryVersion": 2},
    )
    assert await MemoryOutboxProjector(
        _LegacyWindow(), derived_projector=derived
    ).project(event)
    assert derived.events == ["summary-after-commit"]


@pytest.mark.unit
async def test_authority_write_can_commit_versioned_snapshot_with_outbox() -> None:
    class Session:
        def __init__(self) -> None:
            self.statements: list[Any] = []

        async def execute(self, statement: Any) -> object:
            self.statements.append(statement)
            return object()

    class Unit:
        def __init__(self, session: Session) -> None:
            self.session = session
            self.commits = 0

        async def __aenter__(self) -> Unit:
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args

        def session_for_adapter(self) -> Session:
            return self.session

        async def commit(self) -> None:
            self.commits += 1

    scope = _scope()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    source = _source_event()
    snapshot = PreferenceSnapshot(
        snapshot_id="snapshot-atomic",
        snapshot_version=4,
        isolation_key=scope,
        policy_version="memory-policy/v1",
        source_record_versions={_record().record_id: "v4"},
        generated_at=now,
    )
    outbox = _event(outbox_id="snapshot-outbox", scope=scope, authority_version=4)
    session = Session()
    unit = Unit(session)
    repository = SQLAlchemyMemoryRepository(lambda: unit)  # type: ignore[arg-type]

    assert await repository.commit_authority_write(
        MemoryAuthorityWrite(source_event=source, snapshot=snapshot, outbox=outbox)
    ) == outbox.outbox_id
    assert unit.commits == 1
    assert [statement.table.name for statement in session.statements] == [
        "memory_events",
        "preference_snapshots",
        "outbox",
    ]


def _source_event() -> MemoryEvent:
    record = _record()
    return MemoryEvent(
        event_id="source-event-b3",
        tenant_id=record.tenant_id,
        subject=record.subject,
        event_type="memory.explicit",
        payload={"recordId": record.record_id},
        idempotency_key="source-event-b3",
        occurred_at=record.valid_from,
        policy_version=record.policy_version,
        created_at=record.created_at,
    )
