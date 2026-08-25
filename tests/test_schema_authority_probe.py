"""Tests for the fail-closed runtime schema-authority probe."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "qualification_schema_authority.py"
pytestmark = pytest.mark.unit


def test_current_tree_reports_only_registered_legacy_runtime_ddl() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert report["schemaVersion"] == "schema-authority-probe/v1"
    assert report["status"] == "pending_legacy_contraction"
    assert report["unexpectedFindings"] == []
    assert {item["path"] for item in report["legacyFindings"]} == {
        "scripts/migrate_sse_recovery.py",
        "scripts/migrate_turn_id.py",
        "src/scripts/migrate_favorites.py",
        "src/xhs_food/services/postgres_storage.py",
        "src/xhs_food/services/postgres_vector.py",
        "src/xhs_food/spider/core/logger.py",
        "src/xhs_food/services/user_storage/schema.py",
        "src/xhs_food/services/user_storage/service.py",
    }


def test_unregistered_runtime_ddl_is_a_blocking_failure(tmp_path: Path) -> None:
    source = tmp_path / "unexpected.py"
    source.write_text('SQL = "CREATE TABLE unexpected (id integer)"\n', encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["status"] == "fail"
    assert report["legacyFindings"] == []
    assert report["unexpectedFindings"] == [
        {"path": "unexpected.py", "line": 1, "statement": "CREATE TABLE"}
    ]
