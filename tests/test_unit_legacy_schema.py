"""Offline contracts for the legacy Alembic schema baseline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from xhs_food.foundation.legacy_schema import LEGACY_METADATA, LEGACY_TABLES

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20260825_0008_legacy_schema_baseline.py"

pytestmark = pytest.mark.unit


def _migration():
    spec = importlib.util.spec_from_file_location("legacy_schema_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_metadata_is_a_single_checked_in_schema_contract() -> None:
    assert {table.name for table in LEGACY_TABLES} == {
        "users",
        "restaurants",
        "favorites",
        "search_history",
        "search_results",
        "chat_history",
    }
    assert LEGACY_METADATA.tables["search_results"].c.turn_id.server_default is not None
    assert LEGACY_METADATA.tables["search_results"].c.query.nullable is True
    assert any(
        index.name == "idx_results_session_turn" and index.unique
        for index in LEGACY_METADATA.tables["search_results"].indexes
    )


def test_legacy_revision_is_chained_after_the_existing_head_and_is_fail_closed() -> None:
    migration = _migration()

    assert migration.revision == "20260825_0008_legacy_schema"
    assert migration.down_revision == "20260824_0007_b3_personalization_memory"
    source = MIGRATION.read_text(encoding="utf-8")
    assert "unrecognized legacy schema" in source
    assert "requires restore because populated tables would be deleted" in source
