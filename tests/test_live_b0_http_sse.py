"""Live HTTP/SSE qualification with PostgreSQL projection and Redis Streams."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from redis import asyncio as aioredis
from sqlalchemy import text

from api.search.routes import router
from xhs_food.composition.adapters import PostgresTaskProgressProjectionStore
from xhs_food.contracts import EventEnvelope, TaskEvent, TaskProgressProjection, TaskStatus
from xhs_food.foundation import (
    RedisEventBusAdapter,
    RedisHotStateContract,
    SQLAlchemyDatabase,
)


class _ProjectionStore:
    def __init__(self, delegate: PostgresTaskProgressProjectionStore) -> None:
        self._delegate = delegate

    async def get_by_session_id(self, session_id: str) -> TaskProgressProjection | None:
        return await self._delegate.get_by_session_id(session_id)


def _projection(*, status: TaskStatus = TaskStatus.COMPLETED) -> TaskProgressProjection:
    now = datetime.now(UTC)
    return TaskProgressProjection(
        task_id="live-b0-http-task",
        session_id="live-b0-http-session",
        turn_id="1",
        status=status,
        progress=1.0 if status.is_terminal else 0.0,
        current_step_id="research.execute",
        last_event_id="0-0",
        workflow_id="research:live-b0-http-task",
        run_id="live-b0-http-run",
        updated_at=now,
    )


def _event(*, event_id: str, status: TaskStatus) -> TaskEvent:
    return TaskEvent(
        event_id=event_id,
        task_id="live-b0-http-task",
        event_type="task.completed" if status is TaskStatus.COMPLETED else "task.accepted",
        occurred_at=datetime.now(UTC),
        turn_id="1",
        status=status,
        progress=1.0 if status.is_terminal else 0.5,
        payload={"message": "搜索完成"} if status.is_terminal else {"step": "research.execute"},
    )


@pytest.mark.live
async def test_b0_http_sse_retained_and_expired_cursor_use_pg_snapshot() -> None:
    postgres_url = os.getenv("B0_POSTGRES_URL")
    redis_url = os.getenv("B0_REDIS_URL")
    if not postgres_url:
        pytest.skip("B0_POSTGRES_URL is required for live HTTP/SSE qualification")
    if not redis_url:
        pytest.skip("B0_REDIS_URL is required for live HTTP/SSE qualification")

    database = SQLAlchemyDatabase(postgres_url, enabled=True)
    database.start()
    client = cast(Any, aioredis.from_url(redis_url, decode_responses=True))
    topic = "live-b0-http-session"
    events = RedisEventBusAdapter(
        client,
        RedisHotStateContract(event_read_block_ms=50, event_stream_ttl_seconds=60),
    )
    projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
    app = FastAPI()
    app.state.reliable_task_lifecycle = True
    app.state.reliable_projection_store = _ProjectionStore(projection_store)
    app.state.reliable_event_bus = events
    app.include_router(router, prefix="/v1/search")

    try:
        projection = _projection()
        async with database.unit_of_work() as unit:
            session = unit.session_for_adapter()
            await session.execute(
                text("DELETE FROM task_progress_projection WHERE task_id = :task_id"),
                {"task_id": projection.task_id},
            )
            await unit.commit()
        await events.delete_topic(topic)
        await projection_store.put(projection)
        progress = _event(event_id="live-b0-http-progress", status=TaskStatus.RUNNING)
        terminal = _event(event_id="live-b0-http-completed", status=TaskStatus.COMPLETED)
        first_cursor = await events.publish(
            EventEnvelope(
                event_id=progress.event_id,
                topic=topic,
                payload={"eventType": progress.event_type, "taskEvent": progress.model_dump(mode="json")},
                published_at=progress.occurred_at,
            )
        )
        await events.publish(
            EventEnvelope(
                event_id=terminal.event_id,
                topic=topic,
                payload={"eventType": terminal.event_type, "taskEvent": terminal.model_dump(mode="json")},
                published_at=terminal.occurred_at,
            )
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            retained = await http.get(
                f"/v1/search/stream/{projection.session_id}?sseVersion=v1",
                headers={"Last-Event-ID": first_cursor},
            )
            assert retained.status_code == 200
            assert "event: done\r\n" in retained.text
            assert "id:" in retained.text

            expired = await http.get(
                f"/v1/search/stream/{projection.session_id}?sseVersion=v1",
                headers={"Last-Event-ID": "9999999999999-0"},
            )
            assert expired.status_code == 200
            assert "event: replay_expired\r\n" in expired.text
            assert "id:" not in expired.text
            data_line = next(line for line in expired.text.splitlines() if line.startswith("data: "))
            payload = json.loads(data_line.removeprefix("data: "))
            assert payload["action"] == "resync"
            assert payload["taskId"] == projection.task_id
            assert payload["turnId"] == 1
            assert payload["snapshot"]["status"] == "completed"

            unavailable_client = cast(
                Any,
                aioredis.from_url("redis://127.0.0.1:1/0", decode_responses=True),
            )
            app.state.reliable_event_bus = RedisEventBusAdapter(unavailable_client)
            unavailable = await http.get(
                f"/v1/search/stream/{projection.session_id}?sseVersion=v1",
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["detail"]["code"] == "EVENT_BUS_DEPENDENCY_UNAVAILABLE"
            await unavailable_client.aclose()
    finally:
        await events.delete_topic(topic)
        async with database.unit_of_work() as unit:
            await unit.session_for_adapter().execute(
                text("DELETE FROM task_progress_projection WHERE task_id = :task_id"),
                {"task_id": "live-b0-http-task"},
            )
            await unit.commit()
        await client.aclose()
        await database.aclose()
