"""Add B2 profile read pointer for conditional Bundle activation."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, MetaData, String, Table

from alembic import op

revision = "20260824_0004_b2_activate"
down_revision = "20260824_0003_b2_query_reuse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = MetaData()
    table = Table(
        "embedding_profile_read_pointer",
        metadata,
        Column("pointer_key", String(64), primary_key=True),
        Column(
            "profile_id",
            String(128),
            ForeignKey("embedding_profiles.profile_id", name="fk_embedding_read_profile"),
            nullable=False,
        ),
        Column("model_version", String(64), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(table.name, *table.columns, *table.constraints)


def downgrade() -> None:
    op.drop_table("embedding_profile_read_pointer")
