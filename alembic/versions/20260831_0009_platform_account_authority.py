"""Add the project-owned platform account/session authority tables.

This revision is deliberately additive.  Provider repositories, SQLite
databases, and runtime ``CREATE TABLE`` calls are not part of the authority
chain; only this Alembic revision provisions the six platform tables.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from alembic import context, op
from xhs_food.foundation.platform_account_schema import (
    PLATFORM_ACCOUNT_INDEXES,
    PLATFORM_ACCOUNT_TABLES,
)


revision = "20260831_0009_platform_accounts"
down_revision = "20260825_0008_legacy_schema"
branch_labels = None
depends_on = None


def _is_offline_mode() -> bool:
    """Support direct offline revision probes outside an Alembic environment."""

    try:
        return context.is_offline_mode()
    except NameError:
        # ``MigrationContext`` + ``Operations.context`` is the supported unit
        # test harness; its EnvironmentContext proxy is intentionally absent.
        return True


def _existing_indexes(table_name: str) -> set[str]:
    try:
        return {value["name"] for value in inspect(op.get_bind()).get_indexes(table_name)}
    except Exception:
        return set()


def upgrade() -> None:
    """Provision account authority without inspecting provider state."""

    if _is_offline_mode():
        for table in PLATFORM_ACCOUNT_TABLES:
            op.create_table(table.name, *table.columns, *table.constraints)
        for index in PLATFORM_ACCOUNT_INDEXES:
            op.create_index(
                index.name,
                index.table.name,
                [column.name for column in index.columns],
                unique=bool(index.unique),
                postgresql_where=index.dialect_options["postgresql"].get("where"),
            )
        return

    inspector = inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    for table in PLATFORM_ACCOUNT_TABLES:
        if table.name not in existing_tables:
            op.create_table(table.name, *table.columns, *table.constraints)
    for index in PLATFORM_ACCOUNT_INDEXES:
        if index.name not in _existing_indexes(index.table.name):
            op.create_index(
                index.name,
                index.table.name,
                [column.name for column in index.columns],
                unique=bool(index.unique),
                postgresql_where=index.dialect_options["postgresql"].get("where"),
            )


def _table_has_rows(table_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)"))
        .scalar()
    )


def downgrade() -> None:
    """Drop only an empty authority set; populated data requires restore."""

    if _is_offline_mode():
        for index in reversed(PLATFORM_ACCOUNT_INDEXES):
            op.drop_index(index.name, table_name=index.table.name)
        for table in reversed(PLATFORM_ACCOUNT_TABLES):
            op.drop_table(table.name)
        return

    inspector = inspect(op.get_bind())
    present = [
        table
        for table in reversed(PLATFORM_ACCOUNT_TABLES)
        if table.name in inspector.get_table_names()
    ]
    populated = [table.name for table in present if _table_has_rows(table.name)]
    if populated:
        raise RuntimeError(
            "platform account downgrade requires restore because populated tables would be deleted: "
            + ", ".join(populated)
        )
    for index in reversed(PLATFORM_ACCOUNT_INDEXES):
        if index.name in _existing_indexes(index.table.name):
            op.drop_index(index.name, table_name=index.table.name)
    for table in present:
        op.drop_table(table.name)
