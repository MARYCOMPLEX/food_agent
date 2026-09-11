"""Contracts for the bounded, single-Agent research runtime.

The models in this module are deliberately provider neutral.  A planner can
describe *what* work is needed, while the runtime and its injected ports decide
how that work is fulfilled.  Raw provider values are retained alongside the
small normalized projections used by reducers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from .base import (
    ContractModel,
    ContractPayload,
    JsonValue,
    NonEmptyStr,
    Timestamp,
    VersionedContract,
)
from .research import ResearchGap, ResearchOutcome, ShopProfile, XhsNoteLead

RESEARCH_RUNTIME_SCHEMA_VERSION = "research-runtime/v1"
RESEARCH_EVENT_SCHEMA_VERSION = "research-event/v1"
RESEARCH_ACTION_SCHEMA_VERSION = "research-action/v1"
SOURCE_ENVELOPE_SCHEMA_VERSION = "source-envelope/v1"
COMMENT_INSIGHT_SCHEMA_VERSION = "comment-insight/v1"
RESEARCH_ACTION_RESULT_SCHEMA_VERSION = "research-action-result/v1"


class ResourceClass(StrEnum):
    """Independent budgets used by the in-process executor."""

    XHS_SEARCH = "xhs.search"
    XHS_DETAIL = "xhs.detail"
    XHS_COMMENTS = "xhs.comments"
    LLM = "llm"
    DIANPING_SEARCH = "dianping.search"
    DIANPING_DETAIL = "dianping.detail"
    DIANPING_REVIEWS = "dianping.reviews"
    PERSISTENCE = "persistence"


class SemanticActionKind(StrEnum):
    SEARCH_NOTES = "SearchNotes"
    FETCH_NOTE_EVIDENCE = "FetchNoteEvidence"
    ANALYZE_COMMENT_BATCH = "AnalyzeCommentBatch"
    EXPAND_RESEARCH = "ExpandResearch"
    ENRICH_SHOP_PROFILE = "EnrichShopProfile"
    SYNTHESIZE = "Synthesize"
    STOP_RESEARCH = "StopResearch"


# These names are useful to callers that prefer the shorter terminology used
# in the design document.
ResearchActionKind = SemanticActionKind
ActionKind = SemanticActionKind


class ResearchEventType(StrEnum):
    ACTION_STARTED = "action_started"
    ACTION_PROGRESS = "action_progress"
    ACTION_GAP = "action_gap"
    ACTION_COMPLETED = "action_completed"
    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"

    # Readable aliases for callers that model the lifecycle as start/progress
    # rather than action_started/action_progress.
    START = "action_started"
    PROGRESS = "action_progress"
    GAP = "action_gap"
    COMPLETE = "action_completed"


EventType = ResearchEventType


class CommentIdentity(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    NONE = "none"


class CommentSentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


def _unique_nonempty(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if any(not value for value in values):
        raise ValueError(f"{field_name} must contain non-empty values")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class SourceEnvelope(VersionedContract):
    """Lossless source response envelope and normalized item projection."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    schema_version: Literal["source-envelope/v1"] = SOURCE_ENVELOPE_SCHEMA_VERSION
    source: NonEmptyStr = Field(validation_alias=AliasChoices("source", "source_id"))
    operation: NonEmptyStr = Field(validation_alias=AliasChoices("operation", "op"))
    provider: str | None = None
    provider_response: JsonValue = None
    normalized_items: tuple[JsonValue, ...] = Field(
        default=(),
        validation_alias=AliasChoices("normalized_items", "items", "records"),
    )
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    warnings: tuple[NonEmptyStr, ...] = ()
    raw_payload: Any = Field(
        default=None,
        validation_alias=AliasChoices("raw_payload", "raw"),
    )
    extra: ContractPayload = Field(default_factory=dict)
    provenance: ContractPayload = Field(default_factory=dict)

    @property
    def items(self) -> tuple[JsonValue, ...]:
        """Compatibility alias for consumers that call the projection items."""

        return self.normalized_items

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "warnings")

    @model_validator(mode="after")
    def validate_pagination(self) -> Self:
        if self.has_more and not self.next_cursor:
            raise ValueError("a source envelope with has_more requires next_cursor")
        if self.completeness == "complete" and self.has_more:
            raise ValueError("a complete source envelope cannot have more pages")
        # ``extra=allow`` keeps additive provider fields readable through
        # Pydantic's ``model_extra``.  Mirror them into the explicit extra map
        # as well so adapters do not need to know that implementation detail.
        unknown = self.model_extra or {}
        if unknown:
            merged = dict(self.extra)
            merged.update({str(key): value for key, value in unknown.items() if key != "extra"})
            object.__setattr__(self, "extra", merged)
        return self


class InsightClaim(ContractModel):
    """A normalized claim with explicit evidence provenance."""

    claim_id: NonEmptyStr
    text: str
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    evidence_ref: NonEmptyStr | None = None
    attributes: ContractPayload = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        refs = list(self.evidence_refs)
        if self.evidence_ref is not None and self.evidence_ref not in refs:
            refs.append(self.evidence_ref)
        if not refs:
            raise ValueError("every insight claim requires an evidence reference")
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(refs)))
        if self.evidence_ref is None:
            object.__setattr__(self, "evidence_ref", refs[0])
        return self


class CommentInsight(VersionedContract):
    """Typed comment interpretation; raw comments remain evidence records."""

    schema_version: Literal["comment-insight/v1"] = COMMENT_INSIGHT_SCHEMA_VERSION
    source: NonEmptyStr = "xhs"
    note_id: NonEmptyStr
    comment_id: NonEmptyStr = Field(validation_alias=AliasChoices("comment_id", "id"))
    batch_index: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("batch_index", "batch"),
    )
    identity: CommentIdentity = CommentIdentity.NONE
    sentiment: CommentSentiment = CommentSentiment.NEUTRAL
    is_correction: bool = False
    mentioned_shops: tuple[NonEmptyStr, ...] = Field(
        default=(),
        validation_alias=AliasChoices("mentioned_shops", "shop_mentions"),
    )
    mentioned_dishes: tuple[NonEmptyStr, ...] = Field(
        default=(),
        validation_alias=AliasChoices("mentioned_dishes", "dish_mentions"),
    )
    claims: tuple[InsightClaim, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_payload: Any = None
    metadata: ContractPayload = Field(default_factory=dict)

    @field_validator("mentioned_shops", "mentioned_dishes", "evidence_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @model_validator(mode="after")
    def validate_claim_references(self) -> Self:
        claim_refs = {ref for claim in self.claims for ref in claim.evidence_refs}
        if claim_refs and not claim_refs.issubset(set(self.evidence_refs)):
            raise ValueError("insight evidence_refs must include every claim evidence reference")
        return self

    @property
    def evidence_key(self) -> str:
        # Match the canonical evidence ledger identity exactly.  Keeping one
        # format across the insight reducer and persistence boundary makes
        # deduplication/citation lossless and avoids delimiter heuristics.
        return f"{self.source}:note:{self.note_id}:comment:{self.comment_id}"

    @property
    def comment_ref(self) -> str:
        return self.evidence_key

    @property
    def shop_mentions(self) -> tuple[str, ...]:
        return self.mentioned_shops

    @property
    def dish_mentions(self) -> tuple[str, ...]:
        return self.mentioned_dishes


class _SemanticAction(VersionedContract):
    """Common policy-bound fields shared by all semantic actions."""

    schema_version: Literal["research-action/v1"] = RESEARCH_ACTION_SCHEMA_VERSION
    action_id: NonEmptyStr = Field(validation_alias=AliasChoices("action_id", "id"))
    kind: SemanticActionKind
    dependencies: tuple[NonEmptyStr, ...] = ()
    idempotency_key: NonEmptyStr
    resource_class: ResourceClass = Field(
        validation_alias=AliasChoices("resource_class", "resource")
    )
    capability: NonEmptyStr
    inputs: ContractPayload = Field(
        default_factory=dict,
        validation_alias=AliasChoices("inputs", "input", "input_contract"),
    )
    reason: str = ""

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "dependencies")

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action_id in self.dependencies:
            raise ValueError("an action cannot depend on itself")
        return self

    @property
    def id(self) -> str:
        return self.action_id

    @property
    def input_contract(self) -> ContractPayload:
        return self.inputs

    @property
    def resource(self) -> ResourceClass:
        return self.resource_class

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> Any:
        """Decode the public action base into its concrete kind.

        The concrete classes remain ordinary Pydantic models for callers that
        prefer explicit types, while ``SemanticAction.model_validate`` offers
        a safe discriminated boundary for persisted/planner payloads.
        """

        if cls is _SemanticAction and isinstance(obj, Mapping):
            kind = obj.get("kind", obj.get("type"))
            compact_kind = "".join(character.lower() for character in str(kind) if character.isalnum())
            concrete = {
                SemanticActionKind.SEARCH_NOTES.value: SearchNotes,
                SemanticActionKind.FETCH_NOTE_EVIDENCE.value: FetchNoteEvidence,
                SemanticActionKind.ANALYZE_COMMENT_BATCH.value: AnalyzeCommentBatch,
                SemanticActionKind.EXPAND_RESEARCH.value: ExpandResearch,
                SemanticActionKind.ENRICH_SHOP_PROFILE.value: EnrichShopProfile,
                SemanticActionKind.SYNTHESIZE.value: Synthesize,
                SemanticActionKind.STOP_RESEARCH.value: StopResearch,
            }
            concrete = next(
                (
                    action_type
                    for action_kind, action_type in concrete.items()
                    if "".join(character.lower() for character in action_kind if character.isalnum())
                    == compact_kind
                ),
                None,
            )
            if concrete is None:
                raise ValueError(f"unsupported semantic action kind: {kind!r}")
            payload = dict(obj)
            payload["kind"] = concrete.model_fields["kind"].default
            return concrete.model_validate(payload, *args, **kwargs)
        return super().model_validate(obj, *args, **kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, *args: Any, **kwargs: Any) -> Any:
        """Apply the same concrete-kind dispatch to JSON payloads."""

        if cls is _SemanticAction:
            return cls.model_validate(json.loads(json_data), *args, **kwargs)
        return super().model_validate_json(json_data, *args, **kwargs)


def parse_semantic_action(value: Any) -> SemanticAction:
    """Validate one persisted planner payload as its concrete action type."""

    return _SemanticAction.model_validate(value)


class SearchNotes(_SemanticAction):
    kind: Literal[SemanticActionKind.SEARCH_NOTES] = SemanticActionKind.SEARCH_NOTES
    resource_class: Literal[ResourceClass.XHS_SEARCH] = ResourceClass.XHS_SEARCH
    capability: NonEmptyStr = "notes.search"
    query: NonEmptyStr | None = None
    queries: tuple[NonEmptyStr, ...] = ()
    limit: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        if self.query is None and not self.queries:
            raise ValueError("SearchNotes requires query or queries")
        return self

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "queries")


class FetchNoteEvidence(_SemanticAction):
    kind: Literal[SemanticActionKind.FETCH_NOTE_EVIDENCE] = SemanticActionKind.FETCH_NOTE_EVIDENCE
    resource_class: ResourceClass = ResourceClass.XHS_COMMENTS
    capability: NonEmptyStr = "comments.search"
    note_id: NonEmptyStr
    cursor: str | None = None
    page_size: int | None = Field(default=None, gt=0)


class AnalyzeCommentBatch(_SemanticAction):
    kind: Literal[SemanticActionKind.ANALYZE_COMMENT_BATCH] = SemanticActionKind.ANALYZE_COMMENT_BATCH
    resource_class: Literal[ResourceClass.LLM] = ResourceClass.LLM
    capability: NonEmptyStr = "comments.analyze"
    note_id: NonEmptyStr
    batch_index: int = Field(ge=0)
    comment_ids: tuple[NonEmptyStr, ...] = ()
    token_estimate: int = Field(default=0, ge=0)

    @field_validator("comment_ids")
    @classmethod
    def validate_comment_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "comment_ids")


class ExpandResearch(_SemanticAction):
    kind: Literal[SemanticActionKind.EXPAND_RESEARCH] = SemanticActionKind.EXPAND_RESEARCH
    resource_class: Literal[ResourceClass.XHS_SEARCH] = ResourceClass.XHS_SEARCH
    capability: NonEmptyStr = "notes.search"
    query_variants: tuple[NonEmptyStr, ...] = ()
    reason: str = "research gap"

    @field_validator("query_variants")
    @classmethod
    def validate_variants(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "query_variants")

    @model_validator(mode="after")
    def validate_query_variants(self) -> Self:
        if not self.query_variants:
            raise ValueError("ExpandResearch requires at least one query variant")
        return self


class EnrichShopProfile(_SemanticAction):
    kind: Literal[SemanticActionKind.ENRICH_SHOP_PROFILE] = SemanticActionKind.ENRICH_SHOP_PROFILE
    resource_class: ResourceClass = ResourceClass.DIANPING_DETAIL
    capability: NonEmptyStr = "places.detail"
    shop_id: NonEmptyStr | None = None
    shop_name: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_shop_identity(self) -> Self:
        if self.shop_id is None and self.shop_name is None:
            raise ValueError("EnrichShopProfile requires shop_id or shop_name")
        return self


class Synthesize(_SemanticAction):
    kind: Literal[SemanticActionKind.SYNTHESIZE] = SemanticActionKind.SYNTHESIZE
    resource_class: Literal[ResourceClass.LLM] = ResourceClass.LLM
    capability: NonEmptyStr = "research.synthesize"
    evidence_refs: tuple[NonEmptyStr, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "evidence_refs")


class StopResearch(_SemanticAction):
    kind: Literal[SemanticActionKind.STOP_RESEARCH] = SemanticActionKind.STOP_RESEARCH
    resource_class: Literal[ResourceClass.PERSISTENCE] = ResourceClass.PERSISTENCE
    capability: NonEmptyStr = "research.stop"
    reason: NonEmptyStr = "stop requested"


# Public base name and union-friendly aliases.  The concrete classes keep the
# planner's action vocabulary visible to type checkers and reviewers.
SemanticAction = _SemanticAction
ResearchAction = _SemanticAction
Action = _SemanticAction
SemanticActionModel = _SemanticAction


class ResearchActionResult(VersionedContract):
    """Typed output accepted by the runtime reducer."""

    schema_version: Literal["research-action-result/v1"] = (
        RESEARCH_ACTION_RESULT_SCHEMA_VERSION
    )
    action_id: NonEmptyStr
    success: bool = True
    output: JsonValue = Field(
        default=None,
        validation_alias=AliasChoices("output", "data", "value"),
    )
    source_envelopes: tuple[SourceEnvelope, ...] = ()
    notes: tuple[XhsNoteLead, ...] = ()
    insights: tuple[CommentInsight, ...] = ()
    profiles: tuple[ShopProfile, ...] = ()
    claims: tuple[InsightClaim, ...] = ()
    entities: tuple[JsonValue, ...] = ()
    controversies: tuple[JsonValue, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    item_count: int = Field(default=0, ge=0)
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    continuation: ContractPayload = Field(default_factory=dict)
    tokens_used: int = Field(default=0, ge=0)
    metadata: ContractPayload = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.success and self.gaps and self.completeness == "complete":
            raise ValueError("a complete action result cannot contain gaps")
        if not self.success and self.completeness == "complete":
            raise ValueError("an unsuccessful action result cannot be complete")
        if self.item_count == 0:
            object.__setattr__(
                self,
                "item_count",
                len(self.source_envelopes)
                + len(self.notes)
                + len(self.insights)
                + len(self.profiles),
            )
        return self


class ResearchState(VersionedContract):
    """Immutable state snapshot produced after reducing runtime events."""

    schema_version: Literal["research-runtime/v1"] = RESEARCH_RUNTIME_SCHEMA_VERSION
    run_id: NonEmptyStr
    outcome: ResearchOutcome = ResearchOutcome.EMPTY
    source_envelopes: tuple[SourceEnvelope, ...] = ()
    notes: tuple[XhsNoteLead, ...] = ()
    insights: tuple[CommentInsight, ...] = ()
    profiles: tuple[ShopProfile, ...] = ()
    claims: tuple[InsightClaim, ...] = ()
    entities: tuple[JsonValue, ...] = ()
    controversies: tuple[JsonValue, ...] = ()
    comments: tuple[JsonValue, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    continuation: ContractPayload = Field(default_factory=dict)
    completed_action_ids: tuple[NonEmptyStr, ...] = ()
    failed_action_ids: tuple[NonEmptyStr, ...] = ()
    in_flight_action_ids: tuple[NonEmptyStr, ...] = ()
    applied_event_ids: tuple[NonEmptyStr, ...] = ()
    events: tuple[ResearchEvent, ...] = ()
    sequence: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)

    @field_validator(
        "completed_action_ids",
        "failed_action_ids",
        "in_flight_action_ids",
        "applied_event_ids",
    )
    @classmethod
    def validate_state_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "state ids")

    @model_validator(mode="after")
    def validate_action_sets(self) -> Self:
        completed = set(self.completed_action_ids)
        failed = set(self.failed_action_ids)
        in_flight = set(self.in_flight_action_ids)
        if completed.intersection(failed):
            raise ValueError("an action cannot be both completed and failed")
        if in_flight.intersection(completed.union(failed)):
            raise ValueError("an action cannot be in-flight after terminal completion")
        return self

    @property
    def status(self) -> ResearchOutcome:
        return self.outcome


class ResearchEvent(VersionedContract):
    """One actual runtime transition, ordered by a per-run sequence."""

    schema_version: Literal["research-event/v1"] = RESEARCH_EVENT_SCHEMA_VERSION
    event_id: NonEmptyStr
    run_id: NonEmptyStr
    sequence: int = Field(ge=1)
    event_type: ResearchEventType = Field(
        validation_alias=AliasChoices("event_type", "type", "kind")
    )
    occurred_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    action_id: NonEmptyStr | None = None
    resource_class: ResourceClass | None = None
    attempt: int = Field(default=1, ge=1)
    item_count: int = Field(default=0, ge=0)
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    budget_usage: ContractPayload = Field(default_factory=dict)
    result: ResearchActionResult | None = None
    gap: ResearchGap | None = None
    payload: ContractPayload = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        action_events = {
            ResearchEventType.ACTION_STARTED,
            ResearchEventType.ACTION_PROGRESS,
            ResearchEventType.ACTION_GAP,
            ResearchEventType.ACTION_COMPLETED,
        }
        if self.event_type in action_events and self.action_id is None:
            raise ValueError("action lifecycle events require action_id")
        if self.event_type in {
            ResearchEventType.RUN_COMPLETED,
            ResearchEventType.RUN_CANCELLED,
        } and self.action_id is not None:
            raise ValueError("run terminal events cannot carry an action_id")
        if self.event_type is ResearchEventType.ACTION_GAP and self.gap is None:
            raise ValueError("action_gap events require a typed gap")
        if self.event_type is ResearchEventType.ACTION_COMPLETED and self.result is None:
            raise ValueError("action_completed events require a result")
        if self.result is not None and self.action_id != self.result.action_id:
            raise ValueError("event result action_id must match event action_id")
        return self

    @property
    def kind(self) -> ResearchEventType:
        return self.event_type

    @property
    def type(self) -> ResearchEventType:
        return self.event_type


ResearchState.model_rebuild()


def initial_research_state(run_id: str) -> ResearchState:
    """Create an empty state snapshot for a runtime run."""

    return ResearchState(run_id=run_id)


def _merge_by_key[T](values: Iterable[T], key: Any) -> tuple[T, ...]:
    merged: dict[Any, T] = {}
    for value in values:
        identity = key(value)
        existing = merged.get(identity)
        if identity not in merged or _merge_value_rank(value) > _merge_value_rank(existing):
            merged[identity] = value
    try:
        ordered_keys = sorted(merged)
    except TypeError:
        # Contract keys are normally strings/tuples of strings. Fall back to
        # a canonical encoding only for an adapter that supplies mixed key
        # types; numeric tuple components must retain their natural ordering.
        ordered_keys = sorted(merged, key=_stable_json)
    return tuple(merged[item] for item in ordered_keys)


def _gap_key(gap: ResearchGap) -> tuple[str, str, str, str, str, str]:
    return (
        gap.source,
        gap.operation,
        gap.code,
        gap.message,
        str(gap.retryable),
        _stable_json(gap.details),
    )


def _json_identity(value: JsonValue) -> str:
    """Build a stable key for opaque normalized values."""

    return _stable_json(value)


def _stable_json(value: Any) -> str:
    """Serialize contract values for deterministic identity and tie-breaking."""

    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _merge_value_rank(value: Any) -> tuple[int, str]:
    """Prefer a richer duplicate, then resolve equal richness stably."""

    encoded = _stable_json(value)
    return len(encoded), encoded


def _shop_profile_identity(profile: ShopProfile) -> tuple[str, ...]:
    """Prefer an immutable provider id; use exact normalized name only without one."""

    provider_refs = [
        (str(provider).strip(), str(provider_ref).strip())
        for provider, provider_ref in profile.provider_refs.items()
        if str(provider).strip()
        and provider_ref not in (None, "")
        and str(provider_ref).strip()
    ]
    if provider_refs:
        provider, provider_ref = min(
            provider_refs,
            key=lambda item: (item[0] != "dianping", item[0], item[1]),
        )
        return ("provider", provider, provider_ref)
    return (
        "name",
        "".join(character for character in profile.name.casefold() if character.isalnum()),
    )


_PROFILE_SCALAR_FIELDS = (
    "name",
    "alias",
    "url",
    "image_url",
    "address",
    "city",
    "district",
    "region",
    "business_area",
    "location",
    "latitude",
    "longitude",
    "coordinate_system",
    "phone",
    "rating",
    "review_count",
    "average_price",
    "category",
    "opening_hours",
    "source_url",
    "source_updated_at",
    "fetched_at",
)
_PROFILE_COLLECTION_FIELDS = ("images", "recommended_dishes", "promotions", "tags")


def _merge_shop_profiles(values: Iterable[ShopProfile]) -> tuple[ShopProfile, ...]:
    """Merge duplicate provider profiles field-by-field without data loss.

    A whole-record richness comparison is insufficient for profile refreshes:
    one response can contain the address while another contains dishes or
    photos.  The reducer therefore uses the same identity rules as persistence
    and unions every additive field before applying a deterministic tie-break.
    """

    merged: dict[tuple[str, ...], ShopProfile] = {}
    for profile in values:
        identity = _shop_profile_identity(profile)
        current = merged.get(identity)
        merged[identity] = profile if current is None else _merge_shop_profile(current, profile)
    return tuple(merged[key] for key in sorted(merged, key=_stable_json))


def _merge_shop_profile(left: ShopProfile, right: ShopProfile) -> ShopProfile:
    update: dict[str, Any] = {}
    for field_name in _PROFILE_SCALAR_FIELDS:
        update[field_name] = _prefer_profile_value(
            getattr(left, field_name), getattr(right, field_name)
        )
    update["provider_refs"] = _merge_profile_mapping(left.provider_refs, right.provider_refs)
    update["geo"] = _merge_profile_mapping(left.geo, right.geo)
    for field_name in _PROFILE_COLLECTION_FIELDS:
        update[field_name] = _merge_profile_collection(
            getattr(left, field_name), getattr(right, field_name)
        )
    update["attributes"] = _merge_profile_mapping(left.attributes, right.attributes)
    update["review_completeness"] = _merge_profile_mapping(
        left.review_completeness, right.review_completeness
    )
    update["source_payload"] = _merge_profile_payload(
        left.source_payload, right.source_payload
    )
    update["gaps"] = _merge_by_key((*left.gaps, *right.gaps), _gap_key)
    if left.outcome is ResearchOutcome.COMPLETE and right.outcome is ResearchOutcome.COMPLETE:
        update["outcome"] = ResearchOutcome.COMPLETE
    elif left.outcome is ResearchOutcome.FAILED and right.outcome is ResearchOutcome.FAILED:
        update["outcome"] = ResearchOutcome.FAILED
    else:
        update["outcome"] = ResearchOutcome.PARTIAL
    return left.model_copy(update=update)


def _profile_value_empty(value: Any) -> bool:
    return value in (None, "", [], {}, ())


def _prefer_profile_value(left: Any, right: Any) -> Any:
    if _profile_value_empty(left):
        return right
    if _profile_value_empty(right) or left == right:
        return left
    if isinstance(left, datetime) and isinstance(right, datetime):
        return max(left, right)
    return max((left, right), key=_merge_value_rank)


def _merge_profile_collection(left: Iterable[Any], right: Iterable[Any]) -> tuple[Any, ...]:
    values: dict[str, Any] = {}
    for value in (*tuple(left), *tuple(right)):
        if _profile_value_empty(value):
            continue
        marker = _stable_json(value)
        values[marker] = value
    return tuple(values[key] for key in sorted(values))


def _merge_profile_mapping(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    keys = {str(key) for key in (*left.keys(), *right.keys())}
    for key in sorted(keys):
        left_value = left.get(key)
        right_value = right.get(key)
        if isinstance(left_value, Mapping) and isinstance(right_value, Mapping):
            merged[key] = _merge_profile_mapping(left_value, right_value)
        else:
            value = _prefer_profile_value(left_value, right_value)
            if not _profile_value_empty(value):
                merged[key] = value
    return merged


def _merge_profile_payload(left: Any, right: Any) -> Any:
    if _profile_value_empty(left):
        return right
    if _profile_value_empty(right) or left == right:
        return left
    variants: list[Any] = []
    for value in (left, right):
        if isinstance(value, Mapping) and "variants" in value:
            nested = value.get("variants")
            if isinstance(nested, (list, tuple)):
                variants.extend(nested)
                continue
        variants.append(value)
    unique: dict[str, Any] = {_stable_json(value): value for value in variants}
    ordered = [unique[key] for key in sorted(unique)]
    return ordered[0] if len(ordered) == 1 else {"variants": ordered}


def reduce_research_event(state: ResearchState, event: ResearchEvent) -> ResearchState:
    """Apply one event idempotently and keep all collections deterministically ordered."""

    if event.run_id != state.run_id:
        raise ValueError("research event run_id does not match state")
    if event.event_id in state.applied_event_ids:
        return state

    applied = tuple(sorted((*state.applied_event_ids, event.event_id)))
    events = _merge_by_key(
        (*state.events, event),
        lambda item: (item.sequence, item.event_id),
    )

    # Cancellation is a terminal boundary. A provider task may finish while
    # cancellation is being delivered, but that late result must not turn a
    # cancelled run back into a successful one. Keep the event in the audit
    # log while preserving the already-reduced evidence snapshot.
    if any(item.event_type is ResearchEventType.RUN_CANCELLED for item in state.events):
        failed = set(state.failed_action_ids)
        failed.update(state.in_flight_action_ids)
        outcome = _state_outcome(
            source_envelopes=state.source_envelopes,
            notes=state.notes,
            insights=state.insights,
            profiles=state.profiles,
            claims=state.claims,
            entities=state.entities,
            controversies=state.controversies,
            comments=state.comments,
            gaps=state.gaps,
            completed=set(state.completed_action_ids),
            failed=failed,
            terminal=True,
            cancelled=True,
            partial=any(
                item.completeness == "partial"
                or (item.result is not None and item.result.completeness == "partial")
                for item in state.events
            ),
        )
        return state.model_copy(
            update={
                "outcome": outcome,
                "failed_action_ids": tuple(sorted(failed)),
                "in_flight_action_ids": (),
                "applied_event_ids": applied,
                "events": events,
                "sequence": max(state.sequence, event.sequence),
            }
        )

    # A completed run is also terminal.  Late retries may still carry a
    # useful audit payload, so retain the event and its idempotency marker, but
    # never mutate the already published projections or outcome.
    if any(item.event_type is ResearchEventType.RUN_COMPLETED for item in state.events):
        return state.model_copy(
            update={
                "applied_event_ids": applied,
                "events": events,
                "sequence": max(state.sequence, event.sequence),
            }
        )

    source_envelopes = state.source_envelopes
    notes = state.notes
    insights = state.insights
    profiles = state.profiles
    claims = state.claims
    entities = state.entities
    controversies = state.controversies
    comments = state.comments
    gaps = state.gaps
    completed = set(state.completed_action_ids)
    failed = set(state.failed_action_ids)
    in_flight = set(state.in_flight_action_ids)
    continuation = dict(state.continuation)
    tokens = state.tokens_used
    replans = state.replans
    prior_completion = (
        event.action_id is not None
        and any(
            item.event_type is ResearchEventType.ACTION_COMPLETED
            and item.action_id == event.action_id
            for item in state.events
        )
    )

    if event.action_id is not None:
        if event.event_type is ResearchEventType.ACTION_STARTED:
            if event.action_id not in completed and event.action_id not in failed:
                in_flight.add(event.action_id)
        elif event.event_type is ResearchEventType.ACTION_COMPLETED:
            in_flight.discard(event.action_id)
            if event.result is not None:
                result = event.result
                # A repeated completion may carry a richer replay payload, so
                # merge its evidence below, but never apply terminal status or
                # token accounting twice.
                first_terminal = (
                    not prior_completion
                    and event.action_id not in completed
                    and event.action_id not in failed
                )
                if first_terminal:
                    if result.success:
                        completed.add(event.action_id)
                        failed.discard(event.action_id)
                    else:
                        failed.add(event.action_id)
                        completed.discard(event.action_id)
                source_envelopes = _merge_by_key(
                    (*source_envelopes, *result.source_envelopes),
                    lambda item: (
                        _json_identity(
                            {
                                "source": item.source,
                                "operation": item.operation,
                                "cursor": item.cursor,
                                "next_cursor": item.next_cursor,
                                "raw_payload": item.raw_payload,
                            }
                        )
                    ),
                )
                notes = _merge_by_key((*notes, *result.notes), lambda item: item.note_id)
                insights = _merge_by_key(
                    (*insights, *result.insights), lambda item: item.evidence_key
                )
                profiles = _merge_shop_profiles((*profiles, *result.profiles))
                claims = _merge_by_key(
                    (*claims, *result.claims, *(claim for insight in result.insights for claim in insight.claims)),
                    lambda item: item.claim_id,
                )
                entities = _merge_by_key(
                    (*entities, *result.entities),
                    _json_identity,
                )
                controversies = _merge_by_key(
                    (*controversies, *result.controversies),
                    _json_identity,
                )
                comments = _merge_by_key(
                    (*comments, *(insight.model_dump(mode="json") for insight in result.insights)),
                    _json_identity,
                )
                gaps = _merge_by_key((*gaps, *result.gaps), _gap_key)
                continuation.update(result.continuation)
                if not prior_completion:
                    tokens += result.tokens_used
                replan_index = result.metadata.get("replan_index")
                if isinstance(replan_index, int) and not isinstance(replan_index, bool):
                    replans = max(replans, replan_index)
        elif event.event_type is ResearchEventType.ACTION_GAP:
            in_flight.discard(event.action_id)
            if event.action_id not in completed:
                failed.add(event.action_id)
            if event.gap is not None:
                gaps = _merge_by_key((*gaps, event.gap), _gap_key)

    if event.event_type is ResearchEventType.RUN_CANCELLED and in_flight:
        # A terminal cancellation can be replayed before individual action
        # gaps. Close the state transition so replay cannot leave phantom
        # in-flight actions behind; later gap events remain idempotent.
        failed.update(in_flight)
        in_flight.clear()

    if event.gap is not None and event.event_type is not ResearchEventType.ACTION_GAP:
        gaps = _merge_by_key((*gaps, event.gap), _gap_key)
    event_continuation = event.payload.get("continuation")
    if isinstance(event_continuation, Mapping):
        continuation.update(event_continuation)

    max_sequence = max(state.sequence, event.sequence)
    outcome = _state_outcome(
        source_envelopes=source_envelopes,
        notes=notes,
        insights=insights,
        profiles=profiles,
        claims=claims,
        entities=entities,
        controversies=controversies,
        comments=comments,
        gaps=gaps,
        completed=completed,
        failed=failed,
        terminal=event.event_type in {ResearchEventType.RUN_COMPLETED, ResearchEventType.RUN_CANCELLED},
        cancelled=event.event_type is ResearchEventType.RUN_CANCELLED,
        partial=any(
            item.completeness == "partial"
            or (item.result is not None and item.result.completeness == "partial")
            for item in (*state.events, event)
        ),
    )
    return state.model_copy(
        update={
            "outcome": outcome,
            "source_envelopes": source_envelopes,
            "notes": notes,
            "insights": insights,
            "profiles": profiles,
            "claims": claims,
            "entities": entities,
            "controversies": controversies,
            "comments": comments,
            "gaps": gaps,
            "continuation": continuation,
            "completed_action_ids": tuple(sorted(completed)),
            "failed_action_ids": tuple(sorted(failed)),
            "in_flight_action_ids": tuple(sorted(in_flight)),
            "applied_event_ids": applied,
            "events": events,
            "sequence": max_sequence,
            "tokens_used": tokens,
            "replans": replans,
        }
    )


def reduce_research_events(
    state: ResearchState, events: Sequence[ResearchEvent]
) -> ResearchState:
    """Reduce an arbitrary delivery order into the same logical state."""

    current = state
    for event in sorted(events, key=lambda item: (item.sequence, item.event_id)):
        current = reduce_research_event(current, event)
    return current


class ResearchStateReducer:
    """Small callable wrapper convenient for dependency injection and tests."""

    def __call__(self, state: ResearchState, event: ResearchEvent) -> ResearchState:
        return reduce_research_event(state, event)

    def reduce(self, state: ResearchState, event: ResearchEvent) -> ResearchState:
        return self(state, event)


def _state_outcome(
    *,
    source_envelopes: tuple[SourceEnvelope, ...],
    notes: tuple[XhsNoteLead, ...],
    insights: tuple[CommentInsight, ...],
    profiles: tuple[ShopProfile, ...],
    claims: tuple[InsightClaim, ...],
    entities: tuple[JsonValue, ...],
    controversies: tuple[JsonValue, ...],
    comments: tuple[JsonValue, ...],
    gaps: tuple[ResearchGap, ...],
    completed: set[str],
    failed: set[str],
    terminal: bool,
    cancelled: bool,
    partial: bool,
) -> ResearchOutcome:
    has_items = bool(
        source_envelopes
        or notes
        or insights
        or profiles
        or claims
        or entities
        or controversies
        or comments
    )
    if cancelled:
        return ResearchOutcome.PARTIAL if has_items else ResearchOutcome.FAILED
    if partial:
        return ResearchOutcome.PARTIAL if has_items or completed else ResearchOutcome.FAILED
    if gaps and completed:
        return ResearchOutcome.PARTIAL
    if failed or gaps:
        return ResearchOutcome.PARTIAL if has_items else ResearchOutcome.FAILED
    if terminal and not has_items:
        return ResearchOutcome.EMPTY
    if has_items:
        return ResearchOutcome.COMPLETE
    return ResearchOutcome.EMPTY


__all__ = [
    "Action",
    "ActionKind",
    "AnalyzeCommentBatch",
    "CommentIdentity",
    "CommentInsight",
    "CommentSentiment",
    "COMMENT_INSIGHT_SCHEMA_VERSION",
    "EnrichShopProfile",
    "EventType",
    "ExpandResearch",
    "FetchNoteEvidence",
    "InsightClaim",
    "ResearchAction",
    "ResearchActionKind",
    "ResearchActionResult",
    "ResearchEvent",
    "ResearchEventType",
    "ResearchState",
    "ResearchStateReducer",
    "RESEARCH_ACTION_SCHEMA_VERSION",
    "RESEARCH_ACTION_RESULT_SCHEMA_VERSION",
    "RESEARCH_EVENT_SCHEMA_VERSION",
    "RESEARCH_RUNTIME_SCHEMA_VERSION",
    "ResourceClass",
    "SearchNotes",
    "SemanticAction",
    "SemanticActionKind",
    "SemanticActionModel",
    "SourceEnvelope",
    "SOURCE_ENVELOPE_SCHEMA_VERSION",
    "StopResearch",
    "Synthesize",
    "initial_research_state",
    "parse_semantic_action",
    "reduce_research_event",
    "reduce_research_events",
]
