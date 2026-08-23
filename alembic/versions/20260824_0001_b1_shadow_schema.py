"""Additive B1 canonical query, evidence and embedding shadow tables."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.schema import CreateIndex, CreateTable, DropIndex

from alembic import op
from xhs_food.foundation.evidence_schema import B1_SHADOW_TABLES

revision = "20260824_0001_b1_shadow"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only B1-owned tables; legacy tables are never inspected or changed."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    migration_metadata = MetaData()
    tables = tuple(table.to_metadata(migration_metadata) for table in B1_SHADOW_TABLES)
    for table in tables:
        op.execute(CreateTable(table))
        for index in table.indexes:
            # The immutable candidate dedupe index is deliberately introduced
            # by revision 0002 after any existing candidate rows are checked.
            # Keep it in shared metadata for repository contracts without
            # creating it twice during an upgrade from a clean database.
            if index.name == "uq_evidence_bundles_family_content":
                continue
            op.execute(CreateIndex(index))


def downgrade() -> None:
    """Remove only the unactivated B1 shadow tables during a rollback drill."""

    migration_metadata = MetaData()
    tables = tuple(table.to_metadata(migration_metadata) for table in B1_SHADOW_TABLES)
    for table in reversed(tables):
        for index in table.indexes:
            if index.name == "uq_evidence_bundles_family_content":
                continue
            op.execute(DropIndex(index))
        op.drop_table(table.name)
