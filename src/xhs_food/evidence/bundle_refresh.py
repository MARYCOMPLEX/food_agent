"""Build immutable public Bundle versions from scoped refresh deltas."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BundleActivationRepository,
    BundleCandidateRepository,
    BundleDerivation,
    BundleDerivationRepository,
    BundleRefreshResult,
    BundleState,
    ContractPayload,
    DeltaCollectionResult,
    DomainContract,
    EmbeddingProfile,
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
    ProfileAwareIndexBuild,
    ProfileAwareIndexBuilder,
    RefreshDeltaCollector,
    RefreshJob,
    validate_candidate_bundle,
)


class BundleRefreshService:
    """Keep collection, public derivation, and pointer activation one-way."""

    def __init__(
        self,
        candidate_repository: BundleCandidateRepository,
        activation_repository: BundleActivationRepository,
        collector: RefreshDeltaCollector,
        domain: DomainContract,
        index_builder: ProfileAwareIndexBuilder,
        derivation_repository: BundleDerivationRepository,
        *,
        profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    ) -> None:
        self._candidate_repository = candidate_repository
        self._activation_repository = activation_repository
        self._collector = collector
        self._domain = domain
        self._index_builder = index_builder
        self._derivation_repository = derivation_repository
        self._profile = profile

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def refresh(
        self,
        job: RefreshJob,
        *,
        expected_profile_id: str | None = None,
    ) -> BundleRefreshResult:
        current_ref = await self._activation_repository.get_current_bundle(job.family_id)
        if current_ref is None:
            raise ValueError("delta refresh requires an existing current Bundle")
        if current_ref.bundle_version != job.base_bundle_version:
            raise ValueError("refresh base version does not match the current Bundle")

        current = await self._candidate_repository.get_bundle(current_ref.bundle_id)
        if current is None:
            raise ValueError("current Bundle metadata is unavailable")
        if current.family_id != job.family_id or current.bundle_version != job.base_bundle_version:
            raise ValueError("current Bundle identity does not match the refresh job")
        if current.state is not BundleState.PUBLISHED:
            raise ValueError("delta refresh requires a published base Bundle")
        current_items = await self._candidate_repository.get_items(current.evidence_ids)
        if len(current_items) != len(current.evidence_ids):
            raise ValueError("current Bundle has missing Evidence items")

        delta = await self._collector.collect(job)
        _validate_delta_scope(job, delta)
        merged_items = _merge_items(current_items, delta.evidence_items)
        candidate = build_candidate_bundle(current, merged_items, delta)
        _validate_domain_evidence(self._domain, merged_items)
        validate_candidate_bundle(candidate, merged_items)

        features = _as_payload(self._domain.compute_features(candidate, merged_items))
        public_scores = _as_payload(self._domain.score_public(_score_input(self._domain, features)))
        index = await self._index_builder.build(candidate, features, public_scores, self._profile)
        _validate_index(index, candidate, self._profile)
        derivation = _build_derivation(candidate, self._profile, features, public_scores, index)

        # Candidate and derived rows are deliberately written before the CAS. A
        # failure here leaves an unpublishable candidate while the old read path
        # remains intact.
        await self._candidate_repository.save_candidate(candidate, merged_items)
        await self._derivation_repository.save_candidate_derivation(derivation)
        activated = await self._activation_repository.activate_bundle_and_profile_if_current(
            job.family_id,
            job.base_bundle_version,
            candidate.bundle_id,
            candidate.bundle_version,
            expected_profile_id,
            self._profile,
        )
        return BundleRefreshResult(bundle=candidate, derivation=derivation, activated=activated)


def build_candidate_bundle(
    current: EvidenceBundle,
    merged_items: tuple[EvidenceItem, ...],
    delta: DeltaCollectionResult,
) -> EvidenceBundle:
    """Create a deterministic child Bundle without mutating the published parent."""

    if delta.family_id != current.family_id or delta.base_bundle_version != current.bundle_version:
        raise ValueError("delta must target the supplied current Bundle")
    evidence_ids = tuple(item.evidence_id for item in merged_items)
    item_payload = tuple(
        {
            "evidence_id": item.evidence_id,
            "content_hash": item.content_hash,
            "source_locator_id": item.source_locator_id,
        }
        for item in merged_items
    )
    content_hash = _sha256(
        {
            "family_id": current.family_id,
            "evidence": item_payload,
            "coverage": delta.coverage or current.coverage,
            "watermarks": {**current.watermarks, **delta.watermarks},
        }
    )
    provenance_hash = _sha256(
        {
            "family_id": current.family_id,
            "evidence": [item.model_dump(mode="json") for item in merged_items],
        }
    )
    version = current.bundle_version + 1
    return current.model_copy(
        update={
            "bundle_id": _versioned_id(current.family_id, "bundle", version),
            "bundle_version": version,
            "parent_bundle_version": current.bundle_version,
            "state": BundleState.CANDIDATE,
            "evidence_ids": evidence_ids,
            "coverage": {**current.coverage, **delta.coverage},
            "watermarks": {**current.watermarks, **delta.watermarks},
            "verified_at": delta.verified_at,
            "provenance_hash": provenance_hash,
            "content_hash": content_hash,
        }
    )


class InMemoryBundleDerivationRepository:
    """Deterministic test adapter; production uses the PostgreSQL adapter."""

    def __init__(self) -> None:
        self.rows: dict[str, BundleDerivation] = {}

    async def save_candidate_derivation(self, derivation: BundleDerivation) -> None:
        existing = self.rows.get(derivation.bundle_id)
        if existing is not None and existing.content_hash != derivation.content_hash:
            raise ValueError("Bundle derivation content hash conflicts with existing row")
        self.rows.setdefault(derivation.bundle_id, derivation)


def _validate_delta_scope(job: RefreshJob, delta: DeltaCollectionResult) -> None:
    if delta.family_id != job.family_id:
        raise ValueError("delta family_id does not match the refresh job")
    if delta.base_bundle_version != job.base_bundle_version:
        raise ValueError("delta base_bundle_version does not match the refresh job")
    allowed_sources = set(job.delta_scope.source_ids)
    if allowed_sources and set(delta.source_ids) - allowed_sources:
        raise ValueError("delta contains a source outside the requested scope")
    if set(delta.failed_source_ids) - set(delta.source_ids):
        raise ValueError("delta failure source is outside the collected source set")


def _merge_items(
    current: tuple[EvidenceItem, ...], delta: tuple[EvidenceItem, ...]
) -> tuple[EvidenceItem, ...]:
    merged = {item.evidence_id: item for item in current}
    merged.update({item.evidence_id: item for item in delta})
    return tuple(merged[key] for key in sorted(merged))


def _validate_domain_evidence(domain: DomainContract, items: tuple[EvidenceItem, ...]) -> None:
    for item in items:
        if item.status is not EvidenceStatus.ACCEPTED:
            raise ValueError(f"Evidence {item.evidence_id} is not accepted")
        result = domain.validate_evidence(item)
        if result.get("valid") is not True:
            raise ValueError(f"Domain Pack rejected Evidence {item.evidence_id}")


def _as_payload(value: Mapping[str, object]) -> ContractPayload:
    return cast(ContractPayload, dict(value))


def _score_input(domain: DomainContract, features: ContractPayload) -> ContractPayload:
    manifest = domain.describe()
    return {
        "schema_version": "domain-score-public-input/v1",
        "features": features,
        "policy_id": manifest.scoring_policy.policy_id,
        "policy_version": manifest.scoring_policy.policy_version,
        "config_version": f"{manifest.domain_id}-score-config/v1",
        "config": {},
    }


def _validate_index(
    index: ProfileAwareIndexBuild,
    bundle: EvidenceBundle,
    profile: EmbeddingProfile,
) -> None:
    if index.bundle_id != bundle.bundle_id:
        raise ValueError("profile-aware index belongs to a different Bundle")
    if index.profile_id != profile.profile_id:
        raise ValueError("profile-aware index uses an incompatible profile")
    if index.profile_version != profile.model_version:
        raise ValueError("profile-aware index uses an incompatible model version")
    if index.dimensions != profile.dimensions or index.distance != profile.distance.value:
        raise ValueError("profile-aware index shape does not match the active profile")


def _build_derivation(
    bundle: EvidenceBundle,
    profile: EmbeddingProfile,
    features: ContractPayload,
    public_scores: ContractPayload,
    index: ProfileAwareIndexBuild,
) -> BundleDerivation:
    content_hash = _sha256(
        {
            "bundle_id": bundle.bundle_id,
            "profile": profile.model_dump(mode="json"),
            "features": features,
            "public_scores": public_scores,
            "index": index.model_dump(mode="json"),
        }
    )
    return BundleDerivation(
        bundle_id=bundle.bundle_id,
        family_id=bundle.family_id,
        bundle_version=bundle.bundle_version,
        profile=profile,
        features=features,
        public_scores=public_scores,
        index=index,
        content_hash=content_hash,
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _versioned_id(family_id: str, kind: str, version: int) -> str:
    candidate = f"{family_id}.{kind}.v{version}"
    if len(candidate) <= 128:
        return candidate
    return f"{kind}.{hashlib.sha256(family_id.encode('utf-8')).hexdigest()[:48]}.v{version}"


__all__ = [
    "BundleRefreshService",
    "InMemoryBundleDerivationRepository",
    "build_candidate_bundle",
]
