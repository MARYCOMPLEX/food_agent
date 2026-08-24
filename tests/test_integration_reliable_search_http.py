"""HTTP/SSE qualification for the opt-in reliable search boundary."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.search.dependencies import get_research_task
from api.search.routes import router
from xhs_food.contracts import (
    EventEnvelope,
    ResearchOperation,
    ResearchRequest,
    ResearchTask,
    TaskEvent,
    TaskProgressProjection,
    TaskStatus,
)
from xhs_food.foundation import RedisReplayExpiredError

_NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _projection(*, status: TaskStatus = TaskStatus.RUNNING) -> TaskProgressProjection:
    return TaskProgressProjection(
        task_id="task-http-1",
        session_id="session-http-1",
        turn_id="1",
        status=status,
        progress=1.0 if status.is_terminal else 0.0,
        current_step_id="research.execute",
        last_event_id="1734567890000-1",
        workflow_id="research:task-http-1",
        run_id="run-http-1",
        updated_at=_NOW,
    )


def _task(projection: TaskProgressProjection) -> ResearchTask:
    return ResearchTask(
        task_id=projection.task_id,
        request_id="http:session-http-1",
        operation=ResearchOperation.QUERY,
        domain="food",
        status=projection.status,
        turn_id=projection.turn_id,
        plan_id="plan-http-1",
        workflow_id=projection.workflow_id,
        run_id=projection.run_id,
        progress_projection=projection,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _ReliableTaskFixture:
    def __init__(self, projection: TaskProgressProjection) -> None:
        self.projection = projection
        self.requests: list[ResearchRequest] = []

    async def submit(self, request: ResearchRequest) -> ResearchTask:
        self.requests.append(request)
        return _task(
            self.projection.model_copy(update={"session_id": request.identity.session_ref})
        )


class _ProjectionFixture:
    def __init__(self, projection: TaskProgressProjection | None) -> None:
        self.projection = projection

    async def get_by_session_id(self, session_id: str) -> TaskProgressProjection | None:
        if self.projection is not None and self.projection.session_id == session_id:
            return self.projection
        return None


class _EventBusFixture:
    def __init__(self, events: tuple[EventEnvelope, ...], *, expired: bool = False) -> None:
        self.events = events
        self.expired = expired
        self.cursors: list[tuple[str, str | None]] = []

    def subscribe(self, topic: str, after: str | None = None) -> AsyncIterator[EventEnvelope]:
        self.cursors.append((topic, after))

        async def _iter() -> AsyncIterator[EventEnvelope]:
            if self.expired:
                raise RedisReplayExpiredError(topic=topic, cursor=after or "missing")
            for event in self.events:
                yield event

        return _iter()


def _envelope(event: TaskEvent, event_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        topic="session-http-1",
        payload={"taskEvent": event.model_dump(mode="json")},
        published_at=event.occurred_at,
    )


def _app(
    tasks: _ReliableTaskFixture,
    projection_store: _ProjectionFixture,
    event_bus: _EventBusFixture,
) -> FastAPI:
    app = FastAPI()
    app.state.reliable_task_lifecycle = True
    app.state.reliable_projection_store = projection_store
    app.state.reliable_event_bus = event_bus
    app.dependency_overrides[get_research_task] = lambda: tasks
    app.include_router(router, prefix="/v1/search")
    return app


def test_reliable_new_search_uses_independent_session_and_task_identity() -> None:
    projection = _projection()
    tasks = _ReliableTaskFixture(projection)
    app = _app(tasks, _ProjectionFixture(projection), _EventBusFixture(()))
    with TestClient(app) as client:
        response = client.post(
            "/v1/search/",
            json={"query": "自贡本地菜"},
            headers={"X-User-Id": "user-http-1"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["sessionId"].startswith("session-")
    assert payload["data"] == {
        "sessionId": payload["data"]["sessionId"],
        "taskId": "task-http-1",
        "turnId": 1,
        "streamUrl": (
            f"/v1/search/stream/{payload['data']['sessionId']}?sseVersion=v1"
        ),
        "action": "new_search",
    }
    assert tasks.requests[0].identity.subject_ref == "user-http-1"
    assert tasks.requests[0].identity.session_ref == payload["data"]["sessionId"]


def test_reliable_sse_v1_maps_retained_events_and_cursor_exclusively() -> None:
    projection = _projection(status=TaskStatus.COMPLETED)
    done = TaskEvent(
        event_id="event-2",
        task_id=projection.task_id,
        event_type="task.completed",
        occurred_at=_NOW,
        turn_id="1",
        status=TaskStatus.COMPLETED,
        payload={"message": "搜索完成"},
    )
    bus = _EventBusFixture((_envelope(done, "1734567890000-2"),))
    app = _app(_ReliableTaskFixture(projection), _ProjectionFixture(projection), bus)

    with TestClient(app) as client:
        response = client.get(
            "/v1/search/stream/session-http-1?sseVersion=v1",
            headers={"Last-Event-ID": "1734567890000-1"},
        )

    assert response.status_code == 200
    assert response.headers["x-sse-version"] == "v1"
    assert "id: 1734567890000-2\r\n" in response.text
    assert "event: done\r\n" in response.text
    assert '"sessionId":"session-http-1"' in response.text
    assert bus.cursors == [("session-http-1", "1734567890000-1")]


def test_reliable_sse_expired_cursor_emits_snapshot_resync_without_id() -> None:
    projection = _projection(status=TaskStatus.COMPLETED)
    bus = _EventBusFixture((), expired=True)
    app = _app(_ReliableTaskFixture(projection), _ProjectionFixture(projection), bus)

    with TestClient(app) as client:
        response = client.get(
            "/v1/search/stream/session-http-1?sseVersion=v1",
            headers={"Last-Event-ID": "trimmed-cursor"},
        )

    assert response.status_code == 200
    assert "id:" not in response.text
    assert "event: replay_expired\r\n" in response.text
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    data = json.loads(data_line.removeprefix("data: "))
    assert data["action"] == "resync"
    assert data["taskId"] == "task-http-1"
    assert data["turnId"] == 1
    assert data["snapshot"]["terminal"] == {"event": "done", "message": "搜索完成"}


def test_reliable_sse_rejects_unsupported_version_and_missing_projection() -> None:
    projection = _projection()
    tasks = _ReliableTaskFixture(projection)
    app = _app(tasks, _ProjectionFixture(projection), _EventBusFixture(()))
    with TestClient(app) as client:
        unsupported = client.get("/v1/search/stream/session-http-1?sseVersion=v2")
        missing = client.get("/v1/search/stream/missing-session?sseVersion=v1")

    assert unsupported.status_code == 406
    assert unsupported.json()["detail"]["code"] == "unsupported_sse_version"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Session not found"
