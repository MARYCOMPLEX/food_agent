"""Workflow-ID routing tests for the platform login use case."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xhs_food.contracts import (
    AccountGrantPermission,
    PlatformAccountGrant,
    PlatformChannel,
    WorkflowRun,
    WorkflowStart,
)
from xhs_food.experience import LoginMode, PlatformLoginService
from xhs_food.foundation.platform_accounts import InMemoryPlatformAccountAuthority
from xhs_food.foundation.platform_login_temporal import build_account_auth_workflow_start

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


class _RecordingWorkflow:
    """Minimal WorkflowPort seam that records the command target IDs."""

    def __init__(self) -> None:
        self.starts: list[WorkflowStart] = []
        self.cancels: list[tuple[str, str | None]] = []
        self.signal_starts: list[tuple[WorkflowStart, str, dict[str, object]]] = []

    async def start(self, command: WorkflowStart) -> WorkflowRun:
        self.starts.append(command)
        return WorkflowRun(
            workflow_id=command.workflow_id,
            run_id=f"run-{len(self.starts)}",
            status="running",
        )

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        self.cancels.append((workflow_id, reason))

    async def signal_with_start(
        self,
        command: WorkflowStart,
        signal: str,
        payload: dict[str, object],
    ) -> WorkflowRun:
        self.signal_starts.append((command, signal, payload))
        return WorkflowRun(
            workflow_id=command.workflow_id,
            run_id=f"cancel-run-{len(self.signal_starts)}",
            status="running",
        )


class _CancelOnlyWorkflow:
    """Legacy WorkflowPort without the optional signal-with-start method."""

    def __init__(self) -> None:
        self.starts: list[WorkflowStart] = []
        self.cancels: list[tuple[str, str | None]] = []

    async def start(self, command: WorkflowStart) -> WorkflowRun:
        self.starts.append(command)
        return WorkflowRun(
            workflow_id=command.workflow_id,
            run_id=f"run-{len(self.starts)}",
            status="running",
        )

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        self.cancels.append((workflow_id, reason))


async def _service(
    workflow: _RecordingWorkflow | _CancelOnlyWorkflow | None = None,
) -> tuple[
    PlatformLoginService,
    _RecordingWorkflow | _CancelOnlyWorkflow,
]:
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    account = await authority.register_account(
        tenant_id="tenant-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="account-1",
        alias="primary",
        now=NOW,
    )
    await authority.add_grant(
        PlatformAccountGrant(
            grant_id="grant-login",
            account=account.ref,
            principal_id="principal-a",
            permissions=(
                AccountGrantPermission.VIEW,
                AccountGrantPermission.LOGIN,
            ),
            issued_at=NOW,
        )
    )
    workflow = workflow or _RecordingWorkflow()
    return (
        PlatformLoginService(
            accounts=authority,
            workflow=workflow,
            workflow_start_builder=build_account_auth_workflow_start,
            queue="account-auth",
            clock=lambda: NOW,
        ),
        workflow,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "credential_ref"),
    [
        (LoginMode.QR, None),
        (LoginMode.PHONE, "vault:phone-1"),
        (LoginMode.COOKIE, "vault:cookie-1"),
    ],
)
async def test_login_modes_use_the_public_flow_id_as_workflow_target(
    mode: LoginMode, credential_ref: str | None
) -> None:
    service, workflow = await _service()

    submission = await service.start_login(
        tenant_id="tenant-a",
        principal_id="principal-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="account-1",
        mode=mode,
        idempotency_key=f"start-{mode.value}",
        credential_ref=credential_ref,
    )

    command = workflow.starts[-1]
    assert command.workflow_id == submission.flow.flow_id
    assert command.input["request"]["flow_id"] == submission.flow.flow_id
    assert command.workflow_id.startswith("flow-")


@pytest.mark.unit
async def test_poll_and_cancel_share_one_stable_flow_workflow_id() -> None:
    service, workflow = await _service()
    submission = await service.start_login(
        tenant_id="tenant-a",
        principal_id="principal-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="account-1",
        mode=LoginMode.QR,
        idempotency_key="stable-flow",
    )
    flow_id = submission.flow.flow_id

    # Poll requests may use different HTTP idempotency keys, but they still
    # belong to the same login attempt and therefore must target its stable
    # Temporal ID.  Temporal's USE_EXISTING/ALLOW_DUPLICATE policy serializes
    # an active run and starts a new run after a completed poll.
    first_poll = await service.poll(
        tenant_id="tenant-a",
        principal_id="principal-a",
        flow_id=flow_id,
        idempotency_key="poll-1",
    )
    second_poll = await service.poll(
        tenant_id="tenant-a",
        principal_id="principal-a",
        flow_id=flow_id,
        idempotency_key="poll-2",
    )
    assert first_poll.workflow is not None
    assert second_poll.workflow is not None
    assert [item.workflow_id for item in workflow.starts] == [flow_id, flow_id, flow_id]

    await service.cancel(
        tenant_id="tenant-a",
        principal_id="principal-a",
        flow_id=flow_id,
        reason="operator requested",
    )
    assert isinstance(workflow, _RecordingWorkflow)
    assert workflow.cancels == []
    cancel_command, signal, payload = workflow.signal_starts[-1]
    assert cancel_command.workflow_id == flow_id
    assert cancel_command.input["request"]["operation"] == "cancel"
    assert signal == "platform-account-auth.cancel.requested"
    assert payload == {"reason": "operator requested"}


@pytest.mark.unit
async def test_cancel_targets_phone_and_cookie_flows_without_operation_suffix() -> None:
    service, workflow = await _service()
    for mode, credential_ref in (
        (LoginMode.PHONE, "vault:phone-1"),
        (LoginMode.COOKIE, "vault:cookie-1"),
    ):
        submission = await service.start_login(
            tenant_id="tenant-a",
            principal_id="principal-a",
            platform=PlatformChannel.XHS_PC,
            account_ref="account-1",
            mode=mode,
            idempotency_key=f"{mode.value}-cancel",
            credential_ref=credential_ref,
        )
        await service.cancel(
            tenant_id="tenant-a",
            principal_id="principal-a",
            flow_id=submission.flow.flow_id,
            reason=mode.value,
        )

    assert isinstance(workflow, _RecordingWorkflow)
    assert [command.workflow_id for command, _, _ in workflow.signal_starts] == [
        command.workflow_id for command in workflow.starts
    ]
    assert all(
        "-poll-" not in command.workflow_id
        for command, _, _ in workflow.signal_starts
    )


@pytest.mark.unit
async def test_cancel_keeps_plain_workflow_port_compatibility_fallback() -> None:
    legacy_workflow = _CancelOnlyWorkflow()
    service, workflow = await _service(legacy_workflow)
    submission = await service.start_login(
        tenant_id="tenant-a",
        principal_id="principal-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="account-1",
        mode=LoginMode.QR,
        idempotency_key="legacy-cancel",
    )

    await service.cancel(
        tenant_id="tenant-a",
        principal_id="principal-a",
        flow_id=submission.flow.flow_id,
        reason="legacy",
    )

    assert workflow.cancels == [(submission.flow.flow_id, "legacy")]
