"""Golden characterization for legacy Food DTO and persistence shapes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from xhs_food.agents.poi_enricher import EnrichedRestaurant
from xhs_food.schemas import (
    BlackListItem,
    FoodSearchIntent,
    MustTryItem,
    RestaurantRecommendation,
    ShopStats,
    WanghongAnalysis,
    WanghongScore,
    XHSFoodResponse,
)
from xhs_food.services.user_storage.models import Restaurant, generate_restaurant_hash
from xhs_food.services.user_storage.search_results import SearchResultsMixin


_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/characterization/food_dto.json").read_text(encoding="utf-8")
)


def _full_recommendation() -> RestaurantRecommendation:
    return RestaurantRecommendation(
        name="老灶火锅",
        location="自流井区同兴路 8 号",
        features=["牛油锅底", "本地老店"],
        source_notes=["note-甲", "note-乙"],
        confidence=0.875,
        wanghong_analysis=WanghongAnalysis(
            score=WanghongScore.LIKELY_LOCAL,
            confidence=0.875,
            reasons=["本地人口吻"],
            has_negative_service=True,
            has_local_mentions=True,
            has_years_mentioned=True,
        ),
        poi_details={"poi_id": "POI-中文", "distance_m": 320},
        pros=["味道稳定"],
        cons=["停车不便"],
        must_try=[MustTryItem("鲜毛肚", "脆", "https://img.invalid/毛肚.jpg")],
        black_list=[BlackListItem("冰粉", "偏甜")],
        stats=ShopStats(flavor="9", cost="¥¥", wait="20 分钟", env="老街"),
        tags=["火锅", "夜宵"],
    )


def _full_enriched() -> EnrichedRestaurant:
    return EnrichedRestaurant(
        index=1,
        name="老灶火锅",
        alias="老灶",
        address="自流井区同兴路 8 号",
        location="29.341,104.776",
        city="自贡",
        district="自流井区",
        business_area="同兴路",
        tel="028-12345678",
        rating=4.6,
        cost="88",
        open_time="17:00-02:00",
        trust_score=8.75,
        one_liner="本地人的深夜牛油锅。",
        tags=["火锅"],
        pros=["锅底香"],
        cons=["等位"],
        photos=[{"url": "https://img.invalid/店.jpg", "title": "门头"}],
        source_notes=["note-甲"],
        must_try=[{"name": "毛肚", "reason": "脆"}],
        black_list=[{"name": "冰粉", "reason": "偏甜"}],
        stats={"flavor": "9", "cost": "8", "wait": "6", "env": "7"},
    )


def test_food_intent_full_empty_unicode_and_round_trip() -> None:
    intent = FoodSearchIntent.from_dict(_FIXTURE["intent"])
    assert intent.to_dict() == _FIXTURE["intent"]
    assert FoodSearchIntent.from_dict(intent.to_dict()) == intent
    assert FoodSearchIntent.from_dict({}).to_dict() == {
        "location": "",
        "food_type": None,
        "requirements": [],
        "exclude_keywords": [],
        "time_filter": None,
        "price_range": None,
    }


def test_recommendation_and_response_mixed_case_wire_shape() -> None:
    recommendation = _full_recommendation()
    assert recommendation.to_dict() == _FIXTURE["recommendation"]

    response = XHSFoodResponse(
        recommendations=[recommendation],
        filtered_count=2,
        clarify_questions=["能吃辣吗？"],
        summary="共找到 1 家。",
    ).to_dict()
    expected = dict(_FIXTURE["response"])
    expected["recommendations"] = [_FIXTURE["recommendation"]]
    assert response == expected
    assert RestaurantRecommendation(name="空值店").to_dict() == _FIXTURE["empty_recommendation"]
    assert XHSFoodResponse().to_dict() == {
        "status": "ok",
        "recommendations": [],
        "filtered_count": 0,
        "clarify_questions": [],
        "error_message": None,
        "summary": "",
    }


def test_enriched_and_persisted_restaurant_shapes_are_distinct() -> None:
    enriched = _full_enriched()
    assert enriched.to_dict() == _FIXTURE["enriched"]
    assert "id" not in enriched.to_dict()
    assert EnrichedRestaurant(index=1, name="空值店").to_dict() == _FIXTURE["empty_enriched"]

    persisted = Restaurant(
        id="60da14c2146960f98c934c0f75093bd8",
        name=enriched.name,
        alias=enriched.alias,
        tel=enriched.tel,
        address=enriched.address,
        city=enriched.city,
        district=enriched.district,
        business_area=enriched.business_area,
        location=enriched.location,
        rating=enriched.rating,
        cost=enriched.cost,
        open_time=enriched.open_time,
        trust_score=8.75,
        one_liner=enriched.one_liner,
        tags=enriched.tags,
        pros=enriched.pros,
        cons=enriched.cons,
        photos=enriched.photos,
        source_notes=enriched.source_notes,
        must_try=enriched.must_try,
        black_list=enriched.black_list,
        stats=enriched.stats,
    )
    assert persisted.to_dict() == _FIXTURE["persisted_restaurant"]


def test_restaurant_hash_formula_with_trimmed_unicode_and_optional_phone() -> None:
    assert generate_restaurant_hash("  老灶火锅  ") == "d0e6a2f7137b481c4f3f18dda010eb75"
    assert generate_restaurant_hash("老灶火锅", "") == "d0e6a2f7137b481c4f3f18dda010eb75"
    assert generate_restaurant_hash("老灶火锅", " 028-12345678 ") == (
        "60da14c2146960f98c934c0f75093bd8"
    )


def test_persisted_search_result_json_is_read_back_without_case_conversion() -> None:
    restaurants_json = json.dumps([_FIXTURE["persisted_restaurant"]], ensure_ascii=False)
    row = {
        "session_id": "0328e6da-5ed8-43b8-a25f-532f174a323b",
        "turn_id": 2,
        "query": "自贡深夜火锅",
        "restaurants": restaurants_json,
        "summary": "共找到 1 家。",
        "filtered_count": 2,
        "created_at": datetime(2026, 8, 19, 12, 34, 56, tzinfo=timezone.utc),
    }
    assert SearchResultsMixin()._parse_search_result_row(row) == {
        "session_id": "0328e6da-5ed8-43b8-a25f-532f174a323b",
        "turn_id": 2,
        "query": "自贡深夜火锅",
        "restaurants": [_FIXTURE["persisted_restaurant"]],
        "summary": "共找到 1 家。",
        "filtered_count": 2,
        "created_at": "2026-08-19T12:34:56+00:00",
    }
