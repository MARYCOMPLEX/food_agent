"""Contracts for candidate Bundle activation and stale reads."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyStr
from .embedding import EmbeddingProfile
from .evidence import EvidenceBundle, EvidenceItem, RegisteredSlug
from .query_reuse import FreshnessDecision, FreshnessReason

BUNDLE_ACTIVATION_VERSION = "bundle-activation/v1"
BUNDLE_READ_VERSION = "bundle-read/v1"


class BundleReadState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CurrentBundleRef(ContractModel):
    family_id: RegisteredSlug
    bundle_id: NonEmptyStr
    bundle_version: int = Field(ge=1)


class BundleActivationResult(ContractModel):
    schema_version: Literal["bundle-activation/v1"] = BUNDLE_ACTIVATION_VERSION
    family_id: RegisteredSlug
    bundle_id: NonEmptyStr
    bundle_version: int = Field(ge=1)
    profile_id: RegisteredSlug
    activated: bool


class BundleReadDecision(ContractModel):
    schema_version: Literal["bundle-read/v1"] = BUNDLE_READ_VERSION
    family_id: RegisteredSlug
    bundle_id: NonEmptyStr | None = None
    bundle_version: int | None = Field(default=None, ge=1)
    state: BundleReadState
    reason: FreshnessReason
    coverage: dict[RegisteredSlug, float] = Field(default_factory=dict)
    refresh_failure: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> BundleReadDecision:
        has_bundle = self.bundle_id is not None or self.bundle_version is not None
        if has_bundle != (self.bundle_id is not None and self.bundle_version is not None):
            raise ValueError("bundle_id and bundle_version must be provided together")
        if self.state is BundleReadState.UNAVAILABLE and has_bundle:
            raise ValueError("unavailable Bundle reads cannot expose a Bundle reference")
        if self.state is BundleReadState.FRESH and self.refresh_failure is not None:
            raise ValueError("fresh Bundle reads cannot carry a refresh failure")
        if self.state is BundleReadState.UNAVAILABLE and self.refresh_failure is not None:
            # An unavailable result has no stale response to annotate.  The
            # failure belongs in the surrounding research outcome instead.
            raise ValueError("unavailable Bundle reads cannot carry stale fallback metadata")
        return self


class BundleActivationRepository(Protocol):
    async def activate_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: EmbeddingProfile,
    ) -> bool: ...

    async def restore_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: EmbeddingProfile,
    ) -> bool: ...

    async def get_current_bundle(self, family_id: str) -> CurrentBundleRef | None: ...


def validate_candidate_bundle(bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]) -> None:
    """Validate candidate identity before any pointer can be changed."""

    from .evidence import BundleState

    if bundle.state is not BundleState.CANDIDATE:
        raise ValueError("only candidate Bundles may be activated")
    item_ids = tuple(item.evidence_id for item in items)
    if set(item_ids) != set(bundle.evidence_ids) or len(item_ids) != len(bundle.evidence_ids):
        raise ValueError("candidate Bundle evidence_ids must match the item set")


def decide_bundle_read(
    freshness: FreshnessDecision,
    current: CurrentBundleRef | None,
    coverage: dict[RegisteredSlug, float],
) -> BundleReadDecision:
    """Serve the last committed Bundle while reporting why it is not fresh."""

    if current is not None and current.family_id != freshness.family_id:
        raise ValueError("current Bundle belongs to a different Query Family")
    if current is None or freshness.state.value == "new":
        return BundleReadDecision(
            family_id=freshness.family_id,
            state=BundleReadState.UNAVAILABLE,
            reason=(
                freshness.reason
                if freshness.reason
                in {
                    FreshnessReason.NO_FAMILY,
                    FreshnessReason.NO_BUNDLE,
                    FreshnessReason.MAXIMUM_STALENESS,
                    FreshnessReason.STALE_LIMIT_EXCEEDED,
                }
                else FreshnessReason.NO_BUNDLE
            ),
            coverage=coverage,
        )
    state = (
        BundleReadState.FRESH
        if freshness.state.value == "fresh"
        else BundleReadState.PARTIAL
        if freshness.reason is FreshnessReason.COVERAGE_DEFICIT
        else BundleReadState.STALE
    )
    return BundleReadDecision(
        family_id=current.family_id,
        bundle_id=current.bundle_id,
        bundle_version=current.bundle_version,
        state=state,
        reason=freshness.reason,
        coverage=coverage,
    )


def decide_bundle_read_after_refresh_failure(
    freshness: FreshnessDecision,
    current: CurrentBundleRef | None,
    coverage: dict[RegisteredSlug, float],
    *,
    failure_category: str,
) -> BundleReadDecision:
    """Attach a bounded refresh failure only to an eligible stale fallback."""

    if not isinstance(failure_category, str) or not failure_category.strip():
        raise ValueError("refresh failure category must be non-empty")
    decision = decide_bundle_read(freshness, current, coverage)
    if decision.state not in {BundleReadState.STALE, BundleReadState.PARTIAL}:
        return decision
    return decision.model_copy(
        update={
            "reason": FreshnessReason.REFRESH_FAILED,
            "refresh_failure": failure_category.strip(),
        }
    )


__all__ = [
    "BUNDLE_ACTIVATION_VERSION",
    "BUNDLE_READ_VERSION",
    "BundleActivationRepository",
    "BundleActivationResult",
    "BundleReadDecision",
    "BundleReadState",
    "CurrentBundleRef",
    "decide_bundle_read",
    "decide_bundle_read_after_refresh_failure",
    "validate_candidate_bundle",
]
