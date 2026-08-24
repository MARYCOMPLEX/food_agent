"""B3 preference priority and scope resolution contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xhs_food.contracts import MemoryRecord, PreferenceSnapshot, UserIsolationKey
from xhs_food.personalization import PreferenceResolver

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"


def _records() -> tuple[MemoryRecord, ...]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return tuple(MemoryRecord.model_validate(item) for item in data["exampleRecords"])


@pytest.mark.unit
def test_resolver_keeps_four_layers_and_strategy_feedback_separate() -> None:
    records = _records()
    record = records[1]
    scope = UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)

    snapshot = PreferenceResolver().resolve(
        records[1:],
        scope=scope,
        snapshot_id="snapshot-001",
        snapshot_version=1,
        policy_version="memory-policy/v1",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert snapshot.explicit_hard_constraints["diet.spice"]["hardConstraint"] is True
    assert "diet.spice" not in snapshot.inferred_preferences
    assert snapshot.strategy_feedback["research_depth"]["value"] == "deep"
    assert "research_depth" not in snapshot.explicit_hard_constraints
    assert PreferenceResolver().effective_constraints(snapshot)["diet.spice"]["hardConstraint"] is True
    assert set(snapshot.source_record_versions) == {item.record_id for item in records[1:]}


@pytest.mark.unit
def test_resolver_uses_newest_record_within_each_priority_bucket() -> None:
    record = _records()[1]
    scope = UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)
    newer = record.model_copy(
        update={
            "record_id": "mem-explicit-newer",
            "value": {"kind": "preference", "operator": "equals", "value": "mild"},
            "updated_at": record.updated_at + timedelta(minutes=1),
        }
    )

    snapshot = PreferenceResolver().resolve(
        [record, newer],
        scope=scope,
        snapshot_id="snapshot-002",
        snapshot_version=2,
        policy_version="memory-policy/v1",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert snapshot.stable_explicit_preferences["diet.spice"]["value"] == "mild"
    assert PreferenceResolver().effective_constraints(snapshot)["diet.spice"]["hardConstraint"] is True
    assert snapshot.source_record_versions["mem-explicit-newer"].endswith("+00:00")


@pytest.mark.unit
def test_resolver_rejects_cross_user_records_instead_of_filtering_them() -> None:
    records = _records()
    record = records[1]
    scope = UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)
    other = record.model_copy(
        update={
            "record_id": "mem-explicit-other",
            "subject": {"kind": "user", "id": "user-other-1234567"},
        }
    )

    with pytest.raises(ValueError, match="outside the requested scope"):
        PreferenceResolver().resolve(
            [record, other],
            scope=scope,
            snapshot_id="snapshot-003",
            snapshot_version=3,
            policy_version="memory-policy/v1",
            generated_at=datetime(2026, 8, 24, tzinfo=UTC),
        )


@pytest.mark.unit
def test_resolver_excludes_expired_memory_without_reusing_stale_cache() -> None:
    record = _records()[1]
    scope = UserIsolationKey(tenant_id=record.tenant_id, user_id=record.subject.id)
    expired = record.model_copy(
        update={
            "record_id": "mem-explicit-expired",
            "expires_at": datetime(2026, 8, 23, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 23, tzinfo=UTC),
            "valid_from": datetime(2026, 8, 22, tzinfo=UTC),
            "status": "expired",
        }
    )

    snapshot = PreferenceResolver().resolve(
        [expired],
        scope=scope,
        snapshot_id="snapshot-004",
        snapshot_version=4,
        policy_version="memory-policy/v1",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert snapshot.explicit_hard_constraints == {}
    assert snapshot.source_record_versions == {}


@pytest.mark.unit
def test_effective_constraints_apply_explicit_session_stable_inferred_priority() -> None:
    scope = UserIsolationKey(tenant_id="tenant-cn-1", user_id="user-2b4aa1b95c884d64")
    snapshot = PreferenceSnapshot(
        snapshot_id="snapshot-priority",
        snapshot_version=1,
        isolation_key=scope,
        policy_version="memory-policy/v1",
        source_record_versions={"record-1": "memory-record/v1:memory-policy/v1:v1"},
        inferred_preferences={"budget": {"value": "low"}},
        stable_explicit_preferences={"budget": {"value": "medium"}},
        session_requirements={"budget": {"value": "high"}},
        explicit_hard_constraints={"budget": {"value": "hard"}},
        strategy_feedback={"budget": {"value": "deep"}},
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert PreferenceResolver().effective_constraints(snapshot) == {"budget": {"value": "hard"}}
