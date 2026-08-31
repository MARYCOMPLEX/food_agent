"""Disabled-by-default Temporal Workflow adapter and deterministic payload gate."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from temporalio import exceptions as temporal_errors
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.service import RPCError, RPCStatusCode

from xhs_food.contracts import (
    ActivityCall,
    ActivityResult,
    ContractPayload,
    ErrorScope,
    FailedWorkflow,
    WorkflowRecoveryAction,
    WorkflowRecoveryReceipt,
    WorkflowRetryRequest,
    WorkflowRun,
    WorkflowStart,
    WorkflowTerminateRequest,
)

from .base import require_enabled
from .failures import (
    FoundationAdapterError,
    foundation_error_from_exception,
    foundation_failure_boundary,
)


@dataclass(frozen=True, slots=True)
class TemporalWorkerQuota:
    """Per-queue worker capacity and priority contract."""

    queue: str
    max_concurrent_activities: int
    max_concurrent_workflows: int
    priority: int
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_queue_name(self.queue, field_name="Temporal worker queue")
        if self.max_concurrent_activities < 1 or self.max_concurrent_workflows < 1:
            raise ValueError("Temporal worker concurrency must be at least one")
        if self.priority < 0:
            raise ValueError("Temporal worker priority cannot be negative")


@dataclass(frozen=True, slots=True)
class TemporalTaskQueues:
    research: str = "research"
    refresh: str = "refresh"
    media: str = "media"
    research_quota: TemporalWorkerQuota | None = None
    refresh_quota: TemporalWorkerQuota | None = None
    media_quota: TemporalWorkerQuota | None = None
    # Account authentication is an additive, explicitly opt-in queue.  When
    # ``account_auth`` is omitted the approved baseline remains exactly the
    # three Research/Refresh/Media queues.
    account_auth: str | None = None
    account_auth_quota: TemporalWorkerQuota | None = None

    def __post_init__(self) -> None:
        base_values = (self.research, self.refresh, self.media)
        if any(not _is_valid_queue_name(value) for value in base_values) or len(set(base_values)) != 3:
            raise ValueError("Temporal task queue names must be non-empty and distinct")
        if self.account_auth is not None:
            _validate_queue_name(self.account_auth, field_name="account_auth queue")
        defaults = (
            ("research_quota", self.research, 8, 8, 100, True),
            ("refresh_quota", self.refresh, 2, 2, 50, False),
            ("media_quota", self.media, 2, 2, 25, False),
        )
        for attribute, queue, activities, workflows, priority, enabled in defaults:
            quota = getattr(self, attribute)
            if quota is None:
                quota = TemporalWorkerQuota(
                    queue=queue,
                    max_concurrent_activities=activities,
                    max_concurrent_workflows=workflows,
                    priority=priority,
                    enabled=enabled,
                )
                object.__setattr__(self, attribute, quota)
            elif quota.queue != queue:
                raise ValueError(f"{attribute} must target queue {queue!r}")
        if self.account_auth is None:
            if self.account_auth_quota is not None:
                raise ValueError("account_auth_quota requires an account_auth queue")
        else:
            quota = self.account_auth_quota
            if quota is None:
                quota = TemporalWorkerQuota(
                    queue=self.account_auth,
                    max_concurrent_activities=2,
                    max_concurrent_workflows=2,
                    priority=75,
                    enabled=False,
                )
                object.__setattr__(self, "account_auth_quota", quota)
            elif quota.queue != self.account_auth:
                raise ValueError("account_auth_quota must target the account_auth queue")
        if self.account_auth is not None and self.account_auth in {self.research, self.refresh, self.media}:
            raise ValueError("account_auth queue must be distinct from collection queues")
        if self.research_quota is None or not self.research_quota.enabled:
            raise ValueError("the Research worker quota must be enabled")

    @property
    def allowed(self) -> frozenset[str]:
        queues = [self.research, self.refresh, self.media]
        if self.account_auth is not None:
            queues.append(self.account_auth)
        return frozenset(queues)

    @property
    def active(self) -> frozenset[str]:
        return frozenset(
            quota.queue
            for quota in (
                self.research_quota,
                self.refresh_quota,
                self.media_quota,
                self.account_auth_quota,
            )
            if quota is not None and quota.enabled
        )

    def quota_for(self, queue: str) -> TemporalWorkerQuota:
        if queue not in self.allowed:
            raise ValueError(f"unregistered Temporal task queue: {queue}")
        quota_by_queue = {
            self.research: self.research_quota,
            self.refresh: self.refresh_quota,
            self.media: self.media_quota,
        }
        if self.account_auth is not None:
            quota_by_queue[self.account_auth] = self.account_auth_quota
        quota = quota_by_queue[queue]
        assert quota is not None
        return quota

    def queue_for(self, workload: str) -> str:
        """Resolve a logical workload without exposing queue implementation details."""

        queues = {"research": self.research, "refresh": self.refresh, "media": self.media}
        if self.account_auth is not None:
            queues["account_auth"] = self.account_auth
            # Accept the wire spelling as a convenience at the boundary while
            # retaining one canonical logical workload name in contracts.
            queues["account-auth"] = self.account_auth
        try:
            return queues[workload]
        except KeyError as exc:
            raise ValueError(f"unregistered Temporal workload: {workload}") from exc

    def quota_for_workload(self, workload: str) -> TemporalWorkerQuota:
        return self.quota_for(self.queue_for(workload))

    @property
    def priority_order(self) -> tuple[str, ...]:
        """Active queues ordered by their configured priority."""

        quotas = (
            quota
            for quota in (
                self.research_quota,
                self.refresh_quota,
                self.media_quota,
                self.account_auth_quota,
            )
            if quota is not None and quota.enabled
        )
        return tuple(
            quota.queue
            for quota in sorted(quotas, key=lambda item: (-item.priority, item.queue))
        )

    def assert_enabled(self, queue: str) -> TemporalWorkerQuota:
        quota = self.quota_for(queue)
        if not quota.enabled:
            raise ValueError(f"Temporal task queue {queue!r} is disabled until its milestone")
        return quota


ClientFactory = Callable[..., Awaitable[Any]]
ActivityHandler = Callable[[ContractPayload], Awaitable[ContractPayload]]
# Account-auth uses a dedicated signal rather than Temporal's hard
# cancellation API.  The workflow turns that signal into a durable cancel
# Activity, which commits the authoritative PostgreSQL flow receipt before the
# run returns.  Keep these wire constants local so this foundation module does
# not import the provider/login bridge.
_ACCOUNT_AUTH_WORKFLOW_TYPE = "platform-account-auth/v1"
_ACCOUNT_AUTH_CANCEL_SIGNAL = "platform-account-auth.cancel.requested"


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
        # A workflow ID is normally enough to select the legacy cancellation
        # signal, but account-auth IDs are caller supplied (the initial flow
        # ID is also the Temporal ID).  Remember the type/queue at admission
        # so an arbitrary account-auth ID cannot accidentally receive the
        # Research signal.  The map is only a process-local hint; cancellation
        # also inspects Temporal metadata for IDs admitted by another process.
        self._workflow_cancel_signals: dict[str, str] = {}

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
        self._task_queues.assert_enabled(command.task_queue)
        payload = deterministic_workflow_input(command)
        try:
            # ``WorkflowStart.input`` is the only application payload.  The
            # command envelope remains local to the port and must not become
            # an accidental workflow input contract.
            handle = await self._client.start_workflow(
                command.workflow_type,
                payload["input"],
                id=command.workflow_id,
                task_queue=command.task_queue,
                # Equivalent active submissions attach to the existing run;
                # after a terminal run, an explicit retry may reuse the same
                # stable Workflow ID and receive a new run ID.
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
            self._remember_cancel_signal(command)
            return _run_from_handle(handle, status="running")
        except temporal_errors.WorkflowAlreadyStartedError as duplicate:
            # Temporal's Workflow ID is the single-flight authority.  A
            # duplicate request is successful admission of the existing run,
            # not a Redis lock conflict or a new execution.
            existing = await self.describe(command.workflow_id)
            if existing is not None:
                self._remember_cancel_signal(command)
                return existing
            # A server can report a duplicate while its visibility index is
            # briefly unavailable.  Preserve the stable conflict taxonomy.
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    duplicate,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.start.duplicate_unresolved",
                )
            ) from duplicate
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.start",
                )
            ) from exc

    async def signal(self, workflow_id: str, signal: str, payload: ContractPayload) -> None:
        require_enabled(self._enabled, "temporal")
        value = deterministic_json_value(payload)
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.signal",
        ):
            await self._client.get_workflow_handle(workflow_id).signal(signal, value)

    async def signal_with_start(
        self,
        command: WorkflowStart,
        signal: str,
        payload: ContractPayload,
    ) -> WorkflowRun:
        """Atomically signal an active run or start and signal its successor.

        This is an optional extension to ``WorkflowPort`` used by split-phase
        account-auth cancellation.  A login Activity can finish while its
        PostgreSQL flow remains non-terminal; a later plain signal would then
        fail with ``Completed workflow``.  Temporal's signal-with-start RPC
        closes that race: ``USE_EXISTING`` signals the active run, while
        ``ALLOW_DUPLICATE`` starts a new run with the same stable flow ID when
        the prior run is terminal.  No second scheduler or persisted run-ID
        pointer is needed.
        """

        require_enabled(self._enabled, "temporal")
        self._task_queues.assert_enabled(command.task_queue)
        workflow_payload = deterministic_workflow_input(command)
        signal_payload = deterministic_json_value(payload)
        try:
            handle = await self._client.start_workflow(
                command.workflow_type,
                workflow_payload["input"],
                id=command.workflow_id,
                task_queue=command.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                start_signal=signal,
                start_signal_args=[signal_payload],
            )
            self._remember_cancel_signal(command)
            return _run_from_handle(handle, status="running")
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.signal_with_start",
                )
            ) from exc

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        require_enabled(self._enabled, "temporal")
        with foundation_failure_boundary(
            scope=ErrorScope.WORKFLOW,
            operation="workflow.cancel",
        ):
            # The reliable Research workflow converts this deterministic
            # command into an authoritative cancellation Activity.  A signal
            # keeps the PG receipt inside workflow history instead of ending
            # the execution before the commit barrier runs.
            handle = self._client.get_workflow_handle(workflow_id)
            signal = await self._resolve_cancel_signal(workflow_id, handle)
            await handle.signal(signal, {"reason": reason or ""})

    def _remember_cancel_signal(self, command: WorkflowStart) -> None:
        """Remember the cancellation channel selected at workflow admission."""

        signal = _cancel_signal_for_start(command, self._task_queues)
        if signal == _ACCOUNT_AUTH_CANCEL_SIGNAL:
            self._workflow_cancel_signals[command.workflow_id] = signal
        else:
            # Temporal permits a stable ID to be reused after a terminal run;
            # do not let an old account-auth admission steer a later workload.
            self._workflow_cancel_signals.pop(command.workflow_id, None)

    async def _resolve_cancel_signal(self, workflow_id: str, handle: Any) -> str:
        """Resolve a cancellation signal without guessing account-auth IDs.

        Generated platform flow IDs use the ``flow-`` prefix, and older
    compositions may use ``auth:``/``auth-``/``account-auth:``.  For an arbitrary
        ID admitted by another API process, inspect Temporal's description so
        a custom account-auth queue/type is still routed correctly.  If that
        metadata cannot be read while the auth queue is configured, fail
        closed instead of sending a Research signal to an auth workflow.
        """

        remembered = self._workflow_cancel_signals.get(workflow_id)
        if remembered is not None:
            return remembered
        signal = _cancel_signal_for_workflow(workflow_id)
        if signal == _ACCOUNT_AUTH_CANCEL_SIGNAL:
            return signal

        # Stable workload IDs already encode their signal family.  Avoid a
        # visibility RPC on the established Research/Refresh/Media paths.
        if str(workflow_id).casefold().startswith(("research:", "refresh:", "media:")):
            return signal

        # Only query metadata when an account-auth queue is configured.  This
        # avoids an extra RPC on the established Research/Refresh/Media path.
        account_auth_queue = self._task_queues.account_auth
        if account_auth_queue is None:
            return signal
        describe = getattr(handle, "describe", None)
        if not callable(describe):
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    RuntimeError("Temporal workflow type is unavailable for cancellation routing"),
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.cancel.resolve",
                )
            )
        try:
            description = await describe()
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            # Do not guess Research when a configured account-auth workflow
            # cannot be classified after an adapter/process restart.
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.cancel.resolve",
                )
            ) from exc
        workflow_type = _description_field(description, "workflow_type", "workflowType", "type")
        task_queue = _description_field(description, "task_queue", "taskQueue")
        if workflow_type == _ACCOUNT_AUTH_WORKFLOW_TYPE or task_queue == account_auth_queue:
            return _ACCOUNT_AUTH_CANCEL_SIGNAL
        return signal

    async def aclose(self) -> None:
        """Close the owned Temporal client during application shutdown."""

        client = self._client
        self._client = None
        self._enabled = False
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result

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
            getattr(description, "run_id", None)
            or getattr(getattr(description, "execution", None), "run_id", None)
            or getattr(handle, "run_id", None)
            or "unknown"
        )
        return WorkflowRun(
            workflow_id=workflow_id,
            run_id=str(run_id),
            status=str(status).casefold(),
        )

    async def list_failed_workflows(
        self, *, task_queue: str | None = None, limit: int = 100
    ) -> tuple[FailedWorkflow, ...]:
        """Inspect retry-exhausted executions through Temporal visibility.

        The result is a read-only operator view. It never copies workflow
        state into a second durable store or creates a broker queue.
        """

        require_enabled(self._enabled, "temporal")
        if limit < 1:
            raise ValueError("failed workflow limit must be at least one")
        if task_queue is not None:
            self._task_queues.quota_for(task_queue)
        try:
            query = 'ExecutionStatus="Failed"'
            if task_queue is not None:
                # Queue names are validated against the configured allow-list
                # before they are interpolated into the visibility query.
                query += f' AND TaskQueue="{task_queue}"'
            executions = self._client.list_workflows(
                query=query,
                limit=limit,
            )
            if inspect.isawaitable(executions):
                executions = await executions
            values: list[FailedWorkflow] = []
            if callable(getattr(executions, "__aiter__", None)):
                async for execution in executions:
                    item = _failed_workflow_from_visibility(execution)
                    if item is not None and (
                        task_queue is None or item.task_queue in {task_queue, "unknown"}
                    ):
                        if item.task_queue == "unknown" and task_queue is not None:
                            item = item.model_copy(update={"task_queue": task_queue})
                        values.append(item)
                        if len(values) >= limit:
                            break
            else:
                for execution in executions:
                    item = _failed_workflow_from_visibility(execution)
                    if item is not None and (
                        task_queue is None or item.task_queue in {task_queue, "unknown"}
                    ):
                        if item.task_queue == "unknown" and task_queue is not None:
                            item = item.model_copy(update={"task_queue": task_queue})
                        values.append(item)
                        if len(values) >= limit:
                            break
            return tuple(values)
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.list_failed",
                )
            ) from exc

    async def retry_workflow(
        self, request: WorkflowRetryRequest
    ) -> WorkflowRecoveryReceipt:
        """Start an explicit retry with the original stable Workflow ID."""

        require_enabled(self._enabled, "temporal")
        if request.expected_run_id is not None:
            current = await self.describe(request.command.workflow_id)
            if current is not None and current.run_id != request.expected_run_id:
                raise ValueError("failed workflow run no longer matches the recovery request")
        run = await self.start(request.command)
        return WorkflowRecoveryReceipt(
            workflow_id=run.workflow_id,
            run_id=run.run_id,
            action=WorkflowRecoveryAction.RETRY,
            accepted=True,
            status=run.status,
        )

    async def terminate_workflow(
        self, request: WorkflowTerminateRequest
    ) -> WorkflowRecoveryReceipt:
        """Terminate a failed or stuck execution using Temporal history identity."""

        require_enabled(self._enabled, "temporal")
        try:
            handle = self._client.get_workflow_handle(
                request.workflow_id,
                run_id=request.run_id,
            )
            await handle.terminate(reason=request.reason)
        except asyncio.CancelledError:
            raise
        except FoundationAdapterError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.WORKFLOW,
                    operation="workflow.terminate",
                )
            ) from exc
        return WorkflowRecoveryReceipt(
            workflow_id=request.workflow_id,
            run_id=request.run_id or "current",
            action=WorkflowRecoveryAction.TERMINATE,
            accepted=True,
            status="termination_requested",
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
        self._task_queues.assert_enabled(call.task_queue)
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


def build_temporal_worker(
    client: Any,
    *,
    task_queues: TemporalTaskQueues,
    queue: str,
    workflows: Sequence[type[Any]],
    activities: Sequence[Callable[..., Any]],
    plugins: Sequence[Any] = (),
    telemetry: Any | None = None,
) -> Any:
    """Build one queue-isolated Temporal worker from the approved quota.

    Worker construction is kept at the Foundation boundary so every worker
    uses the same queue registration and concurrency contract.  In
    particular, a caller cannot accidentally start a Refresh or Media worker
    while those queues are disabled for the current milestone.
    """

    quota = task_queues.assert_enabled(queue)
    from temporalio.worker import Worker

    worker = Worker(
        client,
        task_queue=quota.queue,
        workflows=tuple(workflows),
        activities=tuple(activities),
        plugins=tuple(plugins),
        max_concurrent_activities=quota.max_concurrent_activities,
        max_concurrent_workflow_tasks=quota.max_concurrent_workflows,
    )
    record_health = getattr(telemetry, "record_worker_health", None)
    if callable(record_health):
        record_health(task_queue=quota.queue, status="ready")
    return worker


def build_temporal_refresh_worker(
    client: Any,
    activities: Any,
    *,
    task_queues: TemporalTaskQueues | None = None,
    workflows: Sequence[type[Any]] = (),
    plugins: Sequence[Any] = (),
    telemetry: Any | None = None,
) -> Any:
    """Build the isolated Refresh worker; activation is explicit by quota."""

    queues = task_queues or TemporalTaskQueues()
    return build_temporal_worker(
        client,
        task_queues=queues,
        queue=queues.refresh,
        workflows=workflows,
        activities=_resolve_activity_registrations(activities),
        plugins=plugins,
        telemetry=telemetry,
    )


def build_temporal_media_worker(
    client: Any,
    activities: Any,
    *,
    task_queues: TemporalTaskQueues | None = None,
    workflows: Sequence[type[Any]] = (),
    plugins: Sequence[Any] = (),
    telemetry: Any | None = None,
) -> Any:
    """Build the isolated Media worker; activation is explicit by quota."""

    queues = task_queues or TemporalTaskQueues()
    return build_temporal_worker(
        client,
        task_queues=queues,
        queue=queues.media,
        workflows=workflows,
        activities=_resolve_activity_registrations(activities),
        plugins=plugins,
        telemetry=telemetry,
    )


def build_temporal_auth_worker(
    client: Any,
    activities: Any,
    *,
    task_queues: TemporalTaskQueues | None = None,
    workflows: Sequence[type[Any]] = (),
    plugins: Sequence[Any] = (),
    telemetry: Any | None = None,
) -> Any:
    """Build the optional account-auth worker behind an explicit queue gate.

    ``TemporalTaskQueues`` omits the account-auth queue by default.  Calling
    this helper without an explicitly configured queue therefore fails closed,
    which keeps login/manual-import-only behavior until the auth queue has
    passed its qualification gate.  A configured queue remains disabled unless
    its ``account_auth_quota.enabled`` flag is explicitly set to ``True``.
    """

    queues = task_queues or TemporalTaskQueues()
    if queues.account_auth is None:
        raise ValueError("account-auth queue is not configured")
    return build_temporal_worker(
        client,
        task_queues=queues,
        queue=queues.account_auth,
        workflows=workflows,
        activities=_resolve_activity_registrations(activities),
        plugins=plugins,
        telemetry=telemetry,
    )


# Keep a discoverable long-form alias for compositions that name the queue
# after its workload rather than its short auth label.
build_temporal_account_auth_worker = build_temporal_auth_worker


def _is_valid_queue_name(value: str) -> bool:
    return bool(value) and value == value.strip() and not any(
        character.isspace() or ord(character) < 32 for character in value
    )


def _validate_queue_name(value: str, *, field_name: str) -> None:
    if not _is_valid_queue_name(value):
        raise ValueError(f"{field_name} must be non-empty and whitespace-free")


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


def _resolve_activity_registrations(activities: Any) -> tuple[Callable[..., Any], ...]:
    if callable(getattr(activities, "activities", None)):
        activities = activities.activities()
    return tuple(activities)


def _cancel_signal_for_start(command: WorkflowStart, queues: TemporalTaskQueues) -> str:
    """Select the cancellation signal from an admitted workflow command."""

    if command.workflow_type == _ACCOUNT_AUTH_WORKFLOW_TYPE:
        return _ACCOUNT_AUTH_CANCEL_SIGNAL
    if queues.account_auth is not None and command.task_queue == queues.account_auth:
        return _ACCOUNT_AUTH_CANCEL_SIGNAL
    return _cancel_signal_for_workflow(command.workflow_id)


def _cancel_signal_for_workflow(workflow_id: str) -> str:
    """Map stable workflow-ID families to their durable cancel signal.

    Platform login flow IDs are intentionally opaque to callers and therefore
    do not carry a queue prefix.  The generated IDs use ``flow-``; retain a
    few explicit aliases for older compositions and custom fixtures.  Unknown
    IDs continue to follow the historical Research signal for compatibility.
    """

    normalized = str(workflow_id).casefold()
    if normalized.startswith(
        (
            "auth:",
            "auth-",
            "account-auth:",
            "account-auth-",
            "platform-account-auth:",
            "platform-account-auth-",
        )
    ):
        return _ACCOUNT_AUTH_CANCEL_SIGNAL
    if normalized.startswith("flow-"):
        return _ACCOUNT_AUTH_CANCEL_SIGNAL
    if normalized.startswith("refresh:"):
        return "refresh.cancel.requested"
    if normalized.startswith("media:"):
        return "media.cancel.requested"
    return "research.cancel.requested"


def _description_field(value: Any, *names: str) -> Any:
    """Read a workflow-description field across SDK/object/dict shapes."""

    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return None


def _failed_workflow_from_visibility(value: Any) -> FailedWorkflow | None:
    def field(*names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(value, Mapping) and name in value:
                return value[name]
            result = getattr(value, name, None)
            if result is not None:
                return result
        return default

    workflow_id = field("id", "workflow_id", "workflowId")
    run_id = field("run_id", "runId")
    if not workflow_id or not run_id:
        return None
    workflow_type = field("workflow_type", "workflowType", "type", default="unknown")
    task_queue = field("task_queue", "taskQueue", default="unknown")
    status = field("status", default="failed")
    status_value = getattr(status, "name", None) or str(status)
    if status_value.casefold() not in {"failed", "workflowexecutionstatus.failed"}:
        return None
    return FailedWorkflow(
        workflow_id=str(workflow_id),
        run_id=str(run_id),
        workflow_type=str(workflow_type),
        task_queue=str(task_queue),
        status="failed",
        failure_category=field("failure_category", "failureCategory"),
        last_checkpoint=field("last_checkpoint", "lastCheckpoint"),
    )


__all__ = [
    "TemporalActivityAdapter",
    "TemporalTaskQueues",
    "TemporalWorkerQuota",
    "TemporalWorkflowAdapter",
    "build_temporal_account_auth_worker",
    "build_temporal_auth_worker",
    "build_temporal_worker",
    "build_temporal_media_worker",
    "build_temporal_refresh_worker",
    "deterministic_json_value",
    "deterministic_workflow_input",
]
