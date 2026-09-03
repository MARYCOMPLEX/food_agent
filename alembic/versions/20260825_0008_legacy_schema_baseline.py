"""Adopt the legacy PostgreSQL tables into the Alembic authority chain.

The revision is additive for clean databases and recognizes the checked-in
pre/post ``search_results`` shapes.  Unknown table shapes fail closed instead
of being silently repaired.  Runtime legacy initializers remain available
until the separately gated legacy-contraction change removes them.
"""

from __future__ import annotations

from sqlalchemy import Table, inspect, text
from sqlalchemy.exc import NoSuchTableError

from alembic import context, op
from xhs_food.foundation.legacy_schema import LEGACY_TABLES

revision = "20260825_0008_legacy_schema"
down_revision = "20260824_0007_b3_personalization_memory"
branch_labels = None
depends_on = None


_REQUIRED_COLUMNS = {
    "users": {"id", "device_id", "name", "settings", "created_at", "updated_at"},
    "restaurants": {"id", "name", "created_at", "updated_at"},
    "favorites": {"id", "user_id", "restaurant_id", "created_at"},
    "search_history": {"id", "user_id", "session_id", "query", "status", "created_at"},
    "search_results": {"id", "session_id", "restaurants", "created_at"},
    "chat_history": {"id", "session_id", "role", "content", "created_at"},
}
_RECOGNIZED_MISSING_COLUMNS = {
    "restaurants": {
        "region",
        "provider_refs",
        "profile_url",
        "source_url",
        "image_url",
        "category",
        "review_count",
        "average_price",
        "latitude",
        "longitude",
        "coordinate_system",
        "geo",
        "recommended_dishes",
        "promotions",
        "profile_metadata",
        "review_completeness",
        "profile_gaps",
        "source_payload",
        "source_updated_at",
        "profile_fetched_at",
        "profile_refresh_status",
    },
    "users": {"username", "deleted_at"},
    "search_history": {"deleted_at"},
    "search_results": {"turn_id", "query"},
    "chat_history": {"embedding"},
}


def _connection_inspector():
    return inspect(op.get_bind())


def _existing_columns(inspector, table_name: str) -> set[str]:
    try:
        return {column["name"] for column in inspector.get_columns(table_name)}
    except NoSuchTableError:
        return set()


def _existing_indexes(inspector, table_name: str) -> set[str]:
    try:
        return {index["name"] for index in inspector.get_indexes(table_name)}
    except NoSuchTableError:
        return set()


def _create_table(table: Table) -> None:
    op.create_table(table.name, *table.columns, *table.constraints)
    inspector = _connection_inspector()
    for index in table.indexes:
        if index.name not in _existing_indexes(inspector, table.name):
            op.create_index(
                index.name,
                table.name,
                [column.name for column in index.columns],
                unique=bool(index.unique),
                postgresql_where=index.dialect_options["postgresql"].get("where"),
            )


def _create_table_offline(table: Table) -> None:
    op.create_table(table.name, *table.columns, *table.constraints)
    for index in table.indexes:
        op.create_index(
            index.name,
            table.name,
            [column.name for column in index.columns],
            unique=bool(index.unique),
            postgresql_where=index.dialect_options["postgresql"].get("where"),
        )


def _require_base_shape(table: Table, inspector) -> set[str]:
    columns = _existing_columns(inspector, table.name)
    missing = _REQUIRED_COLUMNS[table.name] - columns
    if missing:
        raise RuntimeError(
            f"unrecognized legacy schema for {table.name}: missing {sorted(missing)}"
        )
    unknown_missing = set(table.c.keys()) - columns - _RECOGNIZED_MISSING_COLUMNS.get(table.name, set())
    if unknown_missing:
        raise RuntimeError(
            f"unrecognized legacy schema for {table.name}: missing {sorted(unknown_missing)}"
        )
    return columns


def _add_column_if_missing(table_name: str, table: Table, column_name: str, columns: set[str]) -> None:
    if column_name not in columns:
        op.add_column(table_name, table.c[column_name].copy())


def _drop_unique_session_constraint(inspector) -> None:
    for constraint in inspector.get_unique_constraints("search_results"):
        if constraint.get("column_names") == ["session_id"]:
            name = constraint.get("name")
            if name:
                op.drop_constraint(name, "search_results", type_="unique")


def _upgrade_search_results(table: Table, inspector) -> None:
    columns = _require_base_shape(table, inspector)
    _add_column_if_missing("search_results", table, "turn_id", columns)
    _add_column_if_missing("search_results", table, "query", columns)
    inspector = _connection_inspector()
    _drop_unique_session_constraint(inspector)
    inspector = _connection_inspector()
    indexes = _existing_indexes(inspector, "search_results")
    for index in table.indexes:
        if index.name not in indexes:
            op.create_index(
                index.name,
                "search_results",
                [column.name for column in index.columns],
                unique=bool(index.unique),
            )


def _upgrade_existing(table: Table) -> None:
    inspector = _connection_inspector()
    _require_base_shape(table, inspector)
    columns = _existing_columns(inspector, table.name)
    if table.name == "users":
        _add_column_if_missing("users", table, "username", columns)
        _add_column_if_missing("users", table, "deleted_at", columns)
    elif table.name == "search_history":
        _add_column_if_missing("search_history", table, "deleted_at", columns)
    elif table.name == "chat_history":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        _add_column_if_missing("chat_history", table, "embedding", columns)
    elif table.name == "search_results":
        _upgrade_search_results(table, inspector)

    inspector = _connection_inspector()
    indexes = _existing_indexes(inspector, table.name)
    for index in table.indexes:
        if index.name not in indexes:
            op.create_index(
                index.name,
                table.name,
                [column.name for column in index.columns],
                unique=bool(index.unique),
                postgresql_where=index.dialect_options["postgresql"].get("where"),
            )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if context.is_offline_mode():
        for table in LEGACY_TABLES:
            _create_table_offline(table)
        return

    inspector = _connection_inspector()
    for table in LEGACY_TABLES:
        if table.name not in inspector.get_table_names():
            _create_table(table)
        else:
            _upgrade_existing(table)


def _table_has_rows(table_name: str) -> bool:
    return bool(op.get_bind().execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)")).scalar())


def downgrade() -> None:
    """Drop only empty adopted tables; restore populated databases instead."""

    if context.is_offline_mode():
        for table in reversed(LEGACY_TABLES):
            op.drop_table(table.name)
        return

    inspector = _connection_inspector()
    present = [table for table in reversed(LEGACY_TABLES) if table.name in inspector.get_table_names()]
    populated = [table.name for table in present if _table_has_rows(table.name)]
    if populated:
        raise RuntimeError(
            "legacy schema downgrade requires restore because populated tables would be deleted: "
            + ", ".join(populated)
        )
    for table in present:
        op.drop_table(table.name)
