"""Live PostgreSQL qualification for the B2 Query Family foundation."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from xhs_food.composition.adapters import (
    SQLAlchemyEmbeddingShadowRepository,
    SQLAlchemyQueryFamilyRepository,
)
from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    FreshnessInput,
    QueryFamilyMatch,
    QueryMatchLayer,
    RefreshSingleFlightKey,
    stable_refresh_workflow_id,
)
from xhs_food.foundation.database import SQLAlchemyDatabase
from xhs_food.foundation.evidence_schema import (
    canonical_queries,
    embedding_profiles,
    evidence_bundles,
)


@pytest.mark.live
async def test_b2_postgres_query_reuse_and_cas() -> None:
    url = os.getenv("B2_POSTGRES_URL")
    if not url:
        pytest.skip("B2_POSTGRES_URL is required for live PostgreSQL qualification")

    database = SQLAlchemyDatabase(url, enabled=True)
    database.start()
    prefix = "live-b2-query-reuse"
    canonical_key = f"{prefix}.query"
    family_id = f"{prefix}.family"
    bundle_id = f"{prefix}.bundle.1"
    alias = f"{prefix} zigong local food"
    now = datetime.now(UTC)
    try:
        async with database.unit_of_work() as unit:
            session = unit.session_for_adapter()
            await session.execute(
                insert(canonical_queries).values(
                    canonical_key=canonical_key,
                    family_id=family_id,
                    tenant_scope="public",
                    language="zh-CN",
                    region="CN",
                    schema_version="canonical-query/v1",
                    normalizer_version="canonical-normalizer/v1",
                    classifier_version="food-constraints/v1",
                    payload={"fixture": prefix},
                    created_at=now,
                )
            )
            await session.execute(
                insert(embedding_profiles)
                .values(
                    profile_id=BGE_M3_PROFILE_V1.profile_id,
                    model_id=BGE_M3_PROFILE_V1.model_id,
                    model_version=BGE_M3_PROFILE_V1.model_version,
                    dimensions=BGE_M3_PROFILE_V1.dimensions,
                    distance=BGE_M3_PROFILE_V1.distance.value,
                    normalized=True,
                    schema_version=BGE_M3_PROFILE_V1.schema_version,
                    metadata={},
                )
                .on_conflict_do_nothing(index_elements=[embedding_profiles.c.profile_id])
            )
            await session.execute(
                insert(evidence_bundles).values(
                    bundle_id=bundle_id,
                    family_id=family_id,
                    bundle_version=1,
                    parent_bundle_id=None,
                    state="published",
                    content_hash="1" * 64,
                    payload={"fixture": prefix},
                    created_at=now,
                )
            )
            await unit.commit()

        repository = SQLAlchemyQueryFamilyRepository(database.unit_of_work)
        await repository.save_alias(
            QueryFamilyMatch(
                family_id=family_id,
                canonical_key=canonical_key,
                layer=QueryMatchLayer.TRIGRAM,
                confidence=0.95,
                matched_alias=alias,
                rule_version="pg-trgm/v1",
                audit_basis=("live",),
            ),
            alias,
            language="zh-CN",
            region="CN",
        )
        assert (await repository.get_exact(canonical_key)).family_id == family_id  # type: ignore[union-attr]
        assert (await repository.search_trigram(alias))[0].family_id == family_id

        vector = (1.0,) + (0.0,) * (BGE_M3_PROFILE_V1.dimensions - 1)
        embedding_repository = SQLAlchemyEmbeddingShadowRepository(database.unit_of_work)
        await embedding_repository.put_embedding(
            canonical_key,
            BGE_M3_PROFILE_V1,
            vector,
            "2" * 64,
            now,
        )
        assert (await repository.search_vector(vector, BGE_M3_PROFILE_V1))[0].profile_id == "profile_v1"

        state = FreshnessInput(
            family_id=family_id,
            bundle_version=1,
            verified_at=now,
            coverage={"restaurants": 0.9},
            watermarks={"restaurant.source_updated": "opaque:1"},
        )
        await repository.save_freshness(state)
        assert await repository.get_freshness(family_id) == state

        key = RefreshSingleFlightKey(
            family_id=family_id,
            scope=("restaurants",),
            policy_version="freshness/v1",
        )
        first = await repository.claim_refresh(key)
        second = await repository.claim_refresh(key)
        assert first.acquired is True
        assert second.acquired is False
        assert first.workflow_id == stable_refresh_workflow_id(key)

        assert await repository.activate_bundle_if_current(family_id, None, bundle_id, 1) is True
        assert await repository.activate_bundle_if_current(family_id, 1, bundle_id, 1) is True
        assert await repository.activate_bundle_if_current(family_id, 0, bundle_id, 1) is False
        assert (
            await repository.activate_bundle_and_profile_if_current(
                family_id,
                1,
                bundle_id,
                1,
                None,
                BGE_M3_PROFILE_V1,
            )
            is True
        )
        assert (await repository.get_active_profile()).profile_id == "profile_v1"  # type: ignore[union-attr]
        assert (
            await repository.activate_bundle_and_profile_if_current(
                family_id,
                1,
                bundle_id,
                1,
                "wrong-profile",
                BGE_M3_PROFILE_V1,
            )
            is False
        )
    finally:
        async with database.unit_of_work() as unit:
            session = unit.session_for_adapter()
            await session.execute(
                text("DELETE FROM query_refresh_claims WHERE family_id = :family_id"),
                {"family_id": family_id},
            )
            await session.execute(text("DELETE FROM embedding_profile_read_pointer"))
            await session.execute(
                text("DELETE FROM query_family_freshness WHERE family_id = :family_id"),
                {"family_id": family_id},
            )
            await session.execute(
                text("DELETE FROM evidence_bundle_current WHERE family_id = :family_id"),
                {"family_id": family_id},
            )
            await session.execute(
                text("DELETE FROM evidence_bundles WHERE family_id = :family_id"),
                {"family_id": family_id},
            )
            await session.execute(
                text("DELETE FROM query_family_aliases WHERE family_id = :family_id"),
                {"family_id": family_id},
            )
            await session.execute(
                text("DELETE FROM canonical_query_embeddings WHERE canonical_key = :key"),
                {"key": canonical_key},
            )
            await session.execute(
                text("DELETE FROM canonical_queries WHERE canonical_key = :key"),
                {"key": canonical_key},
            )
            await unit.commit()
        await database.aclose()
