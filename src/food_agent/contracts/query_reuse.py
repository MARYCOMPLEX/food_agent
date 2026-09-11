"""Contracts for versioned Query Family reuse and freshness decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol, Self

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
    NO_FAMILY = "no_family"
    WITHIN_WINDOW = "within_window"
    STALE_TIME = "stale_time"
    COVERAGE_DEFICIT = "coverage_deficit"
    WATERMARK_ADVANCED = "watermark_advanced"
    ACTIVE_REFRESH = "active_refresh"
    MAXIMUM_STALENESS = "maximum_staleness"
    # Alias retained for callers that name the boundary as a limit.
    STALE_LIMIT_EXCEEDED = "maximum_staleness"
    REFRESH_FAILED = "refresh_failed"


class QueryFamilyMatch(ContractModel):
    """Explainable result from exactly one approved matching layer."""

    schema_version: Literal["query-reuse/v1"] = QUERY_REUSE_VERSION
    family_id: RegisteredSlug
    canonical_key: NonEmptyStr
    layer: QueryMatchLayer
    confidence: float = Field(ge=0.0, le=1.0)
    matched_alias: str | None = None
    rule_version: ContractVersion
    normalization_version: ContractVersion = "canonical-normalizer/v1"
    profile_id: RegisteredSlug | None = None
    profile_version: ContractVersion | None = None
    audit_basis: tuple[NonEmptyStr, ...] = ()
    rationale: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_layer_metadata(self) -> QueryFamilyMatch:
        if self.layer is QueryMatchLayer.VECTOR:
            if self.profile_id is None or self.profile_version is None:
                raise ValueError("vector matches require a profile identity")
        elif self.profile_id is not None or self.profile_version is not None:
            raise ValueError("only vector matches may carry embedding profile metadata")
        if self.layer is QueryMatchLayer.DETERMINISTIC and self.confidence != 1.0:
            raise ValueError("deterministic matches must have confidence 1.0")
        if self.layer is QueryMatchLayer.TRIGRAM and not self.matched_alias:
            raise ValueError("trigram matches require the matched alias")
        return self


class QueryReuseRequest(VersionedContract):
    """Public query inputs for the three-tier matcher; no user identity."""

    schema_version: Literal["query-reuse/v1"] = QUERY_REUSE_VERSION
    canonical_key: NonEmptyStr
    alias_text: NonEmptyStr
    vector: tuple[float, ...] | None = None
    embedding_profile: EmbeddingProfile = BGE_M3_PROFILE_V1
    normalization_version: ContractVersion = "canonical-normalizer/v1"
    classifier_version: ContractVersion = "food-constraints/v1"

    @model_validator(mode="after")
    def validate_public_inputs(self) -> Self:
        # The request is a shared cache key.  Private fields are rejected
        # rather than silently becoming part of a supposedly public Family.
        for field_name, value in (
            ("canonical_key", self.canonical_key),
            ("alias_text", self.alias_text),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
            if _contains_private_marker(value):
                raise ValueError(f"{field_name} contains a private identity marker")
        if self.vector is not None and not self.vector:
            raise ValueError("vector must not be empty")
        return self


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
    # ``max_staleness_seconds`` is the freshness window retained by the
    # original contract.  Domain Packs may additionally provide a bounded
    # stale fallback window without changing that wire field.
    fresh_for_seconds: int | None = Field(default=None, gt=0)
    max_stale_for_seconds: int | None = Field(default=None, gt=0)
    maximum_staleness_seconds: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> FreshnessPolicy:
        if any(not 0.0 <= value <= 1.0 for value in self.minimum_coverage.values()):
            raise ValueError("minimum coverage must be between 0 and 1")
        if (
            self.max_stale_for_seconds is not None
            and self.fresh_for_seconds is not None
            and self.max_stale_for_seconds < self.fresh_for_seconds
        ):
            raise ValueError("maximum stale window must not precede the fresh window")
        if (
            self.maximum_staleness_seconds is not None
            and self.fresh_for_seconds is not None
            and self.maximum_staleness_seconds < self.fresh_for_seconds
        ):
            raise ValueError("maximum stale window must not precede the fresh window")
        if (
            self.max_stale_for_seconds is not None
            and self.maximum_staleness_seconds is not None
            and self.max_stale_for_seconds != self.maximum_staleness_seconds
        ):
            raise ValueError("maximum stale windows must agree")
        return self

    @property
    def freshness_window_seconds(self) -> int:
        return self.fresh_for_seconds or self.max_staleness_seconds

    @property
    def stale_fallback_window_seconds(self) -> int | None:
        return self.max_stale_for_seconds or self.maximum_staleness_seconds


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
        if self.active_refresh_workflow_id is not None and not self.active_refresh_workflow_id.strip():
            raise ValueError("active refresh workflow identity must be non-empty")
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
    age_seconds: int | None = Field(default=None, ge=0)


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

    async def update_refresh_status(
        self, claim_key: str, status: Literal["active", "completed", "failed", "cancelled"]
    ) -> bool: ...


class FreshnessPolicyAdapter(Protocol):
    """Domain Pack-owned policy source; storage supplies only authority facts."""

    def policy(self) -> FreshnessPolicy: ...


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
    family_id: str | None = None,
) -> FreshnessDecision:
    """Classify a Family without comparing opaque connector watermarks."""

    if current is None:
        if family_id is None or not family_id:
            raise ValueError("freshness input or family_id is required to identify the family")
        current = FreshnessInput(family_id=family_id)
    elif family_id is not None and current.family_id != family_id:
        raise ValueError("freshness input family does not match the requested family")
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("freshness decision clock must be timezone-aware")
    if current.bundle_version is None or current.verified_at is None:
        return FreshnessDecision(
            family_id=current.family_id,
            state=FreshnessState.NEW,
            reason=FreshnessReason.NO_BUNDLE,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            active_refresh_workflow_id=current.active_refresh_workflow_id,
        )

    age_seconds = max(0, int((clock - current.verified_at).total_seconds()))
    stale_limit = policy.stale_fallback_window_seconds
    if stale_limit is not None and age_seconds > stale_limit:
        return FreshnessDecision(
            family_id=current.family_id,
            state=FreshnessState.NEW,
            reason=FreshnessReason.MAXIMUM_STALENESS,
            base_bundle_version=current.bundle_version,
            active_refresh_workflow_id=current.active_refresh_workflow_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            age_seconds=age_seconds,
        )

    if current.active_refresh_workflow_id:
        reason = FreshnessReason.ACTIVE_REFRESH
    elif age_seconds > policy.freshness_window_seconds:
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

    state = (
        FreshnessState.FRESH
        if reason is FreshnessReason.WITHIN_WINDOW
        else FreshnessState.INCREMENTAL
    )
    return FreshnessDecision(
        family_id=current.family_id,
        state=state,
        reason=reason,
        base_bundle_version=current.bundle_version,
        active_refresh_workflow_id=current.active_refresh_workflow_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        age_seconds=age_seconds,
    )


_PRIVATE_MARKERS = frozenset(
    {
        "user",
        "users",
        "userid",
        "session",
        "sessions",
        "sessionid",
        "subject",
        "subjects",
        "identity",
        "identities",
        "deviceid",
        "preference",
        "preferences",
        "favorite",
        "favorites",
        "memory",
        "cookie",
        "token",
        "credential",
        "credentials",
        "password",
        "secret",
        "account",
        "click",
        "clicks",
    }
)


def _contains_private_marker(value: str) -> bool:
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    return any(marker in normalized for marker in _PRIVATE_MARKERS)


__all__ = [
    "FRESHNESS_GATE_VERSION",
    "QUERY_REUSE_VERSION",
    "REFRESH_SINGLE_FLIGHT_VERSION",
    "FreshnessDecision",
    "FreshnessInput",
    "FreshnessPolicy",
    "FreshnessPolicyAdapter",
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
