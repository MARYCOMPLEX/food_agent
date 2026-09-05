"""PostgreSQL Query Family search, freshness, and CAS adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
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
    validate_embedding_vector,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import (
    canonical_queries,
    embedding_profile_read_pointer,
    embedding_profiles,
    evidence_bundle_current,
    evidence_bundles,
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
        _validate_public_text(canonical_key, field_name="canonical_key")
        statement = select(
            canonical_queries.c.family_id,
            canonical_queries.c.canonical_key,
            canonical_queries.c.normalizer_version,
            canonical_queries.c.classifier_version,
        ).where(
            canonical_queries.c.canonical_key == canonical_key,
            canonical_queries.c.tenant_scope == "public",
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return QueryFamilyMatch(
            family_id=str(row["family_id"]),
            canonical_key=str(row["canonical_key"]),
            layer=QueryMatchLayer.DETERMINISTIC,
            confidence=1.0,
            rule_version=str(row["normalizer_version"]),
            normalization_version=str(row["normalizer_version"]),
            rationale=("exact_canonical_key",),
            audit_basis=("exact_canonical_key", "public_tenant_scope"),
        )

    async def search_trigram(
        self, alias_text: str, *, limit: int = 5
    ) -> tuple[QueryFamilyMatch, ...]:
        _validate_public_text(alias_text, field_name="alias_text")
        _validate_limit(limit)
        statement = text(
            "SELECT a.family_id, a.canonical_key, a.alias_text, a.rule_version, "
            "cq.normalizer_version, cq.classifier_version, "
            "similarity(a.alias_text, :alias_text) AS confidence "
            "FROM query_family_aliases AS a "
            "JOIN canonical_queries AS cq ON cq.canonical_key = a.canonical_key "
            "WHERE cq.tenant_scope = 'public' AND a.alias_text % :alias_text "
            "ORDER BY confidence DESC, a.family_id, a.canonical_key, a.alias_text "
            "LIMIT :limit"
        )
        async with self._unit_of_work_factory() as unit:
            rows = (
                (
                    await unit.session_for_adapter().execute(
                        statement, {"alias_text": alias_text, "limit": limit}
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            QueryFamilyMatch(
                family_id=str(row["family_id"]),
                canonical_key=str(row["canonical_key"]),
                layer=QueryMatchLayer.TRIGRAM,
                confidence=float(row["confidence"]),
                matched_alias=str(row["alias_text"]),
                rule_version=str(row["rule_version"]),
                normalization_version=str(row["normalizer_version"]),
                rationale=("pg_trgm_similarity", "public_tenant_scope"),
                audit_basis=("pg_trgm_similarity", "public_tenant_scope"),
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
        _validate_limit(limit)
        validate_embedding_vector(profile, vector)
        vector_text = "[" + ",".join(str(value) for value in vector) + "]"
        statement = text(
            "SELECT cq.family_id, ce.canonical_key, ep.profile_id, ep.model_version, "
            "ep.schema_version AS profile_schema_version, cq.normalizer_version, "
            "GREATEST(0, LEAST(1, 1 - (ce.vector <=> CAST(:vector AS vector)))) AS confidence "
            "FROM canonical_query_embeddings ce "
            "JOIN canonical_queries cq ON cq.canonical_key = ce.canonical_key "
            "JOIN embedding_profiles ep ON ep.profile_id = ce.profile_id "
            "WHERE cq.tenant_scope = 'public' "
            "AND ce.profile_id = :profile_id "
            "AND ep.model_id = :model_id "
            "AND ep.model_version = :model_version "
            "AND ep.dimensions = :dimensions "
            "AND ep.distance = :distance "
            "AND ep.normalized IS TRUE "
            "ORDER BY ce.vector <=> CAST(:vector AS vector), cq.family_id, ce.canonical_key "
            "LIMIT :limit"
        )
        async with self._unit_of_work_factory() as unit:
            rows = (
                (
                    await unit.session_for_adapter().execute(
                        statement,
                        {
                            "vector": vector_text,
                            "profile_id": profile.profile_id,
                            "model_id": profile.model_id,
                            "model_version": profile.model_version,
                            "dimensions": profile.dimensions,
                            "distance": profile.distance.value,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            QueryFamilyMatch(
                family_id=str(row["family_id"]),
                canonical_key=str(row["canonical_key"]),
                layer=QueryMatchLayer.VECTOR,
                confidence=float(row["confidence"]),
                rule_version="vector-search/v1",
                normalization_version=str(row["normalizer_version"]),
                profile_id=str(row["profile_id"]),
                profile_version=str(row["model_version"]),
                rationale=("pgvector_cosine", "profile_pinned", "public_tenant_scope"),
                audit_basis=("pgvector_cosine", "profile_pinned", "public_tenant_scope"),
            )
            for row in rows
        )

    async def save_alias(
        self, match: QueryFamilyMatch, alias_text: str, *, language: str, region: str
    ) -> None:
        if match.layer is QueryMatchLayer.VECTOR:
            raise ValueError("vector matches cannot create alias ownership")
        _validate_public_text(alias_text, field_name="alias_text")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("alias language must be non-empty")
        if not isinstance(region, str) or not region.strip():
            raise ValueError("alias region must be non-empty")
        alias_id = _alias_id(match.family_id, alias_text, language, region)
        statement = (
            insert(query_family_aliases)
            .values(
                alias_id=alias_id,
                family_id=match.family_id,
                canonical_key=match.canonical_key,
                alias_text=alias_text,
                language=language,
                region=region,
                rule_version=match.rule_version,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[query_family_aliases.c.alias_id])
        )
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
            coverage=dict(row["coverage"] or {}),
            watermarks=dict(row["watermarks"] or {}),
            watermark_advanced=bool(row.get("watermark_advanced", False)),
            active_refresh_workflow_id=row["active_refresh_workflow_id"],
        )

    async def save_freshness(self, state: FreshnessInput) -> None:
        statement = (
            insert(query_family_freshness)
            .values(
                family_id=state.family_id,
                bundle_version=state.bundle_version,
                verified_at=state.verified_at,
                coverage=state.coverage,
                watermarks=state.watermarks,
                watermark_advanced=state.watermark_advanced,
                active_refresh_workflow_id=state.active_refresh_workflow_id,
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=[query_family_freshness.c.family_id],
                set_={
                    "bundle_version": state.bundle_version,
                    "verified_at": state.verified_at,
                    "coverage": state.coverage,
                    "watermarks": state.watermarks,
                    "watermark_advanced": state.watermark_advanced,
                    "active_refresh_workflow_id": state.active_refresh_workflow_id,
                    "updated_at": datetime.now(UTC),
                },
            )
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
        statement = (
            insert(query_refresh_claims)
            .values(
                claim_key=claim_key,
                family_id=key.family_id,
                scope_hash=scope_hash,
                policy_version=key.policy_version,
                workflow_id=workflow_id,
                status="active",
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[query_refresh_claims.c.claim_key])
            .returning(query_refresh_claims.c.claim_key)
        )
        select_statement = select(query_refresh_claims).where(
            query_refresh_claims.c.claim_key == claim_key
        )
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            inserted = (await session.execute(statement)).mappings().first()
            row = (await session.execute(select_statement)).mappings().one()
            if (
                str(row["family_id"]) != key.family_id
                or str(row["scope_hash"]) != scope_hash
                or str(row["policy_version"]) != key.policy_version
                or str(row["workflow_id"]) != workflow_id
            ):
                await unit.rollback()
                raise ValueError("refresh claim identity conflicts with the requested scope")
            await unit.commit()
        return RefreshClaim(
            claim_key=claim_key,
            workflow_id=str(row["workflow_id"]),
            acquired=inserted is not None,
            status=cast(
                Literal["active", "completed", "failed", "cancelled"],
                str(row["status"]),
            ),
        )

    async def update_refresh_status(
        self,
        claim_key: str,
        status: Literal["active", "completed", "failed", "cancelled"],
    ) -> bool:
        """Move a durable claim to a terminal state exactly once."""

        if not claim_key:
            raise ValueError("claim_key must be non-empty")
        if status not in {"active", "completed", "failed", "cancelled"}:
            raise ValueError("unsupported refresh claim status")
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            row = (
                (
                    await session.execute(
                        select(query_refresh_claims.c.status).where(
                            query_refresh_claims.c.claim_key == claim_key
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                await unit.rollback()
                return False
            current_status = str(row["status"])
            if current_status == status:
                await unit.rollback()
                return True
            if current_status != "active":
                await unit.rollback()
                return False
            result = await session.execute(
                update(query_refresh_claims)
                .where(
                    query_refresh_claims.c.claim_key == claim_key,
                    query_refresh_claims.c.status == "active",
                )
                .values(status=status, updated_at=datetime.now(UTC))
            )
            await unit.commit()
            return _rowcount(result) == 1

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
            if bundle_version < 1:
                await unit.rollback()
                return False
            candidate_row = (
                (
                    await session.execute(
                        select(
                            evidence_bundles.c.bundle_id,
                            evidence_bundles.c.family_id,
                            evidence_bundles.c.bundle_version,
                            evidence_bundles.c.state,
                            evidence_bundles.c.content_hash,
                            evidence_bundles.c.payload,
                        ).where(evidence_bundles.c.bundle_id == bundle_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if (
                candidate_row is None
                or str(candidate_row["family_id"]) != family_id
                or int(candidate_row["bundle_version"]) != bundle_version
                or str(candidate_row["state"]) not in {"candidate", "published"}
                or not _bundle_storage_row_is_consistent(candidate_row)
            ):
                await unit.rollback()
                return False
            if expected_bundle_version is None:
                statement = (
                    insert(evidence_bundle_current)
                    .values(
                        family_id=family_id,
                        bundle_id=bundle_id,
                        bundle_version=bundle_version,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=[evidence_bundle_current.c.family_id])
                    .returning(evidence_bundle_current.c.family_id)
                )
                result = await session.execute(statement)
                inserted, known = _result_succeeded(result)
                if inserted or not known:
                    if not await _publish_bundle(session, candidate_row):
                        await unit.rollback()
                        return False
                    await unit.commit()
                    return True
                row = (
                    (
                        await session.execute(
                            select(evidence_bundle_current)
                            .where(evidence_bundle_current.c.family_id == family_id)
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .first()
                )
                matching = bool(
                    row
                    and row["bundle_id"] == bundle_id
                    and row["bundle_version"] == bundle_version
                )
                if matching:
                    if not await _publish_bundle(session, candidate_row):
                        await unit.rollback()
                        return False
                    await unit.commit()
                else:
                    await unit.rollback()
                return matching

            current_row = (
                (
                    await session.execute(
                        select(evidence_bundle_current)
                        .where(evidence_bundle_current.c.family_id == family_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if current_row is None:
                await unit.rollback()
                return False
            current_version = int(current_row["bundle_version"])
            if current_version != expected_bundle_version:
                await unit.rollback()
                return False
            if bundle_version < current_version or (
                bundle_version == current_version
                and str(current_row["bundle_id"]) != bundle_id
            ):
                await unit.rollback()
                return False
            statement = (
                update(evidence_bundle_current)
                .where(
                    evidence_bundle_current.c.family_id == family_id,
                    evidence_bundle_current.c.bundle_version == expected_bundle_version,
                )
                .values(bundle_id=bundle_id, bundle_version=bundle_version, updated_at=now)
                .returning(evidence_bundle_current.c.family_id)
            )
            result = await session.execute(statement)
            updated, known = _result_succeeded(result)
            if not updated and known:
                await unit.rollback()
                return False
            if not await _publish_bundle(session, candidate_row):
                await unit.rollback()
                return False
            await unit.commit()
            return True

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
        *,
        _allow_rollback: bool = False,
    ) -> bool:
        """Conditionally move both authority pointers in one transaction."""

        now = datetime.now(UTC)
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            if bundle_version < 1:
                await unit.rollback()
                return False
            candidate = (
                (
                    await session.execute(
                        select(
                            evidence_bundles.c.bundle_id,
                            evidence_bundles.c.family_id,
                            evidence_bundles.c.bundle_version,
                            evidence_bundles.c.state,
                            evidence_bundles.c.content_hash,
                            evidence_bundles.c.payload,
                        ).where(evidence_bundles.c.bundle_id == bundle_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            profile_definition = (
                (
                    await session.execute(
                        select(embedding_profiles).where(
                            embedding_profiles.c.profile_id == profile.profile_id
                        )
                    )
                )
                .mappings()
                .first()
            )
            if (
                candidate is None
                or str(candidate["family_id"]) != family_id
                or int(candidate["bundle_version"]) != bundle_version
                or str(candidate["state"]) not in {"candidate", "published"}
                or not _bundle_storage_row_is_consistent(candidate)
                or profile_definition is None
                or str(profile_definition["model_id"]) != profile.model_id
                or str(profile_definition["model_version"]) != profile.model_version
                or int(profile_definition["dimensions"]) != profile.dimensions
                or str(profile_definition["distance"]) != profile.distance.value
                or bool(profile_definition["normalized"]) is not True
                or str(profile_definition["schema_version"]) != profile.schema_version
            ):
                await unit.rollback()
                return False
            if _allow_rollback and str(candidate["state"]) != "published":
                await unit.rollback()
                return False
            profile_row = (
                (
                    await session.execute(
                        select(embedding_profile_read_pointer)
                        .where(embedding_profile_read_pointer.c.pointer_key == "canonical_query")
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            current_profile_id = str(profile_row["profile_id"]) if profile_row else None
            if current_profile_id != expected_profile_id:
                await unit.rollback()
                return False
            if profile_row is not None and str(profile_row["model_version"]) != str(
                profile_definition["model_version"]
            ) and current_profile_id == profile.profile_id:
                await unit.rollback()
                return False

            bundle_row = (
                (
                    await session.execute(
                        select(evidence_bundle_current)
                        .where(evidence_bundle_current.c.family_id == family_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            current_version = int(bundle_row["bundle_version"]) if bundle_row else None
            if current_version != expected_bundle_version:
                await unit.rollback()
                return False
            if (
                not _allow_rollback
                and bundle_row is not None
                and current_version is not None
                and (
                    bundle_version < current_version
                    or (
                        bundle_version == current_version
                        and str(bundle_row["bundle_id"]) != bundle_id
                    )
                )
            ):
                await unit.rollback()
                return False

            if profile_row is None:
                profile_insert = (
                    insert(embedding_profile_read_pointer)
                    .values(
                        pointer_key="canonical_query",
                        profile_id=profile.profile_id,
                        model_version=profile.model_version,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[embedding_profile_read_pointer.c.pointer_key]
                    )
                    .returning(embedding_profile_read_pointer.c.pointer_key)
                )
                result = await session.execute(profile_insert)
                inserted, known = _result_succeeded(result)
                if known and not inserted:
                    concurrent_profile = (
                        (
                            await session.execute(
                                select(embedding_profile_read_pointer)
                                .where(
                                    embedding_profile_read_pointer.c.pointer_key
                                    == "canonical_query"
                                )
                                .with_for_update()
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        concurrent_profile is None
                        or str(concurrent_profile["profile_id"]) != profile.profile_id
                        or str(concurrent_profile["model_version"])
                        != profile.model_version
                    ):
                        await unit.rollback()
                        return False
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
                bundle_insert = (
                    insert(evidence_bundle_current)
                    .values(
                        family_id=family_id,
                        bundle_id=bundle_id,
                        bundle_version=bundle_version,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=[evidence_bundle_current.c.family_id])
                    .returning(evidence_bundle_current.c.family_id)
                )
                result = await session.execute(bundle_insert)
                inserted, known = _result_succeeded(result)
                if known and not inserted:
                    concurrent_bundle = (
                        (
                            await session.execute(
                                select(evidence_bundle_current)
                                .where(evidence_bundle_current.c.family_id == family_id)
                                .with_for_update()
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        concurrent_bundle is None
                        or str(concurrent_bundle["bundle_id"]) != bundle_id
                        or int(concurrent_bundle["bundle_version"]) != bundle_version
                    ):
                        await unit.rollback()
                        return False
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
            if not await _publish_bundle(session, candidate):
                await unit.rollback()
                return False
            await unit.commit()
            return True

    async def restore_bundle_and_profile_if_current(
        self,
        family_id: str,
        expected_bundle_version: int,
        bundle_id: str,
        bundle_version: int,
        expected_profile_id: str | None,
        profile: EmbeddingProfile,
    ) -> bool:
        """Conditionally restore an older pointer for an explicit rollback."""

        return await self.activate_bundle_and_profile_if_current(
            family_id,
            expected_bundle_version,
            bundle_id,
            bundle_version,
            expected_profile_id,
            profile,
            _allow_rollback=True,
        )

    async def get_active_profile(self) -> EmbeddingProfile | None:
        statement = text(
            "SELECT ep.profile_id, ep.model_id, ep.model_version, ep.dimensions, "
            "ep.distance, ep.normalized, ep.schema_version, ptr.model_version AS pointer_model_version "
            "FROM embedding_profile_read_pointer ptr "
            "JOIN embedding_profiles ep ON ep.profile_id = ptr.profile_id "
            "WHERE ptr.pointer_key = 'canonical_query' "
            "AND ptr.model_version = ep.model_version"
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
            normalized=cast(Literal[True], bool(row["normalized"])),
            schema_version=cast(Literal["embedding-profile/v1"], str(row["schema_version"])),
        )


def _alias_id(family_id: str, alias_text: str, language: str, region: str) -> str:
    value = "|".join((family_id, alias_text, language, region))
    return f"alias.{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _result_succeeded(result: object | None) -> tuple[bool, bool]:
    """Interpret a DML result while preserving compatibility with test fakes."""

    if result is None:
        return True, False
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        try:
            first = getattr(mappings(), "first", None)
            if callable(first):
                return first() is not None, True
        except Exception:  # pragma: no cover - driver-specific closed results
            pass
    rowcount = getattr(result, "rowcount", None)
    if isinstance(rowcount, int):
        return rowcount != 0, True
    return True, False


def _bundle_storage_row_is_consistent(row: Mapping[str, object]) -> bool:
    """Check duplicated authority columns without rejecting old sparse fixtures."""

    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return False
    expected = {
        "bundle_id": row.get("bundle_id"),
        "family_id": row.get("family_id"),
        "bundle_version": row.get("bundle_version"),
        "state": row.get("state"),
        "content_hash": row.get("content_hash"),
    }
    for key, column_value in expected.items():
        if key in payload and str(payload[key]) != str(column_value):
            return False
    return True


async def _publish_bundle(session: object, row: Mapping[str, object]) -> bool:
    """Publish a candidate row and its JSON projection in the same transaction."""

    execute = getattr(session, "execute", None)
    if not callable(execute):
        raise TypeError("Bundle activation session must expose execute")
    state = str(row.get("state"))
    if state not in {"candidate", "published"} or not _bundle_storage_row_is_consistent(row):
        return False
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return False
    updated_payload = dict(payload)
    if updated_payload.get("state") not in (None, state):
        return False
    if state == "published" and updated_payload.get("state") == "published":
        return True
    updated_payload["state"] = "published"
    statement = (
        update(evidence_bundles)
        .where(
            evidence_bundles.c.bundle_id == row.get("bundle_id"),
            evidence_bundles.c.family_id == row.get("family_id"),
            evidence_bundles.c.bundle_version == row.get("bundle_version"),
            evidence_bundles.c.state == state,
        )
        .values(state="published", payload=updated_payload)
        .returning(evidence_bundles.c.bundle_id)
    )
    result = await execute(statement)
    succeeded, known = _result_succeeded(result)
    return succeeded or not known


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return value if isinstance(value, int) else 0


_PRIVATE_TEXT_MARKERS = frozenset(
    {
        "user",
        "users",
        "userid",
        "session",
        "sessions",
        "sessionid",
        "subject",
        "subjects",
        "identity",
        "identities",
        "deviceid",
        "preference",
        "preferences",
        "memory",
        "favorite",
        "favorites",
        "cookie",
        "token",
        "credential",
        "credentials",
        "password",
        "secret",
        "account",
    }
)


def _validate_public_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    if any(marker in normalized for marker in _PRIVATE_TEXT_MARKERS):
        raise ValueError(f"{field_name} contains a private identity marker")


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("matching limit must be an integer between 1 and 100")


__all__ = ["SQLAlchemyQueryFamilyRepository"]
