"""Golden HTTP characterization for the current unified search API.

These tests intentionally lock the existing wire behavior, including the
different not-found semantics between recover and the read endpoints. They do
not assert that the behavior is desirable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_FIXTURES = Path(__file__).parent / "fixtures" / "http"


def _load_json(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class _CallLog:
    new: list[tuple[str, str]] = field(default_factory=list)
    refine: list[tuple[str, str]] = field(default_factory=list)


class _Emitter:
    steps = [
        {"id": "intent", "label": "理解需求", "status": "done"},
        {"id": "search", "label": "搜索笔记", "status": "loading"},
    ]


class _Storage:
    def __init__(self) -> None:
        self.results: dict[str, list[dict[str, Any]]] = {}
        self.histories: dict[str, Any] = {}

    async def get_all_search_results(self, session_id: str) -> list[dict[str, Any]]:
        return self.results.get(session_id, [])

    async def get_history_by_session(self, session_id: str) -> Any:
        return self.histories.get(session_id)


@pytest.fixture
def search_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, _CallLog, _Storage]]:
    from api.main import app
    from api.search import tasks as tasks_mod
    from api.search.dependencies import get_research_task
    from xhs_food.contracts import ResearchOperation, ResearchTaskAdmission

    calls = _CallLog()
    storage = _Storage()
    states: dict[str, dict[str, Any]] = {
        "session-active": {
            "status": "loading",
            "restaurants": [],
            "summary": "",
        },
        "session-complete": {
            "status": "completed",
            "restaurants": [
                {
                    "id": "restaurant-1",
                    "name": "老街饭店",
                    "trustScore": 8.5,
                    "tags": ["本地", "家常菜"],
                }
            ],
            "summary": "当前结果摘要",
        },
    }

    async def fake_get_storage() -> _Storage:
        return storage

    monkeypatch.setattr(tasks_mod, "get_user_storage_service", fake_get_storage)

    class _ResearchTaskFixture:
        async def start_new(
            self,
            query: str,
            *,
            tool_context: object | None = None,
        ) -> ResearchTaskAdmission:
            assert tool_context is not None
            session_id = "fixed-session-id"
            calls.new.append((session_id, query))
            return ResearchTaskAdmission(
                task_id=session_id,
                session_id=session_id,
                operation=ResearchOperation.QUERY,
                stream_ref=f"/v1/search/stream/{session_id}",
                turn_id=1,
            )

        async def refine(
            self,
            session_id: str,
            query: str,
            *,
            tool_context: object | None = None,
        ) -> ResearchTaskAdmission:
            assert tool_context is not None
            calls.refine.append((session_id, query))
            return ResearchTaskAdmission(
                task_id=session_id,
                session_id=session_id,
                operation=ResearchOperation.REFINE,
                stream_ref=f"/v1/search/stream/{session_id}",
                turn_id=7,
            )

        async def recover(self, session_id: str) -> dict[str, Any]:
            return await tasks_mod.build_recovery_payload(session_id)

        async def status(self, session_id: str) -> dict[str, Any] | None:
            state = states.get(session_id)
            if state is None:
                return None
            return {
                "sessionId": session_id,
                "status": state["status"],
                "loadingSteps": _Emitter().steps,
            }

        async def results(self, session_id: str) -> dict[str, Any] | None:
            state = states.get(session_id)
            if state is None:
                return None
            return {
                "sessionId": session_id,
                "restaurants": state.get("restaurants", []),
                "summary": state.get("summary", ""),
            }

    app.dependency_overrides[get_research_task] = _ResearchTaskFixture

    client = TestClient(app)
    try:
        yield client, calls, storage
    finally:
        client.close()
        app.dependency_overrides.pop(get_research_task, None)


def _assert_golden(response: Any, case: dict[str, Any]) -> None:
    assert response.status_code == case["response"]["status"]
    assert response.json() == case["response"]["json"]


def test_fastapi_openapi_snapshot() -> None:
    from api.main import app

    assert app.openapi() == _load_json("openapi.json")


def test_unified_search_new_refine_and_trailing_slash_wire(
    search_http: tuple[TestClient, _CallLog, _Storage],
) -> None:
    client, calls, _ = search_http
    cases = _load_json("search_http_golden.json")

    new_case = cases["new_search"]
    new_response = client.request(
        new_case["request"]["method"],
        new_case["request"]["path"],
        json=new_case["request"]["json"],
    )
    _assert_golden(new_response, new_case)
    assert calls.new == [("fixed-session-id", "自贡本地人常吃什么？")]

    refine_case = cases["refine"]
    refine_response = client.request(
        refine_case["request"]["method"],
        refine_case["request"]["path"],
        json=refine_case["request"]["json"],
    )
    _assert_golden(refine_response, refine_case)
    assert calls.refine == [("session-active", "不要辣，再近一点")]

    redirect_case = cases["missing_trailing_slash"]
    redirect_response = client.request(
        redirect_case["request"]["method"],
        redirect_case["request"]["path"],
        json=redirect_case["request"]["json"],
        follow_redirects=False,
    )
    assert redirect_response.status_code == redirect_case["response"]["status"]
    assert redirect_response.headers["location"] == redirect_case["response"]["location"]


def test_unified_search_recover_completed_wire(
    search_http: tuple[TestClient, _CallLog, _Storage],
) -> None:
    client, _, storage = search_http
    cases = _load_json("search_http_golden.json")
    case = cases["recover_completed"]
    storage.results["session-recover"] = [
        {
            "turn_id": 1,
            "query": "自贡美食",
            "restaurants": [{"id": "r-1", "name": "盐帮菜馆"}],
            "summary": "第一轮摘要",
            "created_at": "2026-08-18T12:00:00+08:00",
        },
        {
            "turn_id": 2,
            "query": "不要辣",
            "restaurants": [{"id": "r-2", "name": "家常菜馆"}],
            "summary": "第二轮摘要",
            "created_at": "2026-08-18T12:05:00+08:00",
        },
    ]

    response = client.request(
        case["request"]["method"],
        case["request"]["path"],
        json=case["request"]["json"],
    )

    _assert_golden(response, case)


def test_search_status_and_results_wire(
    search_http: tuple[TestClient, _CallLog, _Storage],
) -> None:
    client, _, _ = search_http
    cases = _load_json("search_http_golden.json")

    for name in ("status_loading", "results_completed"):
        case = cases[name]
        response = client.request(
            case["request"]["method"],
            case["request"]["path"],
        )
        _assert_golden(response, case)


@pytest.mark.parametrize(
    "name",
    [
        "new_search_missing_query",
        "request_validation_error",
        "recover_not_found",
        "status_not_found",
        "results_not_found",
    ],
)
def test_search_error_wire(
    search_http: tuple[TestClient, _CallLog, _Storage],
    name: str,
) -> None:
    client, _, _ = search_http
    case = _load_json("search_http_golden.json")[name]
    request = case["request"]

    response = client.request(
        request["method"],
        request["path"],
        json=request.get("json"),
    )

    _assert_golden(response, case)
