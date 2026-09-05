"""Persist the connector-owned watermark advancement bit for B2 freshness."""

from __future__ import annotations

from sqlalchemy import Boolean, Column

from alembic import op

revision = "20260905_0011_b2_freshness_watermark"
down_revision = "20260904_0010_shop_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "query_family_freshness",
        Column("watermark_advanced", Boolean, nullable=False, server_default="false"),
    )
    op.alter_column("query_family_freshness", "watermark_advanced", server_default=None)


def downgrade() -> None:
    op.drop_column("query_family_freshness", "watermark_advanced")
