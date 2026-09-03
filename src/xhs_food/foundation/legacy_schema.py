"""SQLAlchemy Core metadata for the checked-in legacy PostgreSQL schema.

This metadata is an inventory and migration contract for the legacy adapters.
It does not create tables at import time.  The Alembic legacy-baseline
revision is the only writer for clean installs and recognized pre/post
``search_results`` states.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

LEGACY_METADATA = MetaData()

users = Table(
    "users",
    LEGACY_METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("device_id", String(255), unique=True),
    Column("name", String(100), server_default=text("'Guest'")),
    Column("username", String(50), unique=True),
    Column("email", String(255)),
    Column("avatar", Text),
    Column("location", String(100)),
    Column("settings", JSONB, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("deleted_at", DateTime(timezone=True)),
)

restaurants = Table(
    "restaurants",
    LEGACY_METADATA,
    Column("id", String(32), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("alias", String(255)),
    Column("tel", String(50)),
    Column("address", Text),
    Column("city", String(100)),
    Column("district", String(100)),
    Column("business_area", String(100)),
    Column("location", String(50)),
    Column("rating", Float),
    Column("cost", String(50)),
    Column("open_time", String(255)),
    Column("trust_score", Float),
    Column("one_liner", Text),
    Column("tags", JSONB, server_default=text("'[]'::jsonb")),
    Column("pros", JSONB, server_default=text("'[]'::jsonb")),
    Column("cons", JSONB, server_default=text("'[]'::jsonb")),
    Column("warning", Text),
    Column("must_try", JSONB, server_default=text("'[]'::jsonb")),
    Column("black_list", JSONB, server_default=text("'[]'::jsonb")),
    Column("stats", JSONB, server_default=text("'{}'::jsonb")),
    Column("photos", JSONB, server_default=text("'[]'::jsonb")),
    Column("source_notes", JSONB, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
)

favorites = Table(
    "favorites",
    LEGACY_METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")),
    Column("restaurant_id", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("deleted_at", DateTime(timezone=True)),
    UniqueConstraint("user_id", "restaurant_id", name="uq_favorites_user_restaurant"),
)

search_history = Table(
    "search_history",
    LEGACY_METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")),
    Column("session_id", UUID(as_uuid=True), unique=True),
    Column("query", Text, nullable=False),
    Column("status", String(20), server_default=text("'loading'")),
    Column("results_count", Integer, server_default=text("0")),
    Column("location", String(100)),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("deleted_at", DateTime(timezone=True)),
)

search_results = Table(
    "search_results",
    LEGACY_METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("restaurants", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("summary", Text),
    Column("filtered_count", Integer, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
    Column("turn_id", Integer, nullable=False, server_default=text("1")),
    Column("query", Text),
)

chat_history = Table(
    "chat_history",
    LEGACY_METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True)),
    Column("role", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("metadata", JSONB, server_default=text("'{}'::jsonb")),
    Column("embedding", Vector(4096)),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_users_deleted", users.c.deleted_at, postgresql_where=users.c.deleted_at.is_(None))
Index("idx_restaurants_name", restaurants.c.name)
Index("idx_restaurants_city", restaurants.c.city)
Index("idx_favorites_user", favorites.c.user_id)
Index("idx_favorites_restaurant", favorites.c.restaurant_id)
Index(
    "idx_favorites_deleted",
    favorites.c.deleted_at,
    postgresql_where=favorites.c.deleted_at.is_(None),
)
Index("idx_history_user", search_history.c.user_id)
Index("idx_history_created", search_history.c.created_at.desc())
Index("idx_history_session", search_history.c.session_id)
Index(
    "idx_history_deleted",
    search_history.c.deleted_at,
    postgresql_where=search_history.c.deleted_at.is_(None),
)
Index("idx_results_session", search_results.c.session_id)
Index(
    "idx_results_session_turn", search_results.c.session_id, search_results.c.turn_id, unique=True
)
Index("idx_results_turn", search_results.c.session_id, search_results.c.turn_id.desc())
Index("idx_chat_session_id", chat_history.c.session_id)
Index("idx_chat_user_id", chat_history.c.user_id)
Index("idx_chat_created_at", chat_history.c.created_at.desc())

LEGACY_TABLES = (users, restaurants, favorites, search_history, search_results, chat_history)

__all__ = [
    "LEGACY_METADATA",
    "LEGACY_TABLES",
    "chat_history",
    "favorites",
    "restaurants",
    "search_history",
    "search_results",
    "users",
]
