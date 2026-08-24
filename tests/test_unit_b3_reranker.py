"""B3 final reranking and public candidate immutability tests."""

from __future__ import annotations

import pytest

from xhs_food.contracts import PersonalizationPolicy, PublicCandidate, UserIsolationKey
from xhs_food.personalization import PersonalizedReranker


def _policy() -> PersonalizationPolicy:
    return PersonalizationPolicy(
        policy_id="policy-rerank",
        policy_version="personalization-policy/v1",
        isolation_key=UserIsolationKey(
            tenant_id="tenant-cn-1",
            user_id="user-2b4aa1b95c884d64",
        ),
        preference_snapshot_id="snapshot-rerank",
        preference_snapshot_version=3,
        hard_filters={"diet.spice": {"hardConstraint": True, "value": "mild"}},
        ranking_weights={"locality": 0.2},
        explanation_refs=("memory-record:hard-spice",),
    )


def _candidates() -> tuple[PublicCandidate, ...]:
    return (
        PublicCandidate(
            candidate_id="restaurant-a",
            public_score=0.8,
            public_features={"locality": 0.2},
            public_attributes={"diet.spice": "mild"},
            evidence_refs=("evidence-a",),
        ),
        PublicCandidate(
            candidate_id="restaurant-b",
            public_score=0.95,
            public_features={"locality": 0.0},
            public_attributes={"diet.spice": "hot"},
            evidence_refs=("evidence-b",),
        ),
    )


@pytest.mark.unit
def test_reranker_filters_after_public_candidates_and_preserves_public_score() -> None:
    candidates = _candidates()
    ranking = PersonalizedReranker().rerank(candidates, _policy())

    assert [item.candidate_id for item in ranking.candidates] == ["restaurant-a"]
    assert ranking.candidates[0].public_score == 0.8
    assert ranking.candidates[0].personalized_score == pytest.approx(0.84)
    assert ranking.candidates[0].explanation_refs == (
        "memory-record:hard-spice",
        "evidence-a",
    )
    assert ranking.mutates_public_scores is False
    assert ranking.mutates_public_features is False


@pytest.mark.unit
def test_reranker_digest_is_stable_and_changes_when_public_input_changes() -> None:
    reranker = PersonalizedReranker()
    policy = _policy().model_copy(update={"hard_filters": {}})
    first = reranker.rerank(_candidates(), policy)
    second = reranker.rerank(tuple(reversed(_candidates())), policy)
    changed = reranker.rerank(
        _candidates()
        + (
            PublicCandidate(
                candidate_id="restaurant-c",
                public_score=0.2,
                evidence_refs=("evidence-c",),
            ),
        ),
        policy,
    )
    assert first.public_input_digest == second.public_input_digest
    assert first.public_input_digest != changed.public_input_digest


@pytest.mark.unit
def test_two_users_can_rank_same_public_bundle_differently_without_mutating_it() -> None:
    candidates = (
        PublicCandidate(
            candidate_id="restaurant-local",
            public_score=0.7,
            public_features={"locality": 1.0},
            public_attributes={},
            evidence_refs=("evidence-local",),
        ),
        PublicCandidate(
            candidate_id="restaurant-popular",
            public_score=0.8,
            public_features={"locality": 0.0},
            public_attributes={},
            evidence_refs=("evidence-popular",),
        ),
    )
    local_policy = _policy().model_copy(
        update={
            "hard_filters": {},
            "ranking_weights": {"locality": 0.3},
            "policy_id": "policy-local",
        }
    )
    popular_policy = local_policy.model_copy(
        update={"ranking_weights": {"locality": -0.3}, "policy_id": "policy-popular"}
    )
    reranker = PersonalizedReranker()
    local = reranker.rerank(candidates, local_policy)
    popular = reranker.rerank(candidates, popular_policy)

    assert local.candidates[0].candidate_id == "restaurant-local"
    assert popular.candidates[0].candidate_id == "restaurant-popular"
    assert local.public_input_digest == popular.public_input_digest
    assert candidates[0].public_score == 0.7
