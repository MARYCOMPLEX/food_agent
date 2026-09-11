"""Contracts for immutable Bundle delta refresh and derived public indexes."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field, model_validator

from .base import ContractModel, ContractPayload, Timestamp
from .embedding import EmbeddingProfile
from .evidence import ContractVersion, EvidenceBundle, EvidenceItem, RegisteredSlug
from .refresh_media import RefreshJob

BUNDLE_REFRESH_VERSION = "bundle-refresh/v1"
BUNDLE_DERIVATION_VERSION = "bundle-derivation/v1"
BUNDLE_INDEX_VERSION = "bundle-index/v1"


class DeltaCollectionResult(ContractModel):
    """Connector/extractor output for one public refresh scope."""

    schema_version: Literal["bundle-refresh/v1"] = BUNDLE_REFRESH_VERSION
    family_id: RegisteredSlug
    base_bundle_version: int = Field(ge=1)
    evidence_items: tuple[EvidenceItem, ...] = ()
    coverage: dict[RegisteredSlug, float] = Field(default_factory=dict)
    watermarks: dict[RegisteredSlug, str] = Field(default_factory=dict)
    source_ids: tuple[RegisteredSlug, ...] = ()
    failed_source_ids: tuple[RegisteredSlug, ...] = ()
    verified_at: Timestamp

    @model_validator(mode="after")
    def validate_delta(self) -> DeltaCollectionResult:
        evidence_ids = tuple(item.evidence_id for item in self.evidence_items)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("delta evidence_items must have unique evidence_id values")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("delta source_ids must be unique")
        if len(self.failed_source_ids) != len(set(self.failed_source_ids)):
            raise ValueError("failed_source_ids must be unique")
        if set(self.failed_source_ids) - set(self.source_ids):
            raise ValueError("failed_source_ids must be included in source_ids")
        if any(not 0.0 <= value <= 1.0 for value in self.coverage.values()):
            raise ValueError("delta coverage must be between 0 and 1")
        return self


class ProfileAwareIndexBuild(ContractModel):
    """Immutable metadata proving a derived index was built for one profile."""

    schema_version: Literal["bundle-index/v1"] = BUNDLE_INDEX_VERSION
    bundle_id: RegisteredSlug
    profile_id: RegisteredSlug
    profile_version: ContractVersion
    dimensions: int = Field(ge=1)
    distance: Literal["cosine"]
    index_id: RegisteredSlug
    item_count: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BundleDerivation(ContractModel):
    """Public feature/score output and its profile-pinned index receipt."""

    schema_version: Literal["bundle-derivation/v1"] = BUNDLE_DERIVATION_VERSION
    bundle_id: RegisteredSlug
    family_id: RegisteredSlug
    bundle_version: int = Field(ge=1)
    profile: EmbeddingProfile
    features: ContractPayload
    public_scores: ContractPayload
    index: ProfileAwareIndexBuild
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_index_identity(self) -> BundleDerivation:
        if self.index.bundle_id != self.bundle_id:
            raise ValueError("derived index must belong to the Bundle")
        if self.index.profile_id != self.profile.profile_id:
            raise ValueError("derived index profile does not match the Bundle profile")
        if self.index.profile_version != self.profile.model_version:
            raise ValueError("derived index model version does not match the Bundle profile")
        if self.index.dimensions != self.profile.dimensions:
            raise ValueError("derived index dimensions do not match the Bundle profile")
        if self.index.distance != self.profile.distance.value:
            raise ValueError("derived index distance does not match the Bundle profile")
        return self


class BundleRefreshResult(ContractModel):
    """Refresh outcome; an unactivated candidate remains explicitly visible."""

    schema_version: Literal["bundle-refresh/v1"] = BUNDLE_REFRESH_VERSION
    bundle: EvidenceBundle
    derivation: BundleDerivation
    activated: bool


class RefreshDeltaCollector(Protocol):
    async def collect(self, job: RefreshJob) -> DeltaCollectionResult: ...


class ProfileAwareIndexBuilder(Protocol):
    async def build(
        self,
        bundle: EvidenceBundle,
        features: ContractPayload,
        public_scores: ContractPayload,
        profile: EmbeddingProfile,
    ) -> ProfileAwareIndexBuild: ...


class BundleCandidateRepository(Protocol):
    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None: ...

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]: ...

    async def save_candidate(
        self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]
    ) -> EvidenceBundle: ...


class BundleDerivationRepository(Protocol):
    async def save_candidate_derivation(self, derivation: BundleDerivation) -> None: ...


__all__ = [
    "BUNDLE_DERIVATION_VERSION",
    "BUNDLE_INDEX_VERSION",
    "BUNDLE_REFRESH_VERSION",
    "BundleCandidateRepository",
    "BundleDerivation",
    "BundleDerivationRepository",
    "BundleRefreshResult",
    "DeltaCollectionResult",
    "ProfileAwareIndexBuild",
    "ProfileAwareIndexBuilder",
    "RefreshDeltaCollector",
]
