"""SQLAlchemy Core repository for the B1 Canonical Query shadow projection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import CanonicalQueryResult
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import canonical_queries

from .evidence_bundle_repository import (
    SQLAlchemyEvidenceShadowRepository,
    SQLAlchemyEvidenceShadowSink,
)

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyCanonicalQueryShadowRepository:
    """Persist one canonical result with one owner session and transaction."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def save(self, result: CanonicalQueryResult) -> str:
        query = result.canonical_query
        isolation = query.isolation
        # Personal constraints are classifier output for request-time policy,
        # not public Evidence identity.  Enforce the boundary again at the
        # persistence adapter in case a caller bypasses ShadowSourceConnector.
        public_classification = result.classification.model_copy(
            update={"personal_constraints": ()}
        )
        statement = (
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
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(statement)
            await unit.commit()
        return result.canonical_key

__all__ = [
    "SQLAlchemyCanonicalQueryShadowRepository",
    "SQLAlchemyEvidenceShadowRepository",
    "SQLAlchemyEvidenceShadowSink",
]
