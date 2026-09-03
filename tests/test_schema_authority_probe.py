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


def test_current_tree_has_no_postgres_runtime_ddl_and_classifies_local_telemetry() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert report["schemaVersion"] == "schema-authority-probe/v1"
    assert report["status"] == "pass"
    assert report["legacyFindings"] == []
    assert report["telemetryFindings"] == []
    assert report["unexpectedFindings"] == []


def test_unregistered_runtime_ddl_is_a_blocking_failure(tmp_path: Path) -> None:
    source = tmp_path / "unexpected.py"
    source.write_text(
        'SQL = "CREATE TABLE unexpected (id integer); CREATE INDEX idx_unexpected "\n',
        encoding="utf-8",
    )
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
        {"path": "unexpected.py", "line": 1, "statement": "CREATE TABLE"},
        {"path": "unexpected.py", "line": 1, "statement": "CREATE INDEX"},
    ]


@pytest.mark.parametrize(
    ("source", "statement"),
    (
        (
            'TABLE = "unexpected_" + name\nSQL = "CREATE TABLE " + TABLE\n',
            "CREATE TABLE",
        ),
        (
            'name = "unexpected"\nSQL = f"ALTER TABLE {name} ADD COLUMN value text"\n',
            "ALTER TABLE",
        ),
    ),
)
def test_dynamic_runtime_ddl_is_a_blocking_failure(
    tmp_path: Path, source: str, statement: str
) -> None:
    (tmp_path / "unexpected.py").write_text(source, encoding="utf-8")

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
        {"path": "unexpected.py", "line": 2, "statement": statement}
    ]
