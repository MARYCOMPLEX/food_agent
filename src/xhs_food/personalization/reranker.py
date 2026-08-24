"""Read-only final reranking over public candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from xhs_food.contracts import (
    PersonalizationPolicy,
    PersonalizedCandidate,
    PersonalizedRanking,
    PublicCandidate,
)


class PersonalizedReranker:
    """Apply private policy after public candidate generation.

    The input candidates are immutable contracts. The output carries the same
    public score and a digest of all public inputs, so personalization cannot
    become a write path for Evidence, features, or public scores.
    """

    def rerank(
        self,
        candidates: Iterable[PublicCandidate],
        policy: PersonalizationPolicy,
    ) -> PersonalizedRanking:
        values = tuple(candidates)
        public_digest = _public_digest(values)
        ranked: list[tuple[float, PublicCandidate]] = []
        for candidate in values:
            if not _matches_hard_filters(candidate, policy.hard_filters):
                continue
            adjustment = sum(
                weight * candidate.public_features.get(feature, 0.0)
                for feature, weight in policy.ranking_weights.items()
            )
            ranked.append((candidate.public_score + adjustment, candidate))
        ranked.sort(key=lambda item: (-item[0], item[1].candidate_id))

        output = tuple(
            PersonalizedCandidate(
                candidate_id=candidate.candidate_id,
                public_score=candidate.public_score,
                personalized_score=score,
                rank=rank,
                evidence_refs=candidate.evidence_refs,
                explanation_refs=_dedupe(
                    (*policy.explanation_refs, *candidate.evidence_refs)
                ),
            )
            for rank, (score, candidate) in enumerate(ranked, start=1)
        )
        return PersonalizedRanking(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            preference_snapshot_id=policy.preference_snapshot_id,
            preference_snapshot_version=policy.preference_snapshot_version,
            public_input_digest=public_digest,
            candidates=output,
        )


def _matches_hard_filters(candidate: PublicCandidate, filters: Mapping[str, object]) -> bool:
    for key, expected in filters.items():
        expected_value = expected.get("value") if isinstance(expected, Mapping) else expected
        if candidate.public_attributes.get(key) != expected_value:
            return False
    return True


def _public_digest(candidates: tuple[PublicCandidate, ...]) -> str:
    payload = [
        candidate.model_dump(mode="json", by_alias=True)
        for candidate in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = ["PersonalizedReranker"]
