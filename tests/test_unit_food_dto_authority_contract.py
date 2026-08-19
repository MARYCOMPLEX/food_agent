"""Authority contracts for the accepted Food DTO v1 compatibility boundary."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from xhs_food.agents.poi_enricher import EnrichedRestaurant
from xhs_food.schemas import FoodSearchIntent, RestaurantRecommendation, XHSFoodResponse
from xhs_food.services.user_storage.models import Restaurant, generate_restaurant_hash

_ROOT = Path(__file__).parents[1]
_AUTHORITY_FIXTURES = _ROOT / "tests/fixtures/authority"
_AUTHORITY = json.loads(
    (_AUTHORITY_FIXTURES / "food_dto_v1.json").read_text(encoding="utf-8")
)
_SCHEMA = json.loads(
    (_AUTHORITY_FIXTURES / "food_dto_v1.schema.json").read_text(encoding="utf-8")
)
_CHARACTERIZATION = json.loads(
    (_ROOT / "tests/fixtures/characterization/food_dto.json").read_text(encoding="utf-8")
)
_PYTHON_CONTRACT = json.loads(
    (_ROOT / "tests/fixtures/characterization/python_public_contract.json").read_text(
        encoding="utf-8"
    )
)


def _assert_v1_equivalent(actual: Any, expected: Any, *, path: str = "$") -> None:
    """Apply the ADR's strict structure/order and bounded-float comparison."""
    if isinstance(expected, (bool, int)):
        assert type(actual) is type(expected), path
        assert actual == expected, path
        return

    if isinstance(expected, float):
        assert type(actual) is float, path
        assert math.isfinite(actual) and math.isfinite(expected), path
        if path.endswith(".trustScore"):
            assert actual == expected, path
        else:
            tolerance = _AUTHORITY["equivalence"]["floatAbsoluteTolerance"]
            assert math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance), path
        return

    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert set(actual) == set(expected), path
        for key in expected:
            _assert_v1_equivalent(actual[key], expected[key], path=f"{path}.{key}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), path
        assert len(actual) == len(expected), path
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            _assert_v1_equivalent(actual_item, expected_item, path=f"{path}[{index}]")
        return

    assert type(actual) is type(expected), path
    assert actual == expected, path


def test_normative_fixture_is_derived_from_characterization_evidence() -> None:
    dto = _AUTHORITY["dto"]
    assert dto == {
        "intent": _CHARACTERIZATION["intent"],
        "recommendation": _CHARACTERIZATION["recommendation"],
        "response": _CHARACTERIZATION["response"],
        "enriched": _CHARACTERIZATION["enriched"],
        "persistedRestaurant": _CHARACTERIZATION["persisted_restaurant"],
    }
    assert _AUTHORITY["publicExports"] == _PYTHON_CONTRACT["exports"]


def test_schema_freezes_mixed_case_boundary_instead_of_global_case_conversion() -> None:
    definitions = _SCHEMA["$defs"]
    intent_keys = set(definitions["foodSearchIntent"]["required"])
    recommendation_keys = set(definitions["restaurantRecommendation"]["required"])
    restaurant_view_keys = set(definitions["restaurantView"]["required"])

    assert {"food_type", "exclude_keywords", "time_filter", "price_range"} <= intent_keys
    assert {"source_notes", "is_recommended", "mustTry", "blackList"} <= recommendation_keys
    assert {"chnName", "businessArea", "openTime", "trustScore", "sourceNotes"} <= (
        restaurant_view_keys
    )
    assert "id" not in restaurant_view_keys
    assert _SCHEMA["properties"]["schemaVersion"] == {"const": "food-dto/v1"}

    assert set(FoodSearchIntent(location="自贡").to_dict()) == intent_keys
    assert set(RestaurantRecommendation(name="空值店").to_dict()) == recommendation_keys
    assert set(EnrichedRestaurant(index=1, name="空值店").to_dict()) == restaurant_view_keys
    assert set(XHSFoodResponse().to_dict()) == set(definitions["xhsFoodResponse"]["required"])


def test_restaurant_identity_vectors_use_exact_two_branch_formula() -> None:
    identity = _AUTHORITY["identity"]
    for branch in ("withoutTelephone", "withTelephone"):
        vector = identity[branch]
        independent_hash = hashlib.sha256(vector["preimage"].encode("utf-8")).hexdigest()[:32]
        assert independent_hash == vector["id"]
        assert generate_restaurant_hash(vector["name"], vector["tel"]) == vector["id"]

    without_tel = identity["withoutTelephone"]
    assert generate_restaurant_hash(without_tel["name"], "   ") == without_tel["id"]
    assert ":" not in without_tel["preimage"]
    assert identity["withTelephone"]["preimage"] == "老灶火锅:028-12345678"


def test_persisted_id_is_reused_when_mutable_view_fields_change() -> None:
    fixture = _AUTHORITY["dto"]["persistedRestaurant"]
    restaurant = Restaurant(
        id=fixture["id"],
        name=fixture["name"],
        tel=fixture["tel"],
        address=fixture["address"],
    )
    restaurant.name = "更正后的展示名称"
    restaurant.tel = "028-00000000"
    restaurant.address = "新地址"
    restaurant.rating = 5.0

    assert restaurant.to_dict()["id"] == fixture["id"]
    assert generate_restaurant_hash(restaurant.name, restaurant.tel) != fixture["id"]


def test_public_exports_are_exact_ordered_compatibility_surface() -> None:
    for module_name, expected in _AUTHORITY["publicExports"].items():
        module = importlib.import_module(module_name)
        assert module.__all__ == expected
        assert all(hasattr(module, public_name) for public_name in expected)

    assert all(field.name == field.name.lower() for field in fields(FoodSearchIntent))
    assert all(field.name == field.name.lower() for field in fields(RestaurantRecommendation))


def test_result_equivalence_requires_order_and_bounds_unrounded_floats() -> None:
    expected = {
        "recommendations": [
            {"name": "甲", "confidence": 0.875, "trustScore": 8.8},
            {"name": "乙", "confidence": 0.5, "trustScore": 7.0},
        ]
    }
    within_tolerance = json.loads(json.dumps(expected))
    within_tolerance["recommendations"][0]["confidence"] += 0.0000009
    _assert_v1_equivalent(within_tolerance, expected)

    outside_tolerance = json.loads(json.dumps(expected))
    outside_tolerance["recommendations"][0]["confidence"] += 0.0000011
    with pytest.raises(AssertionError):
        _assert_v1_equivalent(outside_tolerance, expected)

    reordered = {"recommendations": list(reversed(expected["recommendations"]))}
    with pytest.raises(AssertionError):
        _assert_v1_equivalent(reordered, expected)

    rerounded = json.loads(json.dumps(expected))
    rerounded["recommendations"][0]["trustScore"] += 0.0000001
    with pytest.raises(AssertionError):
        _assert_v1_equivalent(rerounded, expected)
