"""Add immutable public Bundle derivation receipts for B2 refresh."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260824_0005_b2_derivations"
down_revision = "20260824_0004_b2_activate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = MetaData()
    table = Table(
        "evidence_bundle_derivations",
        metadata,
        Column(
            "bundle_id",
            String(256),
            ForeignKey("evidence_bundles.bundle_id", name="fk_derivation_bundle"),
            primary_key=True,
        ),
        Column("family_id", String(256), nullable=False),
        Column("bundle_version", Integer, nullable=False),
        Column(
            "profile_id",
            String(128),
            ForeignKey("embedding_profiles.profile_id", name="fk_derivation_profile"),
            nullable=False,
        ),
        Column("profile_version", String(64), nullable=False),
        Column("features", JSONB, nullable=False),
        Column("public_scores", JSONB, nullable=False),
        Column("index_metadata", JSONB, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(table.name, *table.columns, *table.constraints)


def downgrade() -> None:
    op.drop_table("evidence_bundle_derivations")
