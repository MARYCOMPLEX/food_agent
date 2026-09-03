"""PostgreSQL candidate Evidence Bundle shadow repository."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import BundleState, EvidenceBundle, EvidenceItem
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import evidence_bundles, evidence_items

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyCandidateBundleRepository:
    """Write immutable candidates only; current pointers are a later B2 concern."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None:
        statement = select(evidence_bundles.c.payload).where(
            evidence_bundles.c.bundle_id == bundle_id
        )
        async with self._unit_of_work_factory() as unit:
            row = (await unit.session_for_adapter().execute(statement)).mappings().first()
        if row is None:
            return None
        return EvidenceBundle.model_validate(row["payload"])

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]:
        if not evidence_ids:
            return ()
        statement = select(evidence_items.c.evidence_id, evidence_items.c.payload).where(
            evidence_items.c.evidence_id.in_(evidence_ids)
        )
        async with self._unit_of_work_factory() as unit:
            rows = (await unit.session_for_adapter().execute(statement)).mappings().all()
        by_id = {
            str(row["evidence_id"]): EvidenceItem.model_validate(row["payload"]) for row in rows
        }
        return tuple(by_id[item_id] for item_id in evidence_ids if item_id in by_id)

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
                await session.execute(
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
            await session.execute(
                insert(evidence_bundles)
                .values(
                    bundle_id=bundle.bundle_id,
                    family_id=bundle.family_id,
                    bundle_version=bundle.bundle_version,
                    parent_bundle_id=(
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
            await unit.commit()
        return bundle


__all__ = ["SQLAlchemyCandidateBundleRepository"]
