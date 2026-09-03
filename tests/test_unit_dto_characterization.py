"""Current Food DTO and durable shop-profile boundaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research.repository import profile_to_storage
from xhs_food.schemas import RestaurantRecommendation, XHSFoodResponse
from xhs_food.services.user_storage.models import Restaurant, generate_restaurant_hash
from xhs_food.services.user_storage.search_results import SearchResultsMixin


def test_food_intent_round_trips_and_has_stable_empty_defaults() -> None:
    value = FoodSearchIntent(
        location="自贡市",
        food_type="冷吃兔",
        requirements=["本地人常去"],
        exclude_keywords=["网红"],
        time_filter="晚餐",
        price_range="¥¥",
    )
    assert FoodSearchIntent.from_dict(value.to_dict()) == value
    assert FoodSearchIntent.from_dict({}).to_dict() == {
        "location": "",
        "food_type": None,
        "requirements": [],
        "exclude_keywords": [],
        "time_filter": None,
        "price_range": None,
    }


def test_recommendation_wire_shape_has_evidence_and_shop_profile() -> None:
    recommendation = RestaurantRecommendation(
        name="老灶火锅",
        source_notes=["note-1"],
        evidence_refs=["xhs:note:note-1:comment:c-1"],
        shop_profile={"providerRefs": {"dianping": "dp-1"}, "name": "老灶火锅"},
    )
    payload = recommendation.to_dict()
    assert payload["shopProfile"]["providerRefs"]["dianping"] == "dp-1"
    assert payload["evidenceRefs"] == ["xhs:note:note-1:comment:c-1"]
    assert "poi_details" not in payload
    assert XHSFoodResponse(recommendations=[recommendation]).to_dict()["recommendations"]


def test_shop_profile_storage_projection_keeps_structured_provider_fields() -> None:
    from xhs_food.contracts import ShopProfile

    profile = ShopProfile(
        provider_refs={"dianping": "dp-1"},
        name="老灶火锅",
        address="自流井区同兴路 8 号",
        latitude=29.341,
        longitude=104.776,
        images=({"url": "https://img.example/shop.jpg"},),
        recommended_dishes=("毛肚",),
        promotions=({"title": "双人套餐", "price": 88},),
    )
    row = profile_to_storage(profile)
    assert row["provider_refs"] == {"dianping": "dp-1"}
    assert row["latitude"] == 29.341
    assert row["recommended_dishes"] == ["毛肚"]
    assert row["promotions"][0]["title"] == "双人套餐"
    assert row["source_payload"] is None


def test_restaurant_identity_is_stable_when_profile_fields_change() -> None:
    assert generate_restaurant_hash("  老灶火锅  ") == "d0e6a2f7137b481c4f3f18dda010eb75"
    first = Restaurant(id="stable-id", name="老灶火锅", tel="028-123")
    first.name = "更正后的名称"
    first.tel = "028-999"
    assert first.to_dict()["id"] == "stable-id"


def test_persisted_search_result_json_is_read_back_without_case_conversion() -> None:
    restaurant = Restaurant(id="stable-id", name="老店", recommended_dishes=["毛肚"])
    row = {
        "session_id": "0328e6da-5ed8-43b8-a25f-532f174a323b",
        "turn_id": 2,
        "query": "自贡深夜火锅",
        "restaurants": json.dumps([restaurant.to_dict()], ensure_ascii=False),
        "summary": "共找到 1 家。",
        "filtered_count": 0,
        "created_at": datetime(2026, 8, 19, 12, 34, 56, tzinfo=timezone.utc),
    }
    parsed = SearchResultsMixin()._parse_search_result_row(row)
    assert parsed["restaurants"][0]["recommendedDishes"] == ["毛肚"]
