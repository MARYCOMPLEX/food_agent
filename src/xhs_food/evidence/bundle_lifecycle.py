"""Candidate Bundle activation and stale-read decision services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import cast

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
    decide_bundle_read_after_refresh_failure,
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

    async def restore_pointer(
        self,
        target: CurrentBundleRef,
        *,
        expected_current_bundle_version: int,
        expected_current_profile_id: str,
        target_profile: EmbeddingProfile,
    ) -> BundleActivationResult:
        """Conditionally restore an older Bundle/profile pair without deleting versions."""

        if target.bundle_version >= expected_current_bundle_version:
            raise ValueError("rollback target must be older than the current Bundle")
        restore = getattr(self._repository, "restore_bundle_and_profile_if_current", None)
        if callable(restore):
            restore_fn = cast(
                Callable[[str, int, str, int, str | None, EmbeddingProfile], Awaitable[bool]],
                restore,
            )
            restored = await restore_fn(
                target.family_id,
                expected_current_bundle_version,
                target.bundle_id,
                target.bundle_version,
                expected_current_profile_id,
                target_profile,
            )
        else:
            # Keep compatibility with older test/deployment adapters while the
            # explicit rollback port rolls out alongside monotonic activation.
            restored = await self._repository.activate_bundle_and_profile_if_current(
                target.family_id,
                expected_current_bundle_version,
                target.bundle_id,
                target.bundle_version,
                expected_current_profile_id,
                target_profile,
            )
        return BundleActivationResult(
            family_id=target.family_id,
            bundle_id=target.bundle_id,
            bundle_version=target.bundle_version,
            profile_id=target_profile.profile_id,
            activated=restored,
        )

    async def read_decision(
        self,
        current: FreshnessInput | None,
        policy: FreshnessPolicy,
        current_bundle: CurrentBundleRef | None,
        *,
        coverage: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> BundleReadDecision:
        if current is None:
            raise ValueError("freshness input is required for a Bundle read")
        freshness = decide_freshness(current, policy, now=now)
        effective_coverage = current.coverage if coverage is None else coverage
        return decide_bundle_read(freshness, current_bundle, effective_coverage)

    async def read_decision_after_refresh_failure(
        self,
        current: FreshnessInput | None,
        policy: FreshnessPolicy,
        current_bundle: CurrentBundleRef | None,
        *,
        failure_category: str,
        coverage: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> BundleReadDecision:
        """Return a bounded stale fallback or an explicit unavailable result."""

        if current is None:
            raise ValueError("freshness input is required for a Bundle read")
        freshness = decide_freshness(current, policy, now=now)
        effective_coverage = current.coverage if coverage is None else coverage
        return decide_bundle_read_after_refresh_failure(
            freshness,
            current_bundle,
            effective_coverage,
            failure_category=failure_category,
        )


__all__ = ["BundleLifecycleService"]
