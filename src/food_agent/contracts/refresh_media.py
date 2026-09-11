"""Refresh and media-pipeline contracts without runtime or storage SDK bindings."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from .base import NonEmptyStr, SchemaVersion, Timestamp, VersionedContract, schema_version_v1
from .evidence import (
    AuthorityModel,
    ContractVersion,
    DerivedArtifact,
    EvidenceItem,
    EvidenceLicense,
    EvidenceVisibility,
    MediaRef,
    MediaType,
    RegisteredSlug,
    RetentionPolicy,
    SourceLocator,
)
from .ports import ObjectRef, TemporalExecutionPolicy

Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class WorkloadPort(StrEnum):
    """Logical workload identity; concrete queue names belong to runtime adapters."""

    RESEARCH = "research"
    REFRESH = "refresh"
    MEDIA = "media"


class RefreshPriorityReason(StrEnum):
    """Stable reasons from the approved refresh contract, without policy weights."""

    EXPLICIT_REQUEST = "explicit_request"
    POPULAR = "popular"
    EXPIRING = "expiring"
    COVERAGE_DECLINE = "coverage_decline"
    SOURCE_WATERMARK_ADVANCED = "source_watermark_advanced"
    NEW_SOURCE = "new_source"
    NEW_TIME_WINDOW = "new_time_window"
    PRIVACY_SAFE_FEEDBACK = "privacy_safe_feedback"


class RefreshPriorityPolicy(AuthorityModel):
    """Versioned public scheduling thresholds and bounded integer weights."""

    policy_version: ContractVersion = "refresh-priority/v1"
    popular_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    expiring_within_seconds: int = Field(default=3_600, ge=0)
    coverage_decline_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    feedback_min_subjects: int = Field(default=20, ge=2)
    feedback_change_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    popular_weight: int = Field(default=50, ge=0, le=100)
    expiring_weight: int = Field(default=40, ge=0, le=100)
    coverage_decline_weight: int = Field(default=35, ge=0, le=100)
    watermark_weight: int = Field(default=30, ge=0, le=100)
    new_source_weight: int = Field(default=20, ge=0, le=100)
    new_time_window_weight: int = Field(default=15, ge=0, le=100)
    feedback_weight: int = Field(default=10, ge=0, le=100)


class RefreshPrioritySignals(AuthorityModel):
    """Public scheduling signals; individual feedback records are forbidden."""

    family_id: RegisteredSlug
    observed_at: Timestamp
    popularity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    expires_at: Timestamp | None = None
    current_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    previous_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    source_watermark_advanced: bool = False
    has_new_source: bool = False
    has_new_time_window: bool = False
    feedback_subject_count: int = Field(default=0, ge=0)
    feedback_change_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RefreshPriorityDecision(AuthorityModel):
    """Deterministic priority with stable, privacy-safe reason codes."""

    family_id: RegisteredSlug
    policy_version: ContractVersion
    priority: int = Field(ge=0)
    eligible: bool
    reasons: tuple[RefreshPriorityReason, ...] = ()

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("refresh priority reasons must not contain duplicates")
        if self.eligible != bool(self.reasons):
            raise ValueError("refresh eligibility must match the presence of reasons")
        if not self.eligible and self.priority != 0:
            raise ValueError("ineligible refresh decisions must have zero priority")
        return self


class RefreshDeltaScope(AuthorityModel):
    """Public partitions selected for delta collection; no user context is allowed."""

    partition_ids: tuple[RegisteredSlug, ...] = Field(min_length=1)
    source_ids: tuple[RegisteredSlug, ...] = ()

    @model_validator(mode="after")
    def validate_unique_references(self) -> Self:
        for name, values in (
            ("partition_ids", self.partition_ids),
            ("source_ids", self.source_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        return self


class RefreshJob(AuthorityModel):
    """Durable refresh command pinned to one Family base version and workflow identity."""

    schema_version: SchemaVersion = Field(default_factory=schema_version_v1)
    job_id: NonEmptyStr
    family_id: RegisteredSlug
    base_bundle_version: int = Field(ge=1)
    delta_scope: RefreshDeltaScope
    watermarks: dict[RegisteredSlug, str]
    priority_reasons: tuple[RefreshPriorityReason, ...] = Field(min_length=1)
    workflow_id: NonEmptyStr
    idempotency_key: NonEmptyStr
    workload_port: Literal[WorkloadPort.REFRESH] = WorkloadPort.REFRESH
    requested_at: Timestamp

    @model_validator(mode="after")
    def validate_priority_reasons(self) -> Self:
        if len(self.priority_reasons) != len(set(self.priority_reasons)):
            raise ValueError("priority_reasons must not contain duplicates")
        return self


class RefreshWorkflowInput(VersionedContract):
    """Deterministic input for the Refresh Temporal Workflow."""

    job: RefreshJob
    execution_policy: TemporalExecutionPolicy = Field(default_factory=TemporalExecutionPolicy)
    expected_profile_id: NonEmptyStr | None = None


class RefreshWorkflowResult(VersionedContract):
    """Workflow result after candidate validation and conditional activation."""

    job_id: NonEmptyStr
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    status: Literal["completed", "cancelled"]
    activated: bool = False
    bundle_id: RegisteredSlug | None = None
    bundle_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        has_bundle = self.bundle_id is not None and self.bundle_version is not None
        if self.status == "cancelled" and (self.activated or has_bundle):
            raise ValueError("cancelled refresh cannot report an activated Bundle")
        if self.status == "completed" and not has_bundle:
            raise ValueError("completed refresh must identify its candidate Bundle")
        return self


class MediaAsset(AuthorityModel):
    """Committed metadata for raw bytes addressed only through an ObjectRef."""

    asset_id: RegisteredSlug
    media_ref: MediaRef
    source_locator: SourceLocator
    object_ref: ObjectRef
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    content_type: NonEmptyStr
    media_type: MediaType
    fetched_at: Timestamp
    visibility: EvidenceVisibility
    license: EvidenceLicense
    retention: RetentionPolicy

    @model_validator(mode="after")
    def validate_object_and_provenance(self) -> Self:
        if self.media_ref.locator_id != self.source_locator.locator_id:
            raise ValueError("media_ref must belong to source_locator")
        if self.media_type is not self.media_ref.media_type:
            raise ValueError("MediaAsset media_type must match MediaRef media_type")
        if (
            self.media_ref.declared_sha256 is not None
            and self.media_ref.declared_sha256 != self.sha256
        ):
            raise ValueError("MediaRef declared_sha256 must match MediaAsset sha256")
        if (
            self.media_ref.declared_content_type is not None
            and self.media_ref.declared_content_type != self.content_type
        ):
            raise ValueError("MediaRef declared_content_type must match MediaAsset content_type")
        if self.object_ref.content_hash != self.sha256:
            raise ValueError("ObjectRef content_hash must match MediaAsset sha256")
        if self.object_ref.size_bytes != self.size_bytes:
            raise ValueError("ObjectRef size_bytes must match MediaAsset size_bytes")
        if self.object_ref.content_type != self.content_type:
            raise ValueError("ObjectRef content_type must match MediaAsset content_type")
        if self.visibility != self.source_locator.visibility:
            raise ValueError("raw MediaAsset visibility must match its source provenance")
        if self.license != self.source_locator.license:
            raise ValueError("raw MediaAsset license must match its source provenance")
        if self.retention != self.source_locator.retention:
            raise ValueError("raw MediaAsset retention must match its source provenance")
        return self


class MediaFetchRequest(VersionedContract):
    """Streaming fetch policy for one immutable source MediaRef."""

    request_id: NonEmptyStr
    asset_id: RegisteredSlug
    media_ref: MediaRef
    source_locator: SourceLocator
    max_bytes: int = Field(gt=0)
    allowed_content_types: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fetch_scope(self) -> Self:
        if self.media_ref.locator_id != self.source_locator.locator_id:
            raise ValueError("MediaFetchRequest media_ref must belong to source_locator")
        if len(self.allowed_content_types) != len(set(self.allowed_content_types)):
            raise ValueError("allowed_content_types must not contain duplicates")
        return self


class MediaWorkflowInput(VersionedContract):
    """Deterministic Media Workflow envelope; bytes stay outside history."""

    request: MediaFetchRequest
    execution_policy: TemporalExecutionPolicy = Field(default_factory=TemporalExecutionPolicy)


class MediaWorkflowResult(VersionedContract):
    """Candidate media result; publication remains an owner-side Activity concern."""

    request_id: NonEmptyStr
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    status: Literal["completed", "cancelled"]
    asset_id: RegisteredSlug | None = None
    deduplicated: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "cancelled" and self.asset_id is not None:
            raise ValueError("cancelled media cannot report an asset")
        if self.status == "completed" and self.asset_id is None:
            raise ValueError("completed media must identify an asset")
        return self


class MediaFetchResult(VersionedContract):
    """Committed metadata receipt; bytes remain behind ObjectStore."""

    asset: MediaAsset
    deduplicated: bool = False


class ProcessingLimits(AuthorityModel):
    """Explicit per-call ceilings; policy values are supplied by the owning coordinator."""

    timeout_ms: int = Field(gt=0)
    max_input_bytes: int = Field(gt=0)
    max_output_bytes: int = Field(gt=0)
    max_outputs: int = Field(gt=0)
    max_memory_bytes: int = Field(gt=0)


class MediaProcessingRequest(VersionedContract):
    """A processor invocation pinned to one registered implementation version."""

    request_id: NonEmptyStr
    processor_id: RegisteredSlug
    processor_version: ContractVersion
    asset: MediaAsset
    limits: ProcessingLimits
    workload_port: Literal[WorkloadPort.MEDIA] = WorkloadPort.MEDIA


class EvidenceExtractionRequest(VersionedContract):
    """Text/artifact extraction input with explicit lineage, hashes, and schema pinning."""

    request_id: NonEmptyStr
    extractor_id: RegisteredSlug
    extractor_version: ContractVersion
    evidence_schema_version: ContractVersion
    source_locator: SourceLocator
    source_text: str | None = None
    source_text_sha256: Sha256Digest | None = None
    artifacts: tuple[DerivedArtifact, ...] = ()
    limits: ProcessingLimits

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        has_text = self.source_text is not None
        if has_text != (self.source_text_sha256 is not None):
            raise ValueError("source_text and source_text_sha256 must be provided together")
        if not has_text and not self.artifacts:
            raise ValueError("Evidence extraction requires text or a DerivedArtifact")
        if self.source_text is not None:
            digest = hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
            if digest != self.source_text_sha256:
                raise ValueError("source_text_sha256 must match UTF-8 source_text")
        artifact_ids = tuple(item.artifact_id for item in self.artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifacts must not contain duplicate identities")
        return self


@runtime_checkable
class MediaProcessor(Protocol):
    """Registered media extension; storage and durable execution remain external ports."""

    @property
    def processor_id(self) -> str: ...

    @property
    def processor_version(self) -> str: ...

    def supports(self, media_type: MediaType, content_type: str) -> bool: ...

    async def process(self, request: MediaProcessingRequest) -> tuple[DerivedArtifact, ...]: ...


@runtime_checkable
class EvidenceExtractor(Protocol):
    """Registered extension that emits candidate Evidence for domain validation."""

    @property
    def extractor_id(self) -> str: ...

    @property
    def extractor_version(self) -> str: ...

    def supports(self, request: EvidenceExtractionRequest) -> bool: ...

    async def extract(self, request: EvidenceExtractionRequest) -> tuple[EvidenceItem, ...]: ...


__all__ = [
    "EvidenceExtractionRequest",
    "EvidenceExtractor",
    "MediaAsset",
    "MediaFetchRequest",
    "MediaFetchResult",
    "MediaWorkflowInput",
    "MediaWorkflowResult",
    "MediaProcessingRequest",
    "MediaProcessor",
    "ProcessingLimits",
    "RefreshPriorityDecision",
    "RefreshPriorityPolicy",
    "RefreshPrioritySignals",
    "RefreshDeltaScope",
    "RefreshJob",
    "RefreshWorkflowInput",
    "RefreshWorkflowResult",
    "RefreshPriorityReason",
    "Sha256Digest",
    "WorkloadPort",
]
