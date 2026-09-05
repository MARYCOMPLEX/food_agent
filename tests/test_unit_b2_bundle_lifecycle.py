"""Unit gates for B2 Bundle activation and stale/partial reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BundleReadState,
    CurrentBundleRef,
    EvidenceBundle,
    EvidenceItem,
    FreshnessDecision,
    FreshnessInput,
    FreshnessPolicy,
    FreshnessReason,
    FreshnessState,
    decide_bundle_read,
    validate_candidate_bundle,
)
from xhs_food.evidence import BundleLifecycleService

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "evidence_bundle_v1.json"


def _candidate() -> tuple[EvidenceBundle, tuple[EvidenceItem, ...]]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bundle = EvidenceBundle.model_validate(value["bundles"][0]).model_copy(
        update={"state": "candidate"}
    )
    return bundle, tuple(EvidenceItem.model_validate(item) for item in value["evidence_items"])


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.activated = True

    async def activate_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: object,
    ) -> bool:
        self.calls.append(
            (
                family_id,
                expected_bundle_version,
                bundle_id,
                bundle_version,
                expected_profile_id,
                profile,
            )
        )
        return self.activated

    async def get_current_bundle(self, family_id: str) -> CurrentBundleRef | None:
        del family_id
        return None


@pytest.mark.unit
async def test_candidate_activation_validates_before_pointer_change() -> None:
    bundle, items = _candidate()
    repository = _Repository()

    result = await BundleLifecycleService(repository).activate(
        bundle,
        items,
        expected_bundle_version=None,
        expected_profile_id=None,
    )

    assert result.activated is True
    assert result.profile_id == "profile_v1"
    assert len(repository.calls) == 1
    assert repository.calls[0][1] is None


@pytest.mark.unit
def test_candidate_validation_rejects_published_bundle_and_mismatched_items() -> None:
    bundle, items = _candidate()
    with pytest.raises(ValueError, match="only candidate"):
        validate_candidate_bundle(bundle.model_copy(update={"state": "published"}), items)
    with pytest.raises(ValueError, match="evidence_ids"):
        validate_candidate_bundle(bundle, items[:-1])


@pytest.mark.unit
def test_fresh_bundle_read_is_served_without_stale_marker() -> None:
    freshness = FreshnessDecision(
        family_id="family.zigong",
        state=FreshnessState.FRESH,
        reason=FreshnessReason.WITHIN_WINDOW,
        base_bundle_version=3,
        policy_id="food.default",
        policy_version="freshness/v1",
    )
    current = CurrentBundleRef(family_id="family.zigong", bundle_id="bundle.3", bundle_version=3)

    decision = decide_bundle_read(freshness, current, {"restaurants": 0.9})

    assert decision.state is BundleReadState.FRESH
    assert decision.bundle_id == "bundle.3"


@pytest.mark.unit
def test_stale_time_returns_last_bundle_as_stale() -> None:
    freshness = FreshnessDecision(
        family_id="family.zigong",
        state=FreshnessState.INCREMENTAL,
        reason=FreshnessReason.STALE_TIME,
        base_bundle_version=3,
        policy_id="food.default",
        policy_version="freshness/v1",
    )
    current = CurrentBundleRef(family_id="family.zigong", bundle_id="bundle.3", bundle_version=3)

    assert decide_bundle_read(freshness, current, {}).state is BundleReadState.STALE


@pytest.mark.unit
def test_coverage_deficit_returns_last_bundle_as_partial() -> None:
    freshness = FreshnessDecision(
        family_id="family.zigong",
        state=FreshnessState.INCREMENTAL,
        reason=FreshnessReason.COVERAGE_DEFICIT,
        base_bundle_version=3,
        policy_id="food.default",
        policy_version="freshness/v1",
    )
    current = CurrentBundleRef(family_id="family.zigong", bundle_id="bundle.3", bundle_version=3)

    decision = decide_bundle_read(freshness, current, {"restaurants": 0.4})

    assert decision.state is BundleReadState.PARTIAL
    assert decision.coverage["restaurants"] == 0.4


@pytest.mark.unit
def test_new_family_does_not_fabricate_old_bundle() -> None:
    freshness = FreshnessDecision(
        family_id="family.new",
        state=FreshnessState.NEW,
        reason=FreshnessReason.NO_BUNDLE,
        policy_id="food.default",
        policy_version="freshness/v1",
    )

    decision = decide_bundle_read(freshness, None, {})

    assert decision.state is BundleReadState.UNAVAILABLE
    assert decision.bundle_id is None


@pytest.mark.unit
def test_no_family_reason_is_preserved_for_unavailable_read() -> None:
    freshness = FreshnessDecision(
        family_id="family.new",
        state=FreshnessState.NEW,
        reason=FreshnessReason.NO_FAMILY,
        policy_id="food.default",
        policy_version="freshness/v1",
    )

    decision = decide_bundle_read(freshness, None, {})

    assert decision.state is BundleReadState.UNAVAILABLE
    assert decision.reason is FreshnessReason.NO_FAMILY


@pytest.mark.unit
async def test_service_maps_current_freshness_to_read_decision() -> None:
    current = FreshnessInput(
        family_id="family.zigong",
        bundle_version=3,
        verified_at=datetime.now(UTC) - timedelta(hours=2),
        coverage={"restaurants": 0.9},
    )
    policy = FreshnessPolicy(
        policy_id="food.default",
        policy_version="freshness/v1",
        max_staleness_seconds=60,
    )
    ref = CurrentBundleRef(family_id="family.zigong", bundle_id="bundle.3", bundle_version=3)

    decision = await BundleLifecycleService(_Repository()).read_decision(current, policy, ref)

    assert decision.state is BundleReadState.STALE


@pytest.mark.unit
async def test_restore_pointer_uses_one_conditional_bundle_and_profile_cas() -> None:
    repository = _Repository()
    target = CurrentBundleRef(
        family_id="family.zigong",
        bundle_id="bundle.2",
        bundle_version=2,
    )

    result = await BundleLifecycleService(repository).restore_pointer(
        target,
        expected_current_bundle_version=3,
        expected_current_profile_id="profile_v2",
        target_profile=BGE_M3_PROFILE_V1,
    )

    assert result.activated is True
    assert result.bundle_id == "bundle.2"
    assert repository.calls == [
        (
            "family.zigong",
            3,
            "bundle.2",
            2,
            "profile_v2",
            BGE_M3_PROFILE_V1,
        )
    ]


@pytest.mark.unit
async def test_restore_pointer_rejects_non_older_target_before_repository_call() -> None:
    repository = _Repository()
    target = CurrentBundleRef(
        family_id="family.zigong",
        bundle_id="bundle.3",
        bundle_version=3,
    )

    with pytest.raises(ValueError, match="older"):
        await BundleLifecycleService(repository).restore_pointer(
            target,
            expected_current_bundle_version=3,
            expected_current_profile_id="profile_v1",
            target_profile=BGE_M3_PROFILE_V1,
        )

    assert repository.calls == []
