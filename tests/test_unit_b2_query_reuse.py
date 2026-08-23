"""Unit gates for B2 Query Family reuse, freshness, and single-flight."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    EmbeddingProfile,
    FreshnessInput,
    FreshnessPolicy,
    FreshnessReason,
    FreshnessState,
    QueryFamilyMatch,
    QueryMatchLayer,
    QueryReuseRequest,
    RefreshClaim,
    RefreshSingleFlightKey,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
)
from xhs_food.evidence import QueryFamilyReuseService, RefreshSingleFlightService


def _match(
    layer: QueryMatchLayer,
    *,
    confidence: float,
    family_id: str = "family.zigong",
) -> QueryFamilyMatch:
    return QueryFamilyMatch(
        family_id=family_id,
        canonical_key=f"query.{family_id}",
        layer=layer,
        confidence=confidence,
        matched_alias="自贡本地美食" if layer is QueryMatchLayer.TRIGRAM else None,
        rule_version="rule/v1",
        profile_id=BGE_M3_PROFILE_V1.profile_id if layer is QueryMatchLayer.VECTOR else None,
        profile_version=BGE_M3_PROFILE_V1.model_version
        if layer is QueryMatchLayer.VECTOR
        else None,
        audit_basis=("fixture",),
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.exact: QueryFamilyMatch | None = None
        self.trigram: tuple[QueryFamilyMatch, ...] = ()
        self.vector: tuple[QueryFamilyMatch, ...] = ()
        self.claim: RefreshClaim | None = None

    async def get_exact(self, canonical_key: str) -> QueryFamilyMatch | None:
        self.calls.append("deterministic")
        return self.exact

    async def search_trigram(
        self, alias_text: str, *, limit: int = 5
    ) -> tuple[QueryFamilyMatch, ...]:
        del alias_text, limit
        self.calls.append("trigram")
        return self.trigram

    async def search_vector(
        self,
        vector: tuple[float, ...],
        profile: EmbeddingProfile,
        *,
        limit: int = 5,
    ) -> tuple[QueryFamilyMatch, ...]:
        del vector, profile, limit
        self.calls.append("vector")
        return self.vector

    async def get_freshness(self, family_id: str) -> FreshnessInput | None:
        del family_id
        return None

    async def claim_refresh(self, key: RefreshSingleFlightKey) -> RefreshClaim:
        del key
        if self.claim is None:
            raise AssertionError("fixture claim was not configured")
        return self.claim

    async def activate_bundle_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
    ) -> bool:
        del family_id, expected_bundle_version, bundle_id, bundle_version
        return True


def _request(*, vector: tuple[float, ...] | None = (0.1,) * 1024) -> QueryReuseRequest:
    return QueryReuseRequest(canonical_key="query.missing", alias_text="自贡本地美食", vector=vector)


@pytest.mark.unit
async def test_deterministic_match_short_circuits_other_tiers() -> None:
    repository = _Repository()
    repository.exact = _match(QueryMatchLayer.DETERMINISTIC, confidence=1.0)

    decision = await QueryFamilyReuseService(repository).resolve(_request())

    assert decision.match is repository.exact
    assert decision.attempted_layers == (QueryMatchLayer.DETERMINISTIC,)
    assert repository.calls == ["deterministic"]


@pytest.mark.unit
async def test_low_trigram_confidence_falls_through_to_profile_pinned_vector() -> None:
    repository = _Repository()
    repository.trigram = (_match(QueryMatchLayer.TRIGRAM, confidence=0.89),)
    repository.vector = (_match(QueryMatchLayer.VECTOR, confidence=0.91),)

    decision = await QueryFamilyReuseService(repository).resolve(_request())

    assert decision.match is repository.vector[0]
    assert decision.attempted_layers == (
        QueryMatchLayer.DETERMINISTIC,
        QueryMatchLayer.TRIGRAM,
        QueryMatchLayer.VECTOR,
    )
    assert repository.calls == ["deterministic", "trigram", "vector"]
    assert decision.match.profile_id == "profile_v1"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_approved_trigram_does_not_call_vector() -> None:
    repository = _Repository()
    repository.trigram = (_match(QueryMatchLayer.TRIGRAM, confidence=0.93),)

    decision = await QueryFamilyReuseService(repository).resolve(_request())

    assert decision.match is repository.trigram[0]
    assert repository.calls == ["deterministic", "trigram"]


@pytest.mark.unit
async def test_vector_reuse_rejects_another_profile_after_fallback() -> None:
    repository = _Repository()
    profile = EmbeddingProfile(
        profile_id="other_profile",
        model_id="other-model",
        model_version="other/v1",
        dimensions=2,
    )

    with pytest.raises(ValueError, match="profile_v1"):
        await QueryFamilyReuseService(repository).resolve(
            QueryReuseRequest(
                canonical_key="query.missing",
                alias_text="自贡本地美食",
                vector=(0.1, 0.2),
                embedding_profile=profile,
            )
        )


@pytest.mark.unit
def test_freshness_gate_has_new_fresh_and_incremental_states() -> None:
    policy = FreshnessPolicy(
        policy_id="food-default",
        policy_version="freshness/v1",
        max_staleness_seconds=3600,
        minimum_coverage={"restaurants": 0.8},
    )
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    missing = FreshnessInput(family_id="family.new")
    fresh = FreshnessInput(
        family_id="family.fresh",
        bundle_version=1,
        verified_at=now - timedelta(minutes=10),
        coverage={"restaurants": 0.9},
    )
    stale = fresh.model_copy(update={"family_id": "family.stale", "verified_at": now - timedelta(hours=2)})

    from xhs_food.contracts import decide_freshness

    assert decide_freshness(missing, policy, now=now).state is FreshnessState.NEW
    assert decide_freshness(missing, policy, now=now).reason is FreshnessReason.NO_BUNDLE
    assert decide_freshness(fresh, policy, now=now).state is FreshnessState.FRESH
    assert decide_freshness(stale, policy, now=now).state is FreshnessState.INCREMENTAL
    assert decide_freshness(stale, policy, now=now).reason is FreshnessReason.STALE_TIME


@pytest.mark.unit
def test_refresh_workflow_id_is_stable_and_scope_bound() -> None:
    first = RefreshSingleFlightKey(
        family_id="family.zigong",
        scope=("restaurants", "reviews"),
        policy_version="freshness/v1",
    )
    equivalent = first.model_copy()
    different = first.model_copy(update={"scope": ("restaurants",)})

    assert stable_refresh_workflow_id(first) == stable_refresh_workflow_id(equivalent)
    assert stable_refresh_claim_key(first).startswith("family.")
    assert stable_refresh_workflow_id(first) != stable_refresh_workflow_id(different)


@pytest.mark.unit
async def test_single_flight_service_accepts_only_deterministic_claim() -> None:
    key = RefreshSingleFlightKey(
        family_id="family.zigong",
        scope=("restaurants",),
        policy_version="freshness/v1",
    )
    repository = _Repository()
    repository.claim = RefreshClaim(
        claim_key=stable_refresh_claim_key(key),
        workflow_id=stable_refresh_workflow_id(key),
        acquired=True,
    )

    claim = await RefreshSingleFlightService(repository).claim(key)

    assert claim.acquired is True
