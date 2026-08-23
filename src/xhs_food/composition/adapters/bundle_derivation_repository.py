"""PostgreSQL adapter for immutable Bundle feature/score derivations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

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
        statement = insert(bundle_derivations).values(
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
        ).on_conflict_do_nothing(index_elements=[bundle_derivations.c.bundle_id])
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()


__all__ = ["SQLAlchemyBundleDerivationRepository"]
