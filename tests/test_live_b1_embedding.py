"""Live B1 profile dual-write qualification against PostgreSQL + pgvector."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from xhs_food.composition.adapters import SQLAlchemyEmbeddingShadowRepository
from xhs_food.contracts import BGE_M3_PROFILE_V1
from xhs_food.evidence import (
    EmbeddingBackfillInput,
    EmbeddingCompareStatus,
    EmbeddingShadowService,
)
from xhs_food.foundation import SQLAlchemyUnitOfWork


class _Producer:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on

    async def embed(self, content: str, profile) -> tuple[float, ...]:
        if content == self.fail_on:
            raise TimeoutError("live fixture interruption")
        return (0.0,) * profile.dimensions


@asynccontextmanager
async def _database(url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.live
async def test_profile_dual_write_backfill_resume_and_shadow_read() -> None:
    url = os.getenv("B1_POSTGRES_URL")
    if not url:
        pytest.skip("B1_POSTGRES_URL is required for live PostgreSQL qualification")
    fixture_prefix = "live-b1-embedding"
    keys = (f"{fixture_prefix}-1", f"{fixture_prefix}-2")
    contents = ("live first", "live second")

    async with _database(url) as session_factory:
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM embedding_backfill_cursors WHERE profile_id = :profile_id"),
                {"profile_id": BGE_M3_PROFILE_V1.profile_id},
            )
            await session.execute(
                text(
                    "INSERT INTO embedding_profiles "
                    "(profile_id, model_id, model_version, dimensions, distance, normalized, schema_version, metadata) "
                    "VALUES (:profile_id, :model_id, :model_version, :dimensions, :distance, :normalized, :schema_version, '{}'::jsonb) "
                    "ON CONFLICT (profile_id) DO NOTHING"
                ),
                {
                    "profile_id": BGE_M3_PROFILE_V1.profile_id,
                    "model_id": BGE_M3_PROFILE_V1.model_id,
                    "model_version": BGE_M3_PROFILE_V1.model_version,
                    "dimensions": BGE_M3_PROFILE_V1.dimensions,
                    "distance": BGE_M3_PROFILE_V1.distance.value,
                    "normalized": True,
                    "schema_version": BGE_M3_PROFILE_V1.schema_version,
                },
            )
            for key in keys:
                await session.execute(
                    text(
                        "INSERT INTO canonical_queries "
                        "(canonical_key, family_id, tenant_scope, language, region, schema_version, normalizer_version, classifier_version, payload, created_at) "
                        "VALUES (:key, :family, 'public', 'en', 'US', 'canonical-query/v1', 'canonical-normalizer/v1', 'food-constraint-classifier/v1', '{}'::jsonb, :created_at) "
                        "ON CONFLICT (canonical_key) DO NOTHING"
                    ),
                    {"key": key, "family": f"{fixture_prefix}-family", "created_at": datetime.now(UTC)},
                )
            await session.commit()

        def unit_factory() -> SQLAlchemyUnitOfWork:
            return SQLAlchemyUnitOfWork(session_factory)

        service = EmbeddingShadowService(SQLAlchemyEmbeddingShadowRepository(unit_factory))
        rows = tuple(
            EmbeddingBackfillInput(
                source_key=key,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
            for key, content in zip(keys, contents, strict=True)
        )
        try:
            with pytest.raises(TimeoutError, match="interruption"):
                await service.backfill(rows, _Producer(fail_on=contents[1]))
            assert await service.backfill(rows, _Producer())
            comparison = await service.shadow_read_compare(keys[0], contents[0])
            assert comparison.status is EmbeddingCompareStatus.MATCH
            async with session_factory() as session:
                assert await session.scalar(
                    text(
                        "SELECT count(*) FROM canonical_query_embeddings "
                        "WHERE canonical_key LIKE :prefix AND profile_id = :profile_id"
                    ),
                    {"prefix": f"{fixture_prefix}-%", "profile_id": BGE_M3_PROFILE_V1.profile_id},
                ) == 2
                assert await session.scalar(
                    text(
                        "SELECT processed_rows FROM embedding_backfill_cursors WHERE profile_id = :profile_id"
                    ),
                    {"profile_id": BGE_M3_PROFILE_V1.profile_id},
                ) >= 2
        finally:
            async with session_factory() as session:
                await session.execute(
                    text(
                        "DELETE FROM canonical_query_embeddings WHERE canonical_key LIKE :prefix"
                    ),
                    {"prefix": f"{fixture_prefix}-%"},
                )
                await session.execute(
                    text("DELETE FROM canonical_queries WHERE canonical_key LIKE :prefix"),
                    {"prefix": f"{fixture_prefix}-%"},
                )
                await session.execute(
                    text("DELETE FROM embedding_backfill_cursors WHERE profile_id = :profile_id"),
                    {"profile_id": BGE_M3_PROFILE_V1.profile_id},
                )
                await session.commit()
