"""PostgreSQL candidate Evidence Bundle shadow repository."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import Executable

from xhs_food.contracts import (
    BundleState,
    CanonicalQueryResult,
    CanonicalSourceBatch,
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
    SourceLocator,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import (
    canonical_queries,
    evidence_bundles,
    evidence_items,
    source_batch_items,
    source_batches,
    source_locators,
)

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class _ShadowWriteRecord(Protocol):
    """Structural record contract kept out of the evidence layer import graph."""

    batch: CanonicalSourceBatch
    locators: tuple[SourceLocator, ...]
    evidence_items: tuple[EvidenceItem, ...]
    canonical_query: CanonicalQueryResult | None
    candidate_bundle: EvidenceBundle | None
    source_batch_id: str | None


class SQLAlchemyCandidateBundleRepository:
    """Persist immutable candidates and atomic B1 shadow records.

    ``save_candidate`` is retained for B2 refreshes. ``write`` is the B1 sink
    entry point and owns one transaction for the complete source projection.
    Neither operation writes ``evidence_bundle_current``.
    """

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None:
        statement = select(
            evidence_bundles.c.bundle_id,
            evidence_bundles.c.family_id,
            evidence_bundles.c.bundle_version,
            evidence_bundles.c.state,
            evidence_bundles.c.content_hash,
            evidence_bundles.c.payload,
        ).where(
            evidence_bundles.c.bundle_id == bundle_id
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        bundle = EvidenceBundle.model_validate(row["payload"])
        _validate_bundle_storage_row(row, bundle)
        return bundle

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]:
        if not evidence_ids:
            return ()
        statement = select(
            evidence_items.c.evidence_id,
            evidence_items.c.source_locator_id,
            evidence_items.c.content_hash,
            evidence_items.c.status,
            evidence_items.c.payload,
        ).where(evidence_items.c.evidence_id.in_(evidence_ids))
        async with self._unit_of_work_factory() as unit:
            rows = (await unit.session_for_adapter().execute(statement)).mappings().all()
        by_id: dict[str, EvidenceItem] = {}
        for row in rows:
            item = EvidenceItem.model_validate(row["payload"])
            _validate_evidence_storage_row(row, item)
            by_id[str(row["evidence_id"])] = item
        return tuple(by_id[item_id] for item_id in evidence_ids if item_id in by_id)

    async def get_source_batch(self, batch_id: str) -> CanonicalSourceBatch | None:
        """Read a persisted source batch for audit tooling, never for serving."""

        statement = select(source_batches.c.payload).where(source_batches.c.batch_id == batch_id)
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return CanonicalSourceBatch.model_validate(row["payload"])

    @property
    def supports_atomic_canonical_query(self) -> bool:
        """Tell the shadow decorator that ``write`` includes canonical identity."""

        return True

    async def write(self, record: _ShadowWriteRecord) -> None:
        """Persist one complete B1 projection in one owner transaction."""

        _validate_shadow_record(record)
        batch_id = record.source_batch_id
        if batch_id is None:  # Guarded by _validate_shadow_record for type checkers.
            raise ValueError("shadow record requires a source_batch_id")

        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            if record.canonical_query is not None:
                await session.execute(_canonical_query_insert(record.canonical_query))
            await session.execute(_source_batch_insert(record.batch, batch_id, record.canonical_query))
            for locator in record.locators:
                await session.execute(_source_locator_insert(locator))
            for item in record.evidence_items:
                await session.execute(_evidence_item_insert(item))
                await session.execute(
                    _source_batch_item_insert(batch_id=batch_id, evidence_id=item.evidence_id)
                )
            if record.candidate_bundle is not None:
                await _insert_shadow_candidate(session, record.candidate_bundle)
            await unit.commit()

    async def save_candidate(
        self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]
    ) -> EvidenceBundle:
        if bundle.state is not BundleState.CANDIDATE:
            raise ValueError("candidate repository accepts candidate Bundles only")
        item_ids = tuple(item.evidence_id for item in items)
        if set(item_ids) != set(bundle.evidence_ids) or len(item_ids) != len(bundle.evidence_ids):
            raise ValueError("candidate Bundle evidence_ids must match the item set")
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            for item in items:
                result = await session.execute(_evidence_item_insert(item, returning=True))
                inserted, result_known = _insert_result(result)
                if result_known and not inserted:
                    existing = (
                        (
                            await session.execute(
                                select(
                                    evidence_items.c.evidence_id,
                                    evidence_items.c.source_locator_id,
                                    evidence_items.c.content_hash,
                                    evidence_items.c.status,
                                    evidence_items.c.payload,
                                ).where(evidence_items.c.evidence_id == item.evidence_id)
                            )
                        )
                        .mappings()
                        .first()
                    )
                    _validate_existing_evidence_row(existing, item)
            result = await session.execute(_candidate_bundle_insert(bundle, returning=True))
            inserted, result_known = _insert_result(result)
            if result_known and not inserted:
                existing_bundle = (
                    (
                        await session.execute(
                            select(
                                evidence_bundles.c.bundle_id,
                                evidence_bundles.c.family_id,
                                evidence_bundles.c.bundle_version,
                                evidence_bundles.c.state,
                                evidence_bundles.c.content_hash,
                                evidence_bundles.c.payload,
                            ).where(evidence_bundles.c.bundle_id == bundle.bundle_id)
                        )
                    )
                    .mappings()
                    .first()
                )
                _validate_existing_bundle_row(existing_bundle, bundle)
            await unit.commit()
        return bundle


def _canonical_query_insert(result: CanonicalQueryResult) -> Executable:
    query = result.canonical_query
    isolation = query.isolation
    public_classification = result.classification.model_copy(
        update={"personal_constraints": ()}
    )
    return (
        insert(canonical_queries)
        .values(
            canonical_key=result.canonical_key,
            family_id=result.family_id,
            tenant_scope=isolation.tenant_scope,
            language=isolation.language,
            region=isolation.region,
            schema_version=query.schema_version,
            normalizer_version=query.normalizer_version,
            classifier_version=query.classifier_version,
            payload={
                "canonical_query": query.model_dump(mode="json"),
                "classification": public_classification.model_dump(mode="json"),
                "family_match": result.family_match.model_dump(mode="json"),
            },
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=[canonical_queries.c.canonical_key])
    )


def _source_batch_insert(
    batch: CanonicalSourceBatch,
    batch_id: str,
    canonical_result: CanonicalQueryResult | None,
) -> Executable:
    return (
        insert(source_batches)
        .values(
            batch_id=batch_id,
            canonical_key=canonical_result.canonical_key if canonical_result else None,
            source_id=batch.source_id,
            connector_id=batch.connector_id,
            connector_version=batch.connector_version,
            normalizer_version=batch.normalizer_version,
            tenant_scope=batch.isolation.tenant_scope,
            language=batch.isolation.language,
            region=batch.isolation.region,
            watermark=batch.watermark,
            content_hash=batch_id.removeprefix("batch."),
            payload=batch.model_dump(mode="json"),
            created_at=_batch_created_at(batch),
        )
        .on_conflict_do_nothing(index_elements=[source_batches.c.batch_id])
    )


def _source_locator_insert(locator: SourceLocator) -> Executable:
    return (
        insert(source_locators)
        .values(
            locator_id=locator.locator_id,
            source_id=locator.source_id,
            connector_id=locator.connector_id,
            connector_version=locator.connector_version,
            external_item_id=locator.external_id,
            canonical_url=str(locator.canonical_url),
            captured_at=locator.captured_at,
            source_updated_at=locator.source_updated_at,
            watermark=locator.watermark,
            payload=locator.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(index_elements=[source_locators.c.locator_id])
    )


def _evidence_item_insert(item: EvidenceItem, *, returning: bool = False) -> Executable:
    statement = (
        insert(evidence_items)
        .values(
            evidence_id=item.evidence_id,
            source_locator_id=item.source_locator_id,
            content_hash=item.content_hash,
            status=item.status.value,
            payload=item.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(index_elements=[evidence_items.c.evidence_id])
    )
    return statement.returning(evidence_items.c.evidence_id) if returning else statement


def _source_batch_item_insert(*, batch_id: str, evidence_id: str) -> Executable:
    return (
        insert(source_batch_items)
        .values(batch_id=batch_id, evidence_id=evidence_id)
        .on_conflict_do_nothing(
            index_elements=[source_batch_items.c.batch_id, source_batch_items.c.evidence_id]
        )
    )


def _candidate_bundle_insert(bundle: EvidenceBundle, *, returning: bool = False) -> Executable:
    return _candidate_bundle_insert_with_parent(bundle, returning=returning)


def _candidate_bundle_insert_with_parent(
    bundle: EvidenceBundle,
    *,
    parent_bundle_id: str | None = None,
    returning: bool = False,
) -> Executable:
    statement = (
        insert(evidence_bundles)
        .values(
            bundle_id=bundle.bundle_id,
            family_id=bundle.family_id,
            bundle_version=bundle.bundle_version,
            parent_bundle_id=parent_bundle_id
            if parent_bundle_id is not None
            else (
                f"{bundle.family_id}.v{bundle.parent_bundle_version}"
                if bundle.parent_bundle_version is not None
                else None
            ),
            state=bundle.state.value,
            content_hash=bundle.content_hash,
            payload=bundle.model_dump(mode="json"),
            created_at=bundle.verified_at,
        )
        .on_conflict_do_nothing()
    )
    return statement.returning(evidence_bundles.c.bundle_id) if returning else statement


def _insert_result(result: object | None) -> tuple[bool, bool]:
    """Return ``(inserted, known)`` for an INSERT ... RETURNING result.

    Small recording fakes used by the contract tests return ``None`` rather
    than a SQLAlchemy result.  Treat that case as unknown/successful so the
    adapter still exposes the real SQL shape; a live result is always
    authoritative and distinguishes an idempotent conflict from an insert.
    """

    if result is None:
        return True, False
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        first = getattr(mappings(), "first", None)
        if callable(first):
            return first() is not None, True
    rowcount = getattr(result, "rowcount", None)
    if isinstance(rowcount, int):
        return rowcount != 0, True
    return True, False


def _validate_bundle_storage_row(row: Mapping[str, object], bundle: EvidenceBundle) -> None:
    if (
        str(row.get("bundle_id")) != bundle.bundle_id
        or str(row.get("family_id")) != bundle.family_id
        or int(row.get("bundle_version", -1)) != bundle.bundle_version
        or str(row.get("state")) != bundle.state.value
        or str(row.get("content_hash")) != bundle.content_hash
    ):
        raise ValueError("stored Bundle columns do not match its immutable payload")


def _validate_evidence_storage_row(row: Mapping[str, object], item: EvidenceItem) -> None:
    if (
        str(row.get("evidence_id")) != item.evidence_id
        or str(row.get("source_locator_id")) != item.source_locator_id
        or str(row.get("content_hash")) != item.content_hash
        or str(row.get("status")) != item.status.value
        or row.get("payload") != item.model_dump(mode="json")
    ):
        raise ValueError("stored Evidence columns do not match its immutable payload")


def _validate_existing_evidence_row(
    row: Mapping[str, object] | None, item: EvidenceItem
) -> None:
    if row is None:
        raise RuntimeError("Evidence insert conflicted but the existing row is unavailable")
    _validate_evidence_storage_row(row, item)


def _validate_existing_bundle_row(
    row: Mapping[str, object] | None, bundle: EvidenceBundle
) -> None:
    if row is None:
        raise RuntimeError("Bundle insert conflicted but the existing row is unavailable")
    existing = EvidenceBundle.model_validate(row.get("payload"))
    _validate_bundle_storage_row(row, existing)
    if existing != bundle:
        raise ValueError("Bundle content conflicts with an existing immutable row")


async def _insert_shadow_candidate(session: object, bundle: EvidenceBundle) -> None:
    """Insert a B1 candidate and allocate a monotonic version on correction.

    The pure shadow builder intentionally has no database state and therefore
    emits version ``1`` for the first candidate.  PostgreSQL owns the lineage:
    a conflict on ``(family_id, bundle_version)`` is checked for an identical
    content hash (idempotent replay), otherwise the candidate is copied to the
    next version and linked to the latest predecessor in the same transaction.
    Recording fakes used by contract tests return ``None`` from ``execute``;
    that means the insert outcome is unknown and is treated as successful so
    the SQL shape remains unchanged for those tests.
    """

    execute = getattr(session, "execute", None)
    if not callable(execute):
        raise TypeError("shadow candidate session must expose execute")
    result = await execute(_candidate_bundle_insert(bundle))
    if _insert_succeeded(result):
        return

    latest_statement = (
        select(
            evidence_bundles.c.bundle_id,
            evidence_bundles.c.bundle_version,
            evidence_bundles.c.content_hash,
        )
        .where(evidence_bundles.c.family_id == bundle.family_id)
        .order_by(desc(evidence_bundles.c.bundle_version), evidence_bundles.c.bundle_id)
        .limit(1)
    )
    # Competing corrected deliveries can race for the same next version. Each
    # retry gets a fresh READ COMMITTED snapshot and either observes its own
    # content (idempotent) or advances after the winner. The bound prevents a
    # pathological hot family from holding the shadow transaction forever.
    for _attempt in range(8):
        latest_result = await execute(latest_statement)
        mappings = getattr(latest_result, "mappings", None)
        latest = mappings().first() if callable(mappings) else None
        if latest is not None and str(latest.get("content_hash")) == bundle.content_hash:
            return
        latest_version = int(latest["bundle_version"]) if latest is not None else 0
        next_version = max(1, latest_version + 1)
        parent_id = str(latest["bundle_id"]) if latest is not None else None
        adjusted = bundle.model_copy(
            update={
                "bundle_version": next_version,
                "parent_bundle_version": latest_version if latest_version >= 1 else None,
            }
        )
        result = await execute(
            _candidate_bundle_insert_with_parent(
                adjusted,
                parent_bundle_id=parent_id,
            )
        )
        if _insert_succeeded(result):
            return
    raise RuntimeError("candidate Bundle version allocation exhausted")


def _insert_succeeded(result: object | None) -> bool:
    """Interpret SQLAlchemy rowcount while keeping SQL-recording fakes simple."""

    if result is None:
        return True
    rowcount = getattr(result, "rowcount", None)
    return rowcount is None or rowcount != 0


def _validate_shadow_record(record: _ShadowWriteRecord) -> None:
    batch_id = record.source_batch_id
    if not batch_id or batch_id != _source_batch_identity(record.batch):
        raise ValueError("shadow record source_batch_id does not match the source batch")
    if record.batch.isolation.tenant_scope != "public":
        raise ValueError("public Evidence requires a public batch partition")
    if len({locator.locator_id for locator in record.locators}) != len(record.locators):
        raise ValueError("shadow record locators must have unique identities")
    locators = {locator.locator_id: locator for locator in record.locators}
    for locator in record.locators:
        if locator.source_id != record.batch.source_id:
            raise ValueError("shadow locator source_id does not match the source batch")
        if locator.connector_id != record.batch.connector_id:
            raise ValueError("shadow locator connector_id does not match the source batch")
    for item in record.evidence_items:
        if item.status is not EvidenceStatus.CANDIDATE:
            raise ValueError("B1 shadow sink accepts candidate Evidence only")
        locator = locators.get(item.source_locator_id)
        if locator is None:
            raise ValueError("shadow Evidence item is missing its source locator")
        if item.schema_version != "food-evidence/v1":
            raise ValueError("shadow Evidence item has an unsupported schema_version")
        if item.media_ref_ids or item.derived_artifact_ids:
            raise ValueError(
                "shadow Evidence item contains references outside the atomic B1 projection"
            )
        if item.visibility.scope.value != "public" or item.visibility.tenant_scope != "public":
            raise ValueError("public Evidence requires public visibility")
        if locator.visibility != item.visibility:
            raise ValueError("Evidence visibility does not match its source locator")
        if not _reusable_license(locator.license):
            raise ValueError("shadow source locator license is not reusable")
        if not _reusable_license(item.license):
            raise ValueError("shadow Evidence license is not reusable")
        if not _license_at_least_as_restrictive(item.license, locator.license):
            raise ValueError("shadow Evidence license broadens its source locator")
        if not _retention_at_least_as_restrictive(item.retention, locator.retention):
            raise ValueError("shadow Evidence retention broadens its source locator")
        if item.content_hash != _evidence_content_hash(item):
            raise ValueError("shadow Evidence content_hash does not match its content")
    if (
        record.canonical_query is not None
        and record.canonical_query.canonical_query.isolation != record.batch.isolation
    ):
        raise ValueError("canonical query and source batch partitions must match")
    bundle = record.candidate_bundle
    item_ids = tuple(item.evidence_id for item in record.evidence_items)
    if (bundle is None) != (not item_ids):
        raise ValueError("shadow candidate Bundle must match the Evidence item set")
    if bundle is not None:
        if bundle.state is not BundleState.CANDIDATE:
            raise ValueError("candidate repository accepts candidate Bundles only")
        if set(bundle.evidence_ids) != set(item_ids) or len(bundle.evidence_ids) != len(item_ids):
            raise ValueError("candidate Bundle evidence_ids must match the item set")
        if record.canonical_query is not None and bundle.family_id != record.canonical_query.family_id:
            raise ValueError("candidate Bundle family_id does not match canonical query")


def _source_batch_identity(batch: CanonicalSourceBatch) -> str:
    encoded = json.dumps(
        batch.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"batch.{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _evidence_content_hash(item: EvidenceItem) -> str:
    """Recompute the B1 claim hash at the persistence boundary."""

    encoded = json.dumps(
        {
            "claim_type": item.claim_type,
            "claim_value": item.claim_value,
            "evidence_type": item.evidence_type,
            "source_locator_id": item.source_locator_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reusable_license(license: object) -> bool:
    status = getattr(getattr(license, "status", None), "value", None)
    allowed_use = getattr(getattr(license, "allowed_use", None), "value", None)
    expires_at = getattr(license, "expires_at", None)
    return (
        status == "known"
        and allowed_use in {"internal_reuse", "redistributable"}
        and (expires_at is None or expires_at > datetime.now(UTC))
    )


def _license_at_least_as_restrictive(candidate: object, source: object) -> bool:
    rank = {"extract_only": 0, "internal_reuse": 1, "redistributable": 2}
    candidate_status = getattr(getattr(candidate, "status", None), "value", None)
    source_status = getattr(getattr(source, "status", None), "value", None)
    candidate_use = getattr(getattr(candidate, "allowed_use", None), "value", None)
    source_use = getattr(getattr(source, "allowed_use", None), "value", None)
    if candidate_status != source_status or candidate_use not in rank or source_use not in rank:
        return False
    if rank[candidate_use] > rank[source_use]:
        return False
    if getattr(source, "attribution_required", False) and not getattr(
        candidate, "attribution_required", False
    ):
        return False
    source_expires = getattr(source, "expires_at", None)
    candidate_expires = getattr(candidate, "expires_at", None)
    return source_expires is None or (
        candidate_expires is not None and candidate_expires <= source_expires
    )


def _retention_at_least_as_restrictive(candidate: object, source: object) -> bool:
    if getattr(source, "legal_hold", False) and not getattr(candidate, "legal_hold", False):
        return False
    source_duration = getattr(source, "duration_seconds", None)
    candidate_duration = getattr(candidate, "duration_seconds", None)
    if source_duration is None:
        return candidate_duration is None
    return candidate_duration is None or candidate_duration >= source_duration


def _batch_created_at(batch: CanonicalSourceBatch) -> datetime:
    timestamps = tuple(
        item.captured_at
        for item in (*batch.documents, *batch.comments, *batch.authors, *batch.media_refs)
    )
    return max(timestamps, default=datetime.now(UTC))


class SQLAlchemyEvidenceShadowRepository(SQLAlchemyCandidateBundleRepository):
    """Named B1 sink facade sharing the candidate repository implementation."""


SQLAlchemyEvidenceShadowSink = SQLAlchemyEvidenceShadowRepository


__all__ = [
    "SQLAlchemyCandidateBundleRepository",
    "SQLAlchemyEvidenceShadowRepository",
    "SQLAlchemyEvidenceShadowSink",
]
