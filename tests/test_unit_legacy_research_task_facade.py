"""Legacy-policy proxy contracts for the S2 ResearchTask facade."""

from __future__ import annotations

from collections.abc import Coroutine
from copy import deepcopy
from typing import Any

import pytest

from xhs_food.contracts import (
    AgentToolExecutionContext,
    PlatformChannel,
    RecommendationSnapshot,
    ResearchContextSnapshot,
)
from xhs_food.schemas import MustTryItem, RestaurantRecommendation, ShopStats
from xhs_food.services.user_storage import generate_restaurant_hash


class _AdmissionEmitter:
    def __init__(self) -> None:
        self.reset_count = 0
        self.queries: list[str] = []
        self.steps = [{"id": "step1", "label": "legacy", "status": "loading"}]

    def reset(self) -> None:
        self.reset_count += 1

    def init_steps(self, query: str) -> None:
        self.queries.append(query)


class _RunnerCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, AgentToolExecutionContext | None]] = []

    def __call__(
        self,
        session_id: str,
        query: str,
        tool_context: AgentToolExecutionContext | None,
    ) -> Coroutine[Any, Any, None]:
        self.calls.append((session_id, query, tool_context))

        async def _run() -> None:
            return None

        return _run()


def _tool_context() -> AgentToolExecutionContext:
    return AgentToolExecutionContext(
        tenant_ref="tenant-test",
        platforms=(PlatformChannel.XHS_PC,),
        account_refs={PlatformChannel.XHS_PC.value: "xhs-test"},
    )


class _SpawnerCapture:
    def __init__(self) -> None:
        self.coroutines: list[Coroutine[Any, Any, None]] = []

    def __call__(self, coroutine: Coroutine[Any, Any, None]) -> object:
        self.coroutines.append(coroutine)
        return object()

    def close(self) -> None:
        for coroutine in self.coroutines:
            coroutine.close()


async def test_start_new_spawns_the_legacy_runner_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.composition import legacy_research_task
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade

    state_updates: list[tuple[str, dict[str, Any]]] = []
    user_messages: list[tuple[str, str]] = []
    emitter = _AdmissionEmitter()
    runner = _RunnerCapture()
    spawner = _SpawnerCapture()

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        state_updates.append((session_id, changes))
        return changes

    class _Manager:
        async def add_user_message(self, session_id: str, query: str) -> None:
            user_messages.append((session_id, query))

    class _StorageWithoutLegacyHistoryAlias:
        pass

    async def _get_emitter(session_id: str) -> _AdmissionEmitter:
        assert session_id == "new-session"
        return emitter

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _get_storage() -> _StorageWithoutLegacyHistoryAlias:
        return _StorageWithoutLegacyHistoryAlias()

    monkeypatch.setattr(legacy_research_task.legacy_state, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)
    monkeypatch.setattr(legacy_research_task, "get_session_manager", _get_manager)
    monkeypatch.setattr(legacy_research_task, "get_user_storage_service", _get_storage)

    facade = LegacyResearchTaskFacade(
        task_runner=runner,
        task_spawner=spawner,
        session_id_factory=lambda: "new-session",
    )
    try:
        admission = await facade.start_new("自贡冷吃兔")
    finally:
        spawner.close()

    assert runner.calls == [("new-session", "自贡冷吃兔", None)]
    assert len(spawner.coroutines) == 1
    assert state_updates == [
        (
            "new-session",
            {"status": "loading", "query": "自贡冷吃兔", "turn_id": 1},
        )
    ]
    assert user_messages == [("new-session", "自贡冷吃兔")]
    assert emitter.reset_count == 1
    assert emitter.queries == ["自贡冷吃兔"]
    assert admission.model_dump(mode="json", exclude={"schema_version"}) == {
        "task_id": "new-session",
        "session_id": "new-session",
        "operation": "query",
        "stream_ref": "/v1/search/stream/new-session",
        "turn_id": 1,
    }


async def test_refine_spawns_the_legacy_runner_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.composition import legacy_research_task
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade

    state = {"status": "completed", "turn_id": 4}
    emitter = _AdmissionEmitter()
    runner = _RunnerCapture()
    spawner = _SpawnerCapture()

    async def _load_state(session_id: str) -> dict[str, Any]:
        assert session_id == "refine-session"
        return state

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        assert session_id == "refine-session"
        state.update(changes)
        return state

    class _Manager:
        async def add_user_message(self, session_id: str, query: str) -> None:
            assert (session_id, query) == ("refine-session", "不要辣")

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _get_emitter(session_id: str) -> _AdmissionEmitter:
        assert session_id == "refine-session"
        return emitter

    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task, "get_session_manager", _get_manager)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    facade = LegacyResearchTaskFacade(task_runner=runner, task_spawner=spawner)
    try:
        admission = await facade.refine("refine-session", "不要辣")
    finally:
        spawner.close()

    assert runner.calls == [("refine-session", "不要辣", None)]
    assert len(spawner.coroutines) == 1
    assert state == {"status": "loading", "turn_id": 5, "query": "不要辣"}
    assert emitter.reset_count == 1
    assert emitter.queries == ["不要辣"]
    assert admission.turn_id == 5
    assert admission.operation.value == "refine"


async def test_terminal_error_return_is_still_marked_completed_then_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Freeze the legacy defect: an emitted error is hidden by a normal return."""
    from api.search import tasks

    calls: list[str] = []

    class _Emitter:
        async def emit_error(self, error: str) -> None:
            calls.append(f"event:error:{error}")

    emitter = _Emitter()

    class _Orchestrator:
        async def search_stream(self, query: str, received_emitter: _Emitter) -> None:
            assert query == "会触发领域错误"
            assert received_emitter is emitter
            calls.append("orchestrator:search")
            await received_emitter.emit_error("领域错误")

    class _Manager:
        async def get_context(self, session_id: str) -> list[dict[str, str]]:
            assert session_id == "error-return-session"
            calls.append("manager:context")
            return []

    async def _get_emitter(session_id: str) -> _Emitter:
        assert session_id == "error-return-session"
        return emitter

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        assert session_id == "error-return-session"
        calls.append(f"state:{changes['status']}")
        return changes

    async def _persist(session_id: str, query: str, orchestrator: Any, manager: Any) -> None:
        assert (session_id, query) == ("error-return-session", "会触发领域错误")
        calls.append("persist")

    monkeypatch.setattr(tasks, "get_orchestrator", lambda _: _Orchestrator())
    monkeypatch.setattr(tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(tasks, "update_state", _update_state)
    monkeypatch.setattr(tasks, "_persist_results", _persist)

    await tasks.run_stream_search(
        "error-return-session",
        "会触发领域错误",
        tool_context=_tool_context(),
    )

    assert calls == [
        "manager:context",
        "orchestrator:search",
        "event:error:领域错误",
        "state:completed",
        "persist",
    ]


async def test_uncaught_runner_error_sets_error_then_emits_and_updates_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.search import tasks

    calls: list[str] = []

    class _Emitter:
        async def emit_error(self, error: str) -> None:
            calls.append(f"event:error:{error}")

    class _Orchestrator:
        async def search_stream(self, query: str, emitter: _Emitter) -> None:
            calls.append("orchestrator:search")
            raise RuntimeError("runner exploded")

    class _Manager:
        async def get_context(self, session_id: str) -> list[dict[str, str]]:
            calls.append("manager:context")
            return []

    class _Storage:
        async def update_history_status(self, session_id: str, status: str) -> None:
            assert (session_id, status) == ("raised-session", "error")
            calls.append("history:error")

    async def _get_emitter(session_id: str) -> _Emitter:
        return _Emitter()

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _get_storage() -> _Storage:
        return _Storage()

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        assert changes == {"status": "error", "error": "runner exploded"}
        calls.append("state:error")
        return changes

    async def _unexpected_persist(*args: Any, **kwargs: Any) -> None:
        pytest.fail("persistence must not run after an uncaught orchestrator error")

    monkeypatch.setattr(tasks, "get_orchestrator", lambda _: _Orchestrator())
    monkeypatch.setattr(tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(tasks, "update_state", _update_state)
    monkeypatch.setattr(tasks, "_persist_results", _unexpected_persist)

    await tasks.run_stream_search(
        "raised-session",
        "查询",
        tool_context=_tool_context(),
    )

    assert calls == [
        "manager:context",
        "orchestrator:search",
        "state:error",
        "event:error:runner exploded",
        "history:error",
    ]


async def test_persistence_failure_is_swallowed_after_completed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.search import tasks

    state_updates: list[dict[str, Any]] = []
    emitted_errors: list[str] = []

    class _Emitter:
        async def emit_error(self, error: str) -> None:
            emitted_errors.append(error)

    class _Orchestrator:
        async def search_stream(self, query: str, emitter: _Emitter) -> None:
            return None

        def snapshot_context(self) -> ResearchContextSnapshot:
            return ResearchContextSnapshot()

    class _Manager:
        async def get_context(self, session_id: str) -> list[dict[str, str]]:
            return []

    class _Storage:
        history_updates: list[tuple[str, str]] = []

        async def save_search_result(self, **kwargs: Any) -> None:
            raise RuntimeError("database unavailable")

        async def update_history_status(self, session_id: str, status: str, **_: Any) -> None:
            self.history_updates.append((session_id, status))

    storage = _Storage()

    async def _get_emitter(session_id: str) -> _Emitter:
        return _Emitter()

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(session_id: str) -> dict[str, Any]:
        return {"summary": "", "filtered_count": 0}

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        state_updates.append(changes)
        return changes

    monkeypatch.setattr(tasks, "get_orchestrator", lambda _: _Orchestrator())
    monkeypatch.setattr(tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(tasks, "load_state", _load_state)
    monkeypatch.setattr(tasks, "update_state", _update_state)

    await tasks.run_stream_search(
        "persistence-failure-session",
        "查询",
        tool_context=_tool_context(),
    )

    assert state_updates == [
        {"status": "completed"},
        {"restaurants": [], "summary": ""},
    ]
    assert emitted_errors == []
    assert storage.history_updates == []


async def test_recover_status_and_results_delegate_without_changing_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.composition import legacy_research_task
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade

    mapper_calls: list[tuple[str, dict[str, Any]]] = []
    recovery_calls: list[tuple[str, object]] = []
    load_calls: list[str] = []

    class _Mapper:
        def to_http_results(self, session_id: str, state: dict[str, Any]) -> dict[str, Any]:
            mapper_calls.append((session_id, state))
            return {"mapped": "unchanged-result-payload"}

    mapper = _Mapper()

    async def _recover(session_id: str, result_mapper: object) -> dict[str, Any]:
        recovery_calls.append((session_id, result_mapper))
        return {"success": False, "data": {"status": "not_found"}}

    async def _load_state(session_id: str) -> dict[str, Any] | None:
        load_calls.append(session_id)
        if session_id == "status-session":
            return {"status": "loading"}
        if session_id == "results-session":
            return {"restaurants": [{"name": "老店"}], "summary": "原摘要"}
        return None

    emitter = _AdmissionEmitter()

    async def _get_emitter(session_id: str) -> _AdmissionEmitter:
        assert session_id == "status-session"
        return emitter

    monkeypatch.setattr(legacy_research_task.legacy_tasks, "build_recovery_payload", _recover)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    facade = LegacyResearchTaskFacade(result_mapper=mapper)  # type: ignore[arg-type]

    recovered = await facade.recover("recover-session")
    status = await facade.status("status-session")
    results = await facade.results("results-session")
    missing_status = await facade.status("missing-session")
    missing_results = await facade.results("missing-session")

    assert recovered == {"success": False, "data": {"status": "not_found"}}
    assert recovery_calls == [("recover-session", mapper)]
    assert status == {
        "sessionId": "status-session",
        "status": "loading",
        "loadingSteps": emitter.steps,
    }
    assert results == {"mapped": "unchanged-result-payload"}
    assert mapper_calls == [
        (
            "results-session",
            {"restaurants": [{"name": "老店"}], "summary": "原摘要"},
        )
    ]
    assert missing_status is None
    assert missing_results is None
    assert load_calls == [
        "status-session",
        "results-session",
        "missing-session",
        "missing-session",
    ]


async def test_persist_results_writes_recommendation_dict_plus_id_in_legacy_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.search import tasks

    recommendation = RestaurantRecommendation(
        name="老灶火锅",
        location="自流井区",
        features=["牛油锅底"],
        source_notes=["note-甲"],
        confidence=0.875,
        must_try=[MustTryItem(name="毛肚", reason="脆")],
        stats=ShopStats(flavor="9", cost="8", wait="6", env="7"),
        tags=["火锅"],
    )
    recommendation_payload = recommendation.to_dict()
    snapshot = ResearchContextSnapshot(
        recommendations=(
            RecommendationSnapshot(
                key=recommendation.name,
                payload=deepcopy(recommendation_payload),
            ),
        ),
        last_summary="context summary",
    )
    expected_id = generate_restaurant_hash(recommendation.name)
    expected_writer_item = {**recommendation_payload, "id": expected_id}
    calls: list[str] = []
    saved_search: dict[str, Any] = {}
    context_updates: list[tuple[str, dict[str, Any]]] = []
    state_updates: list[tuple[str, dict[str, Any]]] = []

    class _Orchestrator:
        def snapshot_context(self) -> ResearchContextSnapshot:
            calls.append("snapshot")
            return snapshot

        def update_context_recommendation(self, key: str, payload: dict[str, Any]) -> None:
            calls.append("context:update")
            context_updates.append((key, deepcopy(payload)))

    class _Manager:
        async def add_assistant_message(self, session_id: str, summary: str) -> None:
            assert (session_id, summary) == ("writer-session", "state summary")
            calls.append("manager:add-summary")

    class _Storage:
        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            calls.append("storage:upsert")
            assert payload == expected_writer_item

        async def save_search_result(self, **kwargs: Any) -> None:
            calls.append("storage:save-result")
            saved_search.update(deepcopy(kwargs))

        async def update_history_status(self, **kwargs: Any) -> None:
            calls.append("storage:history-completed")
            assert kwargs == {
                "session_id": "writer-session",
                "status": "completed",
                "results_count": 1,
            }

    async def _load_state(session_id: str) -> dict[str, Any]:
        assert session_id == "writer-session"
        calls.append("state:load")
        return {"summary": "state summary", "filtered_count": 2}

    async def _get_storage() -> _Storage:
        calls.append("storage:get")
        return _Storage()

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        calls.append("state:update-result")
        state_updates.append((session_id, deepcopy(changes)))
        return changes

    monkeypatch.setattr(tasks, "load_state", _load_state)
    monkeypatch.setattr(tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(tasks, "update_state", _update_state)

    await tasks._persist_results(
        "writer-session",
        "自贡火锅",
        _Orchestrator(),
        _Manager(),
    )

    assert calls == [
        "state:load",
        "manager:add-summary",
        "storage:get",
        "snapshot",
        "context:update",
        "storage:upsert",
        "storage:save-result",
        "storage:history-completed",
        "state:update-result",
    ]
    assert saved_search == {
        "session_id": "writer-session",
        "restaurants": [expected_writer_item],
        "summary": "context summary",
        "filtered_count": 2,
        "query": "自贡火锅",
    }
    assert context_updates == [(recommendation.name, expected_writer_item)]
    assert state_updates == [
        (
            "writer-session",
            {"restaurants": [expected_writer_item], "summary": "context summary"},
        )
    ]
    assert "id" not in recommendation_payload
    assert "source_notes" in expected_writer_item
    assert "mustTry" in expected_writer_item
    assert "chnName" not in expected_writer_item
    assert "trustScore" not in expected_writer_item


@pytest.mark.parametrize("legacy_id", ["", None])
async def test_persist_results_preserves_an_existing_falsey_legacy_id(
    monkeypatch: pytest.MonkeyPatch,
    legacy_id: object,
) -> None:
    from api.search import tasks

    calls: list[str] = []
    persisted: list[dict[str, Any]] = []
    snapshot = ResearchContextSnapshot(
        recommendations=(
            RecommendationSnapshot(
                key="旧记录",
                payload={"id": legacy_id, "name": "旧记录", "tel": "123"},
            ),
        )
    )

    class _Orchestrator:
        def snapshot_context(self) -> ResearchContextSnapshot:
            return snapshot

        def update_context_recommendation(self, key: str, payload: dict[str, Any]) -> None:
            assert key == "旧记录"
            calls.append("context:update")
            assert payload["id"] is legacy_id

    class _Storage:
        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            calls.append("storage:upsert")
            assert payload["id"] is legacy_id

        async def save_search_result(self, **kwargs: Any) -> None:
            persisted.extend(deepcopy(kwargs["restaurants"]))

        async def update_history_status(self, **kwargs: Any) -> None:
            return None

    async def _get_storage() -> _Storage:
        return _Storage()

    async def _load_state(session_id: str) -> dict[str, Any]:
        return {}

    async def _update_state(session_id: str, **changes: Any) -> dict[str, Any]:
        return changes

    monkeypatch.setattr(tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(tasks, "load_state", _load_state)
    monkeypatch.setattr(tasks, "update_state", _update_state)

    await tasks._persist_results("session", "query", _Orchestrator(), object())

    assert calls == ["context:update", "storage:upsert"]
    assert persisted == [{"id": legacy_id, "name": "旧记录", "tel": "123"}]


def test_default_runner_receives_the_facade_result_mapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.composition import legacy_research_task
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
    from xhs_food.experience import StableResultMapper

    mapper = StableResultMapper()
    received: list[object] = []
    spawner = _SpawnerCapture()

    async def _run(
        session_id: str,
        query: str,
        *,
        result_mapper: object | None = None,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> None:
        assert (session_id, query) == ("session", "query")
        received.append(result_mapper)
        assert tool_context == _tool_context()

    monkeypatch.setattr(legacy_research_task.legacy_tasks, "run_stream_search", _run)
    facade = LegacyResearchTaskFacade(result_mapper=mapper, task_spawner=spawner)
    try:
        facade._spawn_run("session", "query", _tool_context())  # noqa: SLF001
        assert received == []
        assert len(spawner.coroutines) == 1
        assert spawner.coroutines[0].cr_frame is not None
        assert spawner.coroutines[0].cr_frame.f_locals["result_mapper"] is mapper
    finally:
        spawner.close()
