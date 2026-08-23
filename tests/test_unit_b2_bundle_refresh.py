"""B2 delta refresh, public derivation, and pointer safety gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    DeltaCollectionResult,
    EmbeddingProfile,
    EvidenceBundle,
    EvidenceItem,
    ProfileAwareIndexBuild,
    RefreshDeltaScope,
    RefreshJob,
    RefreshPriorityReason,
    validate_candidate_bundle,
)
from xhs_food.evidence import BundleRefreshService, InMemoryBundleDerivationRepository

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "evidence_bundle_v1.json"


def _base() -> tuple[EvidenceBundle, tuple[EvidenceItem, ...]]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bundle = EvidenceBundle.model_validate(value["bundles"][0])
    return bundle, tuple(EvidenceItem.model_validate(item) for item in value["evidence_items"])


def _job(base: EvidenceBundle) -> RefreshJob:
    return RefreshJob(
        job_id="refresh.job.b2",
        family_id=base.family_id,
        base_bundle_version=base.bundle_version,
        delta_scope=RefreshDeltaScope(partition_ids=("public_attributes",), source_ids=("xhs",)),
        watermarks={"restaurant.source_updated": "opaque:source-watermark-42"},
        priority_reasons=(RefreshPriorityReason.EXPLICIT_REQUEST,),
        workflow_id="refresh.family.fixture",
        idempotency_key="family.fixture.refresh",
        requested_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )


class _CandidateRepository:
    def __init__(self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...], *, fail: bool = False) -> None:
        self.bundle = bundle
        self.items = items
        self.fail = fail
        self.saved: EvidenceBundle | None = None

    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None:
        return self.bundle if bundle_id == self.bundle.bundle_id else None

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]:
        return tuple(item for item in self.items if item.evidence_id in evidence_ids)

    async def save_candidate(
        self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]
    ) -> EvidenceBundle:
        if self.fail:
            raise RuntimeError("candidate evidence write failed")
        validate_candidate_bundle(bundle, items)
        self.saved = bundle
        return bundle


class _ActivationRepository:
    def __init__(self, bundle: EvidenceBundle, *, activated: bool = True) -> None:
        self.bundle = bundle
        self.activated = activated
        self.calls: list[tuple[object, ...]] = []

    async def get_current_bundle(self, family_id: str):
        if family_id != self.bundle.family_id:
            return None
        from xhs_food.contracts import CurrentBundleRef

        return CurrentBundleRef(
            family_id=self.bundle.family_id,
            bundle_id=self.bundle.bundle_id,
            bundle_version=self.bundle.bundle_version,
        )

    async def activate_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: EmbeddingProfile,
    ) -> bool:
        self.calls.append(
            (family_id, expected_bundle_version, bundle_id, bundle_version, expected_profile_id, profile)
        )
        return self.activated


class _Collector:
    def __init__(self, delta: DeltaCollectionResult) -> None:
        self.delta = delta

    async def collect(self, job: RefreshJob) -> DeltaCollectionResult:
        assert job.delta_scope.partition_ids == ("public_attributes",)
        return self.delta


class _Domain:
    class _Manifest:
        domain_id = "fixture"

        class _Policy:
            policy_id = "fixture.public-score"
            policy_version = "1.0.0"

        scoring_policy = _Policy()

    def describe(self):
        return self._Manifest()

    def validate_evidence(self, evidence: EvidenceItem):
        return {"valid": evidence.evidence_type == "restaurant"}

    def compute_features(self, bundle: EvidenceBundle, evidence_items: tuple[EvidenceItem, ...]):
        return {
            "bundle_id": bundle.bundle_id,
            "features": [{"entity_id": item.evidence_id, "values": {"confidence": item.confidence}} for item in evidence_items],
        }

    def score_public(self, features):
        return {"bundle_id": features["features"]["bundle_id"], "scores": []}


class _IndexBuilder:
    def __init__(self, *, fail: bool = False, profile: EmbeddingProfile = BGE_M3_PROFILE_V1) -> None:
        self.fail = fail
        self.profile = profile

    async def build(self, bundle, features, public_scores, profile):
        del features, public_scores
        if self.fail:
            raise RuntimeError("index build failed")
        return ProfileAwareIndexBuild(
            bundle_id=bundle.bundle_id,
            profile_id=self.profile.profile_id,
            profile_version=self.profile.model_version,
            dimensions=self.profile.dimensions,
            distance=self.profile.distance.value,
            index_id="index.bundle.v2",
            item_count=len(bundle.evidence_ids),
            content_hash="f" * 64,
        )


class _FailingDerivationRepository(InMemoryBundleDerivationRepository):
    async def save_candidate_derivation(self, derivation) -> None:
        del derivation
        raise RuntimeError("derivation write failed")


def _service(
    *,
    fail_index: bool = False,
    fail_candidate: bool = False,
    derivations: InMemoryBundleDerivationRepository | None = None,
    activated: bool = True,
    profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    builder_profile: EmbeddingProfile | None = None,
) -> tuple[BundleRefreshService, _CandidateRepository, _ActivationRepository, InMemoryBundleDerivationRepository]:
    base, items = _base()
    candidate = _CandidateRepository(base, items, fail=fail_candidate)
    activation = _ActivationRepository(base, activated=activated)
    delta = DeltaCollectionResult(
        family_id=base.family_id,
        base_bundle_version=base.bundle_version,
        evidence_items=(items[0].model_copy(update={"confidence": 0.99}),),
        coverage={"public_attributes": 0.95},
        watermarks={"restaurant.source_updated": "opaque:source-watermark-43"},
        source_ids=("xhs",),
        verified_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    derivations = derivations or InMemoryBundleDerivationRepository()
    service = BundleRefreshService(
        candidate,
        activation,
        _Collector(delta),
        _Domain(),
        _IndexBuilder(fail=fail_index, profile=builder_profile or profile),
        derivations,
        profile=profile,
    )
    return service, candidate, activation, derivations


@pytest.mark.unit
async def test_delta_refresh_recomputes_public_derivation_before_atomic_activation() -> None:
    service, candidate, activation, derivations = _service()
    base, _ = _base()

    result = await service.refresh(_job(base), expected_profile_id=None)

    assert result.activated is True
    assert result.bundle.bundle_version == 2
    assert result.bundle.parent_bundle_version == 1
    assert candidate.saved == result.bundle
    assert derivations.rows[result.bundle.bundle_id] == result.derivation
    assert activation.calls[0][2] == result.bundle.bundle_id
    assert result.derivation.profile.profile_id == "profile_v1"


@pytest.mark.unit
async def test_index_failure_keeps_old_bundle_and_pointer_untouched() -> None:
    service, candidate, activation, derivations = _service(fail_index=True)
    base, _ = _base()

    with pytest.raises(RuntimeError, match="index build failed"):
        await service.refresh(_job(base))

    assert candidate.saved is None
    assert derivations.rows == {}
    assert activation.calls == []


@pytest.mark.unit
async def test_refresh_rejects_cross_profile_index_before_candidate_write() -> None:
    other = EmbeddingProfile(
        profile_id="other_profile",
        model_id="other-model",
        model_version="other-model/v1",
        dimensions=2,
    )
    service, candidate, activation, derivations = _service(builder_profile=other)
    base, _ = _base()

    with pytest.raises(ValueError, match="profile-aware index"):
        await service.refresh(_job(base))

    assert candidate.saved is None
    assert derivations.rows == {}
    assert activation.calls == []


@pytest.mark.unit
async def test_refresh_rejects_model_version_change_before_candidate_write() -> None:
    changed = EmbeddingProfile(
        profile_id="profile_v1",
        model_id="bge-m3",
        model_version="bge-m3/v2",
        dimensions=1024,
    )
    service, candidate, activation, derivations = _service(builder_profile=changed)
    base, _ = _base()

    with pytest.raises(ValueError, match="profile-aware index"):
        await service.refresh(_job(base))

    assert candidate.saved is None
    assert derivations.rows == {}
    assert activation.calls == []


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["candidate", "derivation", "activation"])
async def test_refresh_failure_injection_never_replaces_old_pointer(failure: str) -> None:
    derivations = _FailingDerivationRepository() if failure == "derivation" else None
    service, candidate, activation, stored = _service(
        fail_candidate=failure == "candidate",
        derivations=derivations,
        activated=failure != "activation",
    )
    base, _ = _base()

    if failure == "candidate":
        with pytest.raises(RuntimeError, match="candidate evidence"):
            await service.refresh(_job(base))
        assert activation.calls == []
    elif failure == "derivation":
        with pytest.raises(RuntimeError, match="derivation"):
            await service.refresh(_job(base))
        assert candidate.saved is not None
        assert activation.calls == []
    else:
        result = await service.refresh(_job(base))
        assert result.activated is False
        assert candidate.saved is not None
        assert stored.rows[result.bundle.bundle_id] == result.derivation

    assert activation.bundle.bundle_id == base.bundle_id
    assert activation.bundle.bundle_version == base.bundle_version
