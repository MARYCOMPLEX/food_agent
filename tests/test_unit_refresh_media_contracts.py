"""Focused contracts for versioned refresh and media extension boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import xhs_food.contracts as contracts
from xhs_food.contracts import (
    EvidenceExtractionRequest,
    EvidenceExtractor,
    MediaAsset,
    MediaProcessingRequest,
    MediaProcessor,
    ProcessingLimits,
    RefreshDeltaScope,
    RefreshJob,
    RefreshPriorityReason,
    WorkloadPort,
)
from xhs_food.contracts.evidence import (
    DerivedArtifact,
    EvidenceLicense,
    EvidenceVisibility,
    LicenseStatus,
    LicenseUse,
    MediaRef,
    MediaType,
    RetentionPolicy,
    SourceLocator,
    VisibilityScope,
)
from xhs_food.contracts.ports import ObjectRef

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def _governance() -> tuple[EvidenceVisibility, EvidenceLicense, RetentionPolicy]:
    return (
        EvidenceVisibility(
            scope=VisibilityScope.PUBLIC,
            tenant_scope="public",
            entitlement_ids=(),
        ),
        EvidenceLicense(
            license_id="fixture-license",
            status=LicenseStatus.KNOWN,
            allowed_use=LicenseUse.INTERNAL_REUSE,
            attribution_required=True,
            expires_at=None,
            policy_version="evidence-license/v1",
        ),
        RetentionPolicy(
            retention_class="source_default",
            duration_seconds=None,
            legal_hold=False,
        ),
    )


def _source_locator() -> SourceLocator:
    visibility, license_, retention = _governance()
    return SourceLocator(
        locator_id="source.fixture.document",
        source_id="fixture",
        connector_id="fixture.connector",
        connector_version="fixture_connector/v1",
        external_id="document-1",
        canonical_url="https://fixture.invalid/document-1",
        captured_at=NOW,
        source_updated_at=None,
        watermark="opaque-watermark",
        visibility=visibility,
        license=license_,
        retention=retention,
    )


def _media_asset() -> MediaAsset:
    locator = _source_locator()
    return MediaAsset(
        asset_id="asset.fixture.image",
        media_ref=MediaRef(
            media_ref_id="media.fixture.image",
            locator_id=locator.locator_id,
            media_type=MediaType.IMAGE,
            source_url="https://fixture.invalid/image.jpg",
            declared_content_type="image/jpeg",
            declared_sha256=HASH,
        ),
        source_locator=locator,
        object_ref=ObjectRef(
            object_id="object-1",
            key="raw/sha256/" + HASH,
            content_hash=HASH,
            size_bytes=128,
            content_type="image/jpeg",
        ),
        sha256=HASH,
        size_bytes=128,
        content_type="image/jpeg",
        media_type=MediaType.IMAGE,
        fetched_at=NOW,
        visibility=locator.visibility,
        license=locator.license,
        retention=locator.retention,
    )


def _limits() -> ProcessingLimits:
    return ProcessingLimits(
        timeout_ms=30_000,
        max_input_bytes=1_000_000,
        max_output_bytes=100_000,
        max_outputs=20,
        max_memory_bytes=256_000_000,
    )


def _artifact() -> DerivedArtifact:
    visibility, license_, retention = _governance()
    return DerivedArtifact(
        artifact_id="artifact.fixture.ocr",
        object_ref="s3://fixture/derived/" + HASH,
        sha256=HASH,
        size_bytes=64,
        content_type="application/json",
        processor_id="ocr",
        processor_version="ocr/v1",
        input_refs=("media.fixture.image",),
        created_at=NOW,
        visibility=visibility,
        license=license_,
        retention=retention,
    )


def test_refresh_job_is_versioned_and_has_only_a_logical_queue_port() -> None:
    job = RefreshJob(
        job_id="refresh-job-1",
        family_id="family.fixture",
        base_bundle_version=3,
        delta_scope=RefreshDeltaScope(
            partition_ids=("expired.documents", "missing.media"),
            source_ids=("fixture",),
        ),
        watermarks={"fixture.updated": "opaque:42"},
        priority_reasons=(
            RefreshPriorityReason.EXPLICIT_REQUEST,
            RefreshPriorityReason.SOURCE_WATERMARK_ADVANCED,
        ),
        workflow_id="refresh:family.fixture:3",
        idempotency_key="refresh:family.fixture:3:scope-hash",
        requested_at=NOW,
    )

    payload = json.loads(job.model_dump_json())
    assert payload["schema_version"] == "1.0"
    assert payload["workload_port"] == WorkloadPort.REFRESH
    assert {"workflow_id", "idempotency_key", "base_bundle_version"} <= payload.keys()
    assert all("temporal" not in name for name in RefreshJob.model_fields)
    assert RefreshJob.model_validate_json(job.model_dump_json()) == job


def test_refresh_scope_and_reasons_are_nonempty_and_deduplicated() -> None:
    with pytest.raises(ValidationError):
        RefreshDeltaScope(partition_ids=())
    with pytest.raises(ValidationError):
        RefreshDeltaScope(partition_ids=("expired.documents", "expired.documents"))
    with pytest.raises(ValidationError):
        RefreshJob(
            job_id="refresh-job-1",
            family_id="family.fixture",
            base_bundle_version=1,
            delta_scope=RefreshDeltaScope(partition_ids=("expired.documents",)),
            watermarks={},
            priority_reasons=(),
            workflow_id="workflow-1",
            idempotency_key="key-1",
            requested_at=NOW,
        )


def test_media_asset_uses_object_ref_and_preserves_hash_provenance_and_governance() -> None:
    asset = _media_asset()
    payload = asset.model_dump(mode="json")

    assert payload["object_ref"]["content_hash"] == HASH
    assert payload["media_ref"]["locator_id"] == payload["source_locator"]["locator_id"]
    assert payload["visibility"] == payload["source_locator"]["visibility"]
    assert payload["license"] == payload["source_locator"]["license"]
    assert payload["retention"] == payload["source_locator"]["retention"]
    assert {"bytes", "data", "base64", "signed_url"}.isdisjoint(payload)

    with pytest.raises(ValidationError):
        MediaAsset.model_validate({**payload, "bytes": b"not-contract-data"})
    with pytest.raises(ValidationError, match="content_hash"):
        MediaAsset.model_validate(
            {
                **payload,
                "object_ref": {**payload["object_ref"], "content_hash": "b" * 64},
            }
        )


def test_media_asset_rejects_detached_or_broadened_source_governance() -> None:
    payload = _media_asset().model_dump(mode="json")
    payload["media_ref"]["locator_id"] = "source.other.document"
    with pytest.raises(ValidationError, match="media_ref"):
        MediaAsset.model_validate(payload)

    payload = _media_asset().model_dump(mode="json")
    payload["retention"] = {
        "retention_class": "different",
        "duration_seconds": None,
        "legal_hold": False,
    }
    with pytest.raises(ValidationError, match="retention"):
        MediaAsset.model_validate(payload)


def test_processing_requests_pin_versions_limits_and_media_workload_port() -> None:
    request = MediaProcessingRequest(
        request_id="process-1",
        processor_id="ocr",
        processor_version="ocr/v1",
        asset=_media_asset(),
        limits=_limits(),
    )

    assert request.workload_port is WorkloadPort.MEDIA
    assert request.processor_version == "ocr/v1"
    assert request.limits.timeout_ms == 30_000
    assert MediaProcessingRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        ProcessingLimits(
            timeout_ms=0,
            max_input_bytes=1,
            max_output_bytes=1,
            max_outputs=1,
            max_memory_bytes=1,
        )


def test_extraction_requires_hashed_text_or_versioned_artifacts() -> None:
    text = "fixture extracted text"
    request = EvidenceExtractionRequest(
        request_id="extract-1",
        extractor_id="food.ocr",
        extractor_version="food_ocr/v1",
        evidence_schema_version="food_evidence/v1",
        source_locator=_source_locator(),
        source_text=text,
        source_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        artifacts=(_artifact(),),
        limits=_limits(),
    )

    assert request.artifacts[0].processor_version == "ocr/v1"
    assert EvidenceExtractionRequest.model_validate_json(request.model_dump_json()) == request

    payload = request.model_dump(mode="json")
    with pytest.raises(ValidationError, match="source_text_sha256"):
        EvidenceExtractionRequest.model_validate(
            {**payload, "source_text_sha256": "b" * 64}
        )
    with pytest.raises(ValidationError, match="requires text or"):
        EvidenceExtractionRequest.model_validate(
            {
                **payload,
                "source_text": None,
                "source_text_sha256": None,
                "artifacts": [],
            }
        )


def test_processor_and_extractor_are_sdk_neutral_structural_protocols() -> None:
    assert getattr(MediaProcessor, "_is_protocol", False) is True
    assert getattr(MediaProcessor, "_is_runtime_protocol", False) is True
    assert getattr(EvidenceExtractor, "_is_protocol", False) is True
    assert getattr(EvidenceExtractor, "_is_runtime_protocol", False) is True

    class FixtureProcessor:
        processor_id = "ocr"
        processor_version = "ocr/v1"

        def supports(self, media_type: MediaType, content_type: str) -> bool:
            return media_type is MediaType.IMAGE and content_type == "image/jpeg"

        async def process(
            self, request: MediaProcessingRequest
        ) -> tuple[DerivedArtifact, ...]:
            return (_artifact(),)

    class FixtureExtractor:
        extractor_id = "food.ocr"
        extractor_version = "food_ocr/v1"

        def supports(self, request: EvidenceExtractionRequest) -> bool:
            return bool(request.artifacts)

        async def extract(self, request: EvidenceExtractionRequest) -> tuple:
            return ()

    assert isinstance(FixtureProcessor(), MediaProcessor)
    assert isinstance(FixtureExtractor(), EvidenceExtractor)


def test_contract_fields_cannot_embed_binary_or_access_material() -> None:
    forbidden = {"bytes", "data", "base64", "credentials", "cookies", "signed_url"}
    contract_types = (
        RefreshJob,
        MediaAsset,
        MediaProcessingRequest,
        EvidenceExtractionRequest,
    )
    for contract_type in contract_types:
        assert forbidden.isdisjoint(contract_type.model_fields)


def test_refresh_media_contracts_are_public_sdk_exports() -> None:
    names = {
        "EvidenceExtractionRequest",
        "EvidenceExtractor",
        "MediaAsset",
        "MediaProcessingRequest",
        "MediaProcessor",
        "ProcessingLimits",
        "RefreshDeltaScope",
        "RefreshJob",
        "RefreshPriorityReason",
        "Sha256Digest",
        "WorkloadPort",
    }
    assert names <= set(contracts.__all__)
    assert all(getattr(contracts, name) is not None for name in names)
