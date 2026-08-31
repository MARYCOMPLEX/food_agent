"""Cancellation-signal routing for account-auth Temporal workflows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from xhs_food.contracts import WorkflowStart
from xhs_food.foundation.temporal import (
    FoundationAdapterError,
    TemporalTaskQueues,
    TemporalWorkerQuota,
    TemporalWorkflowAdapter,
)

pytestmark = pytest.mark.unit


class _Handle:
    def __init__(
        self,
        workflow_id: str,
        *,
        description: Any | None = None,
        run_id: str = "run-1",
    ) -> None:
        self.id = workflow_id
        self.result_run_id = run_id
        self.description = description
        self.signals: list[tuple[str, dict[str, Any]]] = []
        self.describe_calls = 0

    async def signal(self, name: str, payload: dict[str, Any]) -> None:
        self.signals.append((name, payload))

    async def describe(self) -> Any:
        self.describe_calls += 1
        if isinstance(self.description, BaseException):
            raise self.description
        return self.description


class _Client:
    def __init__(self, handle: _Handle) -> None:
        self.handle = handle
        self.start_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def start_workflow(self, *args: Any, **kwargs: Any) -> _Handle:
        self.start_calls.append((args, kwargs))
        return self.handle

    def get_workflow_handle(self, workflow_id: str, **_kwargs: Any) -> _Handle:
        assert workflow_id == self.handle.id
        return self.handle


def _queues() -> TemporalTaskQueues:
    return TemporalTaskQueues(
        account_auth="account-auth",
        account_auth_quota=TemporalWorkerQuota(
            "account-auth",
            max_concurrent_activities=2,
            max_concurrent_workflows=2,
            priority=75,
            enabled=True,
        ),
    )


def _auth_command(workflow_id: str = "flow-auth-1") -> WorkflowStart:
    return WorkflowStart(
        workflow_id=workflow_id,
        workflow_type="platform-account-auth/v1",
        task_queue="account-auth",
        input={"flow_id": workflow_id},
        idempotency_key=f"idem-{workflow_id}",
    )


@pytest.mark.asyncio
async def test_account_auth_start_remembers_cancel_signal_for_arbitrary_flow_id() -> None:
    handle = _Handle("flow-auth-1")
    adapter = TemporalWorkflowAdapter(_Client(handle), task_queues=_queues(), enabled=True)

    await adapter.start(_auth_command())
    await adapter.cancel("flow-auth-1", reason="operator requested")

    assert handle.signals == [
        ("platform-account-auth.cancel.requested", {"reason": "operator requested"})
    ]
    # The local admission hint avoids a metadata RPC for the common API path.
    assert handle.describe_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "run_id"),
    [
        ("active run receives signal", "run-active"),
        ("completed run starts successor", "run-successor"),
    ],
)
async def test_account_auth_signal_with_start_is_atomic_for_active_or_completed_run(
    case: str,
    run_id: str,
) -> None:
    # Temporal chooses whether this handle represents the existing active run
    # or a new successor after a completed run.  The adapter must use the same
    # atomic request and stable Workflow ID in both cases.
    handle = _Handle("flow-auth-atomic", run_id=run_id)
    client = _Client(handle)
    adapter = TemporalWorkflowAdapter(client, task_queues=_queues(), enabled=True)
    command = _auth_command("flow-auth-atomic")

    result = await adapter.signal_with_start(
        command,
        "platform-account-auth.cancel.requested",
        {"reason": case},
    )

    assert result.workflow_id == command.workflow_id
    assert result.run_id == run_id
    assert len(client.start_calls) == 1
    args, kwargs = client.start_calls[0]
    assert args == ("platform-account-auth/v1", {"flow_id": command.workflow_id})
    assert kwargs["id"] == command.workflow_id
    assert kwargs["task_queue"] == "account-auth"
    assert kwargs["id_conflict_policy"].name == "USE_EXISTING"
    assert kwargs["id_reuse_policy"].name == "ALLOW_DUPLICATE"
    assert kwargs["start_signal"] == "platform-account-auth.cancel.requested"
    assert kwargs["start_signal_args"] == [{"reason": case}]


@pytest.mark.asyncio
async def test_account_auth_flow_prefix_routes_after_adapter_restart() -> None:
    handle = _Handle("flow-generated-after-restart")
    adapter = TemporalWorkflowAdapter(_Client(handle), task_queues=_queues(), enabled=True)

    # PlatformLoginService-generated IDs start with ``flow-`` and remain
    # routable even when cancellation is handled by a fresh API process.
    await adapter.cancel("flow-generated-after-restart", reason=None)

    assert handle.signals == [
        ("platform-account-auth.cancel.requested", {"reason": ""})
    ]
    assert handle.describe_calls == 0


@pytest.mark.asyncio
async def test_custom_account_auth_id_uses_temporal_description() -> None:
    description = SimpleNamespace(
        workflow_type="platform-account-auth/v1",
        task_queue="custom-account-auth",
    )
    handle = _Handle("custom-login-id", description=description)
    queues = TemporalTaskQueues(
        account_auth="custom-account-auth",
        account_auth_quota=TemporalWorkerQuota(
            "custom-account-auth", 2, 2, 75, enabled=True
        ),
    )
    adapter = TemporalWorkflowAdapter(_Client(handle), task_queues=queues, enabled=True)

    await adapter.cancel("custom-login-id", reason="cancel")

    assert handle.signals == [
        ("platform-account-auth.cancel.requested", {"reason": "cancel"})
    ]
    assert handle.describe_calls == 1


@pytest.mark.asyncio
async def test_unclassifiable_custom_id_fails_closed() -> None:
    handle = _Handle("custom-login-id", description=RuntimeError("visibility unavailable"))
    adapter = TemporalWorkflowAdapter(_Client(handle), task_queues=_queues(), enabled=True)

    with pytest.raises(FoundationAdapterError) as caught:
        await adapter.cancel("custom-login-id")

    assert caught.value.error.boundary_ref == "workflow.cancel.resolve"
    assert handle.signals == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("workflow_id", "expected"),
    [
        ("research:task-1", "research.cancel.requested"),
        ("refresh:job-1", "refresh.cancel.requested"),
        ("media:job-1", "media.cancel.requested"),
    ],
)
async def test_existing_workload_cancel_signals_remain_unchanged(
    workflow_id: str, expected: str
) -> None:
    handle = _Handle(workflow_id)
    adapter = TemporalWorkflowAdapter(_Client(handle), task_queues=_queues(), enabled=True)

    await adapter.cancel(workflow_id)

    assert handle.signals == [(expected, {"reason": ""})]
    assert handle.describe_calls == 0
