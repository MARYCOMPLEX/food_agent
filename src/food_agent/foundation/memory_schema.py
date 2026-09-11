"""Alembic-owned PostgreSQL metadata for private memory authority facts.

Redis windows, summaries, embeddings, and framework messages remain derived
projections and are not represented as authority tables here.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

MEMORY_METADATA = MetaData()

conversation_turns = Table(
    "conversation_turns",
    MEMORY_METADATA,
    Column("turn_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("role", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("metadata", JSONB, nullable=False),
    Column("source_event_id", String(256), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

session_state = Table(
    "session_state",
    MEMORY_METADATA,
    Column("tenant_id", String(256), primary_key=True),
    Column("subject_kind", String(32), primary_key=True),
    Column("subject_id", String(256), primary_key=True),
    Column("session_id", String(256), primary_key=True),
    Column("state", JSONB, nullable=False),
    Column("authority_version", String(128), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

memory_records = Table(
    "memory_records",
    MEMORY_METADATA,
    Column("record_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("layer", String(64), nullable=False),
    Column("memory_key", String(256), nullable=False),
    Column("value", JSONB, nullable=False),
    Column("confidence", Float),
    Column("source_event_ids", JSONB, nullable=False),
    Column("consent", JSONB, nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("status", String(32), nullable=False),
    Column("supersedes_record_id", String(256)),
    Column("policy_version", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

memory_events = Table(
    "memory_events",
    MEMORY_METADATA,
    Column("event_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("event_type", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

preference_snapshots = Table(
    "preference_snapshots",
    MEMORY_METADATA,
    Column("snapshot_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("snapshot_version", Integer, nullable=False),
    Column("policy_version", String(128), nullable=False),
    Column("source_record_versions", JSONB, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "subject_kind",
        "subject_id",
        "session_id",
        "snapshot_version",
        name="uq_preference_snapshot_scope_version",
    ),
)

memory_summaries = Table(
    "memory_summaries",
    MEMORY_METADATA,
    Column("summary_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("summary_version", Integer, nullable=False),
    Column("source_authority_version", String(128), nullable=False),
    Column("profile_version", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "subject_kind",
        "subject_id",
        "session_id",
        "summary_version",
        name="uq_memory_summary_scope_version",
    ),
)

consent_events = Table(
    "consent_events",
    MEMORY_METADATA,
    Column("consent_event_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("basis", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("policy_version", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

claim_events = Table(
    "claim_events",
    MEMORY_METADATA,
    Column("claim_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("anonymous_subject_id", String(256), nullable=False),
    Column("session_id", String(256), nullable=False),
    Column("target_user_id", String(256), nullable=False),
    Column("status", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

outbox = Table(
    "outbox",
    MEMORY_METADATA,
    Column("outbox_id", String(256), primary_key=True),
    Column("tenant_id", String(256), nullable=False),
    Column("subject_kind", String(32), nullable=False),
    Column("subject_id", String(256), nullable=False),
    Column("session_id", String(256)),
    Column("event_type", String(128), nullable=False),
    Column("aggregate_id", String(256), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("idempotency_key", String(512), nullable=False, unique=True),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "ix_conversation_turns_scope_time",
    conversation_turns.c.tenant_id,
    conversation_turns.c.subject_kind,
    conversation_turns.c.subject_id,
    conversation_turns.c.session_id,
    conversation_turns.c.occurred_at,
)
Index(
    "ix_memory_records_scope_status",
    memory_records.c.tenant_id,
    memory_records.c.subject_kind,
    memory_records.c.subject_id,
    memory_records.c.session_id,
    memory_records.c.status,
)
Index(
    "ix_memory_events_scope_time",
    memory_events.c.tenant_id,
    memory_events.c.subject_kind,
    memory_events.c.subject_id,
    memory_events.c.session_id,
    memory_events.c.occurred_at,
)
Index(
    "ix_preference_snapshots_scope_time",
    preference_snapshots.c.tenant_id,
    preference_snapshots.c.subject_kind,
    preference_snapshots.c.subject_id,
    preference_snapshots.c.session_id,
    preference_snapshots.c.generated_at,
)
Index("ix_memory_outbox_pending", outbox.c.processed_at, outbox.c.available_at)

B3_MEMORY_TABLES = (
    conversation_turns,
    session_state,
    memory_records,
    memory_events,
    preference_snapshots,
    memory_summaries,
    consent_events,
    claim_events,
    outbox,
)
B3_MEMORY_INDEXES = tuple(index for table in B3_MEMORY_TABLES for index in table.indexes)

__all__ = [
    "B3_MEMORY_INDEXES",
    "B3_MEMORY_TABLES",
    "MEMORY_METADATA",
    "claim_events",
    "consent_events",
    "conversation_turns",
    "memory_events",
    "memory_records",
    "memory_summaries",
    "outbox",
    "preference_snapshots",
    "session_state",
]
