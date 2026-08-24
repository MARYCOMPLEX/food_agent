"""B3 ContextAssembler ordering, budgeting, and provenance contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xhs_food.contracts import (
    ContextAssemblyRequest,
    ContextBudget,
    EvidenceBundleManifest,
    EvidenceVisibility,
    MemoryConversationTurn,
    MemoryRecord,
    MemorySubject,
    UserIsolationKey,
    VersionedMemorySummary,
    VisibilityScope,
)
from xhs_food.personalization import ContextAssembler

ROOT = Path(__file__).parents[1]
MEMORY_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"
EVIDENCE_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "evidence_bundle_v1.json"


def _memories() -> tuple[MemoryRecord, ...]:
    values = json.loads(MEMORY_FIXTURE.read_text(encoding="utf-8"))
    return tuple(MemoryRecord.model_validate(item) for item in values["exampleRecords"][1:])


def _scope() -> UserIsolationKey:
    return UserIsolationKey(tenant_id="tenant-cn-1", user_id="user-2b4aa1b95c884d64")


def _budget(total: int = 128) -> ContextBudget:
    return ContextBudget(
        total_tokens=total,
        request_constraints_tokens=24,
        recent_messages_tokens=32,
        versioned_summary_tokens=24,
        related_memory_tokens=24,
        related_evidence_tokens=24,
    )


@pytest.mark.unit
def test_context_assembly_has_fixed_order_and_source_versions() -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    turn = MemoryConversationTurn(
        turn_id="turn-100",
        scope=_scope(),
        role="user",
        content="找不辣的本地菜",
        source_event_id="event-100",
        occurred_at=now,
        idempotency_key="turn-100-idempotency",
    )
    summary = VersionedMemorySummary(
        summary_id="summary-100",
        summary_version=3,
        content="用户偏好清淡口味。",
        source_authority_version="authority-17",
        profile_version="profile/v1",
        policy_version="memory-policy/v1",
    )
    assembly = ContextAssembler().assemble(
        assembly_id="assembly-100",
        policy_version="context-policy/v1",
        request_constraints={"diet.spice": {"kind": "hard_constraint", "value": "none"}},
        recent_messages=[turn],
        summaries=[summary],
        memories=_memories(),
        budget=_budget(),
        scope=_scope(),
    )

    assert [section.section.value for section in assembly.sections] == [
        "request_constraints",
        "recent_messages",
        "versioned_summary",
        "related_memory",
        "related_evidence",
    ]
    assert assembly.sections[0].fragments[0].source.versions["policy"] == "context-policy/v1"
    assert assembly.sections[2].fragments[0].source.versions["summary"] == "v3"
    assert assembly.sections[3].fragments[0].source.versions["schema"] == "memory-record/v1"
    assert "mem-feedback-001" not in {
        ref.source_id for ref in assembly.sections[3].source_refs
    }
    assert "ModelMessage" not in assembly.text


@pytest.mark.unit
def test_low_confidence_inferred_memory_is_dropped_before_hard_constraint() -> None:
    records = _memories()
    low_confidence = records[1].model_copy(
        update={
            "record_id": "mem-inferred-low",
            "confidence": 0.1,
            "updated_at": records[1].updated_at + timedelta(minutes=1),
        }
    )
    assembly = ContextAssembler().assemble(
        assembly_id="assembly-budget",
        policy_version="context-policy/v1",
        memories=[records[0], low_confidence],
        budget=_budget(),
        scope=_scope(),
    )

    section = assembly.sections[3]
    selected = {ref.source_id for ref in section.source_refs}
    dropped = {ref.source_id for ref in section.dropped_source_refs}
    assert "mem-explicit-001" in selected
    assert "mem-inferred-low" in dropped or "mem-inferred-low" not in selected


@pytest.mark.unit
def test_context_rejects_memory_from_another_scope() -> None:
    record = _memories()[0]
    other = record.model_copy(
        update={
            "record_id": "mem-other-user",
            "subject": MemorySubject(kind="user", id="user-other-1234567"),
        }
    )
    with pytest.raises(ValueError, match="outside the requested scope"):
        ContextAssembler().assemble(
            memories=[record, other],
            scope=_scope(),
        )


@pytest.mark.unit
def test_typed_request_records_public_evidence_bundle_and_citation() -> None:
    manifest = EvidenceBundleManifest.model_validate_json(
        EVIDENCE_FIXTURE.read_text(encoding="utf-8")
    )
    request = ContextAssemblyRequest(
        assembly_id="assembly-evidence",
        policy_version="context-policy/v1",
        evidence=manifest.evidence_items,
        evidence_bundle=manifest.bundles[0],
        scope=_scope(),
    )

    assembly = ContextAssembler().assemble(request)
    section = assembly.sections[4]
    assert section.source_refs[0].citation == manifest.evidence_items[0].source_locator_id
    assert section.source_refs[0].versions["bundle"] == (
        f"{manifest.bundles[0].bundle_id}:v{manifest.bundles[0].bundle_version}"
    )

    private = manifest.evidence_items[0].model_copy(
        update={
            "visibility": EvidenceVisibility(
                scope=VisibilityScope.TENANT,
                tenant_scope="tenant:private",
                entitlement_ids=(),
            )
        }
    )
    with pytest.raises(ValueError, match="public Evidence only"):
        ContextAssembler().assemble(evidence=[private])
