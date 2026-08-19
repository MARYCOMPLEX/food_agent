"""Focused compatibility tests for the pure Stable Result Mapper."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from xhs_food.contracts import RecommendationSnapshot, ResearchResultSnapshot
from xhs_food.experience import StableResultMapper

AUTHORITY = Path(__file__).parent / "fixtures" / "authority" / "food_dto_v1.json"


def _food_dto() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(AUTHORITY.read_text(encoding="utf-8"))["dto"])


def test_http_results_preserve_legacy_envelope_keys_defaults_and_nested_values() -> None:
    mapper = StableResultMapper()
    restaurants = [{"name": "老灶火锅", "tags": ["火锅"], "trustScore": 8.8}]
    state = {
        "status": "completed",
        "restaurants": restaurants,
        "summary": "共找到 1 家。",
        "ignored": "not part of the frozen results view",
    }

    mapped = mapper.to_http_results("session-中文", state)

    assert mapped == {
        "sessionId": "session-中文",
        "restaurants": restaurants,
        "summary": "共找到 1 家。",
    }
    restaurants[0]["tags"].append("source mutation")
    cast(list[dict[str, Any]], mapped["restaurants"])[0]["tags"].append("output mutation")
    assert mapped["restaurants"] == [
        {"name": "老灶火锅", "tags": ["火锅", "output mutation"], "trustScore": 8.8}
    ]
    assert state["restaurants"] == [
        {"name": "老灶火锅", "tags": ["火锅", "source mutation"], "trustScore": 8.8}
    ]
    assert mapper.to_http_results("empty", {}) == {
        "sessionId": "empty",
        "restaurants": [],
        "summary": "",
    }


def test_completed_recovery_preserves_turn_order_and_current_legacy_shape() -> None:
    mapper = StableResultMapper()
    records = (
        {
            "turn_id": 1,
            "query": "第一轮",
            "restaurants": [{"id": "r-1", "name": "盐帮菜馆"}],
            "summary": "第一轮摘要",
            "created_at": "2026-08-19T10:00:00+00:00",
        },
        {
            "turn_id": 2,
            "query": "第二轮",
            "restaurants": [{"id": "r-2", "name": "老灶火锅"}],
            "summary": "第二轮摘要",
            "created_at": "2026-08-19T11:00:00+00:00",
        },
    )

    mapped = mapper.to_completed_recovery("session-recover", records)

    assert mapped == {
        "success": True,
        "data": {
            "sessionId": "session-recover",
            "status": "completed",
            "turnId": 2,
            "query": "第二轮",
            "restaurants": [{"id": "r-2", "name": "老灶火锅"}],
            "summary": "第二轮摘要",
            "total": 1,
            "turns": [
                {
                    "turnId": 1,
                    "query": "第一轮",
                    "restaurants": [{"id": "r-1", "name": "盐帮菜馆"}],
                    "summary": "第一轮摘要",
                    "total": 1,
                    "createdAt": "2026-08-19T10:00:00+00:00",
                },
                {
                    "turnId": 2,
                    "query": "第二轮",
                    "restaurants": [{"id": "r-2", "name": "老灶火锅"}],
                    "summary": "第二轮摘要",
                    "total": 1,
                    "createdAt": "2026-08-19T11:00:00+00:00",
                },
            ],
            "turnCount": 2,
            "fromDatabase": True,
        },
    }
    cast(list[dict[str, Any]], records[-1]["restaurants"])[0]["name"] = "source mutation"
    assert cast(dict[str, Any], mapped["data"])["restaurants"] == [
        {"id": "r-2", "name": "老灶火锅"}
    ]


def test_sse_views_keep_current_restaurant_and_result_payloads_exact() -> None:
    dto = _food_dto()
    mapper = StableResultMapper()
    enriched = deepcopy(dto["enriched"])
    steps = (
        {"id": "step1", "label": "解析用户意图", "status": "done"},
        {"id": "step2", "label": "搜索小红书笔记", "status": "loading"},
    )
    snapshot = ResearchResultSnapshot(
        recommendations=(RecommendationSnapshot(key="老灶火锅", payload=dto["recommendation"]),),
        presentation_items=(enriched,),
        summary="推荐完成",
        filtered_count=2,
        total_count=3,
    )

    restaurant_event = mapper.to_sse_restaurant(enriched)
    result_event = mapper.to_sse_result(snapshot, steps)

    assert restaurant_event == {"restaurant": dto["enriched"]}
    assert result_event == {
        "summary": "推荐完成",
        "total": 3,
        "filtered": 2,
        "steps": list(steps),
    }
    enriched["tags"].append("source mutation")
    cast(dict[str, Any], restaurant_event["restaurant"])["tags"].append("output mutation")
    assert dto["enriched"]["tags"] == ["火锅"]
    assert restaurant_event["restaurant"] != enriched


def test_sse_result_total_falls_back_to_recommendation_count_without_new_fields() -> None:
    snapshot = ResearchResultSnapshot(
        recommendations=(
            RecommendationSnapshot(key="one", payload={"name": "一店"}),
            RecommendationSnapshot(key="two", payload={"name": "二店"}),
        ),
        presentation_items=({"name": "presentation-only"},),
        summary="共两家",
        filtered_count=1,
    )

    mapped = StableResultMapper().to_sse_result(snapshot, ())

    assert mapped == {"summary": "共两家", "total": 2, "filtered": 1, "steps": []}
    assert "recommendations" not in mapped
    assert "presentationItems" not in mapped


def test_persistence_mapper_matches_authority_without_case_normalization() -> None:
    dto = _food_dto()
    enriched = deepcopy(dto["enriched"])
    original = deepcopy(enriched)

    mapped = StableResultMapper().to_persisted_restaurant(
        enriched,
        "60da14c2146960f98c934c0f75093bd8",
    )

    assert mapped == dto["persistedRestaurant"]
    assert enriched == original
    assert "businessArea" in mapped and "business_area" not in mapped
    assert "sourceNotes" in mapped and "source_notes" not in mapped
    assert "mustTry" in mapped and "must_try" not in mapped
    assert "blackList" in mapped and "black_list" not in mapped


def test_persistence_mapper_overrides_only_the_id_on_an_existing_record() -> None:
    source = {"id": "temporary", "name": "空值店", "warning": None, "tags": []}

    mapped = StableResultMapper().to_persisted_restaurant(source, "stable-id")

    assert mapped == {"id": "stable-id", "name": "空值店", "warning": None, "tags": []}
    assert source["id"] == "temporary"
