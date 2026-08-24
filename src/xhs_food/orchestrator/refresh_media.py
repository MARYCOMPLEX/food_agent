"""Temporal Refresh workflow shell; storage and source work stay in Activities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ActivityConfig

from xhs_food.contracts import (
    BundleRefreshResult,
    ContractPayload,
    MediaFetchRequest,
    MediaFetchResult,
    MediaWorkflowInput,
    MediaWorkflowResult,
    RefreshJob,
    RefreshWorkflowInput,
    RefreshWorkflowResult,
    TemporalExecutionPolicy,
    WorkflowStart,
)

REFRESH_WORKFLOW_TYPE = "refresh-workflow/v1"
REFRESH_EXECUTE_ACTIVITY = "refresh.execute/v1"
REFRESH_TASK_QUEUE = "refresh"
REFRESH_CANCEL_SIGNAL = "refresh.cancel.requested"
MEDIA_WORKFLOW_TYPE = "media-workflow/v1"
MEDIA_FETCH_ACTIVITY = "media.fetch/v1"
MEDIA_TASK_QUEUE = "media"
MEDIA_CANCEL_SIGNAL = "media.cancel.requested"

RefreshExecutor = Callable[[RefreshJob, str | None], Awaitable[BundleRefreshResult]]
MediaFetchExecutor = Callable[[MediaFetchRequest], Awaitable[MediaFetchResult]]


def refresh_activity_config(
    policy: TemporalExecutionPolicy, *, timeout_seconds: int | None = None
) -> ActivityConfig:
    """Translate the shared SDK-neutral policy at the Temporal boundary."""

    timeout = timeout_seconds or policy.activity_timeout_seconds
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


def build_refresh_workflow_start(
    job: RefreshJob,
    *,
    execution_policy: TemporalExecutionPolicy | None = None,
) -> WorkflowStart:
    """Build the stable-ID command used by both scheduled and explicit refresh."""

    policy = execution_policy or TemporalExecutionPolicy()
    payload = RefreshWorkflowInput(job=job, execution_policy=policy)
    return WorkflowStart(
        workflow_id=job.workflow_id,
        workflow_type=REFRESH_WORKFLOW_TYPE,
        task_queue=REFRESH_TASK_QUEUE,
        input=payload.model_dump(mode="json"),
        idempotency_key=job.idempotency_key,
    )


@workflow.defn(name=REFRESH_WORKFLOW_TYPE)
class TemporalRefreshWorkflow:
    """Deterministic refresh coordinator with candidate-first Activity semantics."""

    def __init__(self) -> None:
        self._cancel_requested = False

    @workflow.signal(name=REFRESH_CANCEL_SIGNAL)
    def request_cancel(self, _payload: Mapping[str, Any]) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, raw_input: Mapping[str, Any]) -> RefreshWorkflowResult:
        value = RefreshWorkflowInput.model_validate(raw_input)
        run_id = workflow.info().run_id
        if self._cancel_requested:
            return RefreshWorkflowResult(
                job_id=value.job.job_id,
                workflow_id=value.job.workflow_id,
                run_id=run_id,
                status="cancelled",
            )
        raw_result = await workflow.execute_activity(
            REFRESH_EXECUTE_ACTIVITY,
            args=[value.model_dump(mode="json")],
            **refresh_activity_config(value.execution_policy),
        )
        if not isinstance(raw_result, Mapping):
            raise ApplicationError("refresh Activity returned a non-object", type="ValidationError")
        result = RefreshWorkflowResult.model_validate(
            {
                **raw_result,
                "job_id": value.job.job_id,
                "workflow_id": value.job.workflow_id,
                "run_id": run_id,
            }
        )
        if self._cancel_requested and not result.activated:
            return result.model_copy(
                update={"status": "cancelled", "bundle_id": None, "bundle_version": None}
            )
        return result


class RefreshActivities:
    """Activity adapter around the existing BundleRefreshService use-case."""

    def __init__(self, executor: RefreshExecutor) -> None:
        self._executor = executor

    @activity.defn(name=REFRESH_EXECUTE_ACTIVITY)
    async def execute(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        value = RefreshWorkflowInput.model_validate(raw_input)
        try:
            result = await self._executor(value.job, value.expected_profile_id)
        except ValueError as exc:
            raise ApplicationError(str(exc), type="ValidationError") from exc
        if not isinstance(result, BundleRefreshResult):
            raise ApplicationError("refresh executor returned an invalid result", type="ValidationError")
        return {
            "status": "completed",
            "activated": result.activated,
            "bundle_id": result.bundle.bundle_id,
            "bundle_version": result.bundle.bundle_version,
        }

    def activities(self) -> tuple[Any, ...]:
        return (self.execute,)


def media_activity_config(
    policy: TemporalExecutionPolicy, *, timeout_seconds: int | None = None
) -> ActivityConfig:
    return refresh_activity_config(policy, timeout_seconds=timeout_seconds)


def build_media_workflow_start(
    request: MediaFetchRequest,
    *,
    workflow_id: str,
    idempotency_key: str,
    execution_policy: TemporalExecutionPolicy | None = None,
) -> WorkflowStart:
    policy = execution_policy or TemporalExecutionPolicy()
    payload = MediaWorkflowInput(request=request, execution_policy=policy)
    return WorkflowStart(
        workflow_id=workflow_id,
        workflow_type=MEDIA_WORKFLOW_TYPE,
        task_queue=MEDIA_TASK_QUEUE,
        input=payload.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )


@workflow.defn(name=MEDIA_WORKFLOW_TYPE)
class TemporalMediaWorkflow:
    """Media candidate workflow; failures leave no business pointer mutation."""

    def __init__(self) -> None:
        self._cancel_requested = False

    @workflow.signal(name=MEDIA_CANCEL_SIGNAL)
    def request_cancel(self, _payload: Mapping[str, Any]) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, raw_input: Mapping[str, Any]) -> MediaWorkflowResult:
        value = MediaWorkflowInput.model_validate(raw_input)
        run_id = workflow.info().run_id
        workflow_id = workflow.info().workflow_id
        if self._cancel_requested:
            return MediaWorkflowResult(
                request_id=value.request.request_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status="cancelled",
            )
        raw_result = await workflow.execute_activity(
            MEDIA_FETCH_ACTIVITY,
            args=[value.model_dump(mode="json")],
            **media_activity_config(value.execution_policy),
        )
        if not isinstance(raw_result, Mapping):
            raise ApplicationError("media Activity returned a non-object", type="ValidationError")
        return MediaWorkflowResult.model_validate(
            {
                **raw_result,
                "request_id": value.request.request_id,
                "workflow_id": workflow_id,
                "run_id": run_id,
            }
        )


class MediaActivities:
    """Activity boundary for media fetch and metadata commit."""

    def __init__(self, executor: MediaFetchExecutor) -> None:
        self._executor = executor

    @activity.defn(name=MEDIA_FETCH_ACTIVITY)
    async def fetch(self, raw_input: Mapping[str, Any]) -> ContractPayload:
        value = MediaWorkflowInput.model_validate(raw_input)
        try:
            result = await self._executor(value.request)
        except ValueError as exc:
            raise ApplicationError(str(exc), type="ValidationError") from exc
        if not isinstance(result, MediaFetchResult):
            raise ApplicationError(
                "media fetch executor returned an invalid result", type="ValidationError"
            )
        return {
            "status": "completed",
            "asset_id": result.asset.asset_id,
            "deduplicated": result.deduplicated,
        }

    def activities(self) -> tuple[Any, ...]:
        return (self.fetch,)


__all__ = [
    "REFRESH_CANCEL_SIGNAL",
    "REFRESH_EXECUTE_ACTIVITY",
    "REFRESH_TASK_QUEUE",
    "REFRESH_WORKFLOW_TYPE",
    "MEDIA_CANCEL_SIGNAL",
    "MEDIA_FETCH_ACTIVITY",
    "MEDIA_TASK_QUEUE",
    "MEDIA_WORKFLOW_TYPE",
    "MediaActivities",
    "TemporalMediaWorkflow",
    "RefreshActivities",
    "TemporalRefreshWorkflow",
    "build_refresh_workflow_start",
    "refresh_activity_config",
    "media_activity_config",
    "build_media_workflow_start",
]
