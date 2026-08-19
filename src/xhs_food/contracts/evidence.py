"""Public query, canonical source, and evidence contract skeletons."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import (
    ContractModel,
    ContractPayload,
    JsonValue,
    NonEmptyStr,
    TimeRange,
    Timestamp,
    VersionedContract,
)
from .errors import ContractError


class CanonicalQuery(VersionedContract):
    """Public semantics only; identity and personal preferences are separate."""

    domain: NonEmptyStr
    geo: JsonValue
    intent: JsonValue
    audience: JsonValue = None
    constraints: ContractPayload = Field(default_factory=dict)
    time_range: TimeRange | None = None
    freshness_policy: JsonValue
    classifier_version: NonEmptyStr


class MediaPolicy(StrEnum):
    REFS_ONLY = "refs_only"
    SELECTED = "selected"


class CollectRequest(VersionedContract):
    query: CanonicalQuery
    source_scope: tuple[str, ...]
    depth: NonEmptyStr
    cursor: str | None = None
    media_policy: MediaPolicy = MediaPolicy.REFS_ONLY


class CanonicalAuthor(ContractModel):
    source_id: NonEmptyStr
    external_id: NonEmptyStr
    canonical_url: str | None = None
    captured_at: Timestamp
    display_name: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalSourceDocument(ContractModel):
    source_id: NonEmptyStr
    external_id: NonEmptyStr
    canonical_url: NonEmptyStr
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    author_external_id: str | None = None
    title: str | None = None
    text: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalSourceComment(ContractModel):
    source_id: NonEmptyStr
    external_id: NonEmptyStr
    document_external_id: NonEmptyStr
    canonical_url: NonEmptyStr
    captured_at: Timestamp
    source_updated_at: Timestamp | None = None
    author_external_id: str | None = None
    text: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalMediaRef(ContractModel):
    source_id: NonEmptyStr
    external_id: NonEmptyStr
    owner_external_id: NonEmptyStr
    owner_type: NonEmptyStr
    canonical_url: NonEmptyStr
    captured_at: Timestamp
    media_type: str | None = None
    attributes: ContractPayload = Field(default_factory=dict)


class CanonicalSourceBatch(VersionedContract):
    """Canonical source metadata; JSON typing intentionally excludes binary."""

    source_id: NonEmptyStr
    documents: tuple[CanonicalSourceDocument, ...] = ()
    comments: tuple[CanonicalSourceComment, ...] = ()
    authors: tuple[CanonicalAuthor, ...] = ()
    media_refs: tuple[CanonicalMediaRef, ...] = ()
    watermark: JsonValue = None
    next_cursor: str | None = None
    errors: tuple[ContractError, ...] = ()


class SourceLocator(VersionedContract):
    source_id: NonEmptyStr
    document_id: NonEmptyStr
    canonical_url: NonEmptyStr
    captured_at: Timestamp
    comment_id: str | None = None
    media_ref_id: str | None = None
    asset_id: str | None = None


class EvidenceItem(VersionedContract):
    evidence_id: NonEmptyStr
    claim_type: NonEmptyStr
    value: JsonValue
    confidence: float = Field(ge=0.0, le=1.0)
    source_locator: SourceLocator
    asset_id: str | None = None
    extractor_version: NonEmptyStr
    visibility: NonEmptyStr
    license_ref: str | None = None
    derived_from: tuple[SourceLocator, ...] = ()


class EvidenceBundle(VersionedContract):
    """Immutable version envelope; activation is owned by a repository adapter."""

    family_id: NonEmptyStr
    version: NonEmptyStr
    parent_version: str | None = None
    evidence_refs: tuple[str, ...]
    coverage: ContractPayload
    watermarks: ContractPayload
    verified_at: Timestamp
    freshness: ContractPayload
    provenance_refs: tuple[str, ...] = ()
    activation_state: NonEmptyStr


__all__ = [
    "CanonicalAuthor",
    "CanonicalMediaRef",
    "CanonicalQuery",
    "CanonicalSourceBatch",
    "CanonicalSourceComment",
    "CanonicalSourceDocument",
    "CollectRequest",
    "EvidenceBundle",
    "EvidenceItem",
    "MediaPolicy",
    "SourceLocator",
]
