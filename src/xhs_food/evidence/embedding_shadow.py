"""Profile-pinned embedding dual-write, backfill, and shadow-read helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BackfillRow,
    EmbeddingBackfillCursor,
    EmbeddingProfile,
    EmbeddingShadowRepository,
    EmbeddingShadowRow,
    advance_backfill_cursor,
    initial_backfill_cursor,
    validate_embedding_vector,
)


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillInput:
    source_key: str
    content: str
    content_hash: str


class EmbeddingCompareStatus(StrEnum):
    MATCH = "match"
    MISSING = "missing"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class EmbeddingShadowComparison:
    canonical_key: str
    profile_id: str
    status: EmbeddingCompareStatus
    expected_content_hash: str
    stored_content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileBackfillQuality:
    """Bounded quality receipt required before activating a read profile."""

    profile_id: str
    profile_version: str
    expected_rows: int
    indexed_rows: int
    minimum_coverage: float

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_version:
            raise ValueError("profile backfill quality requires a profile identity")
        if self.expected_rows < 0 or self.indexed_rows < 0:
            raise ValueError("profile backfill row counts must be non-negative")
        if self.indexed_rows > self.expected_rows:
            raise ValueError("indexed profile rows cannot exceed expected rows")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError("minimum profile coverage must be between 0 and 1")

    @property
    def coverage(self) -> float:
        if self.expected_rows == 0:
            return 1.0
        return self.indexed_rows / self.expected_rows

    @property
    def passed(self) -> bool:
        return self.coverage >= self.minimum_coverage


class EmbeddingProducer(Protocol):
    async def embed(self, content: str, profile: EmbeddingProfile) -> tuple[float, ...]: ...


class EmbeddingShadowService:
    """Keep the new profile write-only until an explicit read canary exists."""

    def __init__(
        self,
        repository: EmbeddingShadowRepository,
        *,
        profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    ) -> None:
        if profile != BGE_M3_PROFILE_V1:
            raise ValueError("B1 shadow embeddings are pinned to bge-m3/profile_v1")
        self._repository = repository
        self._profile = profile

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def dual_write(
        self,
        canonical_key: str,
        content: str,
        producer: EmbeddingProducer,
    ) -> EmbeddingShadowRow:
        content_hash = _content_hash(content)
        vector = await producer.embed(content, self._profile)
        validate_embedding_vector(self._profile, vector)
        generated_at = datetime.now(UTC)
        await self._repository.put_embedding(
            canonical_key,
            self._profile,
            vector,
            content_hash,
            generated_at,
        )
        return EmbeddingShadowRow(
            canonical_key=canonical_key,
            profile_id=self._profile.profile_id,
            vector=vector,
            content_hash=content_hash,
            generated_at=generated_at,
        )

    async def backfill(
        self,
        rows: tuple[EmbeddingBackfillInput, ...],
        producer: EmbeddingProducer,
    ) -> EmbeddingBackfillCursor:
        cursor = await self._repository.load_backfill_cursor(self._profile)
        if cursor is None:
            cursor = initial_backfill_cursor(self._profile)
        backfill_rows = tuple(
            BackfillRow(source_key=row.source_key, content_hash=row.content_hash) for row in rows
        )
        next_cursor = advance_backfill_cursor(cursor, backfill_rows)
        if next_cursor == cursor:
            return cursor
        for row in rows:
            if _content_hash(row.content) != row.content_hash:
                raise ValueError(f"backfill content hash mismatch for {row.source_key}")
        for row in rows:
            await self.dual_write(row.source_key, row.content, producer)
        await self._repository.save_backfill_cursor(next_cursor)
        return next_cursor

    async def shadow_read_compare(
        self, canonical_key: str, content: str
    ) -> EmbeddingShadowComparison:
        expected_hash = _content_hash(content)
        row = await self._repository.get_embedding(canonical_key, self._profile)
        if row is None:
            return EmbeddingShadowComparison(
                canonical_key=canonical_key,
                profile_id=self._profile.profile_id,
                status=EmbeddingCompareStatus.MISSING,
                expected_content_hash=expected_hash,
            )
        if row.profile_id != self._profile.profile_id:
            raise ValueError("embedding shadow read returned a mismatched profile")
        return EmbeddingShadowComparison(
            canonical_key=canonical_key,
            profile_id=self._profile.profile_id,
            status=(
                EmbeddingCompareStatus.MATCH
                if row.content_hash == expected_hash
                else EmbeddingCompareStatus.MISMATCH
            ),
            expected_content_hash=expected_hash,
            stored_content_hash=row.content_hash,
        )


class ProfileBackfillService:
    """Run a resumable profile backfill and issue a quality receipt."""

    def __init__(
        self,
        repository: EmbeddingShadowRepository,
        *,
        profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    ) -> None:
        self._service = EmbeddingShadowService(repository, profile=profile)
        self._repository = repository
        self._profile = profile

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def backfill(
        self,
        rows: tuple[EmbeddingBackfillInput, ...],
        producer: EmbeddingProducer,
        *,
        minimum_coverage: float = 1.0,
    ) -> tuple[EmbeddingBackfillCursor, ProfileBackfillQuality]:
        if not 0.0 <= minimum_coverage <= 1.0:
            raise ValueError("minimum profile coverage must be between 0 and 1")
        cursor = await self._service.backfill(rows, producer)
        indexed = 0
        for row in rows:
            stored = await self._repository.get_embedding(row.source_key, self._profile)
            if stored is not None and stored.content_hash == row.content_hash:
                indexed += 1
        quality = ProfileBackfillQuality(
            profile_id=self._profile.profile_id,
            profile_version=self._profile.model_version,
            expected_rows=len(rows),
            indexed_rows=indexed,
            minimum_coverage=minimum_coverage,
        )
        if not quality.passed:
            raise ValueError(
                f"profile backfill coverage {quality.coverage:.3f} is below "
                f"{quality.minimum_coverage:.3f}"
            )
        return cursor, quality


def _content_hash(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("embedding content must be non-empty text")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "EmbeddingBackfillInput",
    "EmbeddingCompareStatus",
    "EmbeddingProducer",
    "EmbeddingShadowComparison",
    "ProfileBackfillQuality",
    "ProfileBackfillService",
    "EmbeddingShadowRepository",
    "EmbeddingShadowRow",
    "EmbeddingShadowService",
]
