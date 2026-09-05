"""Add durable source-batch provenance for the B1 shadow sink."""

from __future__ import annotations

from alembic import op
from xhs_food.foundation.evidence_schema import B1_SOURCE_BATCH_TABLES

revision = "20260905_0012_b1_source_batches"
down_revision = "20260905_0011_b2_freshness_watermark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only the additive source-batch provenance tables."""

    for table in B1_SOURCE_BATCH_TABLES:
        op.create_table(table.name, *table.columns, *table.constraints)
        for index in table.indexes:
            op.create_index(
                index.name,
                table.name,
                [column.name for column in index.columns],
                unique=bool(index.unique),
            )


def downgrade() -> None:
    """Remove only source-batch provenance during an explicit rollback drill."""

    for table in reversed(B1_SOURCE_BATCH_TABLES):
        for index in reversed(tuple(table.indexes)):
            op.drop_index(index.name, table_name=table.name)
        op.drop_table(table.name)


__all__ = ["down_revision", "revision", "upgrade", "downgrade"]
