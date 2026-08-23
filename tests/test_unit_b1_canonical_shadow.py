"""Offline B1 Canonical Query and Family identity contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xhs_food.domain_packs.food.pack import FoodPack
from xhs_food.evidence import CanonicalQueryNormalizer, UnclassifiedConstraintError

FIXTURES = Path(__file__).parent / "fixtures" / "authority"


def _canonical_input() -> dict[str, object]:
    value = json.loads((FIXTURES / "canonical_query_v1.json").read_text(encoding="utf-8"))
    value["query"]["constraints"] = [
        {
            "constraint_id": "food-type",
            "key": "food_type",
            "operator": "eq",
            "value": "local_food",
        }
    ]
    return value


@pytest.mark.unit
def test_normalizer_separates_personal_constraints_from_shared_family_identity() -> None:
    base = _canonical_input()
    personalized = copy.deepcopy(base)
    personalized["query"]["constraints"].append(
        {
            "constraint_id": "taste-1",
            "key": "taste",
            "operator": "eq",
            "value": "不要辣",
        }
    )
    normalizer = CanonicalQueryNormalizer(FoodPack())

    public = normalizer.normalize(base)
    private = normalizer.normalize(personalized)

    assert public.family_id == private.family_id
    assert public.canonical_key == private.canonical_key
    assert len(private.classification.public_constraints) == 1
    assert [item.key for item in private.classification.personal_constraints] == ["taste"]
    assert "taste" not in json.dumps(
        private.canonical_query.model_dump(mode="json"), ensure_ascii=False
    )
    assert private.family_match.confidence == 1.0
    assert private.family_match.strategy == "deterministic"


@pytest.mark.unit
def test_normalizer_is_deterministic_for_constraint_and_audience_order() -> None:
    first = _canonical_input()
    second = copy.deepcopy(first)
    second["query"]["audience"] = list(reversed(second["query"]["audience"]))
    second["query"]["constraints"] = list(reversed(second["query"]["constraints"]))
    normalizer = CanonicalQueryNormalizer(FoodPack())

    left = normalizer.normalize(first)
    right = normalizer.normalize(second)

    assert left.canonical_query == right.canonical_query
    assert left.family_match.preimage_sha256 == right.family_match.preimage_sha256
    assert left.canonical_key == right.canonical_key


@pytest.mark.unit
def test_unclassified_constraint_cannot_enter_a_shared_identity() -> None:
    value = _canonical_input()
    value["query"]["constraints"].append(
        {
            "constraint_id": "private-identity",
            "key": "user_id",
            "operator": "eq",
            "value": "user-a",
        }
    )

    with pytest.raises(UnclassifiedConstraintError, match="private-identity"):
        CanonicalQueryNormalizer(FoodPack()).normalize(value)


@pytest.mark.unit
def test_classifier_must_classify_each_constraint_exactly_once() -> None:
    class OmittingPack(FoodPack):
        def classify_constraints(self, value: dict[str, object]) -> dict[str, object]:
            result = super().classify_constraints(value)
            rows = result["results"]
            assert isinstance(rows, list)
            return {**result, "results": rows[:-1]}

    with pytest.raises(ValueError, match="omitted constraints"):
        CanonicalQueryNormalizer(OmittingPack()).normalize(_canonical_input())
