"""B3 personalization canary exposure and observation gates."""

from __future__ import annotations

import pytest
from prometheus_client import generate_latest
from pydantic import ValidationError

from xhs_food.composition import build_composition_root
from xhs_food.contracts import (
    PersonalizationCanaryMode,
    PersonalizationCanarySettings,
    PersonalizationPolicy,
    PublicCandidate,
    UserIsolationKey,
)
from xhs_food.foundation import PersonalizationCanaryTelemetry
from xhs_food.personalization import PersonalizationCanary, PersonalizedReranker


def _policy() -> PersonalizationPolicy:
    return PersonalizationPolicy(
        policy_id="canary-policy",
        policy_version="personalization-policy/v1",
        isolation_key=UserIsolationKey(
            tenant_id="tenant-cn-1", user_id="user-canary-2b4aa1b95c884d64"
        ),
        preference_snapshot_id="snapshot-canary",
        preference_snapshot_version=1,
        ranking_weights={"locality": 0.3},
        explanation_refs=("memory-record:preference",),
    )


def _candidates() -> tuple[PublicCandidate, ...]:
    return (
        PublicCandidate(
            candidate_id="restaurant-popular",
            public_score=0.9,
            public_features={"locality": 0.0},
            evidence_refs=("evidence-popular",),
        ),
        PublicCandidate(
            candidate_id="restaurant-local",
            public_score=0.8,
            public_features={"locality": 1.0},
            evidence_refs=("evidence-local",),
        ),
    )


@pytest.mark.unit
def test_canary_settings_are_independent_and_closed_world() -> None:
    assert PersonalizationCanarySettings().mode is PersonalizationCanaryMode.OFF
    assert PersonalizationCanarySettings().sample_rate == 0.0
    assert PersonalizationCanarySettings().public_refresh_priority_enabled is False
    with pytest.raises(ValidationError, match="off personalization canary"):
        PersonalizationCanarySettings(sample_rate=0.5)
    with pytest.raises(ValidationError, match="positive sample rate"):
        PersonalizationCanarySettings(mode=PersonalizationCanaryMode.SHADOW)


@pytest.mark.unit
def test_shadow_records_difference_but_canary_serves_only_sampled_ranking() -> None:
    observations = []
    shadow = PersonalizationCanary(
        PersonalizedReranker(),
        settings=PersonalizationCanarySettings(
            mode=PersonalizationCanaryMode.SHADOW,
            sample_rate=1.0,
        ),
        recorder=observations.append,
    )
    shadow_result = shadow.evaluate(
        _candidates(),
        _policy(),
        request_key="request-canary-1",
        cache_hit=True,
        outbox_lag_ms=12.5,
        private_records_used=2,
    )
    assert shadow_result.observation.sampled is True
    assert shadow_result.observation.served_personalized is False
    assert shadow_result.observation.ranking_changed is True
    assert shadow_result.observation.served_candidate_ids == (
        "restaurant-popular",
        "restaurant-local",
    )
    assert shadow_result.observation.private_values_exposed is False
    assert shadow_result.observation.public_refresh_priority_changed is False
    assert observations == [shadow_result.observation]

    canary = PersonalizationCanary(
        PersonalizedReranker(),
        settings=PersonalizationCanarySettings(
            mode=PersonalizationCanaryMode.CANARY,
            sample_rate=1.0,
        ),
    )
    canary_result = canary.evaluate(_candidates(), _policy(), request_key="request-canary-1")
    assert canary_result.observation.served_personalized is True
    assert canary_result.observation.served_candidate_ids == (
        "restaurant-local",
        "restaurant-popular",
    )
    assert canary_result.personalized_ranking is not None
    assert canary_result.personalized_ranking.public_input_digest == (
        canary_result.observation.public_input_digest
    )


@pytest.mark.unit
def test_off_mode_does_not_invoke_reranker_or_change_public_order() -> None:
    class FailingReranker:
        def rerank(self, *args: object, **kwargs: object) -> object:
            raise AssertionError((args, kwargs))

    service = PersonalizationCanary(
        FailingReranker(),  # type: ignore[arg-type]
        settings=PersonalizationCanarySettings(),
    )
    result = service.evaluate(_candidates(), _policy(), request_key="request-off")
    reordered = service.evaluate(
        tuple(reversed(_candidates())), _policy(), request_key="request-off-2"
    )
    assert result.personalized_ranking is None
    assert result.observation.sampled is False
    assert result.observation.ranking_changed is False
    assert result.observation.served_candidate_ids == (
        "restaurant-popular",
        "restaurant-local",
    )
    assert result.observation.public_input_digest == reordered.observation.public_input_digest


@pytest.mark.unit
async def test_canary_binding_is_opt_in_and_separate_from_research_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODULAR_TARGET_ADAPTERS_ENABLED", "true")
    monkeypatch.setenv("MODULAR_PERSONALIZATION_CANARY_MODE", "shadow")
    monkeypatch.setenv("MODULAR_PERSONALIZATION_CANARY_SAMPLE_RATE", "1")
    root = build_composition_root()
    try:
        assert "personalization_canary" in root.logical_bindings
        assert root.logical_bindings["research_task"].binding_name == "research_task"
        service = await root.resolve_logical("personalization_canary")
        assert isinstance(service, PersonalizationCanary)
        assert service.settings.mode is PersonalizationCanaryMode.SHADOW
    finally:
        await root.close()


@pytest.mark.unit
def test_canary_telemetry_is_aggregate_only() -> None:
    result = PersonalizationCanary(
        PersonalizedReranker(),
        settings=PersonalizationCanarySettings(
            mode=PersonalizationCanaryMode.SHADOW,
            sample_rate=1.0,
        ),
    ).evaluate(
        _candidates(),
        _policy(),
        request_key="private-request-key",
        cache_hit=True,
        outbox_lag_ms=4,
        private_records_used=2,
    )
    PersonalizationCanaryTelemetry().record(result.observation)
    metrics = generate_latest().decode("utf-8")
    assert "xhs_personalization_canary_exposures_total" in metrics
    assert "xhs_personalization_cache_results_total" in metrics
    assert "private-request-key" not in metrics
    assert "user-canary-2b4aa1b95c884d64" not in metrics
