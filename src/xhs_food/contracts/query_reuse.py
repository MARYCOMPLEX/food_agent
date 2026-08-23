"""Contracts for versioned Query Family reuse and freshness decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyStr, Timestamp, VersionedContract
from .embedding import BGE_M3_PROFILE_V1, EmbeddingProfile
from .evidence import ContractVersion, RegisteredSlug
from .ports import WorkflowRun
from .tasks import ResearchRequest, ResearchTask, TaskEvent

QUERY_REUSE_VERSION = "query-reuse/v1"
FRESHNESS_GATE_VERSION = "freshness-gate/v1"
REFRESH_SINGLE_FLIGHT_VERSION = "refresh-single-flight/v1"


class QueryMatchLayer(StrEnum):
    DETERMINISTIC = "deterministic"
    TRIGRAM = "trigram"
    VECTOR = "vector"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    INCREMENTAL = "incremental"
    NEW = "new"


class FreshnessReason(StrEnum):
    NO_BUNDLE = "no_bundle"
    WITHIN_WINDOW = "within_window"
    STALE_TIME = "stale_time"
    COVERAGE_DEFICIT = "coverage_deficit"
    WATERMARK_ADVANCED = "watermark_advanced"
    ACTIVE_REFRESH = "active_refresh"


class QueryFamilyMatch(ContractModel):
    """Explainable result from exactly one approved matching layer."""

    schema_version: Literal["query-reuse/v1"] = QUERY_REUSE_VERSION
    family_id: RegisteredSlug
    canonical_key: NonEmptyStr
    layer: QueryMatchLayer
    confidence: float = Field(ge=0.0, le=1.0)
    matched_alias: str | None = None
    rule_version: ContractVersion
    profile_id: RegisteredSlug | None = None
    profile_version: ContractVersion | None = None
    audit_basis: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_layer_metadata(self) -> QueryFamilyMatch:
        if self.layer is QueryMatchLayer.VECTOR:
            if self.profile_id is None or self.profile_version is None:
                raise ValueError("vector matches require a profile identity")
        elif self.profile_id is not None or self.profile_version is not None:
            raise ValueError("only vector matches may carry embedding profile metadata")
        if self.layer is QueryMatchLayer.DETERMINISTIC and self.confidence != 1.0:
            raise ValueError("deterministic matches must have confidence 1.0")
        return self


class QueryReuseRequest(VersionedContract):
    """Public query inputs for the three-tier matcher; no user identity."""

    canonical_key: NonEmptyStr
    alias_text: NonEmptyStr
    vector: tuple[float, ...] | None = None
    embedding_profile: EmbeddingProfile = BGE_M3_PROFILE_V1


class QueryReuseDecision(ContractModel):
    schema_version: Literal["query-reuse/v1"] = QUERY_REUSE_VERSION
    request: QueryReuseRequest
    match: QueryFamilyMatch | None = None
    attempted_layers: tuple[QueryMatchLayer, ...]


class FreshnessPolicy(ContractModel):
    """Thresholds are supplied by the Domain Pack, never invented by storage."""

    policy_id: RegisteredSlug
    policy_version: ContractVersion
    max_staleness_seconds: int = Field(gt=0)
    minimum_coverage: dict[RegisteredSlug, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_coverage(self) -> FreshnessPolicy:
        if any(not 0.0 <= value <= 1.0 for value in self.minimum_coverage.values()):
            raise ValueError("minimum coverage must be between 0 and 1")
        return self


class FreshnessInput(ContractModel):
    """Authority facts consumed by Freshness Gate."""

    family_id: RegisteredSlug
    bundle_version: int | None = Field(default=None, ge=1)
    verified_at: Timestamp | None = None
    coverage: dict[RegisteredSlug, float] = Field(default_factory=dict)
    watermarks: dict[RegisteredSlug, str] = Field(default_factory=dict)
    watermark_advanced: bool = False
    active_refresh_workflow_id: str | None = None

    @model_validator(mode="after")
    def validate_bundle_fields(self) -> FreshnessInput:
        if self.bundle_version is None and self.verified_at is not None:
            raise ValueError("verified_at requires a bundle_version")
        if any(not 0.0 <= value <= 1.0 for value in self.coverage.values()):
            raise ValueError("coverage must be between 0 and 1")
        return self


class FreshnessDecision(ContractModel):
    schema_version: Literal["freshness-gate/v1"] = FRESHNESS_GATE_VERSION
    family_id: RegisteredSlug
    state: FreshnessState
    reason: FreshnessReason
    base_bundle_version: int | None = Field(default=None, ge=1)
    active_refresh_workflow_id: str | None = None
    policy_id: RegisteredSlug
    policy_version: ContractVersion


class RefreshSingleFlightKey(ContractModel):
    """Stable public refresh scope used as a Temporal Workflow ID preimage."""

    schema_version: Literal["refresh-single-flight/v1"] = REFRESH_SINGLE_FLIGHT_VERSION
    family_id: RegisteredSlug
    scope: tuple[RegisteredSlug, ...] = Field(min_length=1)
    policy_version: ContractVersion

    @model_validator(mode="after")
    def validate_scope(self) -> RefreshSingleFlightKey:
        if len(self.scope) != len(set(self.scope)):
            raise ValueError("refresh scope must not contain duplicates")
        if self.scope != tuple(sorted(self.scope)):
            raise ValueError("refresh scope must use stable canonical order")
        return self


class RefreshClaim(ContractModel):
    claim_key: NonEmptyStr
    workflow_id: NonEmptyStr
    acquired: bool
    status: Literal["active", "completed", "failed", "cancelled"] = "active"


class RefreshTaskBuilder(Protocol):
    async def build(
        self,
        request: ResearchRequest,
        task_id: str,
        workflow_id: str,
        run: WorkflowRun | None,
        *,
        reused: bool,
    ) -> ResearchTask: ...


class RefreshEventPublisher(Protocol):
    async def publish(self, event: TaskEvent) -> None: ...


class QueryFamilyRepository(Protocol):
    async def get_exact(self, canonical_key: str) -> QueryFamilyMatch | None: ...

    async def search_trigram(
        self, alias_text: str, *, limit: int = 5
    ) -> tuple[QueryFamilyMatch, ...]: ...

    async def search_vector(
        self,
        vector: tuple[float, ...],
        profile: EmbeddingProfile,
        *,
        limit: int = 5,
    ) -> tuple[QueryFamilyMatch, ...]: ...

    async def get_freshness(self, family_id: str) -> FreshnessInput | None: ...

    async def save_freshness(self, state: FreshnessInput) -> None: ...

    async def claim_refresh(self, key: RefreshSingleFlightKey) -> RefreshClaim: ...

    async def activate_bundle_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
    ) -> bool: ...


def stable_refresh_workflow_id(key: RefreshSingleFlightKey) -> str:
    """Derive a Temporal-safe ID without user/session or cache state."""

    preimage = {
        "schema_version": key.schema_version,
        "family_id": key.family_id,
        "scope": key.scope,
        "policy_version": key.policy_version,
    }
    encoded = json.dumps(preimage, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"refresh.family.{digest}"


def stable_refresh_claim_key(key: RefreshSingleFlightKey) -> str:
    """The database idempotency key is the same deterministic scope hash."""

    return stable_refresh_workflow_id(key).removeprefix("refresh.")


def stable_refresh_task_id(workflow_id: str) -> str:
    if not workflow_id:
        raise ValueError("workflow_id must be non-empty")
    return f"task-refresh-{hashlib.sha256(workflow_id.encode('utf-8')).hexdigest()[:32]}"


def decide_freshness(
    current: FreshnessInput | None,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
) -> FreshnessDecision:
    """Classify a Family without comparing opaque connector watermarks."""

    if current is None:
        raise ValueError("freshness input is required to identify the family")
    clock = now or datetime.now(UTC)
    if current.bundle_version is None or current.verified_at is None:
        return FreshnessDecision(
            family_id=current.family_id,
            state=FreshnessState.NEW,
            reason=FreshnessReason.NO_BUNDLE,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            active_refresh_workflow_id=current.active_refresh_workflow_id,
        )

    if current.active_refresh_workflow_id:
        reason = FreshnessReason.ACTIVE_REFRESH
    elif (clock - current.verified_at).total_seconds() > policy.max_staleness_seconds:
        reason = FreshnessReason.STALE_TIME
    elif any(
        current.coverage.get(dimension, 0.0) < minimum
        for dimension, minimum in policy.minimum_coverage.items()
    ):
        reason = FreshnessReason.COVERAGE_DEFICIT
    elif current.watermark_advanced:
        reason = FreshnessReason.WATERMARK_ADVANCED
    else:
        reason = FreshnessReason.WITHIN_WINDOW

    state = FreshnessState.FRESH if reason is FreshnessReason.WITHIN_WINDOW else FreshnessState.INCREMENTAL
    return FreshnessDecision(
        family_id=current.family_id,
        state=state,
        reason=reason,
        base_bundle_version=current.bundle_version,
        active_refresh_workflow_id=current.active_refresh_workflow_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
    )


__all__ = [
    "FRESHNESS_GATE_VERSION",
    "QUERY_REUSE_VERSION",
    "REFRESH_SINGLE_FLIGHT_VERSION",
    "FreshnessDecision",
    "FreshnessInput",
    "FreshnessPolicy",
    "FreshnessReason",
    "FreshnessState",
    "QueryFamilyMatch",
    "QueryFamilyRepository",
    "QueryMatchLayer",
    "QueryReuseDecision",
    "QueryReuseRequest",
    "RefreshClaim",
    "RefreshEventPublisher",
    "RefreshSingleFlightKey",
    "RefreshTaskBuilder",
    "decide_freshness",
    "stable_refresh_claim_key",
    "stable_refresh_task_id",
    "stable_refresh_workflow_id",
]
