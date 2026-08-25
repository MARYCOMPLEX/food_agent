"""Tests for the non-blocking platform probe contract."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "qualification_platform_probe.py"
pytestmark = pytest.mark.unit


def test_probe_records_current_host_without_changing_support_matrix() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--expected-os",
            platform.system(),
            "--expected-arch",
            platform.machine(),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert result["status"] == "pass"
    assert result["productionSupportMatrixChanged"] is False
    assert result["checks"] == {"python312": True, "hostMatch": True}


def test_unavailable_mac_arm_probe_is_explicitly_not_a_pass() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--expected-os",
            "Darwin",
            "--expected-arch",
            "arm64",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(completed.stdout)

    assert completed.returncode in {0, 2}
    assert result["status"] in {"pass", "probe_mismatch"}
    assert result["productionSupportMatrixChanged"] is False
