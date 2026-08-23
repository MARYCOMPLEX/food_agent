"""PostgreSQL Query Family search, freshness, and CAS adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
    EMBEDDING_PROFILE_VERSION,
    CurrentBundleRef,
    EmbeddingDistance,
    EmbeddingProfile,
    FreshnessInput,
    QueryFamilyMatch,
    QueryMatchLayer,
    RefreshClaim,
    RefreshSingleFlightKey,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import (
    canonical_queries,
    embedding_profile_read_pointer,
    evidence_bundle_current,
    query_family_aliases,
    query_family_freshness,
    query_refresh_claims,
)

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyQueryFamilyRepository:
    """Keep all reuse and activation facts in PostgreSQL-owned transactions."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_exact(self, canonical_key: str) -> QueryFamilyMatch | None:
        statement = select(canonical_queries.c.family_id).where(
            canonical_queries.c.canonical_key == canonical_key
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return QueryFamilyMatch(
            family_id=str(row["family_id"]),
            canonical_key=canonical_key,
            layer=QueryMatchLayer.DETERMINISTIC,
            confidence=1.0,
            rule_version="canonical-normalizer/v1",
            audit_basis=("exact_canonical_key",),
        )

    async def search_trigram(
        self, alias_text: str, *, limit: int = 5
    ) -> tuple[QueryFamilyMatch, ...]:
        statement = text(
            "SELECT family_id, canonical_key, alias_text, rule_version, "
            "similarity(alias_text, :alias_text) AS confidence "
            "FROM query_family_aliases "
            "WHERE alias_text % :alias_text "
            "ORDER BY confidence DESC, family_id, canonical_key "
            "LIMIT :limit"
        )
        async with self._unit_of_work_factory() as unit:
            rows = (
                await unit.session_for_adapter().execute(
                    statement, {"alias_text": alias_text, "limit": limit}
                )
            ).mappings().all()
        return tuple(
            QueryFamilyMatch(
                family_id=str(row["family_id"]),
                canonical_key=str(row["canonical_key"]),
                layer=QueryMatchLayer.TRIGRAM,
                confidence=float(row["confidence"]),
                matched_alias=str(row["alias_text"]),
                rule_version=str(row["rule_version"]),
                audit_basis=("pg_trgm_similarity",),
            )
            for row in rows
        )

    async def search_vector(
        self,
        vector: tuple[float, ...],
        profile: EmbeddingProfile,
        *,
        limit: int = 5,
    ) -> tuple[QueryFamilyMatch, ...]:
        vector_text = "[" + ",".join(str(value) for value in vector) + "]"
        statement = text(
            "SELECT cq.family_id, ce.canonical_key, ep.profile_id, ep.model_version, "
            "1 - (ce.vector <=> CAST(:vector AS vector)) AS confidence "
            "FROM canonical_query_embeddings ce "
            "JOIN canonical_queries cq ON cq.canonical_key = ce.canonical_key "
            "JOIN embedding_profiles ep ON ep.profile_id = ce.profile_id "
            "WHERE ce.profile_id = :profile_id "
            "ORDER BY ce.vector <=> CAST(:vector AS vector), ce.canonical_key "
            "LIMIT :limit"
        )
        async with self._unit_of_work_factory() as unit:
            rows = (
                await unit.session_for_adapter().execute(
                    statement,
                    {"vector": vector_text, "profile_id": profile.profile_id, "limit": limit},
                )
            ).mappings().all()
        return tuple(
            QueryFamilyMatch(
                family_id=str(row["family_id"]),
                canonical_key=str(row["canonical_key"]),
                layer=QueryMatchLayer.VECTOR,
                confidence=float(row["confidence"]),
                rule_version="vector-search/v1",
                profile_id=str(row["profile_id"]),
                profile_version=str(row["model_version"]),
                audit_basis=("pgvector_cosine",),
            )
            for row in rows
        )

    async def save_alias(self, match: QueryFamilyMatch, alias_text: str, *, language: str, region: str) -> None:
        if match.layer is QueryMatchLayer.VECTOR:
            raise ValueError("vector matches cannot create alias ownership")
        alias_id = _alias_id(match.family_id, alias_text, language, region)
        statement = insert(query_family_aliases).values(
            alias_id=alias_id,
            family_id=match.family_id,
            canonical_key=match.canonical_key,
            alias_text=alias_text,
            language=language,
            region=region,
            rule_version=match.rule_version,
            created_at=datetime.now(UTC),
        ).on_conflict_do_nothing(index_elements=[query_family_aliases.c.alias_id])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()

    async def get_freshness(self, family_id: str) -> FreshnessInput | None:
        statement = select(query_family_freshness).where(
            query_family_freshness.c.family_id == family_id
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return FreshnessInput(
            family_id=family_id,
            bundle_version=row["bundle_version"],
            verified_at=row["verified_at"],
            coverage=dict(row["coverage"]),
            watermarks=dict(row["watermarks"]),
            active_refresh_workflow_id=row["active_refresh_workflow_id"],
        )

    async def save_freshness(self, state: FreshnessInput) -> None:
        statement = insert(query_family_freshness).values(
            family_id=state.family_id,
            bundle_version=state.bundle_version,
            verified_at=state.verified_at,
            coverage=state.coverage,
            watermarks=state.watermarks,
            active_refresh_workflow_id=state.active_refresh_workflow_id,
            updated_at=datetime.now(UTC),
        ).on_conflict_do_update(
            index_elements=[query_family_freshness.c.family_id],
            set_={
                "bundle_version": state.bundle_version,
                "verified_at": state.verified_at,
                "coverage": state.coverage,
                "watermarks": state.watermarks,
                "active_refresh_workflow_id": state.active_refresh_workflow_id,
                "updated_at": datetime.now(UTC),
            },
        )
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()

    async def claim_refresh(self, key: RefreshSingleFlightKey) -> RefreshClaim:
        claim_key = stable_refresh_claim_key(key)
        workflow_id = stable_refresh_workflow_id(key)
        scope_hash = hashlib.sha256(
            json.dumps(key.scope, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        now = datetime.now(UTC)
        statement = insert(query_refresh_claims).values(
            claim_key=claim_key,
            family_id=key.family_id,
            scope_hash=scope_hash,
            policy_version=key.policy_version,
            workflow_id=workflow_id,
            status="active",
            created_at=now,
            updated_at=now,
        ).on_conflict_do_nothing(index_elements=[query_refresh_claims.c.claim_key])
        select_statement = select(query_refresh_claims).where(
            query_refresh_claims.c.claim_key == claim_key
        )
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(statement)
            row = (await unit.session_for_adapter().execute(select_statement)).mappings().one()
            await unit.commit()
        return RefreshClaim(
            claim_key=claim_key,
            workflow_id=str(row["workflow_id"]),
            acquired=_rowcount(result) == 1,
            status=cast(
                Literal["active", "completed", "failed", "cancelled"],
                str(row["status"]),
            ),
        )

    async def activate_bundle_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            if expected_bundle_version is None:
                statement = insert(evidence_bundle_current).values(
                    family_id=family_id,
                    bundle_id=bundle_id,
                    bundle_version=bundle_version,
                    updated_at=now,
                ).on_conflict_do_nothing(index_elements=[evidence_bundle_current.c.family_id])
                result = await session.execute(statement)
                if _rowcount(result) == 1:
                    await unit.commit()
                    return True
                row = (
                    await session.execute(
                        select(evidence_bundle_current).where(
                            evidence_bundle_current.c.family_id == family_id
                        )
                    )
                ).mappings().first()
                await unit.rollback()
                return bool(row and row["bundle_id"] == bundle_id and row["bundle_version"] == bundle_version)

            statement = (
                update(evidence_bundle_current)
                .where(
                    evidence_bundle_current.c.family_id == family_id,
                    evidence_bundle_current.c.bundle_version == expected_bundle_version,
                )
                .values(bundle_id=bundle_id, bundle_version=bundle_version, updated_at=now)
            )
            result = await session.execute(statement)
            await unit.commit()
            return _rowcount(result) == 1

    async def get_current_bundle(self, family_id: str) -> CurrentBundleRef | None:
        statement = select(evidence_bundle_current).where(
            evidence_bundle_current.c.family_id == family_id
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return CurrentBundleRef(
            family_id=family_id,
            bundle_id=str(row["bundle_id"]),
            bundle_version=int(row["bundle_version"]),
        )

    async def activate_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: EmbeddingProfile,
    ) -> bool:
        """Conditionally move both authority pointers in one transaction."""

        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            profile_row = (
                await session.execute(
                    select(embedding_profile_read_pointer)
                    .where(embedding_profile_read_pointer.c.pointer_key == "canonical_query")
                    .with_for_update()
                )
            ).mappings().first()
            current_profile_id = str(profile_row["profile_id"]) if profile_row else None
            if current_profile_id != expected_profile_id:
                await unit.rollback()
                return False

            bundle_row = (
                await session.execute(
                    select(evidence_bundle_current)
                    .where(evidence_bundle_current.c.family_id == family_id)
                    .with_for_update()
                )
            ).mappings().first()
            current_version = int(bundle_row["bundle_version"]) if bundle_row else None
            if current_version != expected_bundle_version:
                await unit.rollback()
                return False

            if profile_row is None:
                await session.execute(
                    insert(embedding_profile_read_pointer).values(
                        pointer_key="canonical_query",
                        profile_id=profile.profile_id,
                        model_version=profile.model_version,
                        updated_at=now,
                    )
                )
            else:
                await session.execute(
                    update(embedding_profile_read_pointer)
                    .where(embedding_profile_read_pointer.c.pointer_key == "canonical_query")
                    .values(
                        profile_id=profile.profile_id,
                        model_version=profile.model_version,
                        updated_at=now,
                    )
                )
            if bundle_row is None:
                await session.execute(
                    insert(evidence_bundle_current).values(
                        family_id=family_id,
                        bundle_id=bundle_id,
                        bundle_version=bundle_version,
                        updated_at=now,
                    )
                )
            else:
                await session.execute(
                    update(evidence_bundle_current)
                    .where(evidence_bundle_current.c.family_id == family_id)
                    .values(
                        bundle_id=bundle_id,
                        bundle_version=bundle_version,
                        updated_at=now,
                    )
                )
            await unit.commit()
            return True

    async def get_active_profile(self) -> EmbeddingProfile | None:
        statement = text(
            "SELECT ep.profile_id, ep.model_id, ep.model_version, ep.dimensions, "
            "ep.distance, ep.normalized, ep.schema_version "
            "FROM embedding_profile_read_pointer ptr "
            "JOIN embedding_profiles ep ON ep.profile_id = ptr.profile_id "
            "WHERE ptr.pointer_key = 'canonical_query'"
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return EmbeddingProfile(
            profile_id=str(row["profile_id"]),
            model_id=str(row["model_id"]),
            model_version=str(row["model_version"]),
            dimensions=int(row["dimensions"]),
            distance=EmbeddingDistance(str(row["distance"])),
            normalized=True,
            schema_version=EMBEDDING_PROFILE_VERSION,
        )


def _alias_id(family_id: str, alias_text: str, language: str, region: str) -> str:
    value = "|".join((family_id, alias_text, language, region))
    return f"alias.{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return value if isinstance(value, int) else 0


__all__ = ["SQLAlchemyQueryFamilyRepository"]
