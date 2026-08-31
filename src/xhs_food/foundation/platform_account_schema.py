"""Alembic-owned metadata for platform account and login authority.

The tables in this module describe *metadata* for external platform accounts.
Session material is represented only by an authenticated ciphertext envelope;
the plaintext cookie/browser state is never part of SQLAlchemy metadata or a
serializable project contract.  The module intentionally contains no schema
creation calls.  ``alembic/versions/20260831_0009_platform_account_authority``
is the sole writer for these tables.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

PLATFORM_ACCOUNT_METADATA = MetaData()


platform_accounts = Table(
    "platform_accounts",
    PLATFORM_ACCOUNT_METADATA,
    # The natural account identity is composite.  ``account_ref`` may be the
    # same local alias in two tenants or channels without sharing state.
    Column("tenant_id", String(128), primary_key=True),
    Column("platform", String(32), primary_key=True),
    Column("account_ref", String(128), primary_key=True),
    Column("alias", String(256), nullable=False),
    Column("provider_subject_id", String(256)),
    Column("status", String(32), nullable=False),
    Column("health", String(32), nullable=False),
    Column("session_version", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "platform", "alias", name="uq_platform_account_alias"),
    UniqueConstraint(
        "tenant_id",
        "platform",
        "provider_subject_id",
        name="uq_platform_account_subject",
    ),
)


platform_account_sessions = Table(
    "platform_account_sessions",
    PLATFORM_ACCOUNT_METADATA,
    Column("session_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("account_ref", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    # AES-GCM envelope parts.  These are opaque bytes; no plaintext state or
    # filesystem path is persisted in this relation.
    Column("ciphertext", LargeBinary, nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("auth_tag", LargeBinary, nullable=False),
    Column("key_ref", String(256), nullable=False),
    Column("key_version", String(128), nullable=False),
    Column("payload_digest", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("superseded_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("metadata", JSONB, nullable=False),
    UniqueConstraint(
        "tenant_id",
        "platform",
        "account_ref",
        "version",
        name="uq_platform_session_account_version",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "platform", "account_ref"],
        ["platform_accounts.tenant_id", "platform_accounts.platform", "platform_accounts.account_ref"],
        name="fk_platform_session_account",
    ),
)


platform_login_flows = Table(
    "platform_login_flows",
    PLATFORM_ACCOUNT_METADATA,
    Column("flow_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("account_ref", String(128), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("qr_object_key", Text),
    Column("qr_expires_at", DateTime(timezone=True)),
    Column("provider_subject_id", String(256)),
    Column("error_code", String(128)),
    Column("error_message", Text),
    Column("metadata", JSONB, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "platform", "account_ref"],
        ["platform_accounts.tenant_id", "platform_accounts.platform", "platform_accounts.account_ref"],
        name="fk_platform_login_account",
    ),
)


platform_account_grants = Table(
    "platform_account_grants",
    PLATFORM_ACCOUNT_METADATA,
    Column("grant_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("account_ref", String(128), nullable=False),
    Column("principal_id", String(256), nullable=False),
    Column("permissions", JSONB, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("metadata", JSONB, nullable=False),
    UniqueConstraint(
        "tenant_id",
        "platform",
        "account_ref",
        "principal_id",
        name="uq_platform_grant_account_principal",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "platform", "account_ref"],
        ["platform_accounts.tenant_id", "platform_accounts.platform", "platform_accounts.account_ref"],
        name="fk_platform_grant_account",
    ),
)


platform_account_leases = Table(
    "platform_account_leases",
    PLATFORM_ACCOUNT_METADATA,
    Column("lease_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("account_ref", String(128), nullable=False),
    Column("task_id", String(256), nullable=False),
    Column("owner_id", String(256), nullable=False),
    Column("owner_token_digest", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_heartbeat_at", DateTime(timezone=True), nullable=False),
    Column("released_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["tenant_id", "platform", "account_ref"],
        ["platform_accounts.tenant_id", "platform_accounts.platform", "platform_accounts.account_ref"],
        name="fk_platform_lease_account",
    ),
)


platform_account_health_events = Table(
    "platform_account_health_events",
    PLATFORM_ACCOUNT_METADATA,
    Column("event_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("platform", String(32), nullable=False),
    Column("account_ref", String(128), nullable=False),
    Column("signal", String(32), nullable=False),
    Column("health", String(32), nullable=False),
    Column("session_version", Integer),
    Column("task_id", String(256)),
    Column("reason", Text),
    Column("metadata", JSONB, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "platform", "account_ref"],
        ["platform_accounts.tenant_id", "platform_accounts.platform", "platform_accounts.account_ref"],
        name="fk_platform_health_account",
    ),
)


# Ordinary lookup indexes are intentionally non-unique.  The active-session
# and active-lease invariants are represented by PostgreSQL partial unique
# indexes so expired/revoked history remains auditable.
Index(
    "ix_platform_accounts_tenant_platform",
    platform_accounts.c.tenant_id,
    platform_accounts.c.platform,
)
Index(
    "uq_platform_active_session",
    platform_account_sessions.c.tenant_id,
    platform_account_sessions.c.platform,
    platform_account_sessions.c.account_ref,
    unique=True,
    postgresql_where=text("status = 'active'"),
)
Index(
    "ix_platform_sessions_expiry",
    platform_account_sessions.c.expires_at,
    platform_account_sessions.c.status,
)
Index(
    "ix_platform_login_flows_account_state",
    platform_login_flows.c.tenant_id,
    platform_login_flows.c.platform,
    platform_login_flows.c.account_ref,
    platform_login_flows.c.state,
)
Index(
    "ix_platform_login_flows_expiry",
    platform_login_flows.c.expires_at,
    platform_login_flows.c.state,
)
Index(
    "uq_platform_active_lease",
    platform_account_leases.c.tenant_id,
    platform_account_leases.c.platform,
    platform_account_leases.c.account_ref,
    unique=True,
    # Expiry is evaluated transactionally by the lease adapter; a partial
    # index predicate must remain immutable on PostgreSQL, so it only covers
    # the lifecycle status.
    postgresql_where=text("status = 'active'"),
)
Index(
    "ix_platform_health_account_time",
    platform_account_health_events.c.tenant_id,
    platform_account_health_events.c.platform,
    platform_account_health_events.c.account_ref,
    platform_account_health_events.c.observed_at,
)


PLATFORM_ACCOUNT_TABLES = (
    platform_accounts,
    platform_account_sessions,
    platform_login_flows,
    platform_account_grants,
    platform_account_leases,
    platform_account_health_events,
)
PLATFORM_ACCOUNT_INDEXES = tuple(index for table in PLATFORM_ACCOUNT_TABLES for index in table.indexes)


__all__ = [
    "PLATFORM_ACCOUNT_INDEXES",
    "PLATFORM_ACCOUNT_METADATA",
    "PLATFORM_ACCOUNT_TABLES",
    "platform_account_grants",
    "platform_account_health_events",
    "platform_account_leases",
    "platform_account_sessions",
    "platform_accounts",
    "platform_login_flows",
]
