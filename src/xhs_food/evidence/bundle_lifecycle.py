"""Candidate Bundle activation and stale-read decision services."""

from __future__ import annotations

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BundleActivationRepository,
    BundleActivationResult,
    BundleReadDecision,
    CurrentBundleRef,
    EmbeddingProfile,
    EvidenceBundle,
    EvidenceItem,
    FreshnessInput,
    FreshnessPolicy,
    decide_bundle_read,
    decide_freshness,
    validate_candidate_bundle,
)


class BundleLifecycleService:
    """Validate candidates before a conditional pointer/profile activation."""

    def __init__(
        self,
        repository: BundleActivationRepository,
        *,
        profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    ) -> None:
        self._repository = repository
        self._profile = profile

    @property
    def profile_id(self) -> str:
        return self._profile.profile_id

    async def activate(
        self,
        bundle: EvidenceBundle,
        items: tuple[EvidenceItem, ...],
        *,
        expected_bundle_version: int | None,
        expected_profile_id: str | None,
    ) -> BundleActivationResult:
        validate_candidate_bundle(bundle, items)
        activated = await self._repository.activate_bundle_and_profile_if_current(
            bundle.family_id,
            expected_bundle_version,
            bundle.bundle_id,
            bundle.bundle_version,
            expected_profile_id,
            self._profile,
        )
        return BundleActivationResult(
            family_id=bundle.family_id,
            bundle_id=bundle.bundle_id,
            bundle_version=bundle.bundle_version,
            profile_id=self._profile.profile_id,
            activated=activated,
        )

    async def read_decision(
        self,
        current: FreshnessInput | None,
        policy: FreshnessPolicy,
        current_bundle: CurrentBundleRef | None,
        *,
        coverage: dict[str, float] | None = None,
    ) -> BundleReadDecision:
        if current is None:
            raise ValueError("freshness input is required for a Bundle read")
        freshness = decide_freshness(current, policy)
        return decide_bundle_read(freshness, current_bundle, coverage or current.coverage)


__all__ = ["BundleLifecycleService"]
