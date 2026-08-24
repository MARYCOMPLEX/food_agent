"""Offline proof for the Alembic-owned B0 reliable task schema."""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20260824_0006_b0_reliable_task_semantics.py"


def _migration():
    spec = importlib.util.spec_from_file_location("b0_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_b0_migration_is_additive_and_declares_authority_constraints() -> None:
    migration = _migration()
    upgrade_sql = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": upgrade_sql},
    )
    with Operations.context(context):
        migration.upgrade()
    sql = upgrade_sql.getvalue()

    assert "CREATE TABLE reliable_tasks" in sql
    assert "CREATE TABLE reliable_task_results" in sql
    assert "CREATE TABLE task_progress_projection" in sql
    assert "UNIQUE (workflow_id)" in sql
    assert "uq_reliable_task_results_identity" in sql
    assert "UNIQUE (idempotency_key)" in sql
    assert "JSONB" in sql
    assert "CREATE TABLE IF NOT EXISTS" not in sql
    assert "chat_history" not in sql

    downgrade_sql = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": downgrade_sql},
    )
    with Operations.context(context):
        migration.downgrade()
    reverted = downgrade_sql.getvalue()
    assert "DROP TABLE task_progress_projection" in reverted
    assert "DROP TABLE reliable_task_results" in reverted
    assert "DROP TABLE reliable_tasks" in reverted
    assert "DROP TABLE chat_history" not in reverted
