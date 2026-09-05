"""PostgreSQL adapter for immutable Bundle feature/score derivations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import BundleDerivation, BundleDerivationRepository
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import bundle_derivations

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyBundleDerivationRepository(BundleDerivationRepository):
    """Persist one derivation receipt per immutable candidate Bundle."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def save_candidate_derivation(self, derivation: BundleDerivation) -> None:
        index = derivation.index.model_dump(mode="json")
        statement = (
            insert(bundle_derivations)
            .values(
                bundle_id=derivation.bundle_id,
                family_id=derivation.family_id,
                bundle_version=derivation.bundle_version,
                profile_id=derivation.profile.profile_id,
                profile_version=derivation.profile.model_version,
                features=derivation.features,
                public_scores=derivation.public_scores,
                index_metadata=index,
                content_hash=derivation.content_hash,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[bundle_derivations.c.bundle_id])
            .returning(bundle_derivations.c.bundle_id)
        )
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            result = await session.execute(statement)
            inserted, known = _insert_result(result)
            if known and not inserted:
                row = (
                    (
                        await session.execute(
                            select(bundle_derivations).where(
                                bundle_derivations.c.bundle_id == derivation.bundle_id
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                _validate_existing_row(row, derivation)
            await unit.commit()


def _insert_result(result: object | None) -> tuple[bool, bool]:
    """Interpret INSERT ... RETURNING while keeping recording fakes usable."""

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


def _validate_existing_row(
    row: Mapping[str, object] | None, derivation: BundleDerivation
) -> None:
    if row is None:
        raise RuntimeError("derivation insert conflicted but the existing row is unavailable")
    expected_index = derivation.index.model_dump(mode="json")
    if (
        str(row.get("bundle_id")) != derivation.bundle_id
        or str(row.get("family_id")) != derivation.family_id
        or int(row.get("bundle_version", -1)) != derivation.bundle_version
        or str(row.get("profile_id")) != derivation.profile.profile_id
        or str(row.get("profile_version")) != derivation.profile.model_version
        or row.get("features") != derivation.features
        or row.get("public_scores") != derivation.public_scores
        or row.get("index_metadata") != expected_index
        or str(row.get("content_hash")) != derivation.content_hash
    ):
        raise ValueError("Bundle derivation conflicts with an existing immutable row")


__all__ = ["SQLAlchemyBundleDerivationRepository"]
