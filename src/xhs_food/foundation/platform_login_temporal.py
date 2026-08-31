"""Temporal account-auth workflow and provider-neutral login activities.

The workflow carries only account/flow identifiers and redacted status.  A
``PlatformLoginTemporalActivities`` instance receives the project-owned login
coordinator at worker construction; provider cookies, QR bytes, and decrypted
session material therefore remain activity-local and never enter Temporal
history.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ActivityConfig

from xhs_food.contracts import (
    ContractPayload,
    LoginActivityOperation,
    LoginFlowState,
    PlatformLoginActivityRequest,
    PlatformLoginActivityResult,
    PlatformLoginWorkflowInput,
    PlatformLoginWorkflowOutput,
    TemporalExecutionPolicy,
    WorkflowStart,
)

ACCOUNT_AUTH_WORKFLOW_TYPE = "platform-account-auth/v1"
ACCOUNT_AUTH_TASK_QUEUE = "account-auth"
ACCOUNT_AUTH_CREATE_QR_ACTIVITY = "platform-account-auth.create-qr/v1"
ACCOUNT_AUTH_POLL_ACTIVITY = "platform-account-auth.poll/v1"
ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY = "platform-account-auth.phone-login/v1"
ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY = "platform-account-auth.cookie-import/v1"
ACCOUNT_AUTH_CANCEL_ACTIVITY = "platform-account-auth.cancel/v1"
ACCOUNT_AUTH_CANCEL_SIGNAL = "platform-account-auth.cancel.requested"


def account_auth_activity_config(
    policy: TemporalExecutionPolicy,
    *,
    timeout_seconds: int | None = None,
) -> ActivityConfig:
    """Translate the shared execution policy for bounded auth Activities."""

    timeout = (
        policy.activity_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    if timeout < 1:
        raise ValueError("account-auth Activity timeout must be positive")
    if policy.heartbeat_timeout_seconds > timeout:
        raise ValueError("account-auth heartbeat timeout cannot exceed Activity timeout")
    return {
        "start_to_close_timeout": timedelta(seconds=timeout),
        "heartbeat_timeout": timedelta(seconds=policy.heartbeat_timeout_seconds),
        "retry_policy": RetryPolicy(
            initial_interval=timedelta(seconds=policy.retry_initial_interval_seconds),
            maximum_interval=timedelta(seconds=policy.retry_maximum_interval_seconds),
            backoff_coefficient=policy.retry_backoff_coefficient,
            maximum_attempts=policy.retry_maximum_attempts,
            non_retryable_error_types=list(policy.non_retryable_error_types),
        ),
    }


def build_account_auth_workflow_start(
    request: PlatformLoginActivityRequest,
    *,
    workflow_id: str,
    idempotency_key: str,
    execution_policy: TemporalExecutionPolicy | None = None,
    task_queue: str = ACCOUNT_AUTH_TASK_QUEUE,
) -> WorkflowStart:
    """Build a deterministic account-auth Workflow command."""

    if not workflow_id or not idempotency_key or not task_queue:
        raise ValueError("workflow_id, idempotency_key, and task_queue are required")
    policy = execution_policy or TemporalExecutionPolicy()
    payload = PlatformLoginWorkflowInput(request=request, execution_policy=policy)
    return WorkflowStart(
        workflow_id=workflow_id,
        workflow_type=ACCOUNT_AUTH_WORKFLOW_TYPE,
        task_queue=task_queue,
        input=payload.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )


@workflow.defn(name=ACCOUNT_AUTH_WORKFLOW_TYPE)
class TemporalAccountAuthWorkflow:
    """Execute one bounded login operation and honor cancellation signals."""

    def __init__(self) -> None:
        self._cancel_requested = False

    @workflow.signal(name=ACCOUNT_AUTH_CANCEL_SIGNAL)
    def request_cancel(self, _payload: Mapping[str, Any]) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, raw_input: Mapping[str, Any]) -> PlatformLoginWorkflowOutput:
        value = PlatformLoginWorkflowInput.model_validate(raw_input)
        request = value.request
        if self._cancel_requested and request.operation is not LoginActivityOperation.CANCEL:
            request = request.model_copy(update={"operation": LoginActivityOperation.CANCEL})

        result = await self._execute(request, value.execution_policy)
        # If cancellation races a create/poll Activity, perform the provider
        # cancellation at the same durable boundary before returning.
        if (
            self._cancel_requested
            and request.operation is not LoginActivityOperation.CANCEL
            and result.flow.state not in {
                LoginFlowState.SUCCEEDED,
                LoginFlowState.EXPIRED,
                LoginFlowState.FAILED,
                LoginFlowState.CANCELLED,
            }
        ):
            result = await self._execute(
                request.model_copy(update={"operation": LoginActivityOperation.CANCEL}),
                value.execution_policy,
            )
        return PlatformLoginWorkflowOutput(
            flow=result.flow,
            challenge=result.challenge,
        )

    async def _execute(
        self,
        request: PlatformLoginActivityRequest,
        policy: TemporalExecutionPolicy,
    ) -> PlatformLoginActivityResult:
        activity_name = {
            LoginActivityOperation.CREATE_QR: ACCOUNT_AUTH_CREATE_QR_ACTIVITY,
            LoginActivityOperation.POLL: ACCOUNT_AUTH_POLL_ACTIVITY,
            LoginActivityOperation.PHONE_LOGIN: ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY,
            LoginActivityOperation.COOKIE_IMPORT: ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY,
            LoginActivityOperation.CANCEL: ACCOUNT_AUTH_CANCEL_ACTIVITY,
        }[request.operation]
        raw_result = await workflow.execute_activity(
            activity_name,
            args=[request.model_dump(mode="json")],
            **account_auth_activity_config(policy),
        )
        if not isinstance(raw_result, Mapping):
            raise ApplicationError(
                "account-auth Activity returned a non-object",
                type="ValidationError",
            )
        try:
            return PlatformLoginActivityResult.model_validate(raw_result)
        except Exception:
            raise ApplicationError(
                "account-auth Activity returned an invalid result",
                type="ValidationError",
            ) from None


class PlatformLoginTemporalActivities:
    """Typed Activity façade around the injected login coordinator."""

    def __init__(self, coordinator: Any, *, heartbeat: Callable[[object], object] | None = None) -> None:
        self._coordinator = coordinator
        self._heartbeat = heartbeat

    @activity.defn(name=ACCOUNT_AUTH_CREATE_QR_ACTIVITY)
    async def create_qr(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        request = self._request(raw_input, LoginActivityOperation.CREATE_QR)
        self._beat(request)
        try:
            start_qr = self._coordinator.start_qr
            # Keep compatibility with injected coordinators implementing the
            # pre-v1 ``start_qr(account)`` surface while preferring the
            # account-scoped deterministic flow identifier when supported.
            if "flow_id" in inspect.signature(start_qr).parameters:
                flow, challenge = await start_qr(request.account, flow_id=request.flow_id)
            else:
                flow, challenge = await start_qr(request.account)
            # A legacy coordinator may generate a fresh ID when it does not
            # accept the deterministic flow_id argument.  Never let that
            # mismatched flow cross the Temporal boundary: callers must be
            # able to resume/cancel the exact flow they started.
            if flow.flow_id != request.flow_id or flow.account != request.account:
                raise ValueError("login coordinator returned a mismatched flow")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ApplicationError(_safe_message(exc), type="LoginProviderError") from None
        self._beat(request)
        return PlatformLoginActivityResult(flow=flow, challenge=challenge).model_dump(mode="json")

    @activity.defn(name=ACCOUNT_AUTH_POLL_ACTIVITY)
    async def poll(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        request = self._request(raw_input, LoginActivityOperation.POLL)
        self._beat(request)
        try:
            flow = await self._coordinator.poll(
                request.flow_id,
                tenant_id=request.account.tenant_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ApplicationError(_safe_message(exc), type="LoginProviderError") from None
        self._beat(request)
        return PlatformLoginActivityResult(flow=flow).model_dump(mode="json")

    @activity.defn(name=ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY)
    async def phone_login(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        request = self._request(raw_input, LoginActivityOperation.PHONE_LOGIN)
        self._beat(request)
        try:
            flow = await self._coordinator.phone_login(
                request.flow_id,
                tenant_id=request.account.tenant_id,
                credential_ref=request.credential_ref or "",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ApplicationError(_safe_message(exc), type="LoginProviderError") from None
        self._beat(request)
        return PlatformLoginActivityResult(flow=flow).model_dump(mode="json")

    @activity.defn(name=ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY)
    async def cookie_import(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        request = self._request(raw_input, LoginActivityOperation.COOKIE_IMPORT)
        self._beat(request)
        try:
            flow = await self._coordinator.cookie_import(
                request.flow_id,
                tenant_id=request.account.tenant_id,
                credential_ref=request.credential_ref or "",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ApplicationError(_safe_message(exc), type="LoginProviderError") from None
        self._beat(request)
        return PlatformLoginActivityResult(flow=flow).model_dump(mode="json")

    # Compatibility spelling used by a few provider adapters.
    async def import_cookie(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        return await self.cookie_import(raw_input)

    @activity.defn(name=ACCOUNT_AUTH_CANCEL_ACTIVITY)
    async def cancel(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        request = self._request(raw_input, LoginActivityOperation.CANCEL)
        self._beat(request)
        try:
            flow = await self._coordinator.cancel(
                request.flow_id,
                tenant_id=request.account.tenant_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ApplicationError(_safe_message(exc), type="LoginProviderError") from None
        self._beat(request)
        return PlatformLoginActivityResult(flow=flow).model_dump(mode="json")

    def activities(self) -> tuple[Any, ...]:
        return (
            self.create_qr,
            self.poll,
            self.phone_login,
            self.cookie_import,
            self.cancel,
        )

    @staticmethod
    def _request(
        raw_input: Mapping[str, Any], expected: LoginActivityOperation
    ) -> PlatformLoginActivityRequest:
        try:
            request = PlatformLoginActivityRequest.model_validate(raw_input)
        except Exception:
            raise ApplicationError(
                "account-auth Activity input is invalid",
                type="ValidationError",
            ) from None
        if request.operation is not expected:
            raise ApplicationError(
                "account-auth Activity operation does not match registration",
                type="ValidationError",
            )
        return request

    def _beat(self, request: PlatformLoginActivityRequest) -> None:
        payload = {"flow_id": request.flow_id, "operation": request.operation.value}
        callback = self._heartbeat
        if callback is not None:
            callback(payload)
            return
        try:
            activity.heartbeat(payload)
        except RuntimeError:
            # Unit calls outside a Temporal worker have no heartbeat context.
            return


def _safe_message(exc: BaseException) -> str:
    import re

    text = str(exc) or "account-auth provider failure"
    text = re.sub(
        r"(?i)([\"']?(?:cookie|cookie[_ -]?str|authorization|bearer|token|password|passwd|secret|"
        r"qruuid|storage[_ -]?state|signer[_ -]?(?:input|state)|xsec[_ -]?token)[\"']?"
        r"\s*[:=]\s*[\"']?)[^\"'\r\n,;}]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "bearer <redacted>", text)
    return text[:256]


__all__ = [
    "ACCOUNT_AUTH_CANCEL_ACTIVITY",
    "ACCOUNT_AUTH_CANCEL_SIGNAL",
    "ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY",
    "ACCOUNT_AUTH_CREATE_QR_ACTIVITY",
    "ACCOUNT_AUTH_POLL_ACTIVITY",
    "ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY",
    "ACCOUNT_AUTH_TASK_QUEUE",
    "ACCOUNT_AUTH_WORKFLOW_TYPE",
    "PlatformLoginTemporalActivities",
    "TemporalAccountAuthWorkflow",
    "account_auth_activity_config",
    "build_account_auth_workflow_start",
]
