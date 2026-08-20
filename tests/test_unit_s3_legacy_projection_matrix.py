"""ADR-0010 legacy projections across source, task, and recovery boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

import xhs_food.agents as agents_module
from api.search import tasks as search_tasks
from xhs_food.agents.analyzer import AnalyzeResult
from xhs_food.agents.intent_parser import IntentParseResult
from xhs_food.agents.poi_enricher import EnrichedRestaurant, POIEnricherAgent
from xhs_food.composition import legacy_research_task
from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
from xhs_food.contracts import (
    CanonicalQuery,
    CanonicalSourceBatch,
    CollectRequest,
    ErrorCategory,
    ErrorScope,
    SourceAttemptOutcome,
    SourceCoverageMetadata,
    SourceQueryProjection,
)
from xhs_food.events import InMemoryEventBus, SearchEventEmitter, SearchEventType
from xhs_food.gateways import (
    LegacySourceProjection,
    SourceOutcomeKind,
    XHSSourceConnector,
    classify_batch,
    project_legacy_xhs,
)
from xhs_food.orchestrator import XHSFoodOrchestrator
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.protocols import MCPToolRegistry, ToolResult
from xhs_food.schemas import (
    ConversationContext,
    FoodSearchIntent,
    RestaurantRecommendation,
)

pytestmark = pytest.mark.unit


class _IntentParser:
    def __init__(self, intent: FoodSearchIntent) -> None:
        self.intent = intent

    async def parse(self, query: str, context: ConversationContext) -> IntentParseResult:
        _ = (query, context)
        return IntentParseResult(success=True, intent=self.intent)


class _EmptySearchExecutor:
    def __init__(self) -> None:
        self.reset_count = 0
        self.intents: list[FoodSearchIntent] = []

    def reset_cache(self) -> None:
        self.reset_count += 1

    async def execute_4_stage_search(self, intent: FoodSearchIntent) -> list[dict[str, Any]]:
        self.intents.append(intent)
        return []


class _SuccessfulSearchExecutor:
    def __init__(self, recommendation: RestaurantRecommendation) -> None:
        self.recommendation = recommendation
        self.reset_count = 0

    def reset_cache(self) -> None:
        self.reset_count += 1

    async def execute_4_stage_search(self, intent: FoodSearchIntent) -> list[dict[str, Any]]:
        _ = intent
        return [{"id": "note-1", "title": "fixture"}]

    async def analyze_notes_concurrent(
        self,
        notes: list[dict[str, Any]],
        intent: FoodSearchIntent,
    ) -> list[RestaurantRecommendation]:
        _ = (notes, intent)
        return [self.recommendation]

    def merge_and_validate(
        self, recommendations: list[RestaurantRecommendation]
    ) -> list[RestaurantRecommendation]:
        return recommendations


class _PartialAnalyzer:
    def __init__(self, surviving: RestaurantRecommendation) -> None:
        self.surviving = surviving
        self.note_ids: list[str] = []

    async def analyze(
        self,
        *,
        title: str,
        content: str,
        comments: list[Any],
        exclude_keywords: list[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        _ = (title, content, comments, exclude_keywords)
        self.note_ids.append(note_id)
        if note_id == "note-failed":
            return AnalyzeResult(success=False, error="fixture analyzer failure")
        return AnalyzeResult(success=True, restaurants=[self.surviving])


class _NewSearchFollowUp:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def process_follow_up_with_llm(self, query: str) -> None:
        self.queries.append(query)
        return None


class _BasicEnricher:
    async def enrich_stream(
        self,
        recommendations: list[RestaurantRecommendation],
        city: str = "",
    ) -> AsyncIterator[EnrichedRestaurant]:
        _ = city
        for index, recommendation in enumerate(recommendations, 1):
            yield EnrichedRestaurant(
                index=index,
                name=recommendation.name,
                address=recommendation.location or "",
                tags=list(recommendation.features),
                source_notes=list(recommendation.source_notes),
            )


class _Manager:
    def __init__(self) -> None:
        self.context_reads: list[str] = []
        self.assistant_messages: list[tuple[str, str]] = []

    async def get_context(self, session_id: str) -> list[dict[str, str]]:
        self.context_reads.append(session_id)
        return []

    async def add_assistant_message(self, session_id: str, message: str) -> None:
        self.assistant_messages.append((session_id, message))


class _Storage:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.history_updates: list[tuple[str, str, int | None]] = []

    async def save_search_result(self, **record: Any) -> None:
        self.records.append(
            {
                "turn_id": len(self.records) + 1,
                "created_at": "2026-08-20T12:00:00+08:00",
                **record,
            }
        )

    async def update_history_status(
        self,
        session_id: str,
        status: str,
        results_count: int | None = None,
    ) -> None:
        self.history_updates.append((session_id, status, results_count))

    async def get_all_search_results(self, session_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records if record["session_id"] == session_id]

    async def upsert_restaurant(self, restaurant: dict[str, Any]) -> None:
        _ = restaurant
        return None


class _AmapClient:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, str]] = []

    def search_poi(self, keywords: str, city: str = "", types: str = "050000") -> dict[str, Any]:
        self.calls.append({"keywords": keywords, "city": city, "types": types})
        return self.result


class _XHSSearchTool:
    name = "xhs_search"

    def __init__(
        self,
        result: ToolResult | None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def health_check(self) -> bool:
        return True


class _SequencedXHSProvider:
    def __init__(self, name: str, results: tuple[ToolResult, ...]) -> None:
        self.name = name
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        if index >= len(self.results):
            raise AssertionError(f"unexpected {self.name} provider call")
        return self.results[index]


class _CanonicalLegacySearchTool:
    name = "xhs_search"

    def __init__(self, connector: XHSSourceConnector) -> None:
        self.connector = connector
        self.batches: list[CanonicalSourceBatch] = []

    async def execute(self, **kwargs: Any) -> ToolResult:
        keyword = kwargs.get("keyword")
        assert isinstance(keyword, str)
        batch = await self.connector.search(_source_collect_request(keyword))
        self.batches.append(batch)
        projection = project_legacy_xhs(classify_batch(batch))
        if projection is LegacySourceProjection.CONTINUE:
            return ToolResult.ok(
                {"notes": [dict(document.attributes) for document in batch.documents]}
            )
        if batch.errors:
            error = batch.errors[0]
            return ToolResult.fail(error.code, error.message or error.code)
        return ToolResult.ok({"notes": []})

    async def health_check(self) -> bool:
        return True


def _intent() -> FoodSearchIntent:
    return FoodSearchIntent(location="自贡", food_type="本地菜")


def _source_collect_request(keyword: str) -> CollectRequest:
    query = CanonicalQuery.model_validate(
        {
            "schema_version": "canonical-query/v1",
            "normalizer_version": "canonical-normalizer/v1",
            "classifier_version": "food-constraint-classifier/v1",
            "isolation": {
                "tenant_scope": "public",
                "language": "zh-Hans",
                "region": "CN",
            },
            "query": {
                "domain": "food",
                "geo": {
                    "country_code": "CN",
                    "admin_path": ["cn.sc"],
                    "locality": "cn.sc.zigong",
                },
                "intent": {"kind": "recommend", "subject": "restaurant"},
                "audience": ["visitor"],
                "constraints": [],
                "time_range": {
                    "kind": "current",
                    "start": None,
                    "end": None,
                    "timezone": "Asia/Shanghai",
                },
                "freshness_policy": {
                    "policy_id": "food.default",
                    "policy_version": "food-freshness/v1",
                },
            },
        }
    )
    return CollectRequest(
        query=query,
        source_scope=("xhs",),
        source_queries={
            "xhs": SourceQueryProjection(
                source_id="xhs",
                text=keyword,
                language=query.isolation.language,
                renderer_id="food.xhs",
                renderer_version="source-query/v1",
                locality="自贡",
            )
        },
        depth="standard",
    )


def _empty_orchestrator(
    intent: FoodSearchIntent,
) -> tuple[XHSFoodOrchestrator, _EmptySearchExecutor]:
    executor = _EmptySearchExecutor()
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=MCPToolRegistry(),
        intent_parser=cast(Any, _IntentParser(intent)),
        analyzer=cast(Any, object()),
        search_executor=cast(Any, executor),
    )
    return orchestrator, executor


async def _collect_events(bus: InMemoryEventBus, session_id: str) -> list[Any]:
    return [event async for _, event in bus.subscribe(session_id)]


def _assert_no_partial_wire_field(value: object) -> None:
    if isinstance(value, dict):
        assert "partial" not in value
        for item in value.values():
            _assert_no_partial_wire_field(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_partial_wire_field(item)


def _aggregate_xhs_batches(
    batches: list[CanonicalSourceBatch],
) -> CanonicalSourceBatch:
    assert batches
    documents = tuple(document for batch in batches for document in batch.documents)
    errors = tuple(error for batch in batches for error in batch.errors)
    attempts = []
    error_offset = 0
    for index, batch in enumerate(batches, 1):
        assert batch.coverage is not None
        attempt = batch.coverage.attempts[0]
        attempts.append(
            attempt.model_copy(
                update={
                    "attempt_id": f"xhs_search-{index}",
                    "error_indexes": tuple(
                        error_offset + error_index for error_index in attempt.error_indexes
                    ),
                }
            )
        )
        error_offset += len(batch.errors)

    first = batches[0]
    return CanonicalSourceBatch(
        isolation=first.isolation,
        source_id=first.source_id,
        connector_id=first.connector_id,
        connector_version=first.connector_version,
        normalizer_version=first.normalizer_version,
        documents=documents,
        watermark=None,
        errors=errors,
        coverage=SourceCoverageMetadata(
            eligible_item_count=len(documents),
            attempts=tuple(attempts),
        ),
    )


async def test_direct_empty_xhs_result_remains_ok_with_no_recommendations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = _intent()
    executor = SearchExecutor(
        xhs_registry=MCPToolRegistry(),
        analyzer=cast(Any, object()),
        context=ConversationContext(),
    )

    async def _no_notes(
        requested_intent: FoodSearchIntent,
    ) -> list[dict[str, Any]]:
        assert requested_intent is intent
        return []

    monkeypatch.setattr(executor, "execute_4_stage_search", _no_notes)

    response = await executor.handle_new_search(IntentParseResult(success=True, intent=intent))

    assert response.status == "ok"
    assert response.recommendations == []
    assert response.filtered_count == 0
    assert response.error_message is None
    assert response.summary == "未找到关于 自贡 的相关笔记"


async def test_empty_xhs_stream_outer_task_and_read_views_keep_legacy_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-empty-xhs"
    query = "自贡本地菜"
    intent = _intent()
    orchestrator, executor = _empty_orchestrator(intent)
    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)
    manager = _Manager()
    storage = _Storage()
    state: dict[str, Any] = {
        "id": session_id,
        "status": "loading",
        "query": query,
        "turn_id": 1,
        "summary": "",
        "filtered_count": 0,
        "error": None,
        "restaurants": [],
    }
    state_updates: list[dict[str, Any]] = []

    async def _get_emitter(requested_session_id: str) -> SearchEventEmitter:
        assert requested_session_id == session_id
        return emitter

    async def _get_manager() -> _Manager:
        return manager

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _update_state(requested_session_id: str, **changes: Any) -> dict[str, Any]:
        assert requested_session_id == session_id
        state_updates.append(changes)
        state.update(changes)
        return state

    monkeypatch.setattr(search_tasks, "get_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(search_tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(search_tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(search_tasks, "load_state", _load_state)
    monkeypatch.setattr(search_tasks, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    await search_tasks.run_stream_search(session_id, query)

    events = [event async for _, event in bus.subscribe(session_id)]
    event_types = [event.type for event in events]
    assert event_types == [
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_ERROR,
        SearchEventType.ERROR,
    ]
    assert events[-2].data["step"] == "step2"
    assert events[-2].data["error"] == "未找到相关笔记"
    assert events[-1].data == {"error": "未找到相关笔记"}
    assert SearchEventType.RESULT not in event_types
    assert SearchEventType.DONE not in event_types

    assert executor.reset_count == 1
    assert executor.intents == [intent]
    assert state_updates == [
        {"status": "completed"},
        {"restaurants": [], "summary": ""},
    ]
    assert state["status"] == "completed"
    assert storage.history_updates == [(session_id, "completed", 0)]
    assert storage.records == [
        {
            "turn_id": 1,
            "created_at": "2026-08-20T12:00:00+08:00",
            "session_id": session_id,
            "restaurants": [],
            "summary": "",
            "filtered_count": 0,
            "query": query,
        }
    ]

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status == {
        "sessionId": session_id,
        "status": "completed",
        "loadingSteps": emitter.steps,
    }
    assert results == {
        "sessionId": session_id,
        "restaurants": [],
        "summary": "",
    }
    assert recovered == {
        "success": True,
        "data": {
            "sessionId": session_id,
            "status": "completed",
            "turnId": 1,
            "query": query,
            "restaurants": [],
            "summary": "",
            "total": 0,
            "turns": [
                {
                    "turnId": 1,
                    "query": query,
                    "restaurants": [],
                    "summary": "",
                    "total": 0,
                    "createdAt": "2026-08-20T12:00:00+08:00",
                }
            ],
            "turnCount": 1,
            "fromDatabase": True,
        },
    }


@pytest.mark.parametrize(
    ("provider_result", "provider_error"),
    (
        pytest.param(None, TimeoutError("timed out"), id="timeout"),
        pytest.param(
            ToolResult.fail("HTTP_429", "rate limited"),
            None,
            id="rate-limit",
        ),
        pytest.param(
            ToolResult.ok({"notes": "not-a-list"}),
            None,
            id="malformed",
        ),
        pytest.param(
            ToolResult.fail("SEARCH_FAILED", "dependency unavailable"),
            None,
            id="dependency-unavailable",
        ),
        pytest.param(None, RuntimeError("provider exploded"), id="provider-exception"),
    ),
)
async def test_required_xhs_failure_matrix_crosses_outer_task_and_read_views(
    provider_result: ToolResult | None,
    provider_error: Exception | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-required-xhs-failure"
    query = "自贡本地菜"
    intent = _intent()
    provider = _XHSSearchTool(provider_result, error=provider_error)
    registry = MCPToolRegistry()
    registry.register(provider)
    executor = SearchExecutor(
        xhs_registry=registry,
        analyzer=cast(Any, object()),
        context=ConversationContext(),
    )
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=registry,
        intent_parser=cast(Any, _IntentParser(intent)),
        analyzer=cast(Any, object()),
        search_executor=executor,
    )
    direct_response = await executor.handle_new_search(
        IntentParseResult(success=True, intent=intent)
    )
    assert direct_response.status == "ok"
    assert direct_response.recommendations == []
    assert direct_response.error_message is None
    assert direct_response.summary == "未找到关于 自贡 的相关笔记"
    provider.calls.clear()

    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)
    manager = _Manager()
    storage = _Storage()
    state: dict[str, Any] = {
        "id": session_id,
        "status": "loading",
        "query": query,
        "turn_id": 1,
        "summary": "",
        "filtered_count": 0,
        "error": None,
        "restaurants": [],
    }

    async def _get_emitter(requested_session_id: str) -> SearchEventEmitter:
        assert requested_session_id == session_id
        return emitter

    async def _get_manager() -> _Manager:
        return manager

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _update_state(requested_session_id: str, **changes: Any) -> dict[str, Any]:
        assert requested_session_id == session_id
        state.update(changes)
        return state

    monkeypatch.setattr(search_tasks, "get_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(search_tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(search_tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(search_tasks, "load_state", _load_state)
    monkeypatch.setattr(search_tasks, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    await search_tasks.run_stream_search(session_id, query)

    events = await _collect_events(bus, session_id)
    assert [event.type for event in events] == [
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_ERROR,
        SearchEventType.ERROR,
    ]
    assert events[-2].data == {
        "step": "step2",
        "error": "未找到相关笔记",
        "steps": emitter.steps,
    }
    assert events[-1].data == {"error": "未找到相关笔记"}
    assert len(provider.calls) == 8
    assert state["status"] == "completed"
    assert storage.history_updates == [(session_id, "completed", 0)]

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status == {
        "sessionId": session_id,
        "status": "completed",
        "loadingSteps": emitter.steps,
    }
    assert results == {
        "sessionId": session_id,
        "restaurants": [],
        "summary": "",
    }
    assert recovered["success"] is True
    recovery_data = cast(dict[str, Any], recovered["data"])
    assert recovery_data["status"] == "completed"
    assert recovery_data["restaurants"] == []
    assert recovery_data["summary"] == ""
    assert recovery_data["total"] == 0
    _assert_no_partial_wire_field([[event.data for event in events], status, results, recovered])


async def test_mixed_xhs_source_partial_keeps_successful_outer_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-mixed-xhs-partial"
    query = "自贡本地菜"
    intent = _intent()
    surviving = RestaurantRecommendation(
        name="Surviving Restaurant",
        location="自流井区同兴路",
        features=["本地口味"],
        source_notes=["note-survivor"],
        confidence=0.8,
    )
    analyzer = _PartialAnalyzer(surviving)
    source_provider = _SequencedXHSProvider(
        "xhs_search",
        (
            ToolResult.fail("SEARCH_FAILED", "dependency unavailable"),
            ToolResult.ok(
                {
                    "notes": [
                        {
                            "id": "note-survivor",
                            "title": "Surviving Restaurant",
                            "desc": "fixture",
                        }
                    ]
                }
            ),
        ),
    )
    connector = XHSSourceConnector(
        search_provider=source_provider,
        note_provider=_SequencedXHSProvider(
            "xhs_note", (ToolResult.ok({"note": {"id": "unused"}}),)
        ),
        batch_provider=_SequencedXHSProvider("xhs_batch", (ToolResult.ok({"results": {}}),)),
    )
    search_tool = _CanonicalLegacySearchTool(connector)
    registry = MCPToolRegistry()
    registry.register(search_tool)
    executor = SearchExecutor(
        xhs_registry=registry,
        analyzer=cast(Any, analyzer),
        context=ConversationContext(),
        fast_mode_limit=1,
    )
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=registry,
        intent_parser=cast(Any, _IntentParser(intent)),
        analyzer=cast(Any, analyzer),
        search_executor=executor,
    )
    monkeypatch.setattr(agents_module, "get_poi_enricher", lambda: _BasicEnricher())

    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)
    manager = _Manager()
    storage = _Storage()
    state: dict[str, Any] = {
        "id": session_id,
        "status": "loading",
        "query": query,
        "turn_id": 1,
        "summary": "",
        "filtered_count": 0,
        "error": None,
        "restaurants": [],
    }

    async def _get_emitter(requested_session_id: str) -> SearchEventEmitter:
        assert requested_session_id == session_id
        return emitter

    async def _get_manager() -> _Manager:
        return manager

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _update_state(requested_session_id: str, **changes: Any) -> dict[str, Any]:
        assert requested_session_id == session_id
        state.update(changes)
        return state

    monkeypatch.setattr(search_tasks, "get_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(search_tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(search_tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(search_tasks, "load_state", _load_state)
    monkeypatch.setattr(search_tasks, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    await search_tasks.run_stream_search(session_id, query)

    assert [call["keyword"] for call in source_provider.calls] == [
        "自贡 本地人 老店",
        "自贡 本地菜 地道",
    ]
    aggregate = _aggregate_xhs_batches(search_tool.batches)
    outcome = classify_batch(aggregate)
    assert outcome.kind is SourceOutcomeKind.PARTIAL
    assert outcome.item_count == 1
    assert [document.external_id for document in aggregate.documents] == ["note-survivor"]
    assert [error.code for error in aggregate.errors] == ["SEARCH_FAILED"]
    assert aggregate.errors[0].category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert aggregate.errors[0].scope is ErrorScope.SOURCE
    assert aggregate.coverage is not None
    assert aggregate.coverage.eligible_item_count == 1
    assert [attempt.outcome for attempt in aggregate.coverage.attempts] == [
        SourceAttemptOutcome.FAILURE,
        SourceAttemptOutcome.SUCCESS_NONEMPTY,
    ]
    assert project_legacy_xhs(outcome) is LegacySourceProjection.CONTINUE

    events = await _collect_events(bus, session_id)
    event_types = [event.type for event in events]
    assert analyzer.note_ids == ["note-survivor"]
    assert event_types == [
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.RESTAURANT,
        SearchEventType.STEP_DONE,
        SearchEventType.RESULT,
        SearchEventType.DONE,
    ]
    restaurant_event = next(event for event in events if event.type is SearchEventType.RESTAURANT)
    assert restaurant_event.data["restaurant"]["name"] == surviving.name
    assert events[-2].data == {
        "summary": "在自贡找到 1 家推荐店铺",
        "total": 1,
        "filtered": 0,
        "steps": emitter.steps,
    }
    assert events[-1].data == {"message": "搜索完成"}

    assert state["status"] == "completed"
    assert state["summary"] == ""
    assert len(state["restaurants"]) == 1
    persisted = cast(dict[str, Any], state["restaurants"][0])
    assert persisted["name"] == surviving.name
    assert storage.history_updates == [(session_id, "completed", 1)]

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status == {
        "sessionId": session_id,
        "status": "completed",
        "loadingSteps": emitter.steps,
    }
    assert results == {
        "sessionId": session_id,
        "restaurants": [persisted],
        "summary": "",
    }
    assert recovered == {
        "success": True,
        "data": {
            "sessionId": session_id,
            "status": "completed",
            "turnId": 1,
            "query": query,
            "restaurants": [persisted],
            "summary": "",
            "total": 1,
            "turns": [
                {
                    "turnId": 1,
                    "query": query,
                    "restaurants": [persisted],
                    "summary": "",
                    "total": 1,
                    "createdAt": "2026-08-20T12:00:00+08:00",
                }
            ],
            "turnCount": 1,
            "fromDatabase": True,
        },
    }
    _assert_no_partial_wire_field([[event.data for event in events], status, results, recovered])


async def test_refine_with_existing_result_and_new_empty_run_preserves_legacy_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-refine-empty"
    query = "继续找本地馆子"
    previous_query = "自贡本地菜"
    previous_summary = "上一轮找到 1 家店铺"
    previous = RestaurantRecommendation(
        name="Previous Restaurant",
        location="Previous District",
        features=["previous"],
        source_notes=["old-note"],
        confidence=0.7,
    )
    provider = _XHSSearchTool(ToolResult.ok({"notes": []}))
    registry = MCPToolRegistry()
    registry.register(provider)
    executor = SearchExecutor(
        xhs_registry=registry,
        analyzer=cast(Any, object()),
        context=ConversationContext(),
    )
    follow_up = _NewSearchFollowUp()
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=registry,
        intent_parser=cast(Any, _IntentParser(_intent())),
        analyzer=cast(Any, object()),
        follow_up_handler=cast(Any, follow_up),
        search_executor=executor,
    )
    orchestrator.update_context_recommendation(previous.name, previous.to_dict())
    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)
    manager = _Manager()
    storage = _Storage()
    storage.records.append(
        {
            "session_id": session_id,
            "turn_id": 1,
            "query": previous_query,
            "restaurants": [previous.to_dict()],
            "summary": previous_summary,
            "created_at": "2026-08-20T11:55:00+08:00",
        }
    )
    state: dict[str, Any] = {
        "id": session_id,
        "status": "loading",
        "query": query,
        "turn_id": 2,
        "summary": previous_summary,
        "filtered_count": 0,
        "error": None,
        "restaurants": [previous.to_dict()],
    }

    async def _get_emitter(requested_session_id: str) -> SearchEventEmitter:
        assert requested_session_id == session_id
        return emitter

    async def _get_manager() -> _Manager:
        return manager

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _update_state(requested_session_id: str, **changes: Any) -> dict[str, Any]:
        assert requested_session_id == session_id
        state.update(changes)
        return state

    monkeypatch.setattr(search_tasks, "get_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(search_tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(search_tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(search_tasks, "load_state", _load_state)
    monkeypatch.setattr(search_tasks, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    await search_tasks.run_stream_search(session_id, query)

    events = await _collect_events(bus, session_id)
    assert follow_up.queries == [query]
    assert [event.type for event in events] == [
        SearchEventType.STEP_START,
        SearchEventType.STEP_DONE,
        SearchEventType.STEP_START,
        SearchEventType.STEP_ERROR,
        SearchEventType.ERROR,
    ]
    assert events[-1].data == {"error": "未找到相关笔记"}
    assert SearchEventType.RESULT not in [event.type for event in events]
    assert SearchEventType.DONE not in [event.type for event in events]
    assert len(provider.calls) == 8
    assert state["status"] == "completed"
    assert state["summary"] == previous_summary
    assert [restaurant["name"] for restaurant in state["restaurants"]] == [previous.name]
    assert storage.history_updates == [(session_id, "completed", 1)]
    assert len(storage.records) == 2
    assert storage.records[-1]["query"] == query
    assert storage.records[-1]["summary"] == previous_summary
    assert [restaurant["name"] for restaurant in storage.records[-1]["restaurants"]] == [
        previous.name
    ]

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status is not None
    assert status["status"] == "completed"
    assert results is not None
    assert results["summary"] == previous_summary
    result_restaurants = cast(list[dict[str, Any]], results["restaurants"])
    assert [restaurant["name"] for restaurant in result_restaurants] == [previous.name]
    recovery_data = cast(dict[str, Any], recovered["data"])
    assert recovery_data["status"] == "completed"
    assert recovery_data["turnId"] == 2
    assert recovery_data["query"] == query
    assert recovery_data["summary"] == previous_summary
    assert [restaurant["name"] for restaurant in recovery_data["restaurants"]] == [previous.name]
    recovery_turns = cast(list[dict[str, Any]], recovery_data["turns"])
    assert [turn["turnId"] for turn in recovery_turns] == [1, 2]
    assert [turn["query"] for turn in recovery_turns] == [previous_query, query]
    assert [restaurant["name"] for restaurant in recovery_turns[-1]["restaurants"]] == [
        previous.name
    ]
    _assert_no_partial_wire_field([[event.data for event in events], status, results, recovered])


async def test_refine_partial_analyzer_keeps_survivor_existing_result_and_read_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-refine-partial"
    query = "继续找本地馆子"
    intent = _intent()
    previous = RestaurantRecommendation(
        name="Previous Restaurant",
        location="Previous District",
        features=["previous"],
        source_notes=["old-note"],
        confidence=0.7,
    )
    surviving = RestaurantRecommendation(
        name="Surviving Restaurant",
        location="New District",
        features=["surviving"],
        source_notes=["note-valid"],
        confidence=0.8,
    )
    analyzer = _PartialAnalyzer(surviving)
    executor = SearchExecutor(
        xhs_registry=MCPToolRegistry(),
        analyzer=cast(Any, analyzer),
        context=ConversationContext(),
    )

    async def _partial_notes(
        requested_intent: FoodSearchIntent,
    ) -> list[dict[str, Any]]:
        assert requested_intent is intent
        return [
            {"id": "note-valid", "title": "valid"},
            {"id": "note-failed", "title": "analyzer fails"},
        ]

    monkeypatch.setattr(executor, "execute_4_stage_search", _partial_notes)
    follow_up = _NewSearchFollowUp()
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=MCPToolRegistry(),
        intent_parser=cast(Any, _IntentParser(intent)),
        analyzer=cast(Any, analyzer),
        follow_up_handler=cast(Any, follow_up),
        search_executor=executor,
    )
    orchestrator.update_context_recommendation(previous.name, previous.to_dict())
    monkeypatch.setattr(agents_module, "get_poi_enricher", lambda: _BasicEnricher())

    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)
    manager = _Manager()
    storage = _Storage()
    state: dict[str, Any] = {
        "id": session_id,
        "status": "loading",
        "query": query,
        "turn_id": 2,
        "summary": "previous summary",
        "filtered_count": 0,
        "error": None,
        "restaurants": [previous.to_dict()],
    }

    async def _get_emitter(requested_session_id: str) -> SearchEventEmitter:
        assert requested_session_id == session_id
        return emitter

    async def _get_manager() -> _Manager:
        return manager

    async def _get_storage() -> _Storage:
        return storage

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _update_state(requested_session_id: str, **changes: Any) -> dict[str, Any]:
        assert requested_session_id == session_id
        state.update(changes)
        return state

    monkeypatch.setattr(search_tasks, "get_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(search_tasks, "get_emitter", _get_emitter)
    monkeypatch.setattr(search_tasks, "get_session_manager", _get_manager)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(search_tasks, "load_state", _load_state)
    monkeypatch.setattr(search_tasks, "update_state", _update_state)
    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_emitter)

    await search_tasks.run_stream_search(session_id, query)

    events = await _collect_events(bus, session_id)
    event_types = [event.type for event in events]
    assert analyzer.note_ids == ["note-valid", "note-failed"]
    assert follow_up.queries == [query]
    assert SearchEventType.ERROR not in event_types
    assert SearchEventType.STEP_ERROR not in event_types
    assert event_types[-2:] == [SearchEventType.RESULT, SearchEventType.DONE]
    result_event = next(event for event in events if event.type is SearchEventType.RESULT)
    assert result_event.data["total"] == 1
    _assert_no_partial_wire_field([event.data for event in events])

    persisted_names = [restaurant["name"] for restaurant in state["restaurants"]]
    assert persisted_names == [previous.name, surviving.name]
    assert state["status"] == "completed"

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status is not None
    assert status["status"] == "completed"
    assert results is not None
    result_restaurants = cast(list[dict[str, Any]], results["restaurants"])
    assert [restaurant["name"] for restaurant in result_restaurants] == [
        previous.name,
        surviving.name,
    ]
    recovery_data = cast(dict[str, Any], recovered["data"])
    assert [restaurant["name"] for restaurant in recovery_data["restaurants"]] == [
        previous.name,
        surviving.name,
    ]
    _assert_no_partial_wire_field([status, results, recovered])


async def test_amap_empty_and_failure_keep_the_same_basic_restaurant_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommendation = RestaurantRecommendation(
        name="盐帮馆子",
        location="自流井区同兴路",
        features=["本地口味"],
        source_notes=["note-1"],
        confidence=0.8,
    )
    empty_client = _AmapClient({"pois": []})
    failed_client = _AmapClient({"error": "AMAP_UNAVAILABLE"})
    empty_enricher = POIEnricherAgent(amap_api=cast(Any, empty_client))
    failed_enricher = POIEnricherAgent(amap_api=cast(Any, failed_client))

    async def _cache_miss(name: str) -> None:
        assert name == recommendation.name
        return None

    monkeypatch.setattr(empty_enricher, "_get_cached_poi", _cache_miss)
    monkeypatch.setattr(failed_enricher, "_get_cached_poi", _cache_miss)

    empty_result = (await empty_enricher.enrich([recommendation]))[0]
    failed_result = (await failed_enricher.enrich([recommendation]))[0]

    assert empty_result.to_dict() == failed_result.to_dict()
    assert empty_result.name == recommendation.name
    assert empty_result.address == recommendation.location
    assert empty_result.location is None
    assert empty_result.tel is None
    assert (
        empty_client.calls
        == failed_client.calls
        == [{"keywords": recommendation.name, "city": "", "types": "050000"}]
    )

    session_id = "adr-0010-basic-poi"
    basic_restaurant = empty_result.to_dict()
    state = {
        "status": "completed",
        "restaurants": [basic_restaurant],
        "summary": "保留基础餐厅结果",
    }
    storage = _Storage()
    storage.records.append(
        {
            "session_id": session_id,
            "turn_id": 1,
            "query": "自贡本地菜",
            "restaurants": [basic_restaurant],
            "summary": "保留基础餐厅结果",
            "created_at": "2026-08-20T12:00:00+08:00",
        }
    )

    async def _load_state(requested_session_id: str) -> dict[str, Any] | None:
        return state if requested_session_id == session_id else None

    async def _get_storage() -> _Storage:
        return storage

    class _ReadEmitter:
        steps = [{"id": "step5", "status": "done", "message": "完成 POI 补充"}]

    async def _get_read_emitter(requested_session_id: str) -> _ReadEmitter:
        assert requested_session_id == session_id
        return _ReadEmitter()

    monkeypatch.setattr(legacy_research_task.legacy_state, "load_state", _load_state)
    monkeypatch.setattr(legacy_research_task, "get_emitter", _get_read_emitter)
    monkeypatch.setattr(search_tasks, "get_user_storage_service", _get_storage)

    facade = LegacyResearchTaskFacade()
    status = await facade.status(session_id)
    results = await facade.results(session_id)
    recovered = await facade.recover(session_id)

    assert status == {
        "sessionId": session_id,
        "status": "completed",
        "loadingSteps": _ReadEmitter.steps,
    }
    assert results == {
        "sessionId": session_id,
        "restaurants": [basic_restaurant],
        "summary": "保留基础餐厅结果",
    }
    recovery_data = cast(dict[str, Any], recovered["data"])
    recovery_turns = cast(list[dict[str, Any]], recovery_data["turns"])
    assert recovered["success"] is True
    assert recovery_data["status"] == "completed"
    assert recovery_data["restaurants"] == [basic_restaurant]
    assert recovery_turns[0]["restaurants"] == [basic_restaurant]


@pytest.mark.parametrize(
    "amap_payload",
    (
        pytest.param({"pois": []}, id="success-empty"),
        pytest.param({"error": "AMAP_UNAVAILABLE"}, id="failure"),
    ),
)
async def test_optional_poi_empty_or_failure_streams_basic_restaurant_result_and_done(
    amap_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "adr-0010-poi-stream"
    recommendation = RestaurantRecommendation(
        name="盐帮馆子",
        location="自流井区同兴路",
        features=["本地口味"],
        source_notes=["note-1"],
        confidence=0.8,
    )
    client = _AmapClient(amap_payload)
    enricher = POIEnricherAgent(amap_api=cast(Any, client))

    async def _cache_miss(name: str) -> None:
        assert name == recommendation.name
        return None

    monkeypatch.setattr(enricher, "_get_cached_poi", _cache_miss)
    monkeypatch.setattr(agents_module, "get_poi_enricher", lambda: enricher)
    executor = _SuccessfulSearchExecutor(recommendation)
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=MCPToolRegistry(),
        intent_parser=cast(Any, _IntentParser(_intent())),
        analyzer=cast(Any, object()),
        search_executor=cast(Any, executor),
    )
    bus = InMemoryEventBus()
    emitter = SearchEventEmitter(session_id, bus)

    await orchestrator.search_stream("自贡本地菜", emitter)

    events = await _collect_events(bus, session_id)
    event_types = [event.type for event in events]
    assert SearchEventType.ERROR not in event_types
    assert SearchEventType.STEP_ERROR not in event_types
    assert event_types[-4:] == [
        SearchEventType.RESTAURANT,
        SearchEventType.STEP_DONE,
        SearchEventType.RESULT,
        SearchEventType.DONE,
    ]
    restaurant_event = events[-4]
    restaurant = cast(dict[str, Any], restaurant_event.data["restaurant"])
    assert restaurant["name"] == recommendation.name
    assert restaurant["address"] == recommendation.location
    assert restaurant["location"] is None
    assert restaurant["tel"] is None
    assert events[-2].data["total"] == 1
    assert events[-1].data == {"message": "搜索完成"}
    _assert_no_partial_wire_field([event.data for event in events])
    assert client.calls == [
        {"keywords": recommendation.name, "city": "自贡", "types": "050000"},
        {"keywords": recommendation.name, "city": "", "types": "050000"},
    ]
