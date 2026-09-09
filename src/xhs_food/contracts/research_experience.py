"""Versioned, browser-safe research experience contracts.

The runtime owns a separate ``ResearchEvent`` contract in
``research_runtime``.  This module is the public experience boundary.  Its
wire name is ``ResearchEvent v1``; ``ResearchEventV1`` is used in Python to
make the boundary explicit and avoid shadowing the runtime type.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import ConfigDict, Field, JsonValue, field_validator, model_validator

from .base import ContractModel, Timestamp

RESEARCH_EXPERIENCE_EVENT_SCHEMA_VERSION = "research-event/v1"
USER_RESEARCH_PROJECTION_SCHEMA_VERSION = "user-research-projection/v1"
PUBLIC_EXPERIENCE_MAX_EVENT_BYTES = 128_000
PUBLIC_EXPERIENCE_MAX_TEXT = 4_096
PUBLIC_EXPERIENCE_MAX_EXCERPT = 2_000
PUBLIC_EXPERIENCE_MAX_ITEMS = 256
PUBLIC_EXPERIENCE_MAX_IDEMPOTENCY_LEDGER = 2_048

ExperienceId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ShortText = Annotated[str, Field(min_length=1, max_length=512)]
BoundedText = Annotated[str, Field(max_length=PUBLIC_EXPERIENCE_MAX_TEXT)]
BoundedExcerpt = Annotated[str, Field(max_length=PUBLIC_EXPERIENCE_MAX_EXCERPT)]
JsonObject = dict[str, JsonValue]
NamespaceMap = dict[str, JsonValue]


class ResearchEventKind(StrEnum):
    """Core public event kinds.  Namespaced extensions are also accepted."""

    RUN_STARTED = "run_started"
    PLAN_UPDATED = "plan_updated"
    ACTION_STARTED = "action_started"
    ACTION_PROGRESS = "action_progress"
    ACTION_COMPLETED = "action_completed"
    EVIDENCE_ADDED = "evidence_added"
    CONTROVERSY_UPSERTED = "controversy_upserted"
    PROFILE_UPSERTED = "profile_upserted"
    RECOMMENDATION_UPSERTED = "recommendation_upserted"
    GAP_UPSERTED = "gap_upserted"
    RUN_PROGRESS = "run_progress"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


CORE_RESEARCH_EVENT_KINDS = frozenset(item.value for item in ResearchEventKind)
_EXTENSION_KIND = re.compile(r"^x\.[a-z][a-z0-9_-]{0,63}\.[a-z][a-z0-9_.-]{0,127}$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ResearchMutation(StrEnum):
    APPEND = "append"
    UPSERT = "upsert"
    PATCH = "patch"
    REPLACE = "replace"
    REMOVE = "remove"


class ResearchRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class EvidenceStance(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ControversyStatus(StrEnum):
    UNRESOLVED = "unresolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    RESOLVED = "resolved"


class ProfileStatus(StrEnum):
    PENDING = "pending"
    PARTIAL = "partial"
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class RecommendationStatus(StrEnum):
    CANDIDATE = "candidate"
    PARTIAL = "partial"
    RECOMMENDED = "recommended"
    FILTERED = "filtered"


class GapSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class GapStatus(StrEnum):
    OPEN = "open"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    EXHAUSTED = "exhausted"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


_FORBIDDEN_KEY_FRAGMENTS = (
    "prompt",
    "scratch",
    "chainofthought",
    "hiddenreasoning",
    "headers",
    "raw",
    "cookie",
    "credential",
    "authorization",
    "access token",
    "accesstoken",
    "apikey",
    "arguments",
    "callargs",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessioncookie",
    "toolargs",
    "toolinput",
    "requestheaders",
    "mcpargument",
    "mcparg",
    "providerresponse",
    "providerpayload",
    "setcookie",
)
_FORBIDDEN_URL_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}


def _normalise_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _assert_public_json(value: object, *, path: str = "$", depth: int = 0) -> None:
    """Reject values that are unsafe or too large for a browser event.

    This is deliberately applied to the public boundary rather than the
    internal source envelope.  The source authority can retain raw payloads;
    the user projection may only carry bounded, allow-listed facts.
    """

    if depth > 8:
        raise ValueError(f"public payload nesting exceeds the v1 limit at {path}")
    if isinstance(value, str):
        if len(value) > PUBLIC_EXPERIENCE_MAX_TEXT:
            raise ValueError(f"public text exceeds the v1 limit at {path}")
        if "//" in value and "://" in value:
            try:
                query_keys = {
                    key.casefold()
                    for key, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True)
                }
            except ValueError:
                query_keys = set()
            if query_keys & _FORBIDDEN_URL_QUERY_KEYS:
                raise ValueError(f"credential-bearing URL is not public at {path}")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, Mapping):
        if len(value) > PUBLIC_EXPERIENCE_MAX_ITEMS:
            raise ValueError(f"public object has too many fields at {path}")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"public object keys must be strings at {path}")
            normalised = _normalise_key(key)
            if any(fragment in normalised for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError(f"forbidden private field {key!r} at {path}")
            _assert_public_json(item, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > PUBLIC_EXPERIENCE_MAX_ITEMS:
            raise ValueError(f"public array has too many items at {path}")
        for index, item in enumerate(value):
            _assert_public_json(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    raise ValueError(f"unsupported public value {type(value).__name__} at {path}")


class _ExperienceModel(ContractModel):
    """Strict immutable model used only at the public experience boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    @model_validator(mode="after")
    def validate_public_boundary(self) -> Self:
        _assert_public_json(self.model_dump(mode="json", by_alias=True))
        return self


class EntityRef(_ExperienceModel):
    entity_type: ExperienceId = Field(alias="entityType")
    entity_id: ExperienceId = Field(alias="entityId")
    version: int | None = Field(default=None, ge=1)


class ProvenanceRef(_ExperienceModel):
    source: ExperienceId
    source_ref: ExperienceId | None = Field(default=None, alias="sourceRef")
    source_url: BoundedText | None = Field(default=None, alias="sourceUrl")
    note_ref: ExperienceId | None = Field(default=None, alias="noteRef")
    comment_ref: ExperienceId | None = Field(default=None, alias="commentRef")
    captured_at: Timestamp | None = Field(default=None, alias="capturedAt")


class EvidenceItemV1(_ExperienceModel):
    evidence_id: ExperienceId = Field(alias="evidenceId")
    source: ExperienceId
    excerpt: BoundedExcerpt = ""
    title: BoundedText | None = None
    stance: EvidenceStance = EvidenceStance.NEUTRAL
    entity_refs: tuple[EntityRef, ...] = Field(default=(), alias="entityRefs")
    claim_refs: tuple[ExperienceId, ...] = Field(default=(), alias="claimRefs")
    provenance: tuple[ProvenanceRef, ...] = ()
    note_ref: ExperienceId | None = Field(default=None, alias="noteRef")
    comment_ref: ExperienceId | None = Field(default=None, alias="commentRef")
    captured_at: Timestamp | None = Field(default=None, alias="capturedAt")
    confidence: float | None = Field(default=None, ge=0, le=1)
    extensions: NamespaceMap = Field(default_factory=dict)


class ControversySideV1(_ExperienceModel):
    side_id: ExperienceId = Field(alias="sideId")
    label: ShortText
    summary: BoundedText = ""
    evidence_refs: tuple[ExperienceId, ...] = Field(default=(), alias="evidenceRefs")
    claim_refs: tuple[ExperienceId, ...] = Field(default=(), alias="claimRefs")


class ControversyViewV1(_ExperienceModel):
    controversy_id: ExperienceId = Field(alias="controversyId")
    entity_ref: EntityRef | None = Field(default=None, alias="entityRef")
    topic: ShortText
    summary: BoundedText = ""
    status: ControversyStatus = ControversyStatus.UNRESOLVED
    sides: tuple[ControversySideV1, ...] = ()
    evidence_refs: tuple[ExperienceId, ...] = Field(default=(), alias="evidenceRefs")
    resolution: BoundedText | None = None
    remaining_question: BoundedText | None = Field(default=None, alias="remainingQuestion")
    confidence: float | None = Field(default=None, ge=0, le=1)
    updated_at: Timestamp | None = Field(default=None, alias="updatedAt")
    extensions: NamespaceMap = Field(default_factory=dict)


class ProfileViewV1(_ExperienceModel):
    profile_id: ExperienceId = Field(alias="profileId")
    entity_ref: EntityRef | None = Field(default=None, alias="entityRef")
    provider_refs: dict[str, ExperienceId] = Field(default_factory=dict, alias="providerRefs")
    name: BoundedText | None = None
    alias: BoundedText | None = None
    url: BoundedText | None = None
    source_url: BoundedText | None = Field(default=None, alias="sourceUrl")
    image_url: BoundedText | None = Field(default=None, alias="imageUrl")
    status: ProfileStatus = ProfileStatus.PENDING
    address: BoundedText | None = None
    city: BoundedText | None = None
    district: BoundedText | None = None
    region: BoundedText | None = None
    business_area: BoundedText | None = Field(default=None, alias="businessArea")
    location: BoundedText | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    coordinate_system: BoundedText | None = Field(default=None, alias="coordinateSystem")
    geo: JsonObject = Field(default_factory=dict)
    phone: BoundedText | None = None
    rating: float | None = Field(default=None, ge=0, le=10)
    review_count: int | None = Field(default=None, ge=0, alias="reviewCount")
    average_price: float | None = Field(default=None, ge=0, alias="averagePrice")
    price_band: BoundedText | None = Field(default=None, alias="priceBand")
    category: BoundedText | None = None
    opening_hours: BoundedText | None = Field(default=None, alias="openingHours")
    images: tuple[JsonValue, ...] = ()
    recommended_dishes: tuple[JsonValue, ...] = Field(default=(), alias="recommendedDishes")
    promotions: tuple[JsonValue, ...] = ()
    tags: tuple[BoundedText, ...] = ()
    source_refs: tuple[ExperienceId, ...] = Field(default=(), alias="sourceRefs")
    gap_refs: tuple[ExperienceId, ...] = Field(default=(), alias="gapRefs")
    attributes: JsonObject = Field(default_factory=dict)
    review_completeness: JsonObject = Field(default_factory=dict, alias="reviewCompleteness")
    profile_outcome: BoundedText | None = Field(default=None, alias="profileOutcome")
    domain_data: NamespaceMap = Field(default_factory=dict, alias="domainData")
    extensions: NamespaceMap = Field(default_factory=dict)
    updated_at: Timestamp | None = Field(default=None, alias="updatedAt")


class RecommendationViewV1(_ExperienceModel):
    recommendation_id: ExperienceId = Field(alias="recommendationId")
    entity_ref: EntityRef | None = Field(default=None, alias="entityRef")
    title: BoundedText
    summary: BoundedText = ""
    status: RecommendationStatus = RecommendationStatus.CANDIDATE
    rank: int | None = Field(default=None, ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_refs: tuple[ExperienceId, ...] = Field(default=(), alias="evidenceRefs")
    controversy_refs: tuple[ExperienceId, ...] = Field(default=(), alias="controversyRefs")
    profile_ref: ExperienceId | None = Field(default=None, alias="profileRef")
    highlights: tuple[BoundedText, ...] = ()
    warnings: tuple[BoundedText, ...] = ()
    domain_data: NamespaceMap = Field(default_factory=dict, alias="domainData")
    extensions: NamespaceMap = Field(default_factory=dict)
    updated_at: Timestamp | None = Field(default=None, alias="updatedAt")


class GapViewV1(_ExperienceModel):
    gap_id: ExperienceId = Field(alias="gapId")
    source: ExperienceId
    operation: BoundedText
    code: ExperienceId
    message: BoundedText
    retryable: bool = False
    severity: GapSeverity = GapSeverity.WARNING
    status: GapStatus = GapStatus.OPEN
    affected_refs: tuple[EntityRef, ...] = Field(default=(), alias="affectedRefs")
    continuation_ref: ExperienceId | None = Field(default=None, alias="continuationRef")
    occurred_at: Timestamp | None = Field(default=None, alias="occurredAt")
    extensions: NamespaceMap = Field(default_factory=dict)


class PlanStepViewV1(_ExperienceModel):
    step_id: ExperienceId = Field(alias="stepId")
    label: ShortText
    phase: BoundedText = ""
    status: StepStatus = StepStatus.PENDING
    action_name: BoundedText | None = Field(default=None, alias="actionName")
    detail: BoundedText = ""
    counts: dict[str, int] = Field(default_factory=dict)
    started_at: Timestamp | None = Field(default=None, alias="startedAt")
    completed_at: Timestamp | None = Field(default=None, alias="completedAt")

    @field_validator("counts")
    @classmethod
    def validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if any(item < 0 for item in value.values()):
            raise ValueError("plan counts must be non-negative")
        return value


class IntentViewV1(_ExperienceModel):
    objective: BoundedText = ""
    location: BoundedText | None = None
    constraints: tuple[BoundedText, ...] = ()
    exclusions: tuple[BoundedText, ...] = ()
    extensions: NamespaceMap = Field(default_factory=dict)


class CoverageDimensionV1(_ExperienceModel):
    dimension: ExperienceId
    observed: int | None = Field(default=None, ge=0)
    expected: int | None = Field(default=None, ge=0)
    ratio: float | None = Field(default=None, ge=0, le=1)
    status: Literal["unknown", "partial", "sufficient"] = "unknown"


class CoverageViewV1(_ExperienceModel):
    dimensions: tuple[CoverageDimensionV1, ...] = ()
    unresolved_controversies: int = Field(default=0, ge=0, alias="unresolvedControversies")
    candidate_entity_count: int = Field(default=0, ge=0, alias="candidateEntityCount")
    missing: tuple[BoundedText, ...] = ()


class ResearchMetricsV1(_ExperienceModel):
    rounds: int = Field(default=0, ge=0)
    actions: int = Field(default=0, ge=0)
    evidence_items: int = Field(default=0, ge=0, alias="evidenceItems")
    comment_evidence_items: int = Field(default=0, ge=0, alias="commentEvidenceItems")
    profiles: int = Field(default=0, ge=0)
    controversies: int = Field(default=0, ge=0)
    gaps: int = Field(default=0, ge=0)


class TerminationViewV1(_ExperienceModel):
    status: ResearchRunStatus
    reason: ExperienceId
    message: BoundedText = ""
    resumable: bool = False
    continuation_ref: ExperienceId | None = Field(default=None, alias="continuationRef")
    completed_at: Timestamp | None = Field(default=None, alias="completedAt")


class ResearchEventV1(_ExperienceModel):
    """The public ``ResearchEvent v1`` wire envelope."""

    schema_version: Literal["research-event/v1"] = Field(
        default=RESEARCH_EXPERIENCE_EVENT_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    event_id: ExperienceId = Field(alias="eventId")
    session_id: ExperienceId = Field(alias="sessionId")
    task_id: ExperienceId = Field(alias="taskId")
    turn_id: int = Field(alias="turnId", ge=1)
    run_id: ExperienceId | None = Field(default=None, alias="runId")
    sequence: int = Field(ge=1)
    occurred_at: Timestamp = Field(alias="occurredAt")
    kind: str
    phase: BoundedText | None = None
    status: ResearchRunStatus | None = None
    mutation: ResearchMutation = ResearchMutation.APPEND
    entity: EntityRef | None = None
    payload: JsonValue = Field(default_factory=dict)
    extensions: NamespaceMap = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in CORE_RESEARCH_EVENT_KINDS and not _EXTENSION_KIND.fullmatch(value):
            raise ValueError(
                "event kind must be a v1 core kind or a namespaced x.<namespace>.<name> kind"
            )
        return value

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, value: NamespaceMap) -> NamespaceMap:
        invalid = [key for key in value if not _NAMESPACE.fullmatch(key) and not key.startswith("x.")]
        if invalid:
            raise ValueError(f"extension namespaces must be namespaced: {invalid!r}")
        return value

    @model_validator(mode="after")
    def validate_wire_size(self) -> Self:
        # The limit is measured on the canonical JSON representation so that
        # HTTP, SSE, and WebSocket adapters share the same guard.
        if len(self.model_dump_json(by_alias=True).encode("utf-8")) > PUBLIC_EXPERIENCE_MAX_EVENT_BYTES:
            raise ValueError("ResearchEvent v1 exceeds the maximum wire size")
        return self

    @model_validator(mode="after")
    def validate_terminal_status(self) -> Self:
        expected = {
            "run_completed": {ResearchRunStatus.SUCCEEDED, ResearchRunStatus.PARTIAL},
            "run_failed": {ResearchRunStatus.FAILED},
            "run_cancelled": {ResearchRunStatus.CANCELLED},
        }.get(self.kind)
        if expected is not None and self.status is not None and self.status not in expected:
            allowed = ", ".join(sorted(item.value for item in expected))
            raise ValueError(f"{self.kind} status must be one of: {allowed}")
        return self

    def to_wire(self) -> JsonObject:
        return self.model_dump(mode="json", by_alias=True)


class UserResearchProjectionV1(_ExperienceModel):
    """Complete public snapshot obtained by reducing ResearchEvent v1 deltas."""

    schema_version: Literal["user-research-projection/v1"] = Field(
        default=USER_RESEARCH_PROJECTION_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    session_id: ExperienceId = Field(alias="sessionId")
    task_id: ExperienceId = Field(alias="taskId")
    turn_id: int = Field(alias="turnId", ge=1)
    run_id: ExperienceId | None = Field(default=None, alias="runId")
    revision: int = Field(default=0, ge=0)
    last_sequence: int = Field(default=0, ge=0, alias="lastSequence")
    status: ResearchRunStatus = ResearchRunStatus.QUEUED
    phase: BoundedText = ""
    summary: BoundedText = ""
    intent: IntentViewV1 | None = None
    plan: tuple[PlanStepViewV1, ...] = ()
    evidence: tuple[EvidenceItemV1, ...] = ()
    controversies: tuple[ControversyViewV1, ...] = ()
    profiles: tuple[ProfileViewV1, ...] = ()
    recommendations: tuple[RecommendationViewV1, ...] = ()
    gaps: tuple[GapViewV1, ...] = ()
    coverage: CoverageViewV1 | None = None
    metrics: ResearchMetricsV1 = Field(default_factory=ResearchMetricsV1)
    termination: TerminationViewV1 | None = None
    updated_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC), alias="updatedAt")
    extensions: NamespaceMap = Field(default_factory=dict)
    applied_event_ids: tuple[ExperienceId, ...] = Field(default=(), alias="appliedEventIds")

    @field_validator("applied_event_ids")
    @classmethod
    def validate_ledger_size(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > PUBLIC_EXPERIENCE_MAX_IDEMPOTENCY_LEDGER:
            raise ValueError("projection idempotency ledger exceeds the v1 limit")
        if len(value) != len(set(value)):
            raise ValueError("projection idempotency ledger must be unique")
        return value

    @model_validator(mode="after")
    def validate_entity_identity(self) -> Self:
        for values, name, key in (
            (self.plan, "plan", lambda item: item.step_id),
            (self.evidence, "evidence", lambda item: item.evidence_id),
            (self.controversies, "controversies", lambda item: item.controversy_id),
            (self.profiles, "profiles", lambda item: item.profile_id),
            (self.recommendations, "recommendations", lambda item: item.recommendation_id),
            (self.gaps, "gaps", lambda item: item.gap_id),
        ):
            identifiers = [key(item) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} identities must be unique")
        return self

    def to_wire(self) -> JsonObject:
        return self.model_dump(mode="json", by_alias=True)


__all__ = [
    "CORE_RESEARCH_EVENT_KINDS",
    "ControversySideV1",
    "ControversyStatus",
    "ControversyViewV1",
    "CoverageDimensionV1",
    "CoverageViewV1",
    "EntityRef",
    "EvidenceItemV1",
    "EvidenceStance",
    "GapSeverity",
    "GapStatus",
    "GapViewV1",
    "IntentViewV1",
    "PlanStepViewV1",
    "ProfileStatus",
    "ProfileViewV1",
    "ProvenanceRef",
    "PUBLIC_EXPERIENCE_MAX_EVENT_BYTES",
    "PUBLIC_EXPERIENCE_MAX_IDEMPOTENCY_LEDGER",
    "RecommendationStatus",
    "RecommendationViewV1",
    "ResearchEventKind",
    "ResearchEventV1",
    "ResearchMetricsV1",
    "ResearchMutation",
    "ResearchRunStatus",
    "StepStatus",
    "TerminationViewV1",
    "USER_RESEARCH_PROJECTION_SCHEMA_VERSION",
    "UserResearchProjectionV1",
    "RESEARCH_EXPERIENCE_EVENT_SCHEMA_VERSION",
]
