"""SQLAlchemy adapter for the B1 profile-aware embedding shadow tables."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from xhs_food.contracts import (
    EmbeddingBackfillCursor,
    EmbeddingProfile,
    EmbeddingShadowRepository,
    EmbeddingShadowRow,
)
from xhs_food.foundation.database import SQLAlchemyUnitOfWork
from xhs_food.foundation.evidence_schema import backfill_cursors, query_embeddings

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]


class SQLAlchemyEmbeddingShadowRepository(EmbeddingShadowRepository):
    """Persist profile rows and cursors in one explicit owner transaction."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def put_embedding(
        self,
        canonical_key: str,
        profile: EmbeddingProfile,
        vector: tuple[float, ...],
        content_hash: str,
        generated_at: datetime,
    ) -> None:
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            await session.execute(
                insert(query_embeddings)
                .values(
                    canonical_key=canonical_key,
                    profile_id=profile.profile_id,
                    vector=list(vector),
                    content_hash=content_hash,
                    generated_at=generated_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[query_embeddings.c.canonical_key, query_embeddings.c.profile_id]
                )
            )
            result = await session.execute(
                text(
                    "SELECT content_hash FROM canonical_query_embeddings "
                    "WHERE canonical_key = :canonical_key AND profile_id = :profile_id"
                ),
                {"canonical_key": canonical_key, "profile_id": profile.profile_id},
            )
            row = result.mappings().first()
            if row is not None and str(row.get("content_hash")) != content_hash:
                raise ValueError("embedding content hash conflicts with existing profile row")
            await unit.commit()

    async def get_embedding(
        self, canonical_key: str, profile: EmbeddingProfile
    ) -> EmbeddingShadowRow | None:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    "SELECT canonical_key, profile_id, vector, content_hash, generated_at "
                    "FROM canonical_query_embeddings "
                    "WHERE canonical_key = :canonical_key AND profile_id = :profile_id"
                ),
                {"canonical_key": canonical_key, "profile_id": profile.profile_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return EmbeddingShadowRow(
                canonical_key=str(row["canonical_key"]),
                profile_id=str(row["profile_id"]),
                vector=_vector_tuple(row.get("vector")),
                content_hash=str(row["content_hash"]),
                generated_at=row["generated_at"],
            )

    async def load_backfill_cursor(
        self, profile: EmbeddingProfile
    ) -> EmbeddingBackfillCursor | None:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    "SELECT profile_id, source_relation, last_source_key, processed_rows, "
                    "content_hash, last_batch_hash, schema_version "
                    "FROM embedding_backfill_cursors WHERE profile_id = :profile_id"
                ),
                {"profile_id": profile.profile_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return EmbeddingBackfillCursor.model_validate(
                {
                    "profile_id": row["profile_id"],
                    "source_relation": row["source_relation"],
                    "last_source_key": row["last_source_key"],
                    "processed_rows": row["processed_rows"],
                    "content_hash": row["content_hash"],
                    "last_batch_hash": row["last_batch_hash"],
                    "schema_version": row["schema_version"],
                }
            )

    async def save_backfill_cursor(self, cursor: EmbeddingBackfillCursor) -> None:
        async with self._unit_of_work_factory() as unit:
            await unit.session_for_adapter().execute(
                insert(backfill_cursors)
                .values(**cursor.model_dump(mode="json"))
                .on_conflict_do_update(
                    index_elements=[backfill_cursors.c.profile_id],
                    set_={
                        "source_relation": cursor.source_relation,
                        "last_source_key": cursor.last_source_key,
                        "processed_rows": cursor.processed_rows,
                        "content_hash": cursor.content_hash,
                        "last_batch_hash": cursor.last_batch_hash,
                        "schema_version": cursor.schema_version,
                    },
                )
            )
            await unit.commit()


def _vector_tuple(value: object) -> tuple[float, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise TypeError("stored embedding vector must be an array")
    return tuple(float(item) for item in value)


__all__ = ["SQLAlchemyEmbeddingShadowRepository"]
