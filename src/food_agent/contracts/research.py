"""Contracts for the comment-first Food Research Agent.

The contracts in this module deliberately keep source payloads opaque.  A
provider is allowed to add fields without forcing a release of the Agent;
normalised fields are projections used for reasoning, while ``raw_payload``
is the lossless audit copy used by evidence and refresh jobs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from .account_service import PlatformChannel
from .agent import AgentToolExecutionContext
from .base import ContractModel, ContractPayload, JsonValue, NonEmptyStr, VersionedContract


class ResearchOutcome(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"


class ResearchGap(ContractModel):
    """An explicit, machine-readable loss or provider limitation."""

    source: NonEmptyStr
    operation: NonEmptyStr
    code: NonEmptyStr
    message: str = ""
    retryable: bool = False
    details: ContractPayload = Field(default_factory=dict)


class SourceCall(VersionedContract):
    """One typed MCP invocation result, retaining the provider envelope."""

    source: NonEmptyStr
    operation: NonEmptyStr
    success: bool
    data: JsonValue = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    metadata: ContractPayload = Field(default_factory=dict)
    raw_payload: Any = None


class CommentEvidence(ContractModel):
    """A single comment projected for analysis without dropping source data."""

    source: NonEmptyStr = "xhs"
    note_id: NonEmptyStr
    comment_id: NonEmptyStr
    text: str
    author: ContractPayload = Field(default_factory=dict)
    likes: int = Field(default=0, ge=0)
    replies: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    raw_payload: Any = None
    provenance: ContractPayload = Field(default_factory=dict)
    metadata: ContractPayload = Field(default_factory=dict)


class XhsNoteLead(VersionedContract):
    """A note plus the complete comment evidence observed for that note."""

    note_id: NonEmptyStr
    title: str = ""
    summary: str = ""
    url: str | None = None
    comment_count: int = Field(default=0, ge=0)
    comment_expected_count: int | None = Field(default=None, ge=0)
    comment_collected_count: int = Field(default=0, ge=0)
    comment_has_more: bool | None = None
    comment_cursor: str | None = None
    comment_pages: int = Field(default=0, ge=0)
    comment_completeness: str = "unknown"
    comments: tuple[CommentEvidence, ...] = ()
    queries: tuple[str, ...] = ()
    outcome: ResearchOutcome = ResearchOutcome.COMPLETE
    gaps: tuple[ResearchGap, ...] = ()
    raw_payload: Any = None
    metadata: ContractPayload = Field(default_factory=dict)


class ShopProfile(VersionedContract):
    """Durable, low-frequency shop projection sourced primarily from Dianping."""

    provider_refs: dict[str, str] = Field(default_factory=dict)
    name: NonEmptyStr
    alias: str | None = None
    url: str | None = None
    image_url: str | None = None
    images: tuple[JsonValue, ...] = ()
    address: str | None = None
    city: str | None = None
    district: str | None = None
    region: str | None = None
    business_area: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_system: str | None = None
    geo: ContractPayload = Field(default_factory=dict)
    phone: str | None = None
    rating: float | None = None
    review_count: int | None = Field(default=None, ge=0)
    average_price: float | None = Field(default=None, ge=0)
    category: str | None = None
    opening_hours: str | None = None
    source_url: str | None = None
    recommended_dishes: tuple[str, ...] = ()
    promotions: tuple[JsonValue, ...] = ()
    tags: tuple[str, ...] = ()
    attributes: ContractPayload = Field(default_factory=dict)
    review_completeness: ContractPayload = Field(default_factory=dict)
    source_payload: Any = None
    source_updated_at: datetime | None = None
    fetched_at: datetime | None = None
    outcome: ResearchOutcome = ResearchOutcome.COMPLETE
    gaps: tuple[ResearchGap, ...] = ()


class ResearchRunResult(VersionedContract):
    """Internal workflow result, before transport-specific projection."""

    notes: tuple[XhsNoteLead, ...] = ()
    profiles: tuple[ShopProfile, ...] = ()
    # JSON projections keep this contract independent from the runtime module
    # while making the agent's derived evidence reviewable without opening the
    # opaque raw payload.
    insights: tuple[JsonValue, ...] = ()
    claims: tuple[JsonValue, ...] = ()
    entities: tuple[JsonValue, ...] = ()
    controversies: tuple[JsonValue, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    outcome: ResearchOutcome = ResearchOutcome.COMPLETE
    raw_payload: Any = None


@runtime_checkable
class XhsLeadSourcePort(Protocol):
    async def search_notes(self, **arguments: Any) -> SourceCall: ...

    async def note_detail(self, note_id: str, **arguments: Any) -> SourceCall: ...

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall: ...


@runtime_checkable
class DianpingSourcePort(Protocol):
    async def search_places(self, **arguments: Any) -> SourceCall: ...

    async def place_detail(self, shop_id: str, **arguments: Any) -> SourceCall: ...

    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall: ...


@runtime_checkable
class CommentEvidencePort(Protocol):
    async def record(self, note: XhsNoteLead) -> tuple[str, ...]: ...


@runtime_checkable
class CommentEvidenceLifecyclePort(Protocol):
    """Bridge to the existing canonical Evidence/Bundle lifecycle."""

    async def write(self, note: XhsNoteLead) -> None: ...


@runtime_checkable
class ShopProfileRepositoryPort(Protocol):
    async def find_by_name(self, name: str) -> ShopProfile | None: ...

    async def upsert(self, profile: ShopProfile) -> ShopProfile: ...


@runtime_checkable
class McpSessionPort(Protocol):
    async def open(self, context: AgentToolExecutionContext) -> None: ...

    async def call(
        self,
        platform: PlatformChannel,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> SourceCall: ...

    async def close(self) -> None: ...


__all__ = [
    "CommentEvidence",
    "CommentEvidenceLifecyclePort",
    "CommentEvidencePort",
    "DianpingSourcePort",
    "McpSessionPort",
    "ResearchGap",
    "ResearchOutcome",
    "ResearchRunResult",
    "ShopProfile",
    "ShopProfileRepositoryPort",
    "SourceCall",
    "XhsLeadSourcePort",
    "XhsNoteLead",
]
