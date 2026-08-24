"""B4 Refresh Workflow identity and Activity boundary contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from xhs_food.composition import build_refresh_worker
from xhs_food.contracts import (
    BundleRefreshResult,
    RefreshDeltaScope,
    RefreshJob,
    RefreshPriorityReason,
    TemporalExecutionPolicy,
)
from xhs_food.foundation import TemporalTaskQueues, TemporalWorkerQuota
from xhs_food.orchestrator import (
    REFRESH_TASK_QUEUE,
    REFRESH_WORKFLOW_TYPE,
    RefreshActivities,
    build_refresh_workflow_start,
    refresh_activity_config,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _job() -> RefreshJob:
    return RefreshJob(
        job_id="refresh-job-1",
        family_id="family.fixture",
        base_bundle_version=3,
        delta_scope=RefreshDeltaScope(partition_ids=("documents",)),
        watermarks={"fixture": "opaque:3"},
        priority_reasons=(RefreshPriorityReason.EXPIRING,),
        workflow_id="refresh:family.fixture:3:documents",
        idempotency_key="refresh-idempotency-1",
        requested_at=NOW,
    )


@pytest.mark.unit
def test_refresh_start_uses_job_identity_and_shared_policy() -> None:
    policy = TemporalExecutionPolicy(retry_maximum_attempts=4)
    command = build_refresh_workflow_start(_job(), execution_policy=policy)

    assert command.workflow_id == _job().workflow_id
    assert command.idempotency_key == _job().idempotency_key
    assert command.task_queue == REFRESH_TASK_QUEUE
    assert command.workflow_type == REFRESH_WORKFLOW_TYPE
    assert command.input["execution_policy"]["retry_maximum_attempts"] == 4
    config = refresh_activity_config(policy)
    assert config["heartbeat_timeout"].total_seconds() == 30
    assert config["retry_policy"].maximum_attempts == 4


@pytest.mark.unit
async def test_refresh_activity_delegates_bundle_cas_service_and_returns_receipt() -> None:
    calls: list[tuple[str, str | None]] = []

    async def execute(job: RefreshJob, expected_profile_id: str | None) -> BundleRefreshResult:
        calls.append((job.job_id, expected_profile_id))
        return BundleRefreshResult.model_construct(
            bundle=SimpleNamespace(bundle_id="family.fixture.bundle.v4", bundle_version=4),
            derivation=SimpleNamespace(),
            activated=True,
        )

    activities = RefreshActivities(execute)
    raw = {
        "job": _job().model_dump(mode="json"),
        "expected_profile_id": "bge-m3/profile_v1",
    }
    result = await activities.execute(raw)

    assert calls == [("refresh-job-1", "bge-m3/profile_v1")]
    assert result == {
        "status": "completed",
        "activated": True,
        "bundle_id": "family.fixture.bundle.v4",
        "bundle_version": 4,
    }
    assert activities.activities() == (activities.execute,)


@pytest.mark.unit
def test_refresh_composition_worker_registers_refresh_workflow_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_worker(client: Any, activities: Any, **kwargs: Any) -> object:
        del activities
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("xhs_food.foundation.build_temporal_refresh_worker", fake_worker)
    queues = TemporalTaskQueues(
        refresh_quota=TemporalWorkerQuota("refresh", 2, 2, 50, enabled=True)
    )

    build_refresh_worker(object(), type("Activities", (), {"activities": lambda self: ()})(), task_queues=queues)

    assert captured["task_queues"].refresh == "refresh"
    assert [workflow.__name__ for workflow in captured["workflows"]] == ["TemporalRefreshWorkflow"]
