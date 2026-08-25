"""B4 queue isolation and failed-workflow operator contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from xhs_food.composition import build_media_worker, build_refresh_worker
from xhs_food.contracts import (
    FailedWorkflow,
    TemporalExecutionPolicy,
    WorkflowOperatorPort,
    WorkflowRecoveryAction,
    WorkflowRetryRequest,
    WorkflowStart,
    WorkflowTerminateRequest,
)
from xhs_food.foundation import (
    TemporalTaskQueues,
    TemporalWorkerQuota,
    TemporalWorkflowAdapter,
    build_temporal_media_worker,
    build_temporal_refresh_worker,
)


class _Worker:
    def __init__(self, client: Any, **kwargs: Any) -> None:
        self.client = client
        self.kwargs = kwargs


class _Activities:
    def activities(self) -> tuple[str, ...]:
        return ("activity",)


def _all_enabled_queues() -> TemporalTaskQueues:
    return TemporalTaskQueues(
        research_quota=TemporalWorkerQuota("research", 8, 8, 100),
        refresh_quota=TemporalWorkerQuota("refresh", 2, 2, 50, enabled=True),
        media_quota=TemporalWorkerQuota("media", 2, 2, 25, enabled=True),
    )


@pytest.mark.unit
def test_task_queues_keep_workloads_isolated_and_ordered() -> None:
    queues = _all_enabled_queues()

    assert queues.allowed == frozenset({"research", "refresh", "media"})
    assert queues.active == queues.allowed
    assert queues.priority_order == ("research", "refresh", "media")
    assert queues.queue_for("refresh") == "refresh"
    assert queues.quota_for_workload("media").max_concurrent_activities == 2
    with pytest.raises(ValueError, match="workload"):
        queues.queue_for("dead-letter")


@pytest.mark.unit
def test_research_policy_reuses_shared_temporal_execution_contract() -> None:
    from xhs_food.orchestrator import ReliableTaskConfig

    policy = ReliableTaskConfig(retry_maximum_attempts=5)
    assert isinstance(policy, TemporalExecutionPolicy)
    assert policy.activity_timeout_seconds == 300
    assert policy.heartbeat_timeout_seconds == 30
    assert policy.retry_maximum_attempts == 5


@pytest.mark.unit
def test_refresh_and_media_workers_are_disabled_until_explicit_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("temporalio.worker.Worker", _Worker)

    with pytest.raises(ValueError, match="disabled"):
        build_temporal_refresh_worker(object(), _Activities())
    with pytest.raises(ValueError, match="disabled"):
        build_temporal_media_worker(object(), _Activities())

    refresh = build_refresh_worker(
        object(),
        _Activities(),
        task_queues=_all_enabled_queues(),
    )
    media = build_media_worker(
        object(),
        _Activities(),
        task_queues=_all_enabled_queues(),
    )
    assert refresh.kwargs["task_queue"] == "refresh"
    assert media.kwargs["task_queue"] == "media"
    assert refresh.kwargs["max_concurrent_workflow_tasks"] == 2
    assert media.kwargs["max_concurrent_activities"] == 2


class _WorkflowHandle:
    def __init__(self, workflow_id: str, run_id: str) -> None:
        self.id = workflow_id
        self.run_id = run_id
        self.terminated: list[str] = []

    async def describe(self) -> Any:
        return SimpleNamespace(
            status="FAILED",
            execution=SimpleNamespace(run_id=self.run_id),
        )

    async def terminate(self, *, reason: str) -> None:
        self.terminated.append(reason)


class _SdkWorkflowHandle(_WorkflowHandle):
    async def describe(self) -> Any:
        # Temporal Python SDK WorkflowExecutionDescription exposes run_id
        # directly; the base fake covers the older compatibility shape.
        return SimpleNamespace(status=SimpleNamespace(name="FAILED"), run_id=self.run_id)


class _WorkflowClient:
    def __init__(self) -> None:
        self.handle = _WorkflowHandle("research:task-1", "run-old")
        self.started: list[dict[str, Any]] = []

    def list_workflows(self, **_: Any) -> list[Any]:
        return [
            SimpleNamespace(
                id="research:task-1",
                run_id="run-old",
                type="research-task/v1",
                task_queue="research",
                status="FAILED",
            ),
            SimpleNamespace(
                id="refresh:family-1",
                run_id="run-refresh",
                type="refresh/v1",
                task_queue="refresh",
                status="COMPLETED",
            ),
        ]

    async def start_workflow(self, *_: Any, **kwargs: Any) -> Any:
        self.started.append(kwargs)
        return SimpleNamespace(id=kwargs["id"], result_run_id="run-new")

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> _WorkflowHandle:
        assert workflow_id == self.handle.id
        if run_id is not None:
            assert run_id == self.handle.run_id
        return self.handle


@pytest.mark.unit
async def test_temporal_describe_reads_sdk_workflow_execution_shape() -> None:
    client = _WorkflowClient()
    client.handle = _SdkWorkflowHandle("research:task-1", "run-sdk")
    adapter = TemporalWorkflowAdapter(
        client,
        task_queues=TemporalTaskQueues(),
        enabled=True,
    )

    described = await adapter.describe("research:task-1")

    assert described is not None
    assert described.run_id == "run-sdk"
    assert described.status == "failed"


@pytest.mark.unit
async def test_failed_workflow_operator_uses_temporal_history_without_dlq() -> None:
    client = _WorkflowClient()
    adapter = TemporalWorkflowAdapter(
        client,
        task_queues=TemporalTaskQueues(),
        enabled=True,
    )

    assert isinstance(adapter, WorkflowOperatorPort)
    failed = await adapter.list_failed_workflows(task_queue="research")
    assert failed == (
        FailedWorkflow(
            workflow_id="research:task-1",
            run_id="run-old",
            workflow_type="research-task/v1",
            task_queue="research",
        ),
    )

    command = WorkflowStart(
        workflow_id="research:task-1",
        workflow_type="research-task/v1",
        task_queue="research",
        input={"task_id": "task-1"},
        idempotency_key="task-1",
    )
    retry = await adapter.retry_workflow(
        WorkflowRetryRequest(command=command, expected_run_id="run-old")
    )
    assert retry.action is WorkflowRecoveryAction.RETRY
    assert retry.run_id == "run-new"
    assert client.started[0]["id"] == "research:task-1"

    terminated = await adapter.terminate_workflow(
        WorkflowTerminateRequest(
            workflow_id="research:task-1",
            run_id="run-old",
            reason="operator recovery",
        )
    )
    assert terminated.action is WorkflowRecoveryAction.TERMINATE
    assert client.handle.terminated == ["operator recovery"]
