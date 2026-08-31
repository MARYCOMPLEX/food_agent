"""Typed Temporal account-auth workflow/activity boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from temporalio.exceptions import ApplicationError

from xhs_food.contracts import (
    LoginActivityOperation,
    ObjectRef,
    PlatformAccountRef,
    PlatformChannel,
    PlatformLoginActivityRequest,
    PlatformLoginFlow,
    PlatformLoginWorkflowInput,
    TemporalExecutionPolicy,
)
from xhs_food.foundation.platform_login_temporal import _safe_message
from xhs_food.orchestrator import (
    ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY,
    ACCOUNT_AUTH_CREATE_QR_ACTIVITY,
    ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY,
    ACCOUNT_AUTH_POLL_ACTIVITY,
    ACCOUNT_AUTH_TASK_QUEUE,
    PlatformLoginTemporalActivities,
    account_auth_activity_config,
    build_account_auth_workflow_start,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _account() -> PlatformAccountRef:
    return PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="acct-1",
    )


def _flow(state: str = "waiting_scan") -> PlatformLoginFlow:
    return PlatformLoginFlow(
        flow_id="flow-1",
        account=_account(),
        state=state,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        updated_at=NOW,
        qr_object_ref=ObjectRef(
            object_id="qr-1",
            key="login-qr/tenant-a/dianping/flow-1.png",
            content_hash="a" * 64,
            size_bytes=4,
            content_type="image/png",
        ),
        qr_expires_at=NOW + timedelta(minutes=2),
    )


class _Coordinator:
    async def start_qr(self, account: PlatformAccountRef):
        assert account == _account()
        from xhs_food.contracts import LoginChallenge

        flow = _flow()
        return flow, LoginChallenge(
            flow_id=flow.flow_id,
            object_ref=flow.qr_object_ref,
            expires_at=flow.qr_expires_at,
        )

    async def poll(self, flow_id: str, *, tenant_id: str):
        assert (flow_id, tenant_id) == ("flow-1", "tenant-a")
        return _flow("waiting_confirmation")

    async def phone_login(self, flow_id: str, *, tenant_id: str, credential_ref: str):
        assert (flow_id, tenant_id, credential_ref) == ("flow-1", "tenant-a", "vault-phone-1")
        return _flow("waiting_confirmation")

    async def cookie_import(self, flow_id: str, *, tenant_id: str, credential_ref: str):
        assert (flow_id, tenant_id, credential_ref) == ("flow-1", "tenant-a", "vault-cookie-1")
        return _flow("waiting_confirmation")

    async def cancel(self, flow_id: str, *, tenant_id: str):
        assert (flow_id, tenant_id) == ("flow-1", "tenant-a")
        return _flow("cancelled")


@pytest.mark.unit
def test_account_auth_activity_config_is_bounded_and_retryable() -> None:
    policy = TemporalExecutionPolicy(
        activity_timeout_seconds=20,
        heartbeat_timeout_seconds=5,
        retry_maximum_attempts=2,
    )
    config = account_auth_activity_config(policy)
    assert config["start_to_close_timeout"] == timedelta(seconds=20)
    assert config["heartbeat_timeout"] == timedelta(seconds=5)
    assert config["retry_policy"].maximum_attempts == 2
    with pytest.raises(ValueError, match="heartbeat"):
        account_auth_activity_config(
            policy.model_copy(update={"heartbeat_timeout_seconds": 30})
        )


@pytest.mark.unit
async def test_login_temporal_activities_emit_only_redacted_flow_metadata() -> None:
    activities = PlatformLoginTemporalActivities(_Coordinator())
    create_request = PlatformLoginActivityRequest(
        flow_id="flow-1",
        account=_account(),
        operation=LoginActivityOperation.CREATE_QR,
    )
    created = await activities.create_qr(create_request.model_dump(mode="json"))
    assert created["flow"]["flow_id"] == "flow-1"
    assert "cookie" not in str(created).lower()
    assert "storage_state" not in str(created).lower()

    poll_request = create_request.model_copy(update={"operation": LoginActivityOperation.POLL})
    polled = await activities.poll(poll_request.model_dump(mode="json"))
    assert polled["flow"]["state"] == "waiting_confirmation"
    with pytest.raises(ApplicationError, match="does not match"):
        await activities.create_qr(poll_request.model_dump(mode="json"))

    phone_request = create_request.model_copy(
        update={
            "operation": LoginActivityOperation.PHONE_LOGIN,
            "credential_ref": "vault-phone-1",
        }
    )
    phone = await activities.phone_login(phone_request.model_dump(mode="json"))
    assert phone["flow"]["state"] == "waiting_confirmation"

    cookie_request = create_request.model_copy(
        update={
            "operation": LoginActivityOperation.COOKIE_IMPORT,
            "credential_ref": "vault-cookie-1",
        }
    )
    cookie = await activities.cookie_import(cookie_request.model_dump(mode="json"))
    assert cookie["flow"]["state"] == "waiting_confirmation"


@pytest.mark.unit
def test_account_auth_workflow_start_keeps_credentials_out_of_input() -> None:
    request = PlatformLoginActivityRequest(
        flow_id="flow-1",
        account=_account(),
        operation=LoginActivityOperation.POLL,
    )
    command = build_account_auth_workflow_start(
        request,
        workflow_id="auth:flow-1",
        idempotency_key="auth:flow-1",
    )
    assert command.task_queue == ACCOUNT_AUTH_TASK_QUEUE
    assert command.workflow_type == "platform-account-auth/v1"
    payload = PlatformLoginWorkflowInput.model_validate(command.input)
    assert payload.request.account == _account()
    assert "cookie" not in str(command.input).lower()
    assert "storage_state" not in str(command.input).lower()
    assert ACCOUNT_AUTH_CREATE_QR_ACTIVITY.endswith("create-qr/v1")
    assert ACCOUNT_AUTH_POLL_ACTIVITY.endswith("poll/v1")
    assert ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY.endswith("phone-login/v1")
    assert ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY.endswith("cookie-import/v1")


@pytest.mark.unit
def test_temporal_provider_error_redacts_bearer_value_and_storage_path() -> None:
    message = _safe_message(
        RuntimeError(
            "authorization: Bearer very-secret-token; storage_state=C:/tmp/cookies.json"
        )
    )
    assert "very-secret-token" not in message
    assert "cookies.json" not in message
    assert "<redacted>" in message


@pytest.mark.unit
async def test_activity_failure_does_not_chain_secret_bearing_exception() -> None:
    class LeakyCoordinator(_Coordinator):
        async def poll(self, flow_id: str, *, tenant_id: str):
            del flow_id, tenant_id
            raise RuntimeError("authorization: Bearer very-secret-token")

    activities = PlatformLoginTemporalActivities(LeakyCoordinator())
    request = PlatformLoginActivityRequest(
        flow_id="flow-1",
        account=_account(),
        operation=LoginActivityOperation.POLL,
    )
    with pytest.raises(ApplicationError) as caught:
        await activities.poll(request.model_dump(mode="json"))
    assert "very-secret-token" not in str(caught.value)
    assert caught.value.__cause__ is None
