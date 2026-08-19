"""Regression tests for memory lifecycle, media lineage, and object-key hardening."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    MediaAsset,
    MemoryRecord,
    PersonalizationPolicy,
    PreferenceSnapshot,
    ToolCall,
    UserIsolationKey,
)
from xhs_food.contracts.ports import ObjectRef
from xhs_food.contracts.refresh_media import RefreshDeltaScope, RefreshJob, RefreshPriorityReason

ROOT = Path(__file__).parents[1]
MEMORY_FIXTURE = ROOT / "tests/fixtures/authority/memory_privacy_v1.json"


def _memory_records() -> list[dict[str, object]]:
    fixture = json.loads(MEMORY_FIXTURE.read_text(encoding="utf-8"))
    return fixture["exampleRecords"]


def test_memory_lifecycle_rejects_reversed_timestamps_withdrawn_active_and_duplicates() -> None:
    record = _memory_records()[0]

    reversed_times = copy.deepcopy(record)
    cast(dict[str, Any], reversed_times)["updatedAt"] = "2026-08-18T00:00:00Z"
    with pytest.raises(ValidationError, match="valid_from must not be after updated_at"):
        MemoryRecord.model_validate(reversed_times)

    withdrawn = copy.deepcopy(record)
    cast(dict[str, Any], withdrawn["consent"])["status"] = "withdrawn"
    with pytest.raises(ValidationError, match="active memory requires active consent"):
        MemoryRecord.model_validate(withdrawn)

    duplicate_source = copy.deepcopy(record)
    cast(dict[str, Any], duplicate_source)["sourceEventIds"] = ["turn-001", "turn-001"]
    with pytest.raises(ValidationError, match="source_event_ids"):
        MemoryRecord.model_validate(duplicate_source)


def test_memory_expiry_windows_and_inferred_support_ids_follow_authority() -> None:
    records = _memory_records()

    session = copy.deepcopy(records[0])
    cast(dict[str, Any], session)["expiresAt"] = "2026-08-21T01:00:00Z"
    with pytest.raises(ValidationError, match="24 hours"):
        MemoryRecord.model_validate(session)

    inferred = copy.deepcopy(records[2])
    cast(dict[str, Any], inferred["value"])["supportEventIds"] = ["favorite-001"]
    with pytest.raises(ValidationError, match="match source_event_ids"):
        MemoryRecord.model_validate(inferred)

    inferred = copy.deepcopy(records[2])
    cast(dict[str, Any], inferred)["expiresAt"] = "2027-01-27T00:00:00Z"
    with pytest.raises(ValidationError, match="180 days"):
        MemoryRecord.model_validate(inferred)

    feedback = copy.deepcopy(records[3])
    cast(dict[str, Any], feedback)["expiresAt"] = "2026-11-07T00:00:00Z"
    with pytest.raises(ValidationError, match="90 days"):
        MemoryRecord.model_validate(feedback)

    explicit = MemoryRecord.model_validate(records[1])
    assert explicit.expires_at is None


def test_active_and_expired_sessions_preserve_the_24_hour_window() -> None:
    active = MemoryRecord.model_validate(_memory_records()[0])
    session = copy.deepcopy(_memory_records()[0])
    cast(dict[str, Any], session)["status"] = "expired"
    cast(dict[str, Any], session)["updatedAt"] = "2026-08-20T02:00:00Z"

    expired = MemoryRecord.model_validate(session)

    assert active.status.value == "active"
    assert active.expires_at == datetime(2026, 8, 20, 1, tzinfo=UTC)
    assert expired.status.value == "expired"
    assert expired.expires_at == active.expires_at


def test_session_memory_rejects_invalid_active_and_expired_24_hour_windows() -> None:
    active = copy.deepcopy(_memory_records()[0])
    cast(dict[str, Any], active)["updatedAt"] = "2026-08-19T02:00:00Z"
    with pytest.raises(ValidationError, match="24 hours"):
        MemoryRecord.model_validate(active)

    expired = copy.deepcopy(_memory_records()[0])
    cast(dict[str, Any], expired)["status"] = "expired"
    cast(dict[str, Any], expired)["expiresAt"] = "2026-08-19T02:00:00Z"
    cast(dict[str, Any], expired)["updatedAt"] = "2026-08-19T03:00:00Z"
    with pytest.raises(ValidationError, match="24 hours"):
        MemoryRecord.model_validate(expired)

    not_reached = copy.deepcopy(_memory_records()[0])
    cast(dict[str, Any], not_reached)["status"] = "expired"
    cast(dict[str, Any], not_reached)["updatedAt"] = "2026-08-19T23:59:59Z"
    with pytest.raises(ValidationError, match="reached expires_at"):
        MemoryRecord.model_validate(not_reached)

    impossible_future_activity = copy.deepcopy(_memory_records()[0])
    cast(dict[str, Any], impossible_future_activity)["status"] = "superseded"
    cast(dict[str, Any], impossible_future_activity)["expiresAt"] = "2026-08-21T02:00:00Z"
    with pytest.raises(ValidationError, match="24 hours"):
        MemoryRecord.model_validate(impossible_future_activity)


@pytest.mark.parametrize("session_id", ["", "   "])
def test_memory_record_rejects_empty_optional_session_scope(session_id: str) -> None:
    record = copy.deepcopy(_memory_records()[1])
    cast(dict[str, Any], record)["sessionId"] = session_id

    with pytest.raises(ValidationError):
        MemoryRecord.model_validate(record)


@pytest.mark.parametrize("session_id", ["", "   "])
def test_user_isolation_key_rejects_empty_session_scope(session_id: str) -> None:
    without_session = UserIsolationKey(
        tenant_id="tenant-cn-1",
        user_id="user-2b4aa1b95c884d64",
    )
    with_session = UserIsolationKey(
        tenant_id="tenant-cn-1",
        user_id="user-2b4aa1b95c884d64",
        session_id="session-1",
    )

    assert without_session.partition == ("tenant-cn-1", "user-2b4aa1b95c884d64")
    assert with_session.partition == (
        "tenant-cn-1",
        "user-2b4aa1b95c884d64",
        "session-1",
    )
    assert without_session.namespaced_key("memory") != with_session.namespaced_key("memory")

    with pytest.raises(ValidationError):
        UserIsolationKey(
            tenant_id="tenant-cn-1",
            user_id="user-2b4aa1b95c884d64",
            session_id=session_id,
        )


def test_private_mapping_values_are_deeply_immutable() -> None:
    records = _memory_records()
    inferred = MemoryRecord.model_validate(records[2])
    snapshot = PreferenceSnapshot(
        snapshot_id="snapshot-hardening",
        snapshot_version=1,
        isolation_key={
            "kind": "user",
            "tenant_id": "tenant-cn-1",
            "user_id": "user-2b4aa1b95c884d64",
        },  # type: ignore[arg-type]
        policy_version="memory-policy/v1",
        source_record_versions={"record-1": "v1"},
        explicit_hard_constraints={"diet": {"spice": "mild"}},
        generated_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    policy = PersonalizationPolicy(
        policy_id="policy-hardening",
        policy_version="personalization-policy/v1",
        isolation_key=snapshot.isolation_key,
        preference_snapshot_id=snapshot.snapshot_id,
        preference_snapshot_version=snapshot.snapshot_version,
        hard_filters={"diet": {"spice": "mild"}},
        ranking_weights={"locality": 1.0},
    )
    refresh = RefreshJob(
        job_id="refresh-hardening",
        family_id="family.fixture",
        base_bundle_version=1,
        delta_scope=RefreshDeltaScope(partition_ids=("documents",)),
        watermarks={"source": "opaque"},
        priority_reasons=(RefreshPriorityReason.EXPLICIT_REQUEST,),
        workflow_id="workflow-hardening",
        idempotency_key="idempotency-hardening",
        requested_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    call = ToolCall(call_id="call-hardening", tool_name="fixture", arguments={"nested": {"x": 1}})

    for mapping in (
        inferred.value,
        snapshot.explicit_hard_constraints,
        policy.hard_filters,
        refresh.watermarks,
        call.arguments,
    ):
        with pytest.raises((TypeError, AttributeError)):
            mapping["mutation"] = "blocked"  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        inferred.value["supportEventIds"].append("blocked")  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "key",
    [
        "https://objects.invalid/raw",
        "https://user:secret@objects.invalid/raw",
        "raw/object?token=secret",
        "raw/object#fragment",
        "raw/credentials/password",
        "/absolute/object",
        "raw/../object",
        "raw\\object",
    ],
)
def test_object_ref_rejects_url_query_token_and_traversal_key_shapes(key: str) -> None:
    with pytest.raises(ValidationError):
        ObjectRef(
            object_id="object-hardening",
            key=key,
            content_hash="a" * 64,
            size_bytes=1,
            content_type="application/octet-stream",
        )


def test_media_asset_requires_declared_type_and_hash_to_match_fetched_object() -> None:
    from test_unit_refresh_media_contracts import _media_asset

    payload = _media_asset().model_dump(mode="json")
    payload["media_ref"]["media_type"] = "audio"
    with pytest.raises(ValidationError, match="media_type"):
        MediaAsset.model_validate(payload)

    payload = _media_asset().model_dump(mode="json")
    payload["media_ref"]["declared_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="declared_sha256"):
        MediaAsset.model_validate(payload)
