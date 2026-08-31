"""I0 intake gates for the audited platform connector snapshots.

These tests deliberately do not import either upstream project.  They verify
that provenance, import boundaries, and synthetic payloads are reviewable
before any provider adapter is enabled.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHANGE_ROOT = ROOT / "openspec" / "changes" / "integrate-platform-source-connectors"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "platform_connectors"
pytestmark = pytest.mark.unit


def test_provenance_records_pinned_snapshots_and_activation_gate() -> None:
    report = (CHANGE_ROOT / "verification" / "upstream-provenance.md").read_text(
        encoding="utf-8"
    )

    expected = (
        "ffbc1d413ed1c83602212bc1fec12b57cd2b423d",
        "e1888d712519040f5fcc294baeac4b9505b25c98",
        "b535f193e1b82d87541f8604613e92956b85a2b2911d89e3c7efe475806e4f88",
        "472df6713016dfd4c4999ae58a84c625abb7ffc4dba51b71ddd6604344d52ebe",
        "c9e09a0c05189d0f312dac084820f9663c49e749a796506d7e10404a38d9f046",
        "7e0b00e1e38ab5a1599d1d00f097b3bec46ff834a8111fb5c298081c90c4b773",
        "d453db039b224e88b0b9250642bdca30479a582c9dfbadfdf176e58a906d640b",
        "99016bc2c76f1b0d5197581626711ffcb327860b21b2a1b85511579aadab1cc6",
    )
    for value in expected:
        assert value in report

    assert "license_status` is `unknown`" in report
    assert re.search(r"production\s+or\s+commercial traffic", report)
    assert "owner/legal approval" in report
    assert re.search(r"Status:\s+\*\*intake recorded;.*blocked", report, re.IGNORECASE)


def test_provider_allowlist_is_pinned_and_excludes_upstream_runtimes() -> None:
    manifest_path = CHANGE_ROOT / "references" / "provider-import-allowlist.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema"] == "platform-provider-import-boundary/v1"
    providers = manifest["providers"]
    assert providers["dianping"]["commit"] == (
        "ffbc1d413ed1c83602212bc1fec12b57cd2b423d"
    )
    assert providers["xhs_spider"]["commit"] == (
        "e1888d712519040f5fcc294baeac4b9505b25c98"
    )

    assert "dz_engine.auth.dianping" in providers["dianping"]["allowed_modules"]
    assert "dz_engine.providers.dianping.reviews" in providers["dianping"]["allowed_modules"]
    assert "dz_engine.backend" in providers["dianping"]["excluded_modules"]
    assert "dz_engine.risk" in providers["dianping"]["excluded_modules"]
    assert "apis.xhs_pc_apis" in providers["xhs_spider"]["allowed_modules"]
    assert "apis.xhs_pc_login_apis" in providers["xhs_spider"]["allowed_modules"]
    assert "spider.spider" in providers["xhs_spider"]["excluded_modules"]
    assert "apis.xhs_qianfan_apis" in providers["xhs_spider"]["excluded_modules"]

    forbidden = tuple(manifest["forbidden_runtime_patterns"])
    allowed_text = "\n".join(
        module
        for provider in providers.values()
        for module in provider["allowed_modules"]
    ).lower()
    assert not any(pattern in allowed_text for pattern in forbidden)
    assert manifest["activation"]["license_status"] == "unknown"
    assert manifest["activation"]["production_enabled"] is False
    assert manifest["activation"]["owner_approval_ref"] is None


def test_application_source_has_no_upstream_runtime_imports() -> None:
    forbidden_roots = {
        "arq",
        "celery",
        "langgraph",
        "openai_agents",
        "redlock",
        "redis_lock",
        "dz_engine",
        "apis",
        "xhs_utils",
    }
    violations: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        # A legacy provider file carries a UTF-8 BOM; ``utf-8-sig`` keeps this
        # intake scan focused on imports rather than encoding trivia.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    root = imported.split(".", 1)[0].lower()
                    if root in forbidden_roots:
                        violations.append(f"{path}:{node.lineno}: {imported}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
                root = imported.split(".", 1)[0].lower()
                if root in forbidden_roots:
                    violations.append(f"{path}:{node.lineno}: {imported}")
    assert violations == [], "forbidden provider/runtime imports:\n" + "\n".join(violations)


def test_synthetic_provider_fixtures_are_json_safe_and_secret_free() -> None:
    paths = sorted(FIXTURE_ROOT.glob("*.json"))
    assert {path.name for path in paths} >= {
        "dianping_search.json",
        "dianping_detail.json",
        "dianping_reviews.json",
        "dianping_outcomes.json",
        "xhs_search.json",
        "xhs_note.json",
        "xhs_comments.json",
        "xhs_outcomes.json",
    }
    sensitive_key_fragments = (
        "cookie",
        "authorization",
        "storage_state",
        "qr_payload",
        "signer_input",
        "password",
        "secret",
        "credential",
    )
    sensitive_value_fragments = (
        "xsec_token=",
        "authorization: bearer",
        "set-cookie:",
    )

    def walk(value: Any, location: str) -> list[str]:
        findings: list[str] = []
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key).lower()
                if any(fragment in key_text for fragment in sensitive_key_fragments):
                    findings.append(f"{location}.{key}")
                findings.extend(walk(nested, f"{location}.{key}"))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                findings.extend(walk(nested, f"{location}[{index}]"))
        elif isinstance(value, str):
            lowered = value.lower()
            if any(fragment in lowered for fragment in sensitive_value_fragments):
                findings.append(location)
        return findings

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), path
        assert str(payload.get("fixture_version", "")).endswith("/v1"), path
        findings = walk(payload, path.name)
        assert findings == [], f"secret-bearing fixture fields: {findings}"
