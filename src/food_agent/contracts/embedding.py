"""Versioned embedding profile and replayable backfill contracts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyStr
from .evidence import ContractVersion, RegisteredSlug

EMBEDDING_PROFILE_VERSION = "embedding-profile/v1"
BACKFILL_CURSOR_VERSION = "embedding-backfill-cursor/v1"


class EmbeddingDistance(StrEnum):
    COSINE = "cosine"


class EmbeddingProfile(ContractModel):
    """Immutable model/index identity; incompatible profiles never share a column."""

    schema_version: Literal["embedding-profile/v1"] = EMBEDDING_PROFILE_VERSION
    profile_id: RegisteredSlug
    model_id: RegisteredSlug
    model_version: ContractVersion
    dimensions: int = Field(ge=1, le=16_384)
    distance: EmbeddingDistance = EmbeddingDistance.COSINE
    normalized: Literal[True] = True


BGE_M3_PROFILE_V1 = EmbeddingProfile(
    profile_id="profile_v1",
    model_id="bge-m3",
    model_version="bge-m3/v1",
    dimensions=1024,
)


class BackfillRow(ContractModel):
    """Stable source identity and content hash used by a replayable page."""

    source_key: NonEmptyStr
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EmbeddingBackfillCursor(ContractModel):
    """A committed cursor can be replayed after interruption without skipping rows."""

    schema_version: Literal["embedding-backfill-cursor/v1"] = BACKFILL_CURSOR_VERSION
    profile_id: RegisteredSlug
    source_relation: NonEmptyStr
    last_source_key: str | None = None
    processed_rows: int = Field(default=0, ge=0)
    content_hash: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    last_batch_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile_and_cursor(self) -> Self:
        if self.profile_id != BGE_M3_PROFILE_V1.profile_id:
            raise ValueError("unknown embedding profile for B1 backfill")
        if self.last_source_key is None and self.last_batch_hash is not None:
            raise ValueError("a batch hash requires a last source key")
        return self


@dataclass(frozen=True, slots=True)
class EmbeddingShadowRow:
    """Profile-aware row crossing the repository/service boundary."""

    canonical_key: str
    profile_id: str
    vector: tuple[float, ...]
    content_hash: str
    generated_at: datetime


class EmbeddingShadowRepository(Protocol):
    async def put_embedding(
        self,
        canonical_key: str,
        profile: EmbeddingProfile,
        vector: tuple[float, ...],
        content_hash: str,
        generated_at: datetime,
    ) -> None: ...

    async def get_embedding(
        self, canonical_key: str, profile: EmbeddingProfile
    ) -> EmbeddingShadowRow | None: ...

    async def load_backfill_cursor(
        self, profile: EmbeddingProfile
    ) -> EmbeddingBackfillCursor | None: ...

    async def save_backfill_cursor(self, cursor: EmbeddingBackfillCursor) -> None: ...


def initial_backfill_cursor(
    profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    *,
    source_relation: str = "canonical_queries",
) -> EmbeddingBackfillCursor:
    if profile != BGE_M3_PROFILE_V1:
        raise ValueError("B1 backfill is pinned to bge-m3/profile_v1")
    return EmbeddingBackfillCursor(profile_id=profile.profile_id, source_relation=source_relation)


def advance_backfill_cursor(
    cursor: EmbeddingBackfillCursor,
    rows: tuple[BackfillRow, ...],
) -> EmbeddingBackfillCursor:
    """Advance a cursor in source-key order, treating the same page as idempotent."""

    if not rows:
        return cursor
    keys = tuple(row.source_key for row in rows)
    if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
        raise ValueError("backfill rows must be sorted by unique source_key")
    page_hash = hashlib.sha256(
        json.dumps(
            [row.model_dump(mode="json") for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if cursor.last_batch_hash == page_hash:
        return cursor
    if cursor.last_source_key is not None and keys[0] <= cursor.last_source_key:
        raise ValueError("backfill page overlaps the committed cursor")
    chained_hash = hashlib.sha256(f"{cursor.content_hash}:{page_hash}".encode("ascii")).hexdigest()
    return cursor.model_copy(
        update={
            "last_source_key": keys[-1],
            "processed_rows": cursor.processed_rows + len(rows),
            "content_hash": chained_hash,
            "last_batch_hash": page_hash,
        }
    )


def validate_embedding_vector(profile: EmbeddingProfile, values: tuple[float, ...]) -> None:
    if len(values) != profile.dimensions:
        raise ValueError(
            f"embedding dimension mismatch for {profile.profile_id}: "
            f"expected {profile.dimensions}, got {len(values)}"
        )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding vector contains a non-finite value")


__all__ = [
    "BACKFILL_CURSOR_VERSION",
    "BGE_M3_PROFILE_V1",
    "EMBEDDING_PROFILE_VERSION",
    "BackfillRow",
    "EmbeddingBackfillCursor",
    "EmbeddingDistance",
    "EmbeddingProfile",
    "EmbeddingShadowRepository",
    "EmbeddingShadowRow",
    "advance_backfill_cursor",
    "initial_backfill_cursor",
    "validate_embedding_vector",
]
