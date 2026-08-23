"""Offline proof for B1 schema authority, profiles and shadow repository wiring."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from xhs_food.composition.adapters import SQLAlchemyCanonicalQueryShadowRepository
from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BackfillRow,
    CanonicalQueryResult,
    EmbeddingProfile,
    advance_backfill_cursor,
    initial_backfill_cursor,
    validate_embedding_vector,
)
from xhs_food.domain_packs.food.pack import FoodPack
from xhs_food.evidence import CanonicalQueryNormalizer
from xhs_food.foundation.evidence_schema import SHADOW_METADATA

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "authority"
MIGRATION = ROOT / "alembic" / "versions" / "20260824_0001_b1_shadow_schema.py"


def _result() -> CanonicalQueryResult:
    value = json.loads((FIXTURES / "canonical_query_v1.json").read_text(encoding="utf-8"))
    value["query"]["constraints"] = [
        {"constraint_id": "food-type", "key": "food_type", "operator": "eq", "value": "local_food"}
    ]
    return CanonicalQueryNormalizer(FoodPack()).normalize(value)


@pytest.mark.unit
def test_bge_profile_is_independent_and_dimension_pinned() -> None:
    assert BGE_M3_PROFILE_V1.model_dump(mode="json") == {
        "schema_version": "embedding-profile/v1",
        "profile_id": "profile_v1",
        "model_id": "bge-m3",
        "model_version": "bge-m3/v1",
        "dimensions": 1024,
        "distance": "cosine",
        "normalized": True,
    }
    with pytest.raises(ValueError, match="dimension mismatch"):
        validate_embedding_vector(BGE_M3_PROFILE_V1, (0.0,))
    other = EmbeddingProfile(
        profile_id="other_profile",
        model_id="other-model",
        model_version="other-model/v1",
        dimensions=4096,
    )
    with pytest.raises(ValueError, match="pinned"):
        initial_backfill_cursor(other)


@pytest.mark.unit
def test_backfill_cursor_replays_the_same_page_and_rejects_overlap() -> None:
    cursor = initial_backfill_cursor()
    rows = (
        BackfillRow(source_key="q-001", content_hash="1" * 64),
        BackfillRow(source_key="q-002", content_hash="2" * 64),
    )
    advanced = advance_backfill_cursor(cursor, rows)
    assert advanced.processed_rows == 2
    assert advance_backfill_cursor(advanced, rows) == advanced
    with pytest.raises(ValueError, match="overlaps"):
        advance_backfill_cursor(
            advanced,
            (BackfillRow(source_key="q-002", content_hash="2" * 64),),
        )


@pytest.mark.unit
def test_alembic_b1_revision_is_additive_and_never_uses_runtime_create_if_not_exists() -> None:
    spec = importlib.util.spec_from_file_location("b1_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    upgrade_sql = StringIO()
    upgrade_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": upgrade_sql},
    )
    with Operations.context(upgrade_context):
        migration.upgrade()
    sql = upgrade_sql.getvalue()
    assert "CREATE TABLE IF NOT EXISTS" not in sql
    assert "VECTOR(1024)" in sql
    assert "VECTOR(4096)" not in sql
    assert all(table in sql for table in SHADOW_METADATA.tables)
    assert "uq_evidence_bundles_family_content" not in sql

    downgrade_sql = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": downgrade_sql},
    )
    with Operations.context(downgrade_context):
        migration.downgrade()
    assert "uq_evidence_bundles_family_content" not in downgrade_sql.getvalue()
    assert "DROP TABLE chat_history" not in downgrade_sql.getvalue()


@pytest.mark.unit
async def test_shadow_repository_uses_one_uow_and_one_postgres_insert() -> None:
    class Session:
        def __init__(self) -> None:
            self.statements: list[Any] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(statement)

    class Unit:
        def __init__(self, session: Session) -> None:
            self.session = session
            self.commits = 0

        async def __aenter__(self) -> Unit:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def session_for_adapter(self) -> Session:
            return self.session

        async def commit(self) -> None:
            self.commits += 1

    session = Session()
    unit = Unit(session)
    repository = SQLAlchemyCanonicalQueryShadowRepository(lambda: unit)  # type: ignore[arg-type]
    result = _result()
    assert await repository.save(result) == result.canonical_key
    assert unit.commits == 1
    assert len(session.statements) == 1
    compiled = str(session.statements[0].compile(dialect=postgresql_dialect()))
    assert "INSERT INTO canonical_queries" in compiled
    assert "ON CONFLICT (canonical_key) DO NOTHING" in compiled
