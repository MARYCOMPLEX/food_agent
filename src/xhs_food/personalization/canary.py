"""Deterministic, read-only personalization exposure and rollback control."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from typing import Any

from xhs_food.contracts import (
    PersonalizationCanaryMode,
    PersonalizationCanaryObservation,
    PersonalizationCanaryResult,
    PersonalizationCanarySettings,
    PersonalizationPolicy,
    PersonalizationRollbackReceipt,
    PersonalizedRanking,
    PublicCandidate,
)

from .reranker import PersonalizedReranker

ObservationRecorder = Callable[[PersonalizationCanaryObservation], None]


class PersonalizationCanary:
    """Expose personalization independently from public refresh and identity.

    The service never writes public candidates. In ``shadow`` mode it computes
    sampled rankings only for observation; only ``canary`` mode serves them.
    """

    def __init__(
        self,
        reranker: PersonalizedReranker,
        *,
        settings: PersonalizationCanarySettings | None = None,
        recorder: ObservationRecorder | None = None,
    ) -> None:
        self._reranker = reranker
        self._settings = settings or PersonalizationCanarySettings()
        self._recorder = recorder

    @property
    def settings(self) -> PersonalizationCanarySettings:
        return self._settings

    def evaluate(
        self,
        candidates: Iterable[PublicCandidate],
        policy: PersonalizationPolicy,
        *,
        request_key: str,
        cache_hit: bool = False,
        outbox_lag_ms: float = 0.0,
        private_records_used: int = 0,
    ) -> PersonalizationCanaryResult:
        if not request_key:
            raise ValueError("personalization canary request key must be non-empty")
        values = tuple(candidates)
        default_ids = tuple(
            candidate.candidate_id
            for candidate in sorted(values, key=lambda item: (-item.public_score, item.candidate_id))
        )
        request_key_hash = _digest(request_key)
        public_input_digest = _public_input_digest(values)
        sampled = self._settings.mode is not PersonalizationCanaryMode.OFF and _sample(
            request_key, self._settings.sample_rate
        )
        ranking: PersonalizedRanking | None = None
        personalized_ids: tuple[str, ...] = ()
        personalized_digest: str | None = None
        if sampled:
            ranking = self._reranker.rerank(values, policy)
            personalized_ids = tuple(item.candidate_id for item in ranking.candidates)
            personalized_digest = _digest(
                [
                    {
                        "candidate_id": item.candidate_id,
                        "personalized_score": item.personalized_score,
                        "rank": item.rank,
                    }
                    for item in ranking.candidates
                ]
            )
            public_input_digest = ranking.public_input_digest
        served = sampled and self._settings.mode is PersonalizationCanaryMode.CANARY
        served_ids = personalized_ids if served else default_ids
        observation = PersonalizationCanaryObservation(
            request_key_hash=request_key_hash,
            mode=self._settings.mode,
            sampled=sampled,
            served_personalized=served,
            default_strategy_version=self._settings.default_strategy_version,
            personalized_strategy_version=(policy.policy_version if sampled else None),
            public_input_digest=public_input_digest,
            default_result_digest=_digest(default_ids),
            personalized_result_digest=personalized_digest,
            default_candidate_ids=default_ids,
            personalized_candidate_ids=personalized_ids,
            served_candidate_ids=served_ids,
            ranking_changed=sampled and default_ids != personalized_ids,
            cache_hit=cache_hit,
            outbox_lag_ms=outbox_lag_ms,
            private_records_used=private_records_used,
        )
        if self._recorder is not None:
            self._recorder(observation)
        return PersonalizationCanaryResult(
            observation=observation,
            personalized_ranking=ranking,
        )

    def rollback(self) -> PersonalizationRollbackReceipt:
        """Disable exposure and warm-up without deleting PostgreSQL facts."""

        self._settings = self._settings.model_copy(
            update={
                "mode": PersonalizationCanaryMode.OFF,
                "sample_rate": 0.0,
                "projection_warmup_enabled": False,
            }
        )
        return PersonalizationRollbackReceipt()


def _sample(request_key: str, sample_rate: float) -> bool:
    if not 0.0 <= sample_rate <= 1.0:
        raise ValueError("personalization canary sample rate must be between 0 and 1")
    if sample_rate == 0:
        return False
    bucket = int(hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:16], 16) / 16**16
    return bucket < sample_rate


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _public_input_digest(candidates: tuple[PublicCandidate, ...]) -> str:
    return _digest(
        [
            candidate.model_dump(mode="json")
            for candidate in sorted(candidates, key=lambda item: item.candidate_id)
        ]
    )


__all__ = ["PersonalizationCanary", "ObservationRecorder"]
