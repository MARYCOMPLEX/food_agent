"""Alembic-owned SQLAlchemy Core metadata for the B1 evidence shadow schema.

The tables are additive and isolated from legacy ``chat_history`` and its
existing ``VECTOR(4096)`` column.  No function in this module creates or alters
tables at runtime; the Alembic revision is the only schema writer.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

SHADOW_METADATA = MetaData()

canonical_queries = Table(
    "canonical_queries",
    SHADOW_METADATA,
    Column("canonical_key", String(256), primary_key=True),
    Column("family_id", String(256), nullable=False),
    Column("tenant_scope", String(128), nullable=False),
    Column("language", String(32), nullable=False),
    Column("region", String(8), nullable=False),
    Column("schema_version", String(64), nullable=False),
    Column("normalizer_version", String(64), nullable=False),
    Column("classifier_version", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

source_locators = Table(
    "evidence_source_locators",
    SHADOW_METADATA,
    Column("locator_id", String(256), primary_key=True),
    Column("source_id", String(128), nullable=False),
    Column("connector_id", String(128), nullable=False),
    Column("connector_version", String(64), nullable=False),
    Column("external_item_id", String(512), nullable=False),
    Column("canonical_url", Text, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("watermark", Text),
    Column("payload", JSONB, nullable=False),
)

evidence_items = Table(
    "evidence_items",
    SHADOW_METADATA,
    Column("evidence_id", String(256), primary_key=True),
    Column(
        "source_locator_id",
        String(256),
        ForeignKey("evidence_source_locators.locator_id", name="fk_evidence_locator"),
        nullable=False,
    ),
    Column("content_hash", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
)

evidence_bundles = Table(
    "evidence_bundles",
    SHADOW_METADATA,
    Column("bundle_id", String(256), primary_key=True),
    Column("family_id", String(256), nullable=False),
    Column("bundle_version", Integer, nullable=False),
    Column("parent_bundle_id", String(256)),
    Column("state", String(32), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("family_id", "bundle_version", name="uq_evidence_bundle_family_version"),
)

evidence_bundle_current = Table(
    "evidence_bundle_current",
    SHADOW_METADATA,
    Column("family_id", String(256), primary_key=True),
    Column(
        "bundle_id",
        String(256),
        ForeignKey("evidence_bundles.bundle_id", name="fk_current_bundle"),
        nullable=False,
    ),
    Column("bundle_version", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

embedding_profiles = Table(
    "embedding_profiles",
    SHADOW_METADATA,
    Column("profile_id", String(128), primary_key=True),
    Column("model_id", String(128), nullable=False),
    Column("model_version", String(64), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("distance", String(32), nullable=False),
    Column("normalized", Boolean, nullable=False),
    Column("schema_version", String(64), nullable=False),
    Column("metadata", JSONB, nullable=False),
)

query_embeddings = Table(
    "canonical_query_embeddings",
    SHADOW_METADATA,
    Column(
        "canonical_key",
        String(256),
        ForeignKey("canonical_queries.canonical_key", name="fk_embedding_query"),
        primary_key=True,
    ),
    Column(
        "profile_id",
        String(128),
        ForeignKey("embedding_profiles.profile_id", name="fk_embedding_profile"),
        primary_key=True,
    ),
    Column("vector", Vector(1024), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
)

backfill_cursors = Table(
    "embedding_backfill_cursors",
    SHADOW_METADATA,
    Column("profile_id", String(128), primary_key=True),
    Column("source_relation", String(256), nullable=False),
    Column("last_source_key", String(256)),
    Column("processed_rows", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("last_batch_hash", String(64)),
    Column("schema_version", String(64), nullable=False),
)

Index("ix_canonical_queries_family", canonical_queries.c.family_id)
Index("ix_evidence_items_locator", evidence_items.c.source_locator_id)
Index("ix_evidence_bundles_family", evidence_bundles.c.family_id)

B1_SHADOW_TABLES = (
    canonical_queries,
    source_locators,
    evidence_items,
    evidence_bundles,
    evidence_bundle_current,
    embedding_profiles,
    query_embeddings,
    backfill_cursors,
)

__all__ = [
    "B1_SHADOW_TABLES",
    "SHADOW_METADATA",
    "backfill_cursors",
    "canonical_queries",
    "embedding_profiles",
    "evidence_bundle_current",
    "evidence_bundles",
    "evidence_items",
    "query_embeddings",
    "source_locators",
]
