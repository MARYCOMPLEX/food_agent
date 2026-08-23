"""B2 qualification matrix for public Family reuse and refresh boundaries."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    QueryFamilyMatch,
    QueryMatchLayer,
    QueryReuseRequest,
)
from xhs_food.domain_packs.food.pack import FoodPack
from xhs_food.evidence import CanonicalQueryNormalizer, QueryFamilyReuseService

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "canonical_query_v1.json"


def _query() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
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
def test_zigong_two_questions_share_public_family_but_keep_personal_inputs_separate() -> None:
    first = _query()
    second = copy.deepcopy(first)
    first["query"]["audience"] = ["local_eater"]
    second["query"]["audience"] = ["visitor"]
    first["query"]["constraints"].append(
        {"constraint_id": "taste-a", "key": "taste", "operator": "eq", "value": "微辣"}
    )
    second["query"]["constraints"].append(
        {"constraint_id": "taste-b", "key": "taste", "operator": "eq", "value": "不辣"}
    )

    normalizer = CanonicalQueryNormalizer(FoodPack())
    left = normalizer.normalize(first)
    right = normalizer.normalize(second)

    assert left.family_id == right.family_id
    assert left.canonical_key == right.canonical_key
    assert left.classification.public_constraints[0].key == "food_type"
    assert [item.key for item in left.classification.personal_constraints] == ["taste"]
    assert [item.key for item in right.classification.personal_constraints] == ["taste"]


class _TierRepository:
    def __init__(self, *, exact=None, trigram=(), vector=()) -> None:
        self.exact = exact
        self.trigram = trigram
        self.vector = vector

    async def get_exact(self, canonical_key: str):
        del canonical_key
        return self.exact

    async def search_trigram(self, alias_text: str, *, limit: int = 5):
        del alias_text, limit
        return self.trigram

    async def search_vector(self, vector, profile, *, limit: int = 5):
        del vector, profile, limit
        return self.vector


def _match(layer: QueryMatchLayer, confidence: float) -> QueryFamilyMatch:
    return QueryFamilyMatch(
        family_id="family.zigong",
        canonical_key="query.zigong.restaurant",
        layer=layer,
        confidence=confidence,
        matched_alias="自贡本地美食" if layer is not QueryMatchLayer.DETERMINISTIC else None,
        rule_version="query-reuse/v1",
        profile_id=BGE_M3_PROFILE_V1.profile_id if layer is QueryMatchLayer.VECTOR else None,
        profile_version=BGE_M3_PROFILE_V1.model_version if layer is QueryMatchLayer.VECTOR else None,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exact", "trigram", "vector", "expected"),
    [
        (_match(QueryMatchLayer.DETERMINISTIC, 1.0), (), (), QueryMatchLayer.DETERMINISTIC),
        (None, (_match(QueryMatchLayer.TRIGRAM, 0.93),), (), QueryMatchLayer.TRIGRAM),
        (None, (_match(QueryMatchLayer.TRIGRAM, 0.89),), (_match(QueryMatchLayer.VECTOR, 0.91),), QueryMatchLayer.VECTOR),
        (None, (_match(QueryMatchLayer.TRIGRAM, 0.50),), (_match(QueryMatchLayer.VECTOR, 0.50),), None),
    ],
)
async def test_three_tier_reuse_matrix_records_hit_or_no_merge(
    exact, trigram, vector, expected: QueryMatchLayer | None
) -> None:
    decision = await QueryFamilyReuseService(
        _TierRepository(exact=exact, trigram=trigram, vector=vector)
    ).resolve(
        QueryReuseRequest(
            canonical_key="query.zigong.restaurant",
            alias_text="自贡本地美食",
            vector=(0.0,) * BGE_M3_PROFILE_V1.dimensions,
        )
    )

    assert decision.match is None if expected is None else decision.match.layer is expected  # type: ignore[union-attr]


@pytest.mark.unit
def test_temporal_qualification_suite_keeps_replay_and_worker_restart_as_explicit_gates() -> None:
    text = (Path(__file__).parent / "test_temporal_qualification.py").read_text(encoding="utf-8")
    assert "test_temporal_workflow_history_is_deterministic_and_replayable" in text
    assert "test_worker_stop_and_restart_resumes_persisted_workflow" in text
