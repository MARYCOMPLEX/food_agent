"""Characterize the current Food search and follow-up decision pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from xhs_food.composition.managed_search import ManagedSearchResult
from xhs_food.orchestrator.follow_up import FollowUpHandler
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.schemas import (
    ConversationContext,
    FoodSearchIntent,
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)

_FIXTURE = json.loads(
    (
        Path(__file__).parent
        / "fixtures/characterization/food_search_behavior.json"
    ).read_text(encoding="utf-8")
)


class _SearchTool:
    def __init__(self, responses: list[list[dict[str, Any]]] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> ManagedSearchResult:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        if index < len(self.responses):
            notes = self.responses[index]
        else:
            number = index + 1
            notes = [{"id": f"note-{number}", "title": f"第{number}店 探店"}]
        return ManagedSearchResult(success=True, data={"notes": notes})

    async def health(self) -> bool:
        return True


class _Analyzer:
    pass


def _executor(
    tool: _SearchTool,
    *,
    context: ConversationContext | None = None,
    deep_search: bool = False,
    fast_mode_limit: int = 15,
) -> SearchExecutor:
    return SearchExecutor(
        search_tool=tool,
        analyzer=_Analyzer(),
        context=context or ConversationContext(),
        deep_search=deep_search,
        fast_mode_limit=fast_mode_limit,
        notes_per_keyword=4,
        max_restaurants=10,
        analyze_concurrency=2,
    )


def _intent() -> FoodSearchIntent:
    return FoodSearchIntent.from_dict(_FIXTURE["intent"])


def _analysis(
    score: WanghongScore,
    confidence: float,
    *,
    local: bool = False,
    reasons: list[str] | None = None,
) -> WanghongAnalysis:
    return WanghongAnalysis(
        score=score,
        confidence=confidence,
        reasons=reasons or [],
        has_local_mentions=local,
    )


def test_four_stage_and_expand_keyword_snapshots() -> None:
    executor = _executor(_SearchTool())
    intent = _intent()

    assert executor.generate_phase1_keywords(intent) == _FIXTURE["phase1_keywords"]
    assert executor.generate_phase2_keywords(intent) == _FIXTURE["phase2_keywords"]


async def test_fast_mode_stops_after_reaching_note_limit() -> None:
    tool = _SearchTool(
        [[{"id": "note-1", "title": "一号店"}, {"id": "note-2", "title": "二号馆"}]]
    )
    executor = _executor(tool, fast_mode_limit=2)

    notes = await executor.execute_4_stage_search(_intent())

    assert [note["id"] for note in notes] == ["note-1", "note-2"]
    assert [call["keyword"] for call in tool.calls] == [_FIXTURE["phase1_keywords"][0]]


async def test_deep_mode_runs_all_four_stages_without_fast_stop() -> None:
    tool = _SearchTool()
    executor = _executor(tool, deep_search=True, fast_mode_limit=1)

    notes = await executor.execute_4_stage_search(_intent())
    keywords = [call["keyword"] for call in tool.calls]

    assert len(notes) == 10
    assert keywords[:3] == _FIXTURE["phase1_keywords"][:3]
    assert keywords[3:6] == _FIXTURE["phase2_keywords"][:3]
    assert keywords[6:8] == ["自贡 第1店 探店", "自贡 第2店 第3店"]
    assert keywords[8:] == ["自贡 火锅 老店", "自贡 火锅 本地人"]


async def test_note_ids_are_deduplicated_across_keyword_calls() -> None:
    repeated = {"id": "same-note", "title": "同一家店"}
    tool = _SearchTool([[repeated, {"id": "note-a"}], [repeated, {"note_id": "note-b"}]])
    executor = _executor(tool)
    seen_ids: set[str] = set()

    first = await executor.search_with_keyword(tool, "关键词一", seen_ids)
    second = await executor.search_with_keyword(tool, "关键词二", seen_ids)

    assert first == [repeated, {"id": "note-a"}]
    assert second == [{"note_id": "note-b"}]
    assert seen_ids == {"same-note", "note-a", "note-b"}
    assert all(
        call
        == {
            "keyword": keyword,
            "count": 4,
            "sort_type": "most_comments",
            "include_details": True,
            "include_comments": True,
        }
        for call, keyword in zip(tool.calls, ["关键词一", "关键词二"], strict=True)
    )


async def test_expand_search_uses_distinct_keywords_and_skips_previous_notes() -> None:
    previous = {"id": "old-note", "title": "旧店"}
    tool = _SearchTool(
        [
            [previous, {"id": "expand-1"}],
            [previous, {"id": "expand-2"}],
            [previous, {"id": "expand-3"}],
        ]
    )
    context = ConversationContext(last_notes=[previous])
    executor = _executor(tool, context=context)

    notes = await executor.execute_expand_search(_intent())

    assert [call["keyword"] for call in tool.calls] == _FIXTURE["expand_keywords"]
    assert [note["id"] for note in notes] == ["expand-1", "expand-2", "expand-3"]


def test_merge_cross_validation_and_wanghong_filter_are_frozen() -> None:
    executor = _executor(_SearchTool())
    local_first = RestaurantRecommendation(
        name="老 灶店",
        features=["老店"],
        source_notes=["n1"],
        confidence=0.8,
        wanghong_analysis=_analysis(WanghongScore.LIKELY_LOCAL, 0.8),
    )
    local_second = RestaurantRecommendation(
        name="老灶店",
        features=["夜宵", "老店"],
        source_notes=["n2", "n3"],
        confidence=0.9,
        wanghong_analysis=_analysis(WanghongScore.LIKELY_LOCAL, 0.9, local=True),
    )
    wanghong = RestaurantRecommendation(
        name="打卡店",
        source_notes=["n4", "n5"],
        confidence=0.95,
        wanghong_analysis=_analysis(
            WanghongScore.DEFINITELY_WANGHONG,
            0.95,
            reasons=["拍照导向", "排队营销", "第三条不会进入原因"],
        ),
    )

    merged = executor.merge_and_validate(
        [local_first, local_second, wanghong, RestaurantRecommendation(name="未知")]
    )

    assert [item.name for item in merged] == ["老 灶店", "打卡店"]
    assert merged[0].source_notes == ["n1", "n2", "n3"]
    assert merged[0].features == ["老店", "夜宵"]
    assert merged[0].confidence == 1.0
    assert merged[0].wanghong_analysis is local_second.wanghong_analysis
    assert merged[1].is_recommended is False
    assert merged[1].filter_reason == "判定为网红店: 拍照导向, 排队营销"


async def test_new_search_filters_exclusions_and_sorts_by_confidence_then_sources(
    monkeypatch,
) -> None:
    context = ConversationContext(excluded_shops=["排除店"])
    executor = _executor(_SearchTool(), context=context)
    intent = _intent()
    candidates = [
        RestaurantRecommendation(name="来源多", confidence=0.8, source_notes=["1", "2"]),
        RestaurantRecommendation(name="来源少", confidence=0.8, source_notes=["1"]),
        RestaurantRecommendation(name="高置信", confidence=0.9, source_notes=["1"]),
        RestaurantRecommendation(name="排除店分店", confidence=1.0, source_notes=["1"]),
    ]

    async def _notes(_: FoodSearchIntent) -> list[dict[str, str]]:
        return [{"id": "fixture-note"}]

    async def _restaurants(
        notes: list[dict[str, str]], requested_intent: FoodSearchIntent
    ) -> list[RestaurantRecommendation]:
        assert notes == [{"id": "fixture-note"}]
        assert requested_intent is intent
        return candidates

    monkeypatch.setattr(executor, "execute_4_stage_search", _notes)
    monkeypatch.setattr(executor, "analyze_notes_concurrent", _restaurants)

    response = await executor.handle_new_search(SimpleNamespace(intent=intent))

    assert [item.name for item in response.recommendations] == ["高置信", "来源多", "来源少"]
    assert response.filtered_count == 1
    assert context.last_intent == _FIXTURE["intent"]
    assert context.last_notes == [{"id": "fixture-note"}]
    assert context.turn_count == 1


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _FollowUpLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[list[Any]] = []

    async def call(self, messages: list[Any]) -> _Message:
        self.calls.append(messages)
        return _Message(json.dumps(self.payload, ensure_ascii=False))


async def test_follow_up_uses_frozen_llm_selection_without_new_search() -> None:
    context = ConversationContext()
    context.add_user_message("自贡火锅")
    context.add_recommendations(
        [
            RestaurantRecommendation(name="老灶火锅", features=["牛油"], location="同兴路"),
            RestaurantRecommendation(name="另一家店", features=["清油"], location="汇东"),
        ]
    )
    llm = _FollowUpLLM(_FIXTURE["follow_up_llm"])
    handler = FollowUpHandler(context, llm_service=llm)

    response = await handler.process_follow_up_with_llm("只保留第一家")

    assert response is not None
    assert [item.name for item in response.recommendations] == ["老灶火锅"]
    assert response.filtered_count == 1
    assert response.summary == _FIXTURE["follow_up_llm"]["response"]
    assert context.turn_count == 1
    assert len(llm.calls) == 1


async def test_follow_up_new_search_signal_returns_control_to_orchestrator() -> None:
    context = ConversationContext()
    context.add_user_message("换成成都串串")
    handler = FollowUpHandler(
        context,
        llm_service=_FollowUpLLM({"shops": [], "response": "重新搜索", "new_search": True}),
    )

    assert await handler.process_follow_up_with_llm("换个城市") is None
    assert context.turn_count == 0
