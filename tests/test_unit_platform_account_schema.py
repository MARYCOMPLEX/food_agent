"""Offline checks for the platform account Alembic authority revision."""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from xhs_food.foundation.platform_account_schema import (
    PLATFORM_ACCOUNT_INDEXES,
    PLATFORM_ACCOUNT_TABLES,
)

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20260831_0009_platform_account_authority.py"
pytestmark = pytest.mark.unit


def _migration():
    spec = importlib.util.spec_from_file_location("platform_account_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(callable_obj) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        callable_obj()
    return output.getvalue()


def test_metadata_contains_only_additive_account_authority_tables() -> None:
    assert {table.name for table in PLATFORM_ACCOUNT_TABLES} == {
        "platform_accounts",
        "platform_account_sessions",
        "platform_login_flows",
        "platform_account_grants",
        "platform_account_leases",
        "platform_account_health_events",
    }
    assert any(index.name == "uq_platform_active_session" and index.unique for index in PLATFORM_ACCOUNT_INDEXES)
    assert any(index.name == "uq_platform_active_lease" and index.unique for index in PLATFORM_ACCOUNT_INDEXES)
    parent = next(table for table in PLATFORM_ACCOUNT_TABLES if table.name == "platform_accounts")
    assert tuple(column.name for column in parent.primary_key.columns) == (
        "tenant_id",
        "platform",
        "account_ref",
    )
    for table in PLATFORM_ACCOUNT_TABLES:
        if table.name == "platform_accounts":
            continue
        foreign_keys = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
        }
        assert ("tenant_id", "platform", "account_ref") in foreign_keys, table.name


def test_revision_is_chained_and_never_uses_runtime_if_not_exists() -> None:
    migration = _migration()
    assert migration.revision == "20260831_0009_platform_accounts"
    assert migration.down_revision == "20260825_0008_legacy_schema"
    upgrade = _sql(migration.upgrade)
    assert "CREATE TABLE platform_accounts" in upgrade
    assert "CREATE TABLE platform_account_sessions" in upgrade
    assert "CREATE TABLE platform_login_flows" in upgrade
    assert "CREATE TABLE platform_account_grants" in upgrade
    assert "CREATE TABLE platform_account_leases" in upgrade
    assert "CREATE TABLE platform_account_health_events" in upgrade
    assert "CREATE TABLE IF NOT EXISTS" not in upgrade
    assert "ciphertext BYTEA" in upgrade
    assert "uq_platform_active_session" in upgrade

    downgrade = _sql(migration.downgrade)
    assert "DROP TABLE platform_account_health_events" in downgrade
    assert "DROP TABLE platform_accounts" in downgrade
