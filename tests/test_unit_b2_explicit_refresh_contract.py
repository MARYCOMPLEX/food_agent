"""Machine-checkable authority gates for ADR-0013 explicit refresh."""

from __future__ import annotations

from pathlib import Path

from xhs_food.contracts import (
    RefreshSingleFlightKey,
    RequestIdentity,
    ResearchOperation,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
)
from xhs_food.evidence import ExplicitRefreshRequestMapper

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "openspec" / "changes" / "define-modular-architecture" / "decisions"
ADR = DECISIONS / "ADR-0013-explicit-refresh-authority.md"


def test_adr_0013_accepts_refresh_boundary_and_new_behavior_status() -> None:
    text = ADR.read_text(encoding="utf-8")
    index = (DECISIONS / "README.md").read_text(encoding="utf-8")
    row = next(line for line in index.splitlines() if line.startswith("| 28 |"))

    assert "Status: Accepted" in text
    for required in (
        "explicit-refresh/v1",
        "refresh:force",
        "refresh-single-flight/v1",
        "task.refresh.accepted",
        "existing\nversioned SSE boundary",
        "no external SSE route",
        "new target behavior, not a legacy compatibility contract",
    ):
        assert required in text
    assert "| Accepted | [ADR-0013]" in row


def test_refresh_wire_fields_and_identity_exclude_request_identity() -> None:
    request = ExplicitRefreshRequestMapper().to_request(
        {
            "requestId": "wire-refresh-1",
            "domain": "food",
            "queryFamilyId": "family.zigong",
            "refreshScope": ["restaurants", "reviews"],
            "force": False,
            "policyVersion": "refresh-policy/v1",
            "compatibilityVersion": "explicit-refresh/v1",
        },
        identity=RequestIdentity(subject_ref="user-a", session_ref="session-a"),
    )

    assert request.operation is ResearchOperation.REFRESH
    assert request.public_inputs == {
        "refresh_scope": ["restaurants", "reviews"],
        "force": False,
    }

    key = RefreshSingleFlightKey(
        family_id=request.query_family_id or "",
        scope=("restaurants", "reviews"),
        policy_version=request.policy.policy_version,
    )
    same_public_request = request.model_copy(
        update={
            "request_id": "wire-refresh-2",
            "identity": RequestIdentity(subject_ref="user-b", session_ref="session-b"),
        }
    )
    same_key = key.model_copy(
        update={
            "family_id": same_public_request.query_family_id or "",
        }
    )

    assert stable_refresh_workflow_id(key) == stable_refresh_workflow_id(same_key)
    assert stable_refresh_claim_key(key) == stable_refresh_claim_key(same_key)
