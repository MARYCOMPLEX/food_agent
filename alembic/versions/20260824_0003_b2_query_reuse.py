"""Add B2 Query Family aliases, freshness state, and refresh claims."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260824_0003_b2_query_reuse"
down_revision = "20260824_0002_b1_bundle_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    metadata = MetaData()
    aliases = Table(
        "query_family_aliases",
        metadata,
        Column("alias_id", String(256), primary_key=True),
        Column("family_id", String(256), nullable=False),
        Column("canonical_key", String(256), nullable=False),
        Column("alias_text", Text, nullable=False),
        Column("language", String(32), nullable=False),
        Column("region", String(8), nullable=False),
        Column("rule_version", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("family_id", "alias_text", name="uq_query_family_alias_text"),
    )
    freshness = Table(
        "query_family_freshness",
        metadata,
        Column("family_id", String(256), primary_key=True),
        Column("bundle_version", Integer),
        Column("verified_at", DateTime(timezone=True)),
        Column("coverage", JSONB, nullable=False),
        Column("watermarks", JSONB, nullable=False),
        Column("active_refresh_workflow_id", String(256)),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    claims = Table(
        "query_refresh_claims",
        metadata,
        Column("claim_key", String(256), primary_key=True),
        Column("family_id", String(256), nullable=False),
        Column("scope_hash", String(64), nullable=False),
        Column("policy_version", String(64), nullable=False),
        Column("workflow_id", String(256), nullable=False),
        Column("status", String(32), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint(
            "family_id",
            "scope_hash",
            "policy_version",
            name="uq_query_refresh_claim_scope",
        ),
    )
    for table in (aliases, freshness, claims):
        op.create_table(table.name, *table.columns, *table.constraints)
    op.create_index("ix_query_family_aliases_family", "query_family_aliases", ["family_id"])
    op.create_index(
        "ix_query_family_aliases_canonical",
        "query_family_aliases",
        ["canonical_key"],
    )
    op.create_index(
        "ix_query_family_aliases_alias_trgm",
        "query_family_aliases",
        ["alias_text"],
        postgresql_using="gin",
        postgresql_ops={"alias_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_query_family_aliases_alias_trgm", table_name="query_family_aliases")
    op.drop_index("ix_query_family_aliases_canonical", table_name="query_family_aliases")
    op.drop_index("ix_query_family_aliases_family", table_name="query_family_aliases")
    op.drop_table("query_refresh_claims")
    op.drop_table("query_family_freshness")
    op.drop_table("query_family_aliases")
