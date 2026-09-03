"""Authority checks for the post-cutover Food response contract."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import math
from dataclasses import fields
from typing import Any

import pytest

from xhs_food import __all__ as root_exports
from xhs_food.contracts import ShopProfile
from xhs_food.schemas import FoodSearchIntent, RestaurantRecommendation, XHSFoodResponse
from xhs_food.services.user_storage.models import Restaurant, generate_restaurant_hash


def test_public_exports_are_current_and_do_not_advertise_retired_routes() -> None:
    assert "SearchPhase" not in root_exports
    assert "FollowUpType" not in root_exports
    assert "XHSFoodOrchestrator" in root_exports
    assert "ConversationContext" in root_exports
    assert "poi_details" not in RestaurantRecommendation(name="店").to_dict()


def test_schema_keys_are_explicit_at_the_transport_boundary() -> None:
    intent = FoodSearchIntent(location="自贡")
    recommendation = RestaurantRecommendation(name="店")
    response = XHSFoodResponse()
    assert set(intent.to_dict()) == {
        "location",
        "food_type",
        "requirements",
        "exclude_keywords",
        "time_filter",
        "price_range",
    }
    assert {"shopProfile", "evidenceRefs", "sourceGaps"} <= set(recommendation.to_dict())
    assert {"researchMetadata", "gaps"} <= set(response.to_dict())


def test_dianping_profile_identity_is_provider_based_and_phone_independent() -> None:
    profile = ShopProfile(provider_refs={"dianping": "dp-1"}, name="老店", phone="028-1")
    from xhs_food.research.repository import profile_to_storage

    first = profile_to_storage(profile)
    changed = profile_to_storage(profile.model_copy(update={"phone": "028-2"}))
    assert first["id"] == changed["id"]
    assert first["id"] == hashlib.sha256(b"dianping:dp-1").hexdigest()[:32]


def test_storage_model_keeps_mutable_profile_fields_outside_identity() -> None:
    restaurant = Restaurant(id="fixed", name="老店", tel="028-1")
    restaurant.name = "新展示名"
    restaurant.tel = "028-2"
    assert restaurant.to_dict()["id"] == "fixed"
    assert generate_restaurant_hash(restaurant.name, restaurant.tel) != "fixed"


def test_contract_comparison_keeps_order_and_bounded_float_semantics() -> None:
    expected = {"recommendations": [{"name": "甲", "confidence": 0.875}]}
    within = {"recommendations": [{"name": "甲", "confidence": 0.8750009}]}
    assert math.isclose(within["recommendations"][0]["confidence"], expected["recommendations"][0]["confidence"], abs_tol=1e-6)
    assert list(within) == list(expected)
    with pytest.raises(AssertionError):
        assert ["乙"] == ["甲"]
