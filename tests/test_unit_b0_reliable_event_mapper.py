"""B0 reliable-policy version and canonical SSE mapping gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import (
    ContractError,
    ContractPayload,
    ErrorCategory,
    ErrorScope,
    TaskEvent,
    TaskProgressProjection,
    TaskStatus,
)
from xhs_food.experience import EventMappingError, ReliableEventMapper

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "fixtures"
    / "reliable_task_semantics_v1.json"
)
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _event(
    event_type: str,
    *,
    status: TaskStatus,
    turn_id: str = "2",
    payload: ContractPayload | None = None,
    error: ContractError | None = None,
) -> TaskEvent:
    return TaskEvent(
        event_id=f"event-{event_type}",
        task_id="task-reliable-1",
        event_type=event_type,
        occurred_at=NOW,
        turn_id=turn_id,
        status=status,
        progress=1.0 if status.is_terminal else 0.0,
        payload=payload or {},
        error=error,
    )


@pytest.mark.unit
def test_normative_fixture_pins_two_policies_and_commit_order() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["fixtureVersion"] == "b0-reliable-task-semantics/v1"
    assert fixture["policyVersions"] == {
        "legacy": "legacy-task/v1",
        "reliable": "reliable-task/v1",
        "workflow": "research-task/v1",
        "activity": "research-activity/v1",
        "sse": "v1",
    }
    assert fixture["terminal"]["publicationOrder"] == [
        "execute_activities",
        "postgresql_commit",
        "coordinator_terminal_projection",
        "event_projection",
    ]
    assert fixture["redisReplay"] == {
        "cursorHeader": "Last-Event-ID",
        "retainedCursorIsExclusive": True,
        "streamTtlSeconds": 3600,
        "streamMaxlen": 1000,
        "expiredEvent": "replay_expired",
        "expiredAction": "resync",
        "snapshotAuthority": "postgresql_task_progress_projection",
        "createsNewTask": False,
    }


@pytest.mark.unit
def test_reliable_mapper_projects_accepted_and_completed_to_stable_sse() -> None:
    mapper = ReliableEventMapper()

    accepted = mapper.map(
        _event(
            "task.accepted",
            status=TaskStatus.RUNNING,
            payload={"policyVersion": "reliable-task/v1"},
        ),
        session_id="session-1",
    )
    assert accepted.event == "progress"
    assert accepted.data == {
        "schemaVersion": "v1",
        "sessionId": "session-1",
        "taskId": "task-reliable-1",
        "turnId": 2,
        "progress": 0,
    }

    completed = mapper.map(
        _event("task.completed", status=TaskStatus.COMPLETED, payload={"message": "完成"}),
        session_id="session-1",
    )
    assert completed.event == "done"
    assert completed.data == {
        "schemaVersion": "v1",
        "sessionId": "session-1",
        "taskId": "task-reliable-1",
        "turnId": 2,
        "message": "完成",
    }


@pytest.mark.unit
def test_reliable_mapper_projects_failed_and_cancelled_to_stable_error() -> None:
    mapper = ReliableEventMapper()
    error = ContractError(
        code="PROVIDER_TIMEOUT",
        category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        scope=ErrorScope.TASK,
        retryable=True,
        message="provider timeout",
    )
    failed = mapper.map(
        _event("task.failed", status=TaskStatus.FAILED, error=error),
        session_id="session-1",
    )
    assert failed.event == "error"
    assert failed.data["error"] == {
        "code": "PROVIDER_TIMEOUT",
        "message": "provider timeout",
        "retryable": True,
    }

    nested_failed = mapper.map(
        _event(
            "task.failed",
            status=TaskStatus.FAILED,
            payload={"result": {"error": error.model_dump(mode="json")}},
        ),
        session_id="session-1",
    )
    assert nested_failed.data["error"] == failed.data["error"]

    cancelled = mapper.map(
        _event("task.cancelled", status=TaskStatus.CANCELLED),
        session_id="session-1",
    )
    assert cancelled.event == "error"
    assert cancelled.data["error"] == {
        "code": "TASK_CANCELLED",
        "message": "任务已取消",
        "retryable": False,
    }


@pytest.mark.unit
def test_reliable_mapper_builds_expired_cursor_resync_from_authority_snapshot() -> None:
    mapper = ReliableEventMapper()
    projection = TaskProgressProjection(
        task_id="task-authority-1",
        session_id="session-authority-1",
        turn_id="2",
        status=TaskStatus.COMPLETED,
        progress=1.0,
        updated_at=NOW,
    )

    expired = mapper.replay_expired(
        projection,
        session_id="session-authority-1",
        snapshot={
            "snapshotVersion": 7,
            "status": "completed",
            "terminal": {"event": "done", "message": "搜索完成"},
        },
    )

    assert expired.event == "replay_expired"
    assert expired.data == {
        "schemaVersion": "v1",
        "sessionId": "session-authority-1",
        "taskId": "task-authority-1",
        "turnId": 2,
        "reason": "cursor_not_retained",
        "action": "resync",
        "snapshot": {
            "snapshotVersion": 7,
            "status": "completed",
            "terminal": {"event": "done", "message": "搜索完成"},
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "event",
    [
        _event("task.completed", status=TaskStatus.FAILED),
        _event("task.failed", status=TaskStatus.RUNNING),
        _event("task.unknown", status=TaskStatus.RUNNING),
    ],
)
def test_reliable_mapper_rejects_invalid_terminal_or_identity(event: TaskEvent) -> None:
    mapper = ReliableEventMapper()
    with pytest.raises(EventMappingError):
        mapper.map(event, session_id="session-1")

    with pytest.raises(EventMappingError):
        mapper.map(
            _event("task.accepted", status=TaskStatus.RUNNING, turn_id="bad"),
            session_id="session-1",
        )
