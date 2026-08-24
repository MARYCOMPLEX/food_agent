"""Private memory, preference snapshot, and personalization policy contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import ConfigDict, Field, model_validator

from .base import ContractPayload, NonEmptyStr, Timestamp
from .evidence import AuthorityModel

_FORBIDDEN_SUBJECT_VALUES = {"anonymous", "shared", "ip_address", "user_agent", "device_only"}
_SESSION_ACTIVE_WINDOW = timedelta(hours=24)
_INFERRED_ACTIVE_WINDOW = timedelta(days=180)
_STRATEGY_FEEDBACK_ACTIVE_WINDOW = timedelta(days=90)


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _AuthorityModel(AuthorityModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class MemorySubjectKind(StrEnum):
    USER = "user"
    ANONYMOUS = "anonymous"


class MemoryLayer(StrEnum):
    SESSION = "session"
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    STRATEGY_FEEDBACK = "strategy_feedback"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    TOMBSTONED = "tombstoned"
    CLAIMED = "claimed"


class ConsentBasis(StrEnum):
    SERVICE_REQUIRED = "service_required"
    USER_DIRECTED = "user_directed"
    PERSONALIZATION_OPT_IN = "personalization_opt_in"
    FEEDBACK_PERSONALIZATION_OPT_IN = "feedback_personalization_opt_in"


class ConsentStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class MemoryVisibility(StrEnum):
    PRIVATE_SUBJECT = "private_subject"
    PRIVATE_SESSION = "private_session"


class MemorySubject(_AuthorityModel):
    kind: MemorySubjectKind
    id: Annotated[str, Field(min_length=16)]
    cohort: str | None = None
    locale: str | None = None

    @model_validator(mode="after")
    def reject_shared_subjects(self) -> MemorySubject:
        if self.id.casefold() in _FORBIDDEN_SUBJECT_VALUES:
            raise ValueError("shared or ambient values cannot identify a private subject")
        return self


class MemoryConsent(_AuthorityModel):
    basis: ConsentBasis
    policy_version: NonEmptyStr
    status: ConsentStatus
    captured_at: Timestamp


class MemoryRecord(_AuthorityModel):
    schema_version: Literal["memory-record/v1"] = "memory-record/v1"
    record_id: NonEmptyStr
    tenant_id: NonEmptyStr
    subject: MemorySubject
    session_id: NonEmptyStr | None = None
    layer: MemoryLayer
    key: NonEmptyStr
    value: ContractPayload
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_event_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    consent: MemoryConsent
    valid_from: Timestamp
    expires_at: Timestamp | None
    status: MemoryStatus
    supersedes_record_id: str | None = None
    policy_version: NonEmptyStr
    created_at: Timestamp
    updated_at: Timestamp

    @property
    def visibility(self) -> MemoryVisibility:
        if self.subject.kind is MemorySubjectKind.ANONYMOUS or self.layer is MemoryLayer.SESSION:
            return MemoryVisibility.PRIVATE_SESSION
        return MemoryVisibility.PRIVATE_SUBJECT

    @model_validator(mode="after")
    def enforce_layer_and_scope(self) -> MemoryRecord:
        self._enforce_lifecycle_order()
        self._enforce_event_identity()
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be later than valid_from")
        if self.status is MemoryStatus.ACTIVE:
            if self.consent.status is ConsentStatus.WITHDRAWN:
                raise ValueError("active memory requires active consent")
            if self.expires_at is not None and self.updated_at >= self.expires_at:
                raise ValueError("active memory must be unexpired at updated_at")
        if self.status is MemoryStatus.EXPIRED and (
            self.expires_at is None or self.updated_at < self.expires_at
        ):
            raise ValueError("expired memory requires a reached expires_at")
        if self.layer is MemoryLayer.SESSION:
            self._require_session()
            self._require_no_confidence()
            self._require_value("kind", "value")
            self._require_kind({"current_query", "geo", "time", "temporary_constraint"})
            self._require_consent(ConsentBasis.SERVICE_REQUIRED)
            if self.expires_at is None:
                raise ValueError("session memory requires expires_at")
            if self.status is MemoryStatus.ACTIVE:
                self._require_expiry(
                    self.updated_at + _SESSION_ACTIVE_WINDOW,
                    "session memory expires 24 hours after last activity",
                )
            elif not (
                self.valid_from + _SESSION_ACTIVE_WINDOW
                <= self.expires_at
                <= self.updated_at + _SESSION_ACTIVE_WINDOW
            ):
                raise ValueError("session memory expires 24 hours after last activity")
        elif self.layer is MemoryLayer.EXPLICIT:
            self._require_anonymous_session()
            self._require_no_confidence()
            self._require_value("kind", "operator", "value")
            self._require_kind({"preference", "hard_constraint", "budget", "travel_requirement"})
            self._require_consent(ConsentBasis.USER_DIRECTED)
        elif self.layer is MemoryLayer.INFERRED:
            if self.subject.kind is not MemorySubjectKind.USER:
                raise ValueError("inferred memory requires an authenticated user")
            if self.confidence is None:
                raise ValueError("inferred memory requires confidence")
            self._require_value("kind", "value", "supportEventIds")
            self._require_kind({"preference", "affinity", "avoidance"})
            support_ids = self.value["supportEventIds"]
            if (
                not isinstance(support_ids, Sequence)
                or isinstance(support_ids, (str, bytes, bytearray))
                or not support_ids
                or not all(isinstance(item, str) and item for item in support_ids)
            ):
                raise ValueError("inferred memory requires supporting user-action events")
            support_event_ids = tuple(support_ids)
            if len(support_event_ids) != len(set(support_event_ids)):
                raise ValueError("supportEventIds must not contain duplicates")
            if support_event_ids != self.source_event_ids:
                raise ValueError("supportEventIds must match source_event_ids")
            self._require_consent(ConsentBasis.PERSONALIZATION_OPT_IN)
            self._require_expiry(
                self.valid_from + _INFERRED_ACTIVE_WINDOW,
                "inferred memory expires 180 days after its support watermark",
            )
        else:
            self._require_anonymous_session()
            self._require_no_confidence()
            self._require_value("dimension", "value")
            if self.value["dimension"] not in {"research_depth", "source_trust", "result_style"}:
                raise ValueError("strategy feedback dimension is not declared")
            self._require_consent(ConsentBasis.FEEDBACK_PERSONALIZATION_OPT_IN)
            self._require_expiry(
                self.valid_from + _STRATEGY_FEEDBACK_ACTIVE_WINDOW,
                "strategy feedback expires 90 days after capture",
            )
        return self

    def _enforce_lifecycle_order(self) -> None:
        if self.consent.captured_at > self.valid_from:
            raise ValueError("consent captured_at must not be after valid_from")
        if self.valid_from > self.updated_at:
            raise ValueError("valid_from must not be after updated_at")
        if self.created_at > self.updated_at:
            raise ValueError("created_at must not be after updated_at")
        if self.consent.policy_version != self.policy_version:
            raise ValueError("consent and memory policy_version must match")
        if self.supersedes_record_id == self.record_id:
            raise ValueError("a memory record cannot supersede itself")

    def _enforce_event_identity(self) -> None:
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source_event_ids must not contain duplicates")

    def _require_expiry(self, expected: Timestamp, message: str) -> None:
        if self.expires_at != expected:
            raise ValueError(message)

    def _require_session(self) -> None:
        if not self.session_id:
            raise ValueError("this memory layer requires session_id")

    def _require_anonymous_session(self) -> None:
        if self.subject.kind is MemorySubjectKind.ANONYMOUS:
            self._require_session()

    def _require_no_confidence(self) -> None:
        if self.confidence is not None:
            raise ValueError("confidence is forbidden for this memory layer")

    def _require_value(self, *keys: str) -> None:
        missing = set(keys) - set(self.value)
        if missing:
            raise ValueError(f"memory value is missing {sorted(missing)}")

    def _require_kind(self, allowed: set[str]) -> None:
        if self.value["kind"] not in allowed:
            raise ValueError("memory value kind is not declared for this layer")

    def _require_consent(self, basis: ConsentBasis) -> None:
        if self.consent.basis is not basis:
            raise ValueError(f"{self.layer.value} memory requires {basis.value} consent")


class MemoryEvent(_AuthorityModel):
    """Versioned private source event referenced by one or more memory records."""

    schema_version: Literal["memory-event/v1"] = "memory-event/v1"
    event_id: NonEmptyStr
    tenant_id: NonEmptyStr
    subject: MemorySubject
    session_id: NonEmptyStr | None = None
    event_type: NonEmptyStr
    payload: ContractPayload
    idempotency_key: NonEmptyStr
    occurred_at: Timestamp
    policy_version: NonEmptyStr
    created_at: Timestamp

    @model_validator(mode="after")
    def enforce_scope_and_lifecycle(self) -> MemoryEvent:
        if self.subject.kind is MemorySubjectKind.ANONYMOUS and not self.session_id:
            raise ValueError("anonymous memory events require session_id")
        if self.occurred_at > self.created_at:
            raise ValueError("occurred_at must not be after created_at")
        return self


class UserIsolationKey(_AuthorityModel):
    kind: Literal["user"] = "user"
    tenant_id: NonEmptyStr
    user_id: Annotated[str, Field(min_length=16)]
    session_id: NonEmptyStr | None = None

    @property
    def partition(self) -> tuple[str, str] | tuple[str, str, str]:
        if self.session_id is None:
            return (self.tenant_id, self.user_id)
        return (self.tenant_id, self.user_id, self.session_id)

    def namespaced_key(self, namespace: NonEmptyStr) -> str:
        suffix = f":session_id:{_key_part(self.session_id)}" if self.session_id else ""
        return (
            f"tenant_id:{_key_part(self.tenant_id)}:user_id:{_key_part(self.user_id)}"
            f"{suffix}:namespace:{_key_part(namespace)}"
        )


class AnonymousIsolationKey(_AuthorityModel):
    kind: Literal["anonymous"] = "anonymous"
    tenant_id: NonEmptyStr
    anonymous_subject_id: Annotated[str, Field(min_length=16)]
    session_id: NonEmptyStr

    @model_validator(mode="after")
    def reject_shared_subjects(self) -> AnonymousIsolationKey:
        if self.anonymous_subject_id.casefold() in _FORBIDDEN_SUBJECT_VALUES:
            raise ValueError("anonymous memory requires a unique server-issued subject")
        return self

    @property
    def partition(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.anonymous_subject_id, self.session_id)

    def namespaced_key(self, namespace: NonEmptyStr) -> str:
        return (
            f"tenant_id:{_key_part(self.tenant_id)}:anonymous_subject_id:"
            f"{_key_part(self.anonymous_subject_id)}:session_id:{_key_part(self.session_id)}"
            f":namespace:{_key_part(namespace)}"
        )


type MemoryIsolationKey = UserIsolationKey | AnonymousIsolationKey


class MemoryConversationTurn(_AuthorityModel):
    """A typed conversation fact included in an authority write batch."""

    turn_id: NonEmptyStr
    scope: MemoryIsolationKey = Field(discriminator="kind")
    role: Literal["user", "assistant", "system"]
    content: NonEmptyStr
    source_event_id: NonEmptyStr
    occurred_at: Timestamp
    idempotency_key: NonEmptyStr
    metadata: ContractPayload = Field(default_factory=dict)


class MemoryOutboxEvent(_AuthorityModel):
    """A committed post-write projection instruction."""

    outbox_id: NonEmptyStr
    scope: MemoryIsolationKey = Field(discriminator="kind")
    event_type: NonEmptyStr
    aggregate_id: NonEmptyStr
    payload: ContractPayload
    idempotency_key: NonEmptyStr
    available_at: Timestamp


class MemoryAuthorityWrite(_AuthorityModel):
    """Facts that must commit together before any derived projection runs."""

    conversation_turn: MemoryConversationTurn | None = None
    record: MemoryRecord | None = None
    source_event: MemoryEvent | None = None
    outbox: MemoryOutboxEvent

    @model_validator(mode="after")
    def require_authority_fact(self) -> MemoryAuthorityWrite:
        if self.conversation_turn is None and self.record is None and self.source_event is None:
            raise ValueError("an authority write must include a conversation, record, or source event")
        scopes = {
            _scope_identity(
                self.outbox.scope.tenant_id,
                self.outbox.scope.kind,
                _scope_subject_id(self.outbox.scope),
                self.outbox.scope.session_id,
            )
        }
        if self.conversation_turn is not None:
            scopes.add(
                _scope_identity(
                    self.conversation_turn.scope.tenant_id,
                    self.conversation_turn.scope.kind,
                    _scope_subject_id(self.conversation_turn.scope),
                    self.conversation_turn.scope.session_id,
                )
            )
        if self.record is not None:
            scopes.add(
                _scope_identity(
                    self.record.tenant_id,
                    self.record.subject.kind,
                    self.record.subject.id,
                    self.record.session_id,
                )
            )
        if self.source_event is not None:
            scopes.add(
                _scope_identity(
                    self.source_event.tenant_id,
                    self.source_event.subject.kind,
                    self.source_event.subject.id,
                    self.source_event.session_id,
                )
            )
        if len(scopes) != 1:
            raise ValueError("authority write facts must share one tenant/subject/session scope")
        return self


class MemoryWriteReceipt(_AuthorityModel):
    """Result reported after authority commit and optional projection attempt."""

    schema_version: Literal["memory-write-receipt/v1"] = "memory-write-receipt/v1"
    outbox_id: NonEmptyStr
    committed: Literal[True] = True
    projected: bool


def _scope_identity(
    tenant_id: str,
    subject_kind: object,
    subject_id: str,
    session_id: str | None,
) -> tuple[str, str, str, str | None]:
    return (tenant_id, str(subject_kind), subject_id, session_id)


def _scope_subject_id(scope: MemoryIsolationKey) -> str:
    return scope.user_id if isinstance(scope, UserIsolationKey) else scope.anonymous_subject_id


def isolation_key_for(record: MemoryRecord) -> MemoryIsolationKey:
    if record.subject.kind is MemorySubjectKind.USER:
        return UserIsolationKey(
            tenant_id=record.tenant_id,
            user_id=record.subject.id,
            session_id=record.session_id,
        )
    if record.session_id is None:  # Enforced by MemoryRecord, retained for type narrowing.
        raise ValueError("anonymous memory requires session_id")
    return AnonymousIsolationKey(
        tenant_id=record.tenant_id,
        anonymous_subject_id=record.subject.id,
        session_id=record.session_id,
    )


class PreferenceSnapshot(_AuthorityModel):
    """Private, versioned resolver output pinned to its authority records."""

    schema_version: Literal["preference-snapshot/v1"] = "preference-snapshot/v1"
    snapshot_id: NonEmptyStr
    snapshot_version: int = Field(ge=1)
    isolation_key: MemoryIsolationKey = Field(discriminator="kind")
    policy_version: NonEmptyStr
    source_record_versions: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    explicit_hard_constraints: ContractPayload = Field(default_factory=dict)
    session_requirements: ContractPayload = Field(default_factory=dict)
    stable_explicit_preferences: ContractPayload = Field(default_factory=dict)
    inferred_preferences: ContractPayload = Field(default_factory=dict)
    strategy_feedback: ContractPayload = Field(default_factory=dict)
    generated_at: Timestamp


class PersonalizationPolicy(_AuthorityModel):
    """Private policy input that cannot mutate shared identity, facts, or scores."""

    schema_version: Literal["personalization-policy/v1"] = "personalization-policy/v1"
    policy_id: NonEmptyStr
    policy_version: NonEmptyStr
    isolation_key: MemoryIsolationKey = Field(discriminator="kind")
    preference_snapshot_id: NonEmptyStr
    preference_snapshot_version: int = Field(ge=1)
    hard_filters: ContractPayload = Field(default_factory=dict)
    research_depth: str | None = None
    source_priority: tuple[NonEmptyStr, ...] = ()
    selected_source_subset: tuple[NonEmptyStr, ...] = ()
    selected_tool_subset: tuple[NonEmptyStr, ...] = ()
    ranking_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    explanation_refs: tuple[NonEmptyStr, ...] = ()
    mutates_query_family_identity: Literal[False] = False
    mutates_public_evidence: Literal[False] = False
    mutates_public_features: Literal[False] = False
    mutates_public_scores: Literal[False] = False
    public_refresh_influence: Literal[False] = False


class EffectiveCapabilities(_AuthorityModel):
    sources: tuple[NonEmptyStr, ...]
    tools: tuple[NonEmptyStr, ...]


def intersect_personalized_capabilities(
    *,
    pack_sources: set[str],
    authorized_sources: set[str],
    selected_sources: set[str],
    pack_tools: set[str],
    authorized_tools: set[str],
    selected_tools: set[str],
) -> EffectiveCapabilities:
    """Compute Pack allow-list intersect authorization intersect selected subset."""

    return EffectiveCapabilities(
        sources=tuple(sorted(pack_sources & authorized_sources & selected_sources)),
        tools=tuple(sorted(pack_tools & authorized_tools & selected_tools)),
    )


def _key_part(value: str) -> str:
    return quote(value, safe="")


__all__ = [
    "AnonymousIsolationKey",
    "ConsentBasis",
    "ConsentStatus",
    "EffectiveCapabilities",
    "MemoryConsent",
    "MemoryAuthorityWrite",
    "MemoryConversationTurn",
    "MemoryEvent",
    "MemoryIsolationKey",
    "MemoryLayer",
    "MemoryOutboxEvent",
    "MemoryWriteReceipt",
    "MemoryRecord",
    "MemoryStatus",
    "MemorySubject",
    "MemorySubjectKind",
    "MemoryVisibility",
    "PersonalizationPolicy",
    "PreferenceSnapshot",
    "UserIsolationKey",
    "intersect_personalized_capabilities",
    "isolation_key_for",
]
