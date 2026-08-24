"""Add PostgreSQL-owned Personalization memory and outbox facts for B3."""

from __future__ import annotations

from alembic import op
from xhs_food.foundation.memory_schema import B3_MEMORY_INDEXES, B3_MEMORY_TABLES

revision = "20260824_0007_b3_personalization_memory"
down_revision = "20260824_0006_b0_reliable_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Provision only additive private-memory tables; never inspect legacy data."""

    for table in B3_MEMORY_TABLES:
        op.create_table(table.name, *table.columns, *table.constraints)
    for index in B3_MEMORY_INDEXES:
        op.create_index(
            index.name,
            index.table.name,
            [column.name for column in index.columns],
            unique=bool(index.unique),
        )


def downgrade() -> None:
    """Remove only B3 tables during an explicit migration drill."""

    for index in reversed(B3_MEMORY_INDEXES):
        op.drop_index(index.name, table_name=index.table.name)
    for table in reversed(B3_MEMORY_TABLES):
        op.drop_table(table.name)
