"""Tests for the fail-closed B2 canary evaluator entry point."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "b2_qualification_v1.json"
SCRIPT = ROOT / "scripts" / "qualification_b2_canary.py"
pytestmark = pytest.mark.unit


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fixture_canary_passes_without_claiming_production() -> None:
    completed = _run()
    report = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert report["status"] == "pass"
    assert report["canary_approval_id"] == "b2-fixture-canary-20260824"


def test_production_scope_requirement_blocks_fixture_approval() -> None:
    completed = _run("--require-production-scope")
    report = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert report["status"] == "blocked"
    assert "production_scope_required" in report["failures"]


def test_missing_approval_remains_blocked(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.pop("approval")
    input_path = tmp_path / "missing-approval.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert report["status"] == "blocked"
    assert report["failures"] == ["canary_approval_missing"]
