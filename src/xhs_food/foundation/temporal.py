"""Disabled-by-default Temporal Workflow adapter and deterministic payload gate."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.service import RPCError, RPCStatusCode

from xhs_food.contracts import (
    ActivityCall,
    ActivityResult,
    ContractPayload,
    ErrorScope,
    WorkflowRun,
    WorkflowStart,
)

from .base import require_enabled
from .failures import (
    FoundationAdapterError,
    foundation_error_from_exception,
    foundation_failure_boundary,
)


@dataclass(frozen=True, slots=True)
class TemporalTaskQueues:
    research: str = "research"
    refresh: str = "refresh"
    media: str = "media"

    def __post_init__(self) -> None:
        values = (self.research, self.refresh, self.media)
        if any(not value for value in values) or len(set(values)) != 3:
            raise ValueError("Temporal task queue names must be non-empty and distinct")

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset((self.research, self.refresh, self.media))


ClientFactory = Callable[..., Awaitable[Any]]
ActivityHandler = Callable[[ContractPayload], Awaitable[ContractPayload]]


class TemporalWorkflowAdapter:
    """Project WorkflowPort; no Workflow is enabled during structural S3."""

    def __init__(
        self,
        client: Any,
        *,
        task_queues: TemporalTaskQueues | None = None,
        enabled: bool = False,
    ) -> None:
        self._client = client
        self._task_queues = task_queues or TemporalTaskQueues()
        self._enabled = enabled

    @classmethod
    async def connect(
        cls,
        *,
        address: str,
        namespace: str,
        task_queues: TemporalTaskQueues | None = None,
        enabled: bool = False,
        client_factory: ClientFactory | None = None,
    ) -> TemporalWorkflowAdapter:
        require_enabled(enabled, "temporal")
        factory = client_factory or Client.connect
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.connect",
        ):
            client = await factory(
                address,
                namespace=namespace,
                interceptors=[TracingInterceptor()],
            )
        return cls(client, task_queues=task_queues, enabled=True)

    async def start(self, command: WorkflowStart) -> WorkflowRun:
        require_enabled(self._enabled, "temporal")
        if command.task_queue not in self._task_queues.allowed:
            raise ValueError(f"unregistered Temporal task queue: {command.task_queue}")
        payload = deterministic_workflow_input(command)
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.start",
        ):
            handle = await self._client.start_workflow(
                command.workflow_type,
                payload,
                id=command.workflow_id,
                task_queue=command.task_queue,
            )
            return _run_from_handle(handle, status="running")

    async def signal(self, workflow_id: str, signal: str, payload: ContractPayload) -> None:
        require_enabled(self._enabled, "temporal")
        value = deterministic_json_value(payload)
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.signal",
        ):
            await self._client.get_workflow_handle(workflow_id).signal(signal, value)

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        require_enabled(self._enabled, "temporal")
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.cancel",
        ):
            await self._client.get_workflow_handle(workflow_id).cancel(reason=reason or "")

    async def describe(self, workflow_id: str) -> WorkflowRun | None:
        require_enabled(self._enabled, "temporal")
        handle = self._client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.describe",
                )
            ) from exc
        status = getattr(getattr(description, "status", None), "name", None) or str(
            getattr(description, "status", "unknown")
        )
        run_id = (
            getattr(getattr(description, "execution", None), "run_id", None)
            or getattr(handle, "run_id", None)
            or "unknown"
        )
        return WorkflowRun(
            workflow_id=workflow_id,
            run_id=str(run_id),
            status=str(status).casefold(),
        )


class TemporalActivityAdapter:
    """Worker-side Activity boundary; registered but disabled during S3."""

    def __init__(
        self,
        handlers: Mapping[str, ActivityHandler],
        *,
        task_queues: TemporalTaskQueues | None = None,
        enabled: bool = False,
    ) -> None:
        self._handlers = dict(handlers)
        self._task_queues = task_queues or TemporalTaskQueues()
        self._enabled = enabled

    async def execute(self, call: ActivityCall) -> ActivityResult:
        require_enabled(self._enabled, "temporal-activity")
        if call.task_queue not in self._task_queues.allowed:
            raise ValueError(f"unregistered Temporal task queue: {call.task_queue}")
        try:
            handler = self._handlers[call.activity_type]
        except KeyError as exc:
            raise ValueError(f"unregistered Temporal activity: {call.activity_type}") from exc
        payload = deterministic_json_value(call.input)
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.activity.execute",
        ):
            output = deterministic_json_value(await handler(payload))
        return ActivityResult(activity_id=call.activity_id, output=output)


def deterministic_workflow_input(command: WorkflowStart) -> dict[str, Any]:
    """Round-trip through canonical JSON before crossing the Temporal boundary."""

    return json.loads(
        json.dumps(
            command.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def deterministic_json_value(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _run_from_handle(handle: Any, *, status: str) -> WorkflowRun:
    workflow_id = getattr(handle, "id", None)
    run_id = (
        getattr(handle, "result_run_id", None)
        or getattr(handle, "run_id", None)
        or getattr(handle, "first_execution_run_id", None)
    )
    if not workflow_id or not run_id:
        raise TypeError("Temporal did not return workflow and run identities")
    return WorkflowRun(workflow_id=str(workflow_id), run_id=str(run_id), status=status)


def _is_not_found(exc: Exception) -> bool:
    return (isinstance(exc, RPCError) and exc.status is RPCStatusCode.NOT_FOUND) or type(
        exc
    ).__name__ == "WorkflowNotFoundError"


__all__ = [
    "TemporalActivityAdapter",
    "TemporalTaskQueues",
    "TemporalWorkflowAdapter",
    "deterministic_json_value",
    "deterministic_workflow_input",
]
