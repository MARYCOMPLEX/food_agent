"""Wire-level characterization of the current search SSE endpoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xhs_food.contracts import ContractError, ErrorCategory, ErrorScope
from xhs_food.events.bus import (
    STREAM_START,
    EventBusDependencyError,
    InMemoryEventBus,
)
from xhs_food.events.types import SearchEvent, SearchEventType

FIXTURES = Path(__file__).parent / "fixtures" / "sse_characterization"


def _wire_fixture(name: str) -> bytes:
    """Read a reviewable LF fixture in the CRLF form mandated by SSE."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    # Keep the source fixture free of a blank line at EOF; SSE terminates each
    # event with an empty line when converting it to the wire representation.
    text = text.rstrip("\r\n") + "\n\n"
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return normalized.encode("utf-8")


@pytest.fixture
def sse_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, InMemoryEventBus]]:
    from api.search import routes

    bus = InMemoryEventBus()

    async def _get_bus() -> InMemoryEventBus:
        return bus

    monkeypatch.setattr(routes, "get_event_bus", _get_bus)
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1/search")
    with TestClient(app) as client:
        yield client, bus


async def _publish_complete_wire_sample(bus: InMemoryEventBus, session_id: str) -> None:
    await bus.publish(
        session_id,
        SearchEvent(
            SearchEventType.STEP_START,
            {
                "step": "step1",
                "message": "解析: 成都火锅",
                "steps": [{"id": "step1", "label": "解析: 成都火锅", "status": "loading"}],
                "progress": 0,
            },
        ),
    )
    await bus.publish(
        session_id,
        SearchEvent(
            SearchEventType.RESULT,
            {
                "summary": "推荐完成",
                "total": 1,
                "filtered": 0,
                "steps": [{"id": "step1", "label": "解析: 成都火锅", "status": "done"}],
            },
        ),
    )
    await bus.publish(
        session_id,
        SearchEvent(SearchEventType.DONE, {"message": "搜索完成"}),
    )


async def test_complete_sse_response_matches_wire_fixture_byte_for_byte(
    sse_client: tuple[TestClient, InMemoryEventBus],
) -> None:
    client, bus = sse_client
    await _publish_complete_wire_sample(bus, "wire-session")

    response = client.get("/v1/search/stream/wire-session")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.content == _wire_fixture("complete_stream.sse")


async def test_last_event_id_is_an_exclusive_http_replay_cursor(
    sse_client: tuple[TestClient, InMemoryEventBus],
) -> None:
    client, bus = sse_client
    await _publish_complete_wire_sample(bus, "resume-session")

    response = client.get(
        "/v1/search/stream/resume-session",
        headers={"Last-Event-ID": "mem-1"},
    )

    assert response.status_code == 200
    assert b"id: mem-1\r\n" not in response.content
    marker = b"id: mem-2\r\n"
    assert (
        response.content
        == marker + _wire_fixture("complete_stream.sse").split(marker, maxsplit=1)[1]
    )


async def test_unknown_last_event_id_currently_replays_from_stream_start(
    sse_client: tuple[TestClient, InMemoryEventBus],
) -> None:
    """Freeze the current unknown-cursor behavior until replay_expired exists."""
    client, bus = sse_client
    await _publish_complete_wire_sample(bus, "unknown-cursor")

    response = client.get(
        "/v1/search/stream/unknown-cursor",
        headers={"Last-Event-ID": "missing-event-id"},
    )

    assert response.content == _wire_fixture("complete_stream.sse")


async def test_heartbeat_and_terminal_events_have_stable_wire_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.search import routes

    class _HeartbeatThenDoneBus:
        async def subscribe(
            self, session_id: str, last_id: str = STREAM_START
        ) -> AsyncGenerator[tuple[str, SearchEvent], None]:
            assert session_id == "idle-session"
            assert last_id == STREAM_START
            yield "heartbeat", SearchEvent(SearchEventType.PROGRESS, {"heartbeat": True})
            yield "terminal-1", SearchEvent(SearchEventType.DONE, {"message": "搜索完成"})

    scripted_bus = _HeartbeatThenDoneBus()

    async def _get_bus() -> _HeartbeatThenDoneBus:
        return scripted_bus

    monkeypatch.setattr(routes, "get_event_bus", _get_bus)
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1/search")

    with TestClient(app) as client:
        response = client.get("/v1/search/stream/idle-session")

    assert response.content == _wire_fixture("heartbeat_then_done.sse")


async def test_error_is_terminal_and_uses_error_payload_field(
    sse_client: tuple[TestClient, InMemoryEventBus],
) -> None:
    client, bus = sse_client
    await bus.publish(
        "error-session",
        SearchEvent(SearchEventType.ERROR, {"error": "source unavailable"}),
    )
    await bus.publish(
        "error-session",
        SearchEvent(SearchEventType.PROGRESS, {"after_terminal": True}),
    )

    response = client.get("/v1/search/stream/error-session")

    assert response.content == (
        b'id: mem-1\r\nevent: error\r\ndata: {"error": "source unavailable"}\r\n\r\n'
    )
    assert b"after_terminal" not in response.content


async def test_reliable_sse_dependency_failure_is_explicit_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.search import routes

    async def _get_bus(*, require_redis: bool = False) -> object:
        assert require_redis is True
        raise EventBusDependencyError(
            ContractError(
                code="EVENT_BUS_DEPENDENCY_UNAVAILABLE",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                scope=ErrorScope.EVENT_BUS,
                retryable=True,
                boundary_ref="event_bus.redis_connect",
            )
        )

    monkeypatch.setattr(routes, "get_event_bus", _get_bus)
    app = FastAPI()
    app.state.reliable_task_lifecycle = True
    app.include_router(routes.router, prefix="/v1/search")

    with TestClient(app) as client:
        response = client.get("/v1/search/stream/reliable-session")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "schema_version": "1.0",
        "code": "EVENT_BUS_DEPENDENCY_UNAVAILABLE",
        "category": "dependency_unavailable",
        "scope": "event_bus",
        "retryable": True,
        "terminal": False,
        "message": None,
        "boundary_ref": "event_bus.redis_connect",
        "details": {},
    }
