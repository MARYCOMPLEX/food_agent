"""Integration tests for the ``/v1/search`` HTTP surface.

We use FastAPI's :class:`~fastapi.testclient.TestClient` against the real
``api.main:app``. To keep the test hermetic, the orchestrator's actual
``search_stream`` is patched out so no LLM/spider traffic occurs.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# App fixture — patches orchestrator and state store before the app loads
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Yield a TestClient with the heavy orchestrator/storage paths neutered."""
    import os

    os.environ.setdefault("OPENAI_API_KEY", "test-key")

    from api.main import app
    from api.search import state as state_mod
    from api.search import tasks as tasks_mod

    # No-op the background streaming task.
    async def _noop_run_stream_search(  # noqa: ARG001
        session_id: str,
        query: str,
        *,
        result_mapper: object | None = None,
    ) -> None:
        return None

    monkeypatch.setattr(tasks_mod, "run_stream_search", _noop_run_stream_search)
    # Force a fresh in-memory state store to avoid cross-test pollution.
    fresh_store = state_mod._MemoryStateStore()  # noqa: SLF001
    monkeypatch.setattr(state_mod, "_state_store", fresh_store)

    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# POST /v1/search — new search branch
# ---------------------------------------------------------------------------


def test_new_search_returns_session_id_and_stream_url(client: TestClient) -> None:
    # Arrange
    payload: Dict[str, Any] = {"query": "成都本地老火锅"}

    # Act
    response = client.post("/v1/search/", json=payload)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["action"] == "new_search"
    assert data["sessionId"]  # non-empty
    assert data["streamUrl"] == f"/v1/search/stream/{data['sessionId']}"


def test_new_search_rejects_missing_query(client: TestClient) -> None:
    # Arrange — neither sessionId nor query
    payload: Dict[str, Any] = {}

    # Act
    response = client.post("/v1/search/", json=payload)

    # Assert
    assert response.status_code == 400
    assert "query" in response.text


# ---------------------------------------------------------------------------
# POST /v1/search — refine branch
# ---------------------------------------------------------------------------


def test_refine_returns_action_refine_with_existing_session(
    client: TestClient,
) -> None:
    # Arrange — first create a session
    new_resp = client.post("/v1/search/", json={"query": "成都火锅"}).json()
    session_id = new_resp["data"]["sessionId"]

    # Act — refine the same session
    refine_resp = client.post(
        "/v1/search/",
        json={"sessionId": session_id, "query": "换个地方"},
    )

    # Assert
    assert refine_resp.status_code == 200
    data = refine_resp.json()["data"]
    assert data["action"] == "refine"
    assert data["sessionId"] == session_id
    assert "turnId" in data
    assert data["turnId"] >= 2


# ---------------------------------------------------------------------------
# GET /v1/search/status/{sessionId}
# ---------------------------------------------------------------------------


def test_status_returns_404_for_unknown_session(client: TestClient) -> None:
    # Arrange / Act
    response = client.get("/v1/search/status/does-not-exist")

    # Assert
    assert response.status_code == 404
