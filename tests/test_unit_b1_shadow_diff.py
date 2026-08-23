"""B1 shadow/legacy diff and manual approval fixture gates."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from xhs_food.evidence import ShadowDiffApproval, compare_shadow_legacy

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "evidence_shadow_approval_v1.json"


@pytest.mark.unit
def test_shadow_diff_fixture_is_deterministic_and_privacy_preserving() -> None:
    authority = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in authority["cases"]:
        approval = ShadowDiffApproval.from_mapping(
            {
                "schemaVersion": authority["schemaVersion"],
                "fixtureId": case["fixtureId"],
                "allowedPaths": case["allowedPaths"],
            }
        )
        report = compare_shadow_legacy(case["legacy"], case["shadow"], approval=approval)
        repeated = compare_shadow_legacy(case["legacy"], case["shadow"], approval=approval)
        assert report == repeated
        assert report.decision == case["expectedDecision"]
        serialized = json.dumps(asdict(report), ensure_ascii=False)
        assert "note-1" not in serialized
        assert "0.8" not in serialized
        assert "0.9" not in serialized
        assert all(
            item.legacy_digest and item.legacy_digest.startswith("sha256:")
            for item in report.differences
        )


@pytest.mark.unit
def test_unapproved_shadow_difference_requires_review() -> None:
    report = compare_shadow_legacy(
        {"result": {"status": "ok"}},
        {"result": {"status": "failed"}},
        fixture_id="unapproved-v1",
    )
    assert report.decision == "review"
    assert [item.path for item in report.differences] == ["root.result.status"]
    assert report.differences[0].legacy_digest != report.differences[0].shadow_digest


@pytest.mark.unit
def test_approval_fixture_rejects_unknown_schema_or_malformed_paths() -> None:
    with pytest.raises(ValueError, match="schema"):
        ShadowDiffApproval.from_mapping({"schemaVersion": "other/v1", "fixtureId": "x"})
    with pytest.raises(ValueError, match="allowedPaths"):
        ShadowDiffApproval.from_mapping(
            {
                "schemaVersion": "evidence-shadow-approval/v1",
                "fixtureId": "x",
                "allowedPaths": "root.result",
            }
        )
