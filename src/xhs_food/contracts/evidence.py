"""Domain-neutral canonical query, source, provenance, and evidence contracts."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal, Never, Self

from pydantic import AnyUrl, ConfigDict, Field, JsonValue, field_validator, model_validator

from .base import (
    ContractModel,
    ContractPayload,
    NonEmptyStr,
    Timestamp,
    VersionedContract,
)
from .errors import ContractError

CANONICAL_QUERY_VERSION = "canonical-query/v1"
EVIDENCE_BUNDLE_VERSION = "evidence-bundle/v1"

RegisteredSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
ContractVersion = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_-]*/v[1-9][0-9]*$"),
]
TenantScope = Annotated[
    str,
    Field(pattern=r"^(?:public|tenant:[a-z0-9][a-z0-9_-]{0,63})$"),
]
LanguageTag = Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?$")]
RegionCode = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ObjectRef = Annotated[
    str,
    Field(pattern=r"^s3://[a-z0-9][a-z0-9._-]*/[^\s?#]+$"),
]

_PERSONAL_IDENTITY_FIELDS = frozenset(
    {
        "user_id",
        "session_id",
        "device_id",
        "cohort",
        "preference",
        "preferences",
        "click",
        "clicks",
        "favorite",
        "favorites",
        "memory",
    }
)
_PERSONAL_IDENTITY_FIELD_KEYS = frozenset(
    "".join(character for character in field.casefold() if character.isalnum())
    for field in _PERSONAL_IDENTITY_FIELDS
)
# Access-bearing URL parameters are forbidden without rejecting ordinary canonical URLs.
_CREDENTIAL_URL_PARAMETER = re.compile(
    r"(?:^|[&?])(?:"
    r"(?:[a-z0-9]+[-_.])*(?:signature|credentials?|security[-_.]?token)"
    r"|access[-_.]?key(?:[-_.]?id)?|access[-_.]?token|api[-_.]?key"
    r"|auth|authorization|awsaccesskeyid|googleaccessid"
    r"|key[-_.]?pair[-_.]?id|password|secret|sig|token"
    r")=",
    re.IGNORECASE,
)


class _FrozenDict(dict[str, Any]):
    """JSON-serializable mapping that rejects every in-place mutation."""

    @staticmethod
    def _immutable() -> Never:
        raise TypeError("authority JSON values are immutable")

    def __delitem__(self, key: str) -> Never:
        del key
        self._immutable()

    def __ior__(self, value: object) -> Never:
        del value
        self._immutable()

    def __setitem__(self, key: str, value: Any) -> Never:
        del key, value
        self._immutable()

    def clear(self) -> Never:
        self._immutable()

    def pop(self, key: str, default: Any = None) -> Never:
        del key, default
        self._immutable()

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, key: str, default: Any = None) -> Never:
        del key, default
        self._immutable()

    def update(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        self._immutable()


class _FrozenList(list[Any]):
    """JSON-serializable sequence that rejects every in-place mutation."""

    @staticmethod
    def _immutable() -> Never:
        raise TypeError("authority JSON values are immutable")

    def __delitem__(self, key: object) -> Never:
        del key
        self._immutable()

    def __iadd__(self, value: object) -> Never:
        del value
        self._immutable()

    def __imul__(self, value: object) -> Never:
        del value
        self._immutable()

    def __setitem__(self, key: object, value: object) -> Never:
        del key, value
        self._immutable()

    def append(self, value: Any) -> Never:
        del value
        self._immutable()

    def clear(self) -> Never:
        self._immutable()

    def extend(self, values: object) -> Never:
        del values
        self._immutable()

    def insert(self, index: object, value: Any) -> Never:
        del index, value
        self._immutable()

    def pop(self, index: object = -1) -> Never:
        del index
        self._immutable()

    def remove(self, value: Any) -> Never:
        del value
        self._immutable()

    def reverse(self) -> Never:
        self._immutable()

    def sort(self, *, key: Any = None, reverse: bool = False) -> Never:
        del key, reverse
        self._immutable()


def _validate_authority_value(value: object, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains NaN or Infinity")
    if isinstance(value, AnyUrl):
        _ensure_persistable_url(value, path)
        return
    if isinstance(value, datetime):
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{path} must use UTC RFC 3339 time")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_authority_value(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_authority_value(item, f"{path}[{index}]")


def _freeze_authority_value(value: object) -> object:
    if isinstance(value, AuthorityModel):
        return value
    if isinstance(value, Mapping):
        return _FrozenDict(
            {str(key): _freeze_authority_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenList(_freeze_authority_value(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_authority_value(item) for item in value)
    return value


class AuthorityModel(ContractModel):
    """Strict immutable value object used by accepted authority schemas."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        use_enum_values=False,
    )

    @model_validator(mode="after")
    def validate_and_freeze_authority_value(self) -> Self:
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            _validate_authority_value(value, field_name)
            object.__setattr__(self, field_name, _freeze_authority_value(value))
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through full validation so updates cannot bypass authority gates."""

        del deep
        payload = self.model_dump(mode="python", round_trip=True)
        payload.update(update or {})
        return type(self).model_validate(payload)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ensure_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


def _ensure_canonical_strings(value: JsonValue, path: str = "query") -> None:
    if isinstance(value, str):
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        if value != normalized:
            raise ValueError(f"{path} contains a non-canonical string")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _ensure_canonical_strings(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_personal_identity_field(key):
                raise ValueError(f"{path} contains forbidden personal field {key!r}")
            _ensure_canonical_strings(item, f"{path}.{key}")


def _is_personal_identity_field(field: str) -> bool:
    normalized = "".join(character for character in field.casefold() if character.isalnum())
    return normalized in _PERSONAL_IDENTITY_FIELD_KEYS


def _ensure_no_personal_fields(value: JsonValue, path: str) -> None:
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _ensure_no_personal_fields(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_personal_identity_field(key):
                raise ValueError(f"{path} contains forbidden personal field {key!r}")
            _ensure_no_personal_fields(item, f"{path}.{key}")


def _ensure_persistable_url(value: AnyUrl, path: str) -> None:
    if value.username is not None or value.password is not None:
        raise ValueError(f"{path} must not contain embedded credentials")
    if any(
        part is not None and _CREDENTIAL_URL_PARAMETER.search(part)
        for part in (value.query, value.fragment)
    ):
        raise ValueError(f"{path} must not contain signed URL or credential parameters")


def _ensure_stable_media_url(value: AnyUrl, path: str) -> None:
    _ensure_persistable_url(value, path)
    if value.query is not None or value.fragment is not None:
        raise ValueError(f"{path} must not contain query parameters or fragments")


class IsolationCoordinates(AuthorityModel):
    """Partition coordinates that may never be crossed by Family or Evidence reuse."""

    tenant_scope: TenantScope
    language: LanguageTag
    region: RegionCode


class CanonicalGeo(AuthorityModel):
    country_code: RegionCode
    admin_path: tuple[RegisteredSlug, ...] = Field(max_length=8)
    locality: RegisteredSlug

    @model_validator(mode="after")
    def validate_admin_path(self) -> Self:
        _ensure_unique(self.admin_path, "admin_path")
        return self


class IntentKind(StrEnum):
    DISCOVER = "discover"
    RECOMMEND = "recommend"
    COMPARE = "compare"
    VERIFY = "verify"
    PLAN = "plan"


class CanonicalIntent(AuthorityModel):
    kind: IntentKind
    subject: RegisteredSlug


class ConstraintOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    RANGE = "range"
    EXISTS = "exists"


class PublicConstraint(AuthorityModel):
    key: RegisteredSlug
    operator: ConstraintOperator
    value: JsonValue
    classification_rule: RegisteredSlug

    @model_validator(mode="after")
    def validate_public_value(self) -> Self:
        if _is_personal_identity_field(self.key):
            raise ValueError("personal identity cannot be a public constraint")
        if isinstance(self.value, Mapping):
            raise ValueError("public constraint values cannot be objects")
        if isinstance(self.value, (list, tuple)):
            if not self.value:
                raise ValueError("public constraint arrays cannot be empty")
            if any(
                isinstance(item, (Mapping, list, tuple)) or item is None
                for item in self.value
            ):
                raise ValueError("public constraint arrays must contain JSON scalars")
            encoded = tuple(_canonical_json(item) for item in self.value)
            _ensure_unique(encoded, "public constraint array")
            if encoded != tuple(sorted(encoded)):
                raise ValueError("public constraint arrays must use canonical order")
        return self


class CanonicalTimeRangeKind(StrEnum):
    ANY = "any"
    CURRENT = "current"
    INTERVAL = "interval"
    SEASON = "season"


class CanonicalTimeRange(AuthorityModel):
    kind: CanonicalTimeRangeKind
    start: Timestamp | None
    end: Timestamp | None
    timezone: Annotated[
        str,
        Field(pattern=r"^(?:Etc/UTC|[A-Za-z_]+/[A-Za-z_+-]+)$"),
    ]

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("time range start must not be after end")
        if self.kind is CanonicalTimeRangeKind.INTERVAL and (
            self.start is None or self.end is None
        ):
            raise ValueError("interval time ranges require start and end")
        return self


class FreshnessPolicyRef(AuthorityModel):
    policy_id: RegisteredSlug
    policy_version: ContractVersion


class CanonicalQueryValue(AuthorityModel):
    """The seven public query fields fixed by canonical-query/v1."""

    domain: RegisteredSlug
    geo: CanonicalGeo
    intent: CanonicalIntent
    audience: tuple[RegisteredSlug, ...]
    constraints: tuple[PublicConstraint, ...]
    time_range: CanonicalTimeRange
    freshness_policy: FreshnessPolicyRef

    @model_validator(mode="after")
    def validate_set_like_fields(self) -> Self:
        _ensure_unique(self.audience, "audience")
        if self.audience != tuple(sorted(self.audience)):
            raise ValueError("audience must use stable canonical order")

        constraints = tuple(
            _canonical_json(item.model_dump(mode="json")) for item in self.constraints
        )
        _ensure_unique(constraints, "constraints")
        if constraints != tuple(sorted(constraints)):
            raise ValueError("constraints must use stable canonical order")
        return self


class CanonicalQuery(AuthorityModel):
    """Canonical public semantics with explicit normalization and isolation versions."""

    schema_version: Literal["canonical-query/v1"] = CANONICAL_QUERY_VERSION
    normalizer_version: ContractVersion
    classifier_version: ContractVersion
    isolation: IsolationCoordinates
    query: CanonicalQueryValue

    @model_validator(mode="after")
    def validate_canonical_content(self) -> Self:
        _ensure_canonical_strings(self.model_dump(mode="json"))
        return self

    def family_identity_projection(self) -> dict[str, JsonValue]:
        """Return the accepted deterministic Family preimage without audience."""

        query = self.query.model_dump(mode="json")
        query.pop("audience")
        return {
            "isolation": self.isolation.model_dump(mode="json"),
            "query": query,
        }


class MediaPolicy(StrEnum):
    REFS_ONLY = "refs_only"
    SELECTED = "selected"


class CollectRequest(VersionedContract):
    """A connector-neutral collection command pinned to one canonical partition."""

    query: CanonicalQuery
    source_scope: tuple[RegisteredSlug, ...] = Field(min_length=1)
    depth: RegisteredSlug
    cursor: str | None = None
    media_policy: MediaPolicy = MediaPolicy.REFS_ONLY

    @model_validator(mode="after")
    def validate_source_scope(self) -> Self:
        _ensure_unique(self.source_scope, "source_scope")
        return self


class MediaType(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class CanonicalAuthor(AuthorityModel):
    source_id: RegisteredSlug
    external_id: NonEmptyStr
    canonical_url: AnyUrl
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    display_name: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalSourceDocument(AuthorityModel):
    source_id: RegisteredSlug
    external_id: NonEmptyStr
    canonical_url: AnyUrl
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    author_external_id: str | None = None
    title: str | None = None
    text: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalSourceComment(AuthorityModel):
    source_id: RegisteredSlug
    external_id: NonEmptyStr
    document_external_id: NonEmptyStr
    canonical_url: AnyUrl
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    author_external_id: str | None = None
    text: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalMediaRef(AuthorityModel):
    source_id: RegisteredSlug
    external_id: NonEmptyStr
    owner_external_id: NonEmptyStr
    owner_type: RegisteredSlug
    canonical_url: AnyUrl
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    media_type: MediaType
    attributes: ContractPayload = Field(default_factory=dict)

    @field_validator("canonical_url")
    @classmethod
    def validate_stable_media_url(cls, value: AnyUrl) -> AnyUrl:
        _ensure_stable_media_url(value, "canonical_url")
        return value


class CanonicalSourceBatch(VersionedContract):
    """Normalized source metadata; JSON typing intentionally excludes binary data."""

    isolation: IsolationCoordinates
    source_id: RegisteredSlug
    connector_id: RegisteredSlug
    connector_version: ContractVersion
    normalizer_version: ContractVersion
    documents: tuple[CanonicalSourceDocument, ...] = ()
    comments: tuple[CanonicalSourceComment, ...] = ()
    authors: tuple[CanonicalAuthor, ...] = ()
    media_refs: tuple[CanonicalMediaRef, ...] = ()
    watermark: str | None
    next_cursor: str | None = None
    errors: tuple[ContractError, ...] = ()

    @model_validator(mode="after")
    def validate_source_partition(self) -> Self:
        items = (*self.documents, *self.comments, *self.authors, *self.media_refs)
        if any(item.source_id != self.source_id for item in items):
            raise ValueError("all canonical source items must match the batch source_id")
        for name, entries in (
            ("documents", self.documents),
            ("comments", self.comments),
            ("authors", self.authors),
            ("media_refs", self.media_refs),
        ):
            _ensure_unique(tuple(item.external_id for item in entries), name)
        return self


class VisibilityScope(StrEnum):
    PUBLIC = "public"
    TENANT = "tenant"
    ENTITLEMENT = "entitlement"


class EvidenceVisibility(AuthorityModel):
    scope: VisibilityScope
    tenant_scope: TenantScope
    entitlement_ids: tuple[RegisteredSlug, ...]

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        _ensure_unique(self.entitlement_ids, "entitlement_ids")
        if self.scope is VisibilityScope.PUBLIC:
            if self.tenant_scope != "public" or self.entitlement_ids:
                raise ValueError("public visibility cannot carry tenant or entitlement scope")
        elif self.scope is VisibilityScope.TENANT:
            if self.tenant_scope == "public" or self.entitlement_ids:
                raise ValueError("tenant visibility requires one tenant and no entitlements")
        elif not self.entitlement_ids:
            raise ValueError("entitlement visibility requires entitlement_ids")
        return self


class LicenseStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REVOKED = "revoked"


class LicenseUse(StrEnum):
    EXTRACT_ONLY = "extract_only"
    INTERNAL_REUSE = "internal_reuse"
    REDISTRIBUTABLE = "redistributable"


class EvidenceLicense(AuthorityModel):
    license_id: NonEmptyStr
    status: LicenseStatus
    allowed_use: LicenseUse
    attribution_required: bool
    expires_at: Timestamp | None
    policy_version: ContractVersion


class RetentionPolicy(AuthorityModel):
    """A missing duration remains explicit; the contract invents no retention value."""

    retention_class: RegisteredSlug
    duration_seconds: int | None = Field(ge=0)
    legal_hold: bool


class SourceLocator(AuthorityModel):
    locator_id: RegisteredSlug
    source_id: RegisteredSlug
    connector_id: RegisteredSlug
    connector_version: ContractVersion
    external_id: NonEmptyStr
    canonical_url: AnyUrl
    captured_at: Timestamp
    source_updated_at: Timestamp | None
    watermark: str | None
    visibility: EvidenceVisibility
    license: EvidenceLicense
    retention: RetentionPolicy


class MediaRef(AuthorityModel):
    """An unfetched source reference; it never contains bytes or access credentials."""

    media_ref_id: RegisteredSlug
    locator_id: RegisteredSlug
    media_type: MediaType
    source_url: AnyUrl
    declared_content_type: str | None
    declared_sha256: Sha256 | None

    @field_validator("source_url")
    @classmethod
    def validate_stable_media_url(cls, value: AnyUrl) -> AnyUrl:
        _ensure_stable_media_url(value, "source_url")
        return value


class DerivedArtifact(AuthorityModel):
    """Metadata for derived bytes held behind the shared ObjectStore port."""

    artifact_id: RegisteredSlug
    object_ref: ObjectRef
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    content_type: NonEmptyStr
    processor_id: RegisteredSlug
    processor_version: ContractVersion
    input_refs: tuple[RegisteredSlug, ...] = Field(min_length=1)
    created_at: Timestamp
    visibility: EvidenceVisibility
    license: EvidenceLicense
    retention: RetentionPolicy

    @model_validator(mode="after")
    def validate_input_refs(self) -> Self:
        _ensure_unique(self.input_refs, "input_refs")
        if self.artifact_id in self.input_refs:
            raise ValueError("derived artifacts cannot directly reference themselves")
        return self


class EvidenceStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    TOMBSTONED = "tombstoned"


class EvidenceItem(AuthorityModel):
    evidence_id: RegisteredSlug
    evidence_type: RegisteredSlug
    claim_type: RegisteredSlug
    claim_value: JsonValue
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    source_locator_id: RegisteredSlug
    media_ref_ids: tuple[RegisteredSlug, ...]
    derived_artifact_ids: tuple[RegisteredSlug, ...]
    extractor_version: ContractVersion
    schema_version: ContractVersion
    content_hash: Sha256
    status: EvidenceStatus
    visibility: EvidenceVisibility
    license: EvidenceLicense
    retention: RetentionPolicy

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        _ensure_unique(self.media_ref_ids, "media_ref_ids")
        _ensure_unique(self.derived_artifact_ids, "derived_artifact_ids")
        _ensure_no_personal_fields(self.claim_value, "claim_value")
        return self


class BundleState(StrEnum):
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    REJECTED = "rejected"
    TOMBSTONED = "tombstoned"


class EvidenceBundle(AuthorityModel):
    """One immutable candidate or historical Bundle version; pointers live elsewhere."""

    bundle_id: RegisteredSlug
    family_id: RegisteredSlug
    bundle_version: int = Field(ge=1)
    parent_bundle_version: int | None = Field(ge=1)
    state: BundleState
    evidence_ids: tuple[RegisteredSlug, ...] = Field(min_length=1)
    coverage: dict[RegisteredSlug, Annotated[float, Field(ge=0.0, le=1.0)]]
    watermarks: dict[RegisteredSlug, str]
    verified_at: Timestamp
    freshness_policy_id: RegisteredSlug
    freshness_policy_version: ContractVersion
    provenance_hash: Sha256
    content_hash: Sha256
    visibility: EvidenceVisibility
    retention: RetentionPolicy

    @model_validator(mode="after")
    def validate_version_lineage(self) -> Self:
        _ensure_unique(self.evidence_ids, "evidence_ids")
        if self.parent_bundle_version is not None:
            if self.parent_bundle_version >= self.bundle_version:
                raise ValueError("parent_bundle_version must precede bundle_version")
        elif self.bundle_version != 1:
            raise ValueError("only the initial Bundle version may omit its parent")
        return self


class DeletionGovernance(AuthorityModel):
    request_is_idempotent: Literal[True]
    uses_tombstone: Literal[True]
    replacement_candidate_required: Literal[True]
    cleanup_is_async_and_idempotent: Literal[True]
    legal_hold_blocks_bytes_delete: Literal[True]
    metadata_authority: Literal["postgresql"]


class EvidenceGovernance(AuthorityModel):
    visibility_scopes: tuple[VisibilityScope, ...]
    license_use: tuple[LicenseUse, ...]
    deletion: DeletionGovernance

    @model_validator(mode="after")
    def validate_authority_constants(self) -> Self:
        if self.visibility_scopes != tuple(VisibilityScope):
            raise ValueError("visibility_scopes must match evidence-bundle/v1")
        if self.license_use != tuple(LicenseUse):
            raise ValueError("license_use must match evidence-bundle/v1")
        return self


def _visibility_is_at_least_as_restrictive(
    candidate: EvidenceVisibility,
    source: EvidenceVisibility,
) -> bool:
    rank = {
        VisibilityScope.PUBLIC: 0,
        VisibilityScope.TENANT: 1,
        VisibilityScope.ENTITLEMENT: 2,
    }
    if rank[candidate.scope] < rank[source.scope]:
        return False
    if (
        source.scope is not VisibilityScope.PUBLIC
        and candidate.tenant_scope != source.tenant_scope
    ):
        return False
    if source.scope is VisibilityScope.ENTITLEMENT:
        return set(candidate.entitlement_ids).issubset(source.entitlement_ids)
    return True


def _license_is_at_least_as_restrictive(
    candidate: EvidenceLicense,
    source: EvidenceLicense,
) -> bool:
    rank = {
        LicenseUse.EXTRACT_ONLY: 0,
        LicenseUse.INTERNAL_REUSE: 1,
        LicenseUse.REDISTRIBUTABLE: 2,
    }
    if candidate.status is not source.status:
        return False
    if rank[candidate.allowed_use] > rank[source.allowed_use]:
        return False
    if source.attribution_required and not candidate.attribution_required:
        return False
    return not source.expires_at or not (
        candidate.expires_at is None or candidate.expires_at > source.expires_at
    )


def _retention_is_at_least_as_restrictive(
    candidate: RetentionPolicy,
    source: RetentionPolicy,
) -> bool:
    if source.legal_hold and not candidate.legal_hold:
        return False
    if source.duration_seconds is None:
        return candidate.duration_seconds is None
    return candidate.duration_seconds is None or (
        candidate.duration_seconds >= source.duration_seconds
    )


def _governance_is_at_least_as_restrictive(
    candidate: SourceLocator | DerivedArtifact | EvidenceItem,
    source: SourceLocator | DerivedArtifact | EvidenceItem,
) -> bool:
    return (
        _visibility_is_at_least_as_restrictive(candidate.visibility, source.visibility)
        and _license_is_at_least_as_restrictive(candidate.license, source.license)
        and _retention_is_at_least_as_restrictive(candidate.retention, source.retention)
    )


def _license_is_publishable(license: EvidenceLicense, verified_at: Timestamp) -> bool:
    return license.status is LicenseStatus.KNOWN and (
        license.expires_at is None or license.expires_at > verified_at
    )


class EvidenceBundleManifest(AuthorityModel):
    """The evidence-bundle/v1 aggregate used to validate publication atomically."""

    schema_version: Literal["evidence-bundle/v1"] = EVIDENCE_BUNDLE_VERSION
    isolation: IsolationCoordinates
    governance: EvidenceGovernance
    source_locators: tuple[SourceLocator, ...]
    media_refs: tuple[MediaRef, ...]
    derived_artifacts: tuple[DerivedArtifact, ...]
    evidence_items: tuple[EvidenceItem, ...]
    bundles: tuple[EvidenceBundle, ...]

    @model_validator(mode="after")
    def validate_graph_and_publication(self) -> Self:
        locators = {item.locator_id: item for item in self.source_locators}
        media = {item.media_ref_id: item for item in self.media_refs}
        artifacts = {item.artifact_id: item for item in self.derived_artifacts}
        evidence = {item.evidence_id: item for item in self.evidence_items}
        bundles = {item.bundle_id: item for item in self.bundles}
        collections = (
            ("source_locators", locators, self.source_locators),
            ("media_refs", media, self.media_refs),
            ("derived_artifacts", artifacts, self.derived_artifacts),
            ("evidence_items", evidence, self.evidence_items),
            ("bundles", bundles, self.bundles),
        )
        for name, indexed, original in collections:
            if len(indexed) != len(original):
                raise ValueError(f"{name} must have unique identities")

        governed = (
            *self.source_locators,
            *self.derived_artifacts,
            *self.evidence_items,
            *self.bundles,
        )
        for item in governed:
            visibility = item.visibility
            if visibility.scope is VisibilityScope.PUBLIC:
                continue
            if visibility.tenant_scope != self.isolation.tenant_scope:
                raise ValueError("restricted evidence must match the isolation tenant_scope")

        for ref in self.media_refs:
            if ref.locator_id not in locators:
                raise ValueError(f"media ref {ref.media_ref_id!r} has no source locator")

        known_inputs = set(media) | set(artifacts)
        for artifact in self.derived_artifacts:
            missing = set(artifact.input_refs) - known_inputs
            if missing:
                raise ValueError(f"artifact {artifact.artifact_id!r} has missing inputs")
            for input_ref in artifact.input_refs:
                if input_ref in media:
                    source = locators[media[input_ref].locator_id]
                else:
                    source = artifacts[input_ref]
                if not _governance_is_at_least_as_restrictive(artifact, source):
                    raise ValueError("derived artifacts cannot broaden input governance")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit_artifact(artifact_id: str) -> None:
            if artifact_id in visiting:
                raise ValueError("derived artifact lineage must be acyclic")
            if artifact_id in visited:
                return
            visiting.add(artifact_id)
            for input_ref in artifacts[artifact_id].input_refs:
                if input_ref in artifacts:
                    visit_artifact(input_ref)
            visiting.remove(artifact_id)
            visited.add(artifact_id)

        for artifact_id in artifacts:
            visit_artifact(artifact_id)

        def artifact_provenance(artifact_id: str) -> list[SourceLocator | DerivedArtifact]:
            artifact = artifacts[artifact_id]
            result: list[SourceLocator | DerivedArtifact] = [artifact]
            for input_ref in artifact.input_refs:
                if input_ref in media:
                    result.append(locators[media[input_ref].locator_id])
                else:
                    result.extend(artifact_provenance(input_ref))
            return result

        for item in self.evidence_items:
            locator = locators.get(item.source_locator_id)
            if locator is None:
                raise ValueError(f"evidence {item.evidence_id!r} has no source locator")
            if set(item.media_ref_ids) - set(media):
                raise ValueError(f"evidence {item.evidence_id!r} has missing media refs")
            if set(item.derived_artifact_ids) - set(artifacts):
                raise ValueError(f"evidence {item.evidence_id!r} has missing artifacts")

            inputs = [
                locator,
                *(locators[media[ref].locator_id] for ref in item.media_ref_ids),
                *(artifacts[ref] for ref in item.derived_artifact_ids),
            ]
            for source in inputs:
                if not _governance_is_at_least_as_restrictive(item, source):
                    raise ValueError("evidence cannot broaden provenance governance")

        for bundle in self.bundles:
            referenced = [evidence.get(ref) for ref in bundle.evidence_ids]
            if any(item is None for item in referenced):
                raise ValueError(f"bundle {bundle.bundle_id!r} has missing evidence")
            if bundle.state is not BundleState.PUBLISHED:
                continue
            for item in referenced:
                assert item is not None
                if item.status is not EvidenceStatus.ACCEPTED:
                    raise ValueError("published Bundles may contain only accepted Evidence")
                locator = locators[item.source_locator_id]
                direct_media_inputs = [
                    locators[media[ref].locator_id] for ref in item.media_ref_ids
                ]
                artifact_inputs = [
                    source
                    for ref in item.derived_artifact_ids
                    for source in artifact_provenance(ref)
                ]
                if not all(
                    _license_is_publishable(source.license, bundle.verified_at)
                    for source in (
                        locator,
                        *direct_media_inputs,
                        *artifact_inputs,
                        item,
                    )
                ):
                    raise ValueError("published Bundles require known, unexpired licenses")
                if not _visibility_is_at_least_as_restrictive(
                    bundle.visibility, item.visibility
                ):
                    raise ValueError("Bundles cannot broaden Evidence visibility")
                if not _retention_is_at_least_as_restrictive(
                    bundle.retention, item.retention
                ):
                    raise ValueError("Bundles cannot shorten Evidence retention")
        return self


__all__ = [
    "CANONICAL_QUERY_VERSION",
    "EVIDENCE_BUNDLE_VERSION",
    "AuthorityModel",
    "BundleState",
    "CanonicalAuthor",
    "CanonicalGeo",
    "CanonicalIntent",
    "CanonicalMediaRef",
    "CanonicalQuery",
    "CanonicalQueryValue",
    "CanonicalSourceBatch",
    "CanonicalSourceComment",
    "CanonicalSourceDocument",
    "CanonicalTimeRange",
    "CanonicalTimeRangeKind",
    "CollectRequest",
    "ConstraintOperator",
    "ContractVersion",
    "DeletionGovernance",
    "DerivedArtifact",
    "EvidenceBundle",
    "EvidenceBundleManifest",
    "EvidenceGovernance",
    "EvidenceItem",
    "EvidenceLicense",
    "EvidenceStatus",
    "EvidenceVisibility",
    "FreshnessPolicyRef",
    "IntentKind",
    "IsolationCoordinates",
    "LicenseStatus",
    "LicenseUse",
    "MediaPolicy",
    "MediaRef",
    "MediaType",
    "PublicConstraint",
    "RegisteredSlug",
    "RetentionPolicy",
    "SourceLocator",
    "VisibilityScope",
]
