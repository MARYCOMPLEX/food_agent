"""Focused gates for S2 task facades, context snapshots, and refresh deferral."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import pytest
from fastapi import FastAPI, HTTPException, params
from fastapi.testclient import TestClient

from api.schemas import UnifiedSearchRequest
from api.search import routes
from api.search.dependencies import get_research_task
from xhs_food.composition import build_legacy_composition_root
from xhs_food.contracts import (
    ContextMessage,
    ExplicitRefreshUseCase,
    RecommendationSnapshot,
    ResearchContextSnapshot,
    ResearchOperation,
    ResearchTaskAdmission,
    ResearchTaskNotFoundError,
    ResearchTaskPort,
)
from xhs_food.orchestrator import XHSFoodOrchestrator
from xhs_food.schemas import ConversationContext

ROOT = Path(__file__).parents[1]


def _orchestrator(context: ConversationContext | None = None) -> XHSFoodOrchestrator:
    orchestrator = object.__new__(XHSFoodOrchestrator)
    orchestrator._context = context or ConversationContext()  # noqa: SLF001
    return orchestrator


def _full_context() -> ConversationContext:
    context = ConversationContext(
        conversation_history=[{"role": "user", "content": "成都火锅"}],
        last_intent={"location": "成都", "constraints": {"tags": ["本地"]}},
        last_recommendations={"老灶火锅": {"name": "老灶火锅", "details": {"tags": ["牛油"]}}},
        excluded_shops=["网红店"],
        accumulated_preferences=["少排队"],
        turn_count=3,
        last_notes=[{"id": "note-1", "comments": [{"text": "本地人常去"}]}],
        target_city="成都",
    )
    context.last_summary = "找到一家"  # type: ignore[attr-defined]
    return context


def test_context_snapshot_is_a_deep_copy_in_both_directions() -> None:
    context = _full_context()
    snapshot = _orchestrator(context).snapshot_context()

    context.last_intent["constraints"]["tags"].append("source mutation")  # type: ignore[index,union-attr]
    context.last_recommendations["老灶火锅"]["details"]["tags"].append(  # type: ignore[index,union-attr]
        "source mutation"
    )
    context.last_notes[0]["comments"][0]["text"] = "source mutation"  # type: ignore[index]

    assert snapshot.last_intent == {"location": "成都", "constraints": {"tags": ["本地"]}}
    assert snapshot.recommendations[0].payload == {
        "name": "老灶火锅",
        "details": {"tags": ["牛油"]},
    }
    assert snapshot.last_notes == ({"id": "note-1", "comments": [{"text": "本地人常去"}]},)

    snapshot.last_intent["constraints"]["tags"].append("snapshot mutation")  # type: ignore[index,union-attr]
    snapshot.recommendations[0].payload["details"]["tags"].append(  # type: ignore[index,union-attr]
        "snapshot mutation"
    )
    snapshot.last_notes[0]["comments"][0]["text"] = "snapshot mutation"  # type: ignore[index]

    assert context.last_intent["constraints"]["tags"] == [  # type: ignore[index,union-attr]
        "本地",
        "source mutation",
    ]
    assert context.last_recommendations["老灶火锅"]["details"]["tags"] == [  # type: ignore[index,union-attr]
        "牛油",
        "source mutation",
    ]
    assert context.last_notes[0]["comments"][0]["text"] == "source mutation"  # type: ignore[index]


def test_context_restore_replaces_every_field_and_does_not_share_nested_state() -> None:
    snapshot = _orchestrator(_full_context()).snapshot_context()
    target_context = ConversationContext(
        conversation_history=[{"role": "assistant", "content": "stale"}],
        last_intent={"stale": True},
        last_recommendations={"stale": {"name": "stale"}},
        excluded_shops=["stale"],
        accumulated_preferences=["stale"],
        turn_count=99,
        last_notes=[{"stale": True}],
        target_city="stale",
    )
    target_context.last_summary = "stale"  # type: ignore[attr-defined]
    orchestrator = _orchestrator(target_context)

    orchestrator.restore_context(snapshot)

    restored = orchestrator.context
    assert restored.conversation_history == [{"role": "user", "content": "成都火锅"}]
    assert restored.last_intent == snapshot.last_intent
    assert restored.last_recommendations == {
        "老灶火锅": {"name": "老灶火锅", "details": {"tags": ["牛油"]}}
    }
    assert restored.excluded_shops == ["网红店"]
    assert restored.accumulated_preferences == ["少排队"]
    assert restored.turn_count == 3
    assert restored.last_notes == [{"id": "note-1", "comments": [{"text": "本地人常去"}]}]
    assert restored.target_city == "成都"
    assert restored.last_summary == "找到一家"  # type: ignore[attr-defined]

    snapshot.recommendations[0].payload["details"]["tags"].append(  # type: ignore[index,union-attr]
        "snapshot mutation"
    )
    snapshot.last_notes[0]["comments"][0]["text"] = "snapshot mutation"  # type: ignore[index]
    assert restored.last_recommendations["老灶火锅"]["details"]["tags"] == ["牛油"]  # type: ignore[index,union-attr]
    assert restored.last_notes[0]["comments"][0]["text"] == "本地人常去"  # type: ignore[index]

    restored.last_recommendations["老灶火锅"]["details"]["tags"].append(  # type: ignore[index,union-attr]
        "target mutation"
    )
    assert snapshot.recommendations[0].payload["details"]["tags"] == [  # type: ignore[index,union-attr]
        "牛油",
        "snapshot mutation",
    ]


def test_context_restore_can_clear_a_previous_summary() -> None:
    context = ConversationContext()
    context.last_summary = "stale"  # type: ignore[attr-defined]
    orchestrator = _orchestrator(context)

    orchestrator.restore_context(ResearchContextSnapshot(last_summary=""))

    assert orchestrator.snapshot_context().last_summary == ""


def test_context_restore_merge_deep_copies_and_preserves_unmentioned_state() -> None:
    context = ConversationContext(
        conversation_history=[{"role": "user", "content": "existing"}],
        last_intent={"location": "existing"},
        excluded_shops=["existing exclusion"],
        target_city="existing city",
    )
    snapshot = ResearchContextSnapshot(
        messages=(ContextMessage(role="assistant", content="restored"),),
        recommendations=(
            RecommendationSnapshot(
                key="新店",
                payload={"name": "新店", "nested": {"tags": ["new"]}},
            ),
        ),
    )
    orchestrator = _orchestrator(context)

    orchestrator.restore_context(snapshot, merge=True)
    snapshot.recommendations[0].payload["nested"]["tags"].append("snapshot mutation")  # type: ignore[index,union-attr]

    assert context.conversation_history == [
        {"role": "user", "content": "existing"},
        {"role": "assistant", "content": "restored"},
    ]
    assert context.last_recommendations["新店"]["nested"]["tags"] == ["new"]  # type: ignore[index,union-attr]
    assert context.last_intent == {"location": "existing"}
    assert context.excluded_shops == ["existing exclusion"]
    assert context.target_city == "existing city"


class _ResearchTaskSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def start_new(
        self,
        query: str,
        *,
        tool_context: object | None = None,
    ) -> ResearchTaskAdmission:
        assert tool_context is not None
        self.calls.append(("start_new", query))
        return ResearchTaskAdmission(
            task_id="new-session",
            session_id="new-session",
            operation=ResearchOperation.QUERY,
            stream_ref="/v1/search/stream/new-session",
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
        self.calls.append(("refine", session_id, query))
        return ResearchTaskAdmission(
            task_id=session_id,
            session_id=session_id,
            operation=ResearchOperation.REFINE,
            stream_ref=f"/v1/search/stream/{session_id}",
            turn_id=2,
        )

    async def recover(self, session_id: str) -> dict[str, Any]:
        self.calls.append(("recover", session_id))
        return {"success": True, "data": {"sessionId": session_id, "status": "loading"}}

    async def status(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(("status", session_id))
        return {"sessionId": session_id, "status": "loading", "loadingSteps": []}

    async def results(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(("results", session_id))
        return {"sessionId": session_id, "restaurants": [], "summary": ""}


def test_search_routes_delegate_every_task_operation_only_through_the_port() -> None:
    application = FastAPI()
    application.include_router(routes.router, prefix="/v1/search")
    spy = _ResearchTaskSpy()
    application.dependency_overrides[get_research_task] = lambda: spy

    with TestClient(application) as client:
        assert client.post("/v1/search/", json={"query": "new"}).status_code == 200
        assert (
            client.post("/v1/search/", json={"sessionId": "session-1", "query": "more"}).status_code
            == 200
        )
        assert client.post("/v1/search/", json={"sessionId": "session-1"}).status_code == 200
        assert client.get("/v1/search/status/session-1").status_code == 200
        assert client.get("/v1/search/results/session-1").status_code == 200

    assert isinstance(spy, ResearchTaskPort)
    assert spy.calls == [
        ("start_new", "new"),
        ("refine", "session-1", "more"),
        ("recover", "session-1"),
        ("status", "session-1"),
        ("results", "session-1"),
    ]


@pytest.mark.parametrize(
    "route_handler",
    [routes.unified_search, routes.search_status, routes.search_results],
)
def test_task_route_dependency_annotation_is_the_public_port(route_handler: Any) -> None:
    assert inspect.signature(route_handler).parameters["tasks"].annotation
    annotation = get_type_hints(route_handler, include_extras=True)["tasks"]

    assert get_origin(annotation) is Annotated
    contract, dependency = get_args(annotation)
    assert contract is ResearchTaskPort
    assert isinstance(dependency, params.Depends)
    assert dependency.dependency is get_research_task


def test_search_routes_do_not_import_legacy_task_state_or_orchestrator_implementations() -> None:
    source = ROOT / "src" / "api" / "search" / "routes.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(f"{'.' * node.level}{node.module or ''}")

    assert imported.isdisjoint(
        {
            "api.search.state",
            "api.search.tasks",
            ".state",
            ".tasks",
            "xhs_food.composition.legacy_research_task",
            "xhs_food.orchestrator",
            "xhs_food.orchestrator.core",
        }
    )
    assert "xhs_food.contracts" in imported


async def test_refine_maps_only_the_contract_not_found_error_to_404() -> None:
    class _NotFound(_ResearchTaskSpy):
        async def refine(
            self,
            session_id: str,
            query: str,
            *,
            tool_context: object | None = None,
        ) -> ResearchTaskAdmission:
            raise ResearchTaskNotFoundError(session_id)

    class _Broken(_ResearchTaskSpy):
        async def refine(
            self,
            session_id: str,
            query: str,
            *,
            tool_context: object | None = None,
        ) -> ResearchTaskAdmission:
            raise KeyError("adapter invariant")

    request = UnifiedSearchRequest(sessionId="missing", query="refine")
    with pytest.raises(HTTPException) as exc_info:
        await routes.unified_search(request, _NotFound())
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Session not found"

    with pytest.raises(KeyError, match="adapter invariant"):
        await routes.unified_search(request, _Broken())


async def test_explicit_refresh_is_a_public_but_unbound_s2_port() -> None:
    root = build_legacy_composition_root()
    try:
        use_cases = root.registries["use_cases"]
        assert "research_task" in use_cases.bindings
        assert "explicit_refresh" not in use_cases.bindings
        assert getattr(ExplicitRefreshUseCase, "_is_protocol", False) is True
        assert getattr(ExplicitRefreshUseCase, "_is_runtime_protocol", False) is True
        with pytest.raises(KeyError, match="unknown binding: use_cases.explicit_refresh"):
            await root.resolve("use_cases", "explicit_refresh")
    finally:
        await root.close()


def test_openapi_has_no_refresh_route_during_s2() -> None:
    from api.main import app

    paths = set(app.openapi()["paths"])

    assert not any("refresh" in path.casefold() for path in paths)
    assert {
        "/v1/search/",
        "/v1/search/stream/{sessionId}",
        "/v1/search/status/{sessionId}",
        "/v1/search/results/{sessionId}",
    } <= paths
