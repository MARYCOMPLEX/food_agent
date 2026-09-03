"""Temporal-backed research task lifecycle for the B0 behavior milestone.

The module deliberately keeps the durable runtime at the edge of the
orchestrator.  A workflow only coordinates deterministic commands and named
activities; task state transitions are delegated to ``ReliableTaskOwner`` and
business results are committed through ``ReliableTaskAuthority`` before a
terminal event is published.

The default composition root does not construct this policy.  Production
activation must provide real Temporal/PostgreSQL adapters explicitly; the
small in-memory doubles in this module are intended for contract tests only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import Field, TypeAdapter
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ActivityConfig

from xhs_food.contracts import (
    ContractError,
    ContractModel,
    ContractPayload,
    ErrorCategory,
    ErrorScope,
    PlanBudget,
    PlanStatus,
    PlanStepStatus,
    ResearchOperation,
    ResearchPlan,
    ResearchPlanStep,
    ResearchRequest,
    ResearchTask,
    ResultCommitReceipt,
    TaskEvent,
    TaskProgressProjection,
    TaskStatus,
    TemporalExecutionPolicy,
    WorkflowPort,
    WorkflowRun,
    WorkflowStart,
)

RELIABLE_TASK_POLICY_VERSION = "reliable-task/v1"
LEGACY_TASK_POLICY_VERSION = "legacy-task/v1"
RESEARCH_WORKFLOW_TYPE = "research-task/v1"
RESEARCH_TASK_QUEUE = "research"
RESEARCH_ACTIVITY_VERSION = "research-activity/v1"
RESEARCH_EXECUTE_ACTIVITY = "research.execute/v1"
RESEARCH_PROGRESS_ACTIVITY = "research.progress/v1"
RESEARCH_COMMIT_ACTIVITY = "research.commit/v1"
RESEARCH_FAIL_ACTIVITY = "research.fail/v1"
RESEARCH_PUBLISH_ACTIVITY = "research.publish-terminal/v1"
RESEARCH_CANCEL_ACTIVITY = "research.cancel/v1"
RESEARCH_RECONCILE_ACTIVITY = "research.reconcile/v1"
RESEARCH_CANCEL_SIGNAL = "research.cancel.requested"


class ReliableTaskFailure(RuntimeError):
    """Serializable lifecycle failure exposed by the reliable policy."""

    def __init__(self, error: ContractError) -> None:
        super().__init__(error.message or error.code)
        self.error = error


class ReliableDependencyUnavailable(ReliableTaskFailure):
    """Raised when a required durable dependency is not configured/available."""


class ReliableTaskConflict(ReliableTaskFailure):
    """Raised when a task identity cannot be reconciled safely."""


class ReliableTaskTerminal(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReliableTaskConfig(TemporalExecutionPolicy):
    """Research queue binding over the shared Temporal execution policy."""

    policy_version: str = RELIABLE_TASK_POLICY_VERSION
    task_queue: str = RESEARCH_TASK_QUEUE

    def activity_config(self, *, timeout_seconds: int | None = None) -> ActivityConfig:
        """Return one explicit, inspectable Temporal Activity configuration."""

        timeout = timeout_seconds or self.activity_timeout_seconds
        return {
            "start_to_close_timeout": timedelta(seconds=timeout),
            "heartbeat_timeout": timedelta(seconds=self.heartbeat_timeout_seconds),
            "retry_policy": RetryPolicy(
                initial_interval=timedelta(seconds=self.retry_initial_interval_seconds),
                maximum_interval=timedelta(seconds=self.retry_maximum_interval_seconds),
                backoff_coefficient=self.retry_backoff_coefficient,
                maximum_attempts=self.retry_maximum_attempts,
                non_retryable_error_types=list(self.non_retryable_error_types),
            ),
        }


class ResearchWorkflowInput(ContractModel):
    """JSON-only input crossing the Temporal workflow boundary."""

    task_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    request: ResearchRequest
    plan_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    policy_version: str = RELIABLE_TASK_POLICY_VERSION
    contract_versions: dict[str, str] = Field(default_factory=dict)
    activity_policy: ReliableTaskConfig = Field(default_factory=ReliableTaskConfig)


class ResearchWorkflowOutput(ContractModel):
    """Workflow result; ``committed`` is true only after the authority barrier."""

    task_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    committed: bool = False
    published: bool = False
    result: ContractPayload = Field(default_factory=dict)


@runtime_checkable
class ReliableTaskOwner(Protocol):
    """The only owner allowed to calculate ResearchTask state transitions."""

    async def admit_reliable_task(
        self,
        request: ResearchRequest,
        *,
        task_id: str,
        workflow_id: str,
    ) -> ResearchTask: ...

    async def reliable_task(self, task_id: str) -> ResearchTask | None: ...

    async def attach_reliable_run(
        self, task_id: str, workflow_run: WorkflowRun
    ) -> ResearchTask: ...

    async def record_reliable_progress(
        self,
        task_id: str,
        *,
        workflow_id: str,
        run_id: str,
        progress: float,
        current_step_id: str | None = None,
    ) -> TaskProgressProjection: ...

    async def finalize_reliable_task(
        self,
        task_id: str,
        *,
        workflow_id: str,
        run_id: str,
        status: TaskStatus,
        result: ContractPayload | None = None,
        error: ContractError | None = None,
    ) -> ResearchTask: ...

    async def reliable_request(self, task_id: str) -> ResearchRequest | None: ...


@runtime_checkable
class ReliableTaskAuthority(Protocol):
    """PostgreSQL-owned durable facts used by worker Activities."""

    async def commit_result(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        result: ContractPayload,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt: ...

    async def commit_cancelled(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt: ...

    async def commit_failed(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        error: ContractError,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt: ...

    async def reconcile(
        self, task_id: str, workflow_id: str, run_id: str
    ) -> ContractPayload | None: ...


@runtime_checkable
class ReliableTaskEventPublisher(Protocol):
    """Short-lived event projection; implementations must be idempotent by ID."""

    async def publish_task_event(self, event: TaskEvent, *, idempotency_key: str) -> str: ...


ResearchExecutor = Callable[[ResearchWorkflowInput, str], Awaitable[ContractPayload]]


def stable_research_task_id(request: ResearchRequest) -> str:
    """Derive a stable task identity without using a Redis lock or lease.

    Callers may provide an explicit idempotency key in ``public_inputs``.  When
    absent, the request identity/session and public operation form the key;
    ``request_id`` is the last-resort identity for anonymous one-shot queries.
    """

    explicit = request.public_inputs.get("idempotency_key")
    if isinstance(explicit, str) and explicit:
        source = {"explicit": explicit}
    else:
        session = request.identity.session_ref
        source = {
            "operation": request.operation.value,
            "domain": request.domain,
            "query": request.query,
            "target_task_id": request.target_task_id,
            "query_family_id": request.query_family_id,
            "session_ref": session,
            "tenant_ref": request.identity.tenant_ref,
            "compatibility_version": request.policy.compatibility_version,
            "request_id": request.request_id if not session else None,
        }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"task-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"


def stable_research_workflow_id(task_id: str) -> str:
    if not task_id:
        raise ValueError("task_id must be non-empty")
    return f"research:{task_id}"


def reliable_plan(*, task_id: str, query: str, turn_id: int) -> ResearchPlan:
    """Construct the small deterministic plan owned by the Coordinator."""

    step = ResearchPlanStep(
        step_id="research.execute",
        capability="research.execute",
        status=PlanStepStatus.RUNNING,
    )
    return ResearchPlan(
        plan_id=f"plan:{task_id}:turn:{turn_id}",
        task_id=task_id,
        goal=query.strip() or "research",
        status=PlanStatus.RUNNING,
        steps=(step,),
        budget=PlanBudget(max_steps=1),
        contract_versions={
            "task_policy": RELIABLE_TASK_POLICY_VERSION,
            "workflow": RESEARCH_WORKFLOW_TYPE,
        },
    )


def build_workflow_start(
    request: ResearchRequest,
    *,
    task_id: str,
    plan_id: str,
    turn_id: str,
    config: ReliableTaskConfig | None = None,
) -> WorkflowStart:
    """Build the one canonical Temporal command for a reliable task."""

    config = config or ReliableTaskConfig()
    workflow_id = stable_research_workflow_id(task_id)
    payload = ResearchWorkflowInput(
        task_id=task_id,
        workflow_id=workflow_id,
        request=request,
        plan_id=plan_id,
        turn_id=turn_id,
        policy_version=config.policy_version,
        contract_versions={
            "task_policy": config.policy_version,
            "research_workflow": RESEARCH_WORKFLOW_TYPE,
            "activity_policy": RESEARCH_ACTIVITY_VERSION,
        },
        activity_policy=config,
    )
    return WorkflowStart(
        workflow_id=workflow_id,
        workflow_type=RESEARCH_WORKFLOW_TYPE,
        task_queue=config.task_queue,
        input=payload.model_dump(mode="json"),
        idempotency_key=task_id,
    )


@workflow.defn(name=RESEARCH_WORKFLOW_TYPE)
class TemporalResearchWorkflow:
    """Generic Research workflow used when the worker supplies named Activities."""

    def __init__(self) -> None:
        self._cancel_requested = False

    @workflow.signal(name=RESEARCH_CANCEL_SIGNAL)
    def request_cancel(self, payload: Mapping[str, Any]) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, raw_input: Mapping[str, Any]) -> ResearchWorkflowOutput:
        value = ResearchWorkflowInput.model_validate(raw_input)
        run_id = workflow.info().run_id
        config = value.activity_policy

        try:
            return await _run_research_workflow(
                value, run_id, config, cancel_requested=lambda: self._cancel_requested
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A result-commit failure must remain a Workflow failure/retry.  A
            # failed terminal is only written for work that never crossed the
            # result commit barrier; otherwise the authority would receive a
            # second, competing terminal write.
            if _is_commit_barrier_failure(exc):
                raise
            if self._cancel_requested:
                return await _cancel_research_workflow(value, run_id, config)
            return await _fail_research_workflow(value, run_id, config, exc)


async def _run_research_workflow(
    value: ResearchWorkflowInput,
    run_id: str,
    config: ReliableTaskConfig,
    *,
    cancel_requested: Callable[[], bool],
) -> ResearchWorkflowOutput:
    """Execute the deterministic control path behind the public Workflow."""

    await workflow.execute_activity(
        RESEARCH_PROGRESS_ACTIVITY,
        args=[
            {
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "progress": 0.0,
                "current_step_id": "research.execute",
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    if cancel_requested():
        return await _cancel_research_workflow(value, run_id, config)
    result = await workflow.execute_activity(
        RESEARCH_EXECUTE_ACTIVITY,
        args=[value.model_dump(mode="json"), RESEARCH_ACTIVITY_VERSION],
        **config.activity_config(),
    )
    if not isinstance(result, Mapping):
        raise ApplicationError("research activity returned a non-object", type="ValidationError")
    result_payload = {str(key): item for key, item in result.items()}
    # Signals are delivered between Workflow tasks.  Checking after every
    # external Activity gives cancellation a deterministic precedence point.
    if cancel_requested():
        return await _cancel_research_workflow(value, run_id, config)
    await workflow.execute_activity(
        RESEARCH_PROGRESS_ACTIVITY,
        args=[
            {
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "progress": 0.8,
                "current_step_id": "research.commit",
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    receipt = await workflow.execute_activity(
        RESEARCH_COMMIT_ACTIVITY,
        args=[
            {
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "result": result_payload,
                "idempotency_key": f"{value.task_id}:{run_id}:result",
            }
        ],
        **config.activity_config(),
    )
    if not isinstance(receipt, Mapping) or not bool(receipt.get("committed")):
        raise ApplicationError(
            "authoritative result commit was not confirmed", type="ResultCommitRejected"
        )

    event_id = f"{value.task_id}:{run_id}:completed"
    published = await workflow.execute_activity(
        RESEARCH_PUBLISH_ACTIVITY,
        args=[
            {
                "event_id": event_id,
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "status": TaskStatus.COMPLETED.value,
                "progress": 1.0,
                "result": result_payload,
                "idempotency_key": event_id,
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    return ResearchWorkflowOutput(
        task_id=value.task_id,
        workflow_id=value.workflow_id,
        run_id=run_id,
        committed=True,
        published=bool(published),
        result=result_payload,
    )


async def _cancel_research_workflow(
    value: ResearchWorkflowInput,
    run_id: str,
    config: ReliableTaskConfig,
) -> ResearchWorkflowOutput:
    receipt = await workflow.execute_activity(
        RESEARCH_CANCEL_ACTIVITY,
        args=[
            {
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "idempotency_key": f"{value.task_id}:{run_id}:cancel",
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    if not isinstance(receipt, Mapping) or not bool(receipt.get("committed")):
        raise ApplicationError(
            "authoritative cancellation was not confirmed", type="ResultCommitRejected"
        )
    terminal_status = _receipt_terminal_status(receipt, TaskStatus.CANCELLED)
    event_id = f"{value.task_id}:{run_id}:{terminal_status.value}"
    published = await workflow.execute_activity(
        RESEARCH_PUBLISH_ACTIVITY,
        args=[
            {
                "event_id": event_id,
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "status": terminal_status.value,
                "result": {"status": terminal_status.value},
                "idempotency_key": event_id,
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    return ResearchWorkflowOutput(
        task_id=value.task_id,
        workflow_id=value.workflow_id,
        run_id=run_id,
        committed=True,
        published=bool(published),
        result={"status": terminal_status.value},
    )


async def _fail_research_workflow(
    value: ResearchWorkflowInput,
    run_id: str,
    config: ReliableTaskConfig,
    exc: Exception,
) -> ResearchWorkflowOutput:
    """Persist a failed execution before exposing its terminal event."""

    error = _error_from_workflow_exception(exc)
    receipt = await workflow.execute_activity(
        RESEARCH_FAIL_ACTIVITY,
        args=[
            {
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "error": error.model_dump(mode="json"),
                "idempotency_key": f"{value.task_id}:{run_id}:failed",
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    if not isinstance(receipt, Mapping) or not bool(receipt.get("committed")):
        raise ApplicationError(
            "authoritative failure was not confirmed", type="ResultCommitRejected"
        )
    terminal_status = _receipt_terminal_status(receipt, TaskStatus.FAILED)
    event_id = f"{value.task_id}:{run_id}:{terminal_status.value}"
    published = await workflow.execute_activity(
        RESEARCH_PUBLISH_ACTIVITY,
        args=[
            {
                "event_id": event_id,
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "status": terminal_status.value,
                "progress": 1.0,
                "result": {"error": error.model_dump(mode="json")},
                "idempotency_key": event_id,
            }
        ],
        **config.activity_config(timeout_seconds=30),
    )
    return ResearchWorkflowOutput(
        task_id=value.task_id,
        workflow_id=value.workflow_id,
        run_id=run_id,
        committed=True,
        published=bool(published),
        result={"status": terminal_status.value, "error": error.model_dump(mode="json")},
    )


def _is_commit_barrier_failure(exc: BaseException) -> bool:
    """Identify an exception raised by the authoritative commit Activity."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ApplicationError):
            error_type = getattr(current, "type", None)
            if error_type in {"ResultCommitRejected", "POSTGRES_RESULT_COMMIT_UNAVAILABLE"}:
                return True
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if "commit" in name or "commit" in message and "activity" in message:
            return True
        cause = getattr(current, "cause", None) or current.__cause__
        if isinstance(cause, BaseException):
            pending.append(cause)
    return False


def _error_from_workflow_exception(exc: BaseException) -> ContractError:
    error_type = getattr(exc, "type", None) or type(exc).__name__
    message = str(exc).strip() or error_type
    category = ErrorCategory.INTERNAL
    if str(error_type).casefold() in {"validationerror", "validation"}:
        category = ErrorCategory.VALIDATION
    elif "timeout" in str(error_type).casefold() or "timeout" in message.casefold():
        category = ErrorCategory.TIMEOUT
    return ContractError(
        code="RESEARCH_EXECUTION_FAILED",
        category=category,
        scope=ErrorScope.TASK,
        retryable=False,
        terminal=True,
        message=message[:500],
        details={"exceptionType": str(error_type)},
    )


def _status_from_reconciled_payload(payload: Mapping[str, Any]) -> TaskStatus:
    raw = payload.get("status")
    if isinstance(raw, str):
        try:
            status = TaskStatus(raw)
        except ValueError:
            status = TaskStatus.COMPLETED
        if status.is_terminal:
            return status
    return TaskStatus.COMPLETED


def _error_from_reconciled_payload(payload: Mapping[str, Any]) -> ContractError | None:
    raw = payload.get("error")
    if not isinstance(raw, Mapping):
        return None
    try:
        return ContractError.model_validate(raw)
    except Exception:
        return None


def build_pydantic_ai_research_workflow(
    agent: Any,
    *,
    name: str = "research-agent",
) -> type[Any]:
    """Create the official Pydantic AI Temporal workflow variant.

    ``TemporalAgent`` converts model requests and function-tool calls into
    bounded Activities.  The returned workflow still uses the same commit and
    publish Activities as :class:`TemporalResearchWorkflow`, so model output
    can never publish a terminal before PostgreSQL acknowledges the result.

    The factory is intentionally explicit instead of hiding a second Agent
    runtime in a Domain Pack.  Workers register the returned class together
    with ``PydanticAIPlugin`` (see :func:`pydantic_ai_worker_plugin`).
    """

    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow, TemporalAgent

    temporal_agent = agent if isinstance(agent, TemporalAgent) else TemporalAgent(agent, name=name)

    class PydanticResearchWorkflow(PydanticAIWorkflow):
        __pydantic_ai_agents__ = (temporal_agent,)

        @workflow.run
        async def run(self, raw_input: Mapping[str, Any]) -> ResearchWorkflowOutput:
            value = ResearchWorkflowInput.model_validate(raw_input)
            run_id = workflow.info().run_id
            from xhs_food.contracts import AgentDependencies

            dependencies = AgentDependencies(
                task_id=value.task_id,
                plan_id=value.plan_id,
                domain=value.request.domain,
                contract_versions=value.contract_versions,
            )
            prompt = value.request.query or value.request.domain
            agent_result = await temporal_agent.run(prompt, deps=dependencies)
            output = getattr(agent_result, "output", None)
            dump = getattr(output, "model_dump", None)
            if callable(dump):
                output_payload = dump(mode="json")
            elif isinstance(output, Mapping):
                output_payload = dict(output)
            else:
                output_payload = {"value": output}
            result_payload = TypeAdapter(ContractPayload).validate_python({"agent": output_payload})
            receipt = await workflow.execute_activity(
                RESEARCH_COMMIT_ACTIVITY,
                args=[
                    {
                        "task_id": value.task_id,
                        "workflow_id": value.workflow_id,
                        "run_id": run_id,
                        "result": result_payload,
                        "idempotency_key": f"{value.task_id}:{run_id}:result",
                    }
                ],
                **value.activity_policy.activity_config(),
            )
            if not isinstance(receipt, Mapping) or not bool(receipt.get("committed")):
                raise ApplicationError(
                    "authoritative result commit was not confirmed",
                    type="ResultCommitRejected",
                )
            event_id = f"{value.task_id}:{run_id}:completed"
            published = await workflow.execute_activity(
                RESEARCH_PUBLISH_ACTIVITY,
                args=[
                    {
                        "event_id": event_id,
                        "task_id": value.task_id,
                        "workflow_id": value.workflow_id,
                        "run_id": run_id,
                        "turn_id": value.turn_id,
                        "status": TaskStatus.COMPLETED.value,
                        "progress": 1.0,
                        "result": result_payload,
                        "idempotency_key": event_id,
                    }
                ],
                **value.activity_policy.activity_config(timeout_seconds=30),
            )
            return ResearchWorkflowOutput(
                task_id=value.task_id,
                workflow_id=value.workflow_id,
                run_id=run_id,
                committed=True,
                published=bool(published),
                result=result_payload,
            )

    return workflow.defn(name=RESEARCH_WORKFLOW_TYPE)(PydanticResearchWorkflow)


def pydantic_ai_worker_plugin() -> Any:
    """Return the official plugin required by a Pydantic AI Temporal worker."""

    from pydantic_ai.durable_exec.temporal import PydanticAIPlugin

    return PydanticAIPlugin()


class ReliableResearchActivities:
    """Worker Activity implementations with explicit authority boundaries."""

    def __init__(
        self,
        *,
        owner: ReliableTaskOwner,
        authority: ReliableTaskAuthority,
        executor: ResearchExecutor,
        publisher: ReliableTaskEventPublisher | None = None,
        config: ReliableTaskConfig | None = None,
    ) -> None:
        self._owner = owner
        self._authority = authority
        self._executor = executor
        self._publisher = publisher
        self._config = config or ReliableTaskConfig()

    @activity.defn(name=RESEARCH_EXECUTE_ACTIVITY)
    async def execute(self, raw_input: Mapping[str, Any], activity_version: str) -> ContractPayload:
        if activity_version != RESEARCH_ACTIVITY_VERSION:
            raise ApplicationError("unsupported research Activity contract", type="ValidationError")
        value = ResearchWorkflowInput.model_validate(raw_input)
        result = await self._executor(value, f"{value.task_id}:execute")
        if not isinstance(result, Mapping):
            raise ApplicationError(
                "research executor returned a non-object", type="ValidationError"
            )
        return {str(key): item for key, item in result.items()}

    @activity.defn(name=RESEARCH_PROGRESS_ACTIVITY)
    async def progress(self, raw: Mapping[str, Any]) -> ContractPayload:
        task_id = _required_text(raw, "task_id")
        workflow_id = _required_text(raw, "workflow_id")
        run_id = _required_text(raw, "run_id")
        raw_progress = raw.get("progress")
        if not isinstance(raw_progress, (int, float)) or not 0 <= float(raw_progress) <= 1:
            raise ApplicationError("invalid task progress", type="ValidationError")
        projection = await self._owner.record_reliable_progress(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            progress=float(raw_progress),
            current_step_id=_optional_text(raw.get("current_step_id")),
        )
        return projection.model_dump(mode="json")

    @activity.defn(name=RESEARCH_COMMIT_ACTIVITY)
    async def commit(self, raw: Mapping[str, Any]) -> ContractPayload:
        task_id = _required_text(raw, "task_id")
        workflow_id = _required_text(raw, "workflow_id")
        run_id = _required_text(raw, "run_id")
        result = raw.get("result")
        if not isinstance(result, Mapping):
            raise ApplicationError("result must be an object", type="ValidationError")
        idempotency_key = _required_text(raw, "idempotency_key")
        receipt = await self._authority.commit_result(
            task_id,
            workflow_id,
            run_id,
            {str(key): item for key, item in result.items()},
            idempotency_key=idempotency_key,
        )
        if not receipt.committed:
            raise ApplicationError(
                "authoritative result commit was rejected", type="ResultCommitRejected"
            )
        effective_status = receipt.terminal_status or TaskStatus.COMPLETED
        await self._owner.finalize_reliable_task(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=effective_status,
            result={str(key): item for key, item in result.items()},
        )
        return _receipt_payload(receipt)

    @activity.defn(name=RESEARCH_PUBLISH_ACTIVITY)
    async def publish_terminal(self, raw: Mapping[str, Any]) -> bool:
        event_id = _required_text(raw, "event_id")
        task_id = _required_text(raw, "task_id")
        try:
            status = TaskStatus(str(raw.get("status")))
        except ValueError as exc:
            raise ApplicationError(
                "terminal event requires a valid task status", type="ValidationError"
            ) from exc
        result = raw.get("result")
        payload: ContractPayload = {
            "result": {str(key): item for key, item in result.items()}
            if isinstance(result, Mapping)
            else {},
            "workflowId": _required_text(raw, "workflow_id"),
            "runId": _required_text(raw, "run_id"),
        }
        event_type = {
            TaskStatus.COMPLETED: "task.completed",
            TaskStatus.FAILED: "task.failed",
            TaskStatus.CANCELLED: "task.cancelled",
        }.get(status)
        if event_type is None:
            raise ApplicationError(
                "terminal event requires a terminal status", type="ValidationError"
            )
        event = TaskEvent(
            event_id=event_id,
            task_id=task_id,
            event_type=event_type,
            occurred_at=datetime.now(UTC),
            turn_id=_optional_text(raw.get("turn_id")),
            status=status,
            progress=1.0,
            payload=payload,
        )
        if self._publisher is None:
            return False
        try:
            await self._publisher.publish_task_event(
                event, idempotency_key=_required_text(raw, "idempotency_key")
            )
        except Exception:
            # The event stream is rebuildable hot state.  The committed result
            # and Temporal history remain authoritative; reconciliation can
            # republish this deterministic event later.
            return False
        return True

    @activity.defn(name=RESEARCH_CANCEL_ACTIVITY)
    async def cancel(self, raw: Mapping[str, Any]) -> ContractPayload:
        task_id = _required_text(raw, "task_id")
        workflow_id = _required_text(raw, "workflow_id")
        run_id = _required_text(raw, "run_id")
        receipt = await self._authority.commit_cancelled(
            task_id,
            workflow_id,
            run_id,
            idempotency_key=_required_text(raw, "idempotency_key"),
        )
        if not receipt.committed:
            raise ApplicationError("cancel commit was rejected", type="ResultCommitRejected")
        effective_status = receipt.terminal_status or TaskStatus.CANCELLED
        await self._owner.finalize_reliable_task(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=effective_status,
        )
        return _receipt_payload(receipt)

    @activity.defn(name=RESEARCH_FAIL_ACTIVITY)
    async def fail(self, raw: Mapping[str, Any]) -> ContractPayload:
        task_id = _required_text(raw, "task_id")
        workflow_id = _required_text(raw, "workflow_id")
        run_id = _required_text(raw, "run_id")
        raw_error = raw.get("error")
        if not isinstance(raw_error, Mapping):
            raise ApplicationError("failure error must be an object", type="ValidationError")
        try:
            error = ContractError.model_validate(raw_error)
        except Exception as exc:
            raise ApplicationError(
                "failure error has an invalid contract", type="ValidationError"
            ) from exc
        receipt = await self._authority.commit_failed(
            task_id,
            workflow_id,
            run_id,
            error,
            idempotency_key=_required_text(raw, "idempotency_key"),
        )
        if not receipt.committed:
            raise ApplicationError("failure commit was rejected", type="ResultCommitRejected")
        effective_status = receipt.terminal_status or TaskStatus.FAILED
        await self._owner.finalize_reliable_task(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=effective_status,
            error=error,
            result={"error": error.model_dump(mode="json")},
        )
        return _receipt_payload(receipt)

    @activity.defn(name=RESEARCH_RECONCILE_ACTIVITY)
    async def reconcile(self, raw: Mapping[str, Any]) -> bool:
        """Rebuild a terminal projection/event after a worker crash.

        Reconciliation is deliberately idempotent and keyed by the complete
        `(task_id, workflow_id, run_id)` identity.  It never invents a result
        when PostgreSQL has no committed receipt.
        """

        task_id = _required_text(raw, "task_id")
        workflow_id = _required_text(raw, "workflow_id")
        run_id = _required_text(raw, "run_id")
        result = await self._authority.reconcile(task_id, workflow_id, run_id)
        if result is None:
            return False
        task = await self._owner.reliable_task(task_id)
        if task is None:
            return False
        status = _status_from_reconciled_payload(result)
        error = _error_from_reconciled_payload(result) if status is TaskStatus.FAILED else None
        if not task.status.is_terminal:
            await self._owner.finalize_reliable_task(
                task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status=status,
                result=result,
                error=error,
            )
        current = await self._owner.reliable_task(task_id)
        if current is not None and current.status.is_terminal:
            status = current.status
        event_suffix = status.value
        return await self.publish_terminal(
            {
                "event_id": f"{task_id}:{run_id}:{event_suffix}",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "turn_id": current.turn_id if current is not None else task.turn_id,
                "status": status.value,
                "result": result,
                "idempotency_key": f"{task_id}:{run_id}:{event_suffix}",
            }
        )

    def activities(self) -> tuple[Callable[..., Any], ...]:
        """Return the complete Research worker registration set."""

        return (
            self.execute,
            self.progress,
            self.commit,
            self.fail,
            self.publish_terminal,
            self.cancel,
            self.reconcile,
        )


class InMemoryReliableTaskAuthority:
    """Explicit test double for the PostgreSQL authority port.

    It is intentionally not selected by the Composition Root.  The double
    models the important idempotency property: repeating a commit with the
    same key returns the original receipt without changing the result.
    """

    def __init__(self) -> None:
        self.results: dict[str, ContractPayload] = {}
        self._results_by_run: dict[tuple[str, str, str], ContractPayload] = {}
        self.receipts: dict[str, ResultCommitReceipt] = {}
        self._terminal_by_run: dict[tuple[str, str, str], ResultCommitReceipt] = {}
        self.cancelled: set[str] = set()
        self.fail_commits = False
        self._lock = asyncio.Lock()

    async def commit_result(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        result: ContractPayload,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        if self.fail_commits:
            raise ReliableDependencyUnavailable(
                _lifecycle_error(
                    code="POSTGRES_RESULT_COMMIT_UNAVAILABLE",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    scope=ErrorScope.REPOSITORY,
                    message="test authority commit failed",
                    retryable=True,
                )
            )
        async with self._lock:
            previous = self.receipts.get(idempotency_key)
            if previous is not None:
                return previous.model_copy(update={"already_committed": True})
            identity = (task_id, workflow_id, run_id)
            existing = self._terminal_by_run.get(identity)
            if existing is not None:
                return existing.model_copy(update={"already_committed": True})
            self.results[task_id] = dict(result)
            self._results_by_run[identity] = dict(result)
            receipt = ResultCommitReceipt(
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                committed=True,
                result_version=f"result:{task_id}:{run_id}",
                terminal_status=TaskStatus.COMPLETED,
            )
            self.receipts[idempotency_key] = receipt
            self._terminal_by_run[identity] = receipt
            return receipt

    async def commit_cancelled(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        async with self._lock:
            previous = self.receipts.get(idempotency_key)
            if previous is not None:
                return previous.model_copy(update={"already_committed": True})
            identity = (task_id, workflow_id, run_id)
            existing = self._terminal_by_run.get(identity)
            if existing is not None:
                return existing.model_copy(update={"already_committed": True})
            self.cancelled.add(task_id)
            receipt = ResultCommitReceipt(
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                committed=True,
                result_version=None,
                terminal_status=TaskStatus.CANCELLED,
            )
            self.receipts[idempotency_key] = receipt
            self._terminal_by_run[identity] = receipt
            return receipt

    async def commit_failed(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        error: ContractError,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        async with self._lock:
            previous = self.receipts.get(idempotency_key)
            if previous is not None:
                return previous.model_copy(update={"already_committed": True})
            identity = (task_id, workflow_id, run_id)
            existing = self._terminal_by_run.get(identity)
            if existing is not None:
                return existing.model_copy(update={"already_committed": True})
            failed_result = cast(
                ContractPayload,
                {"error": error.model_dump(mode="json")},
            )
            self.results[task_id] = failed_result
            self._results_by_run[identity] = failed_result
            receipt = ResultCommitReceipt(
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                committed=True,
                result_version=f"failure:{task_id}:{run_id}",
                terminal_status=TaskStatus.FAILED,
            )
            self.receipts[idempotency_key] = receipt
            self._terminal_by_run[identity] = receipt
            return receipt

    async def reconcile(
        self, task_id: str, workflow_id: str, run_id: str
    ) -> ContractPayload | None:
        receipt = self._terminal_by_run.get((task_id, workflow_id, run_id))
        result = self._results_by_run.get((task_id, workflow_id, run_id))
        if result is None:
            result = self.results.get(task_id)
        if result is None:
            return None
        # A few offline fixtures seed ``results`` directly to model a crash
        # after a database commit.  The production PostgreSQL adapter always
        # requires the transactional receipt; this compatibility branch is
        # intentionally confined to the explicit in-memory test double.
        if receipt is None:
            return result
        if receipt.terminal_status is TaskStatus.CANCELLED:
            return {"status": TaskStatus.CANCELLED.value}
        if receipt.terminal_status is TaskStatus.FAILED:
            return {
                "status": TaskStatus.FAILED.value,
                **result,
            }
        return result


class InMemoryReliableTaskEventPublisher:
    """Explicit test publisher with deterministic event de-duplication."""

    def __init__(self) -> None:
        self.events: dict[str, TaskEvent] = {}
        self.available = True

    async def publish_task_event(self, event: TaskEvent, *, idempotency_key: str) -> str:
        if not self.available:
            raise RuntimeError("event backend unavailable")
        self.events.setdefault(idempotency_key, event)
        return event.event_id


class TemporalReliableResearchPolicy:
    """Coordinator-facing policy that starts one Temporal workflow per task."""

    def __init__(
        self,
        workflow_port: WorkflowPort,
        owner: ReliableTaskOwner | None = None,
        *,
        config: ReliableTaskConfig | None = None,
    ) -> None:
        self._workflow = workflow_port
        self._owner = owner
        self._config = config or ReliableTaskConfig()
        # This coalesces callers sharing one policy instance. Temporal
        # Workflow ID and the PostgreSQL admission/CAS boundary remain the
        # cross-worker authorities.
        self._admission_lock = asyncio.Lock()
        self._inflight_admissions: dict[str, asyncio.Future[ResearchTask]] = {}
        self._admission_enabled = True

    def bind_owner(self, owner: ReliableTaskOwner) -> None:
        """Bind the Coordinator after Composition Root construction."""

        if self._owner is not None and self._owner is not owner:
            raise RuntimeError("reliable policy cannot change its task owner")
        self._owner = owner

    @property
    def config(self) -> ReliableTaskConfig:
        return self._config

    @property
    def admission_enabled(self) -> bool:
        """Whether this policy may start or attach a new reliable Workflow."""

        return self._admission_enabled

    def disable_admission(self) -> None:
        """Close the reliable ingress during a staged rollback.

        Existing Workflow histories and PostgreSQL facts remain untouched. A
        deployment should drain active requests before calling this method;
        the guard is the final in-process check before Temporal start.
        """

        self._admission_enabled = False

    def enable_admission(self) -> None:
        """Re-open reliable ingress after the rollback qualification gate."""

        self._admission_enabled = True

    async def submit(self, request: ResearchRequest) -> ResearchTask:
        owner = self._require_owner()
        if not self._admission_enabled:
            raise ReliableTaskConflict(
                _lifecycle_error(
                    code="RELIABLE_ADMISSION_DISABLED",
                    category=ErrorCategory.POLICY_DENIED,
                    scope=ErrorScope.REQUEST,
                    message="reliable task admission is disabled during rollback",
                )
            )
        if request.operation is ResearchOperation.RECOVER:
            if request.target_task_id is None:
                raise ValueError("recover operation requires target_task_id")
            task = await owner.reliable_task(request.target_task_id)
            if task is None:
                raise LookupError(request.target_task_id)
            return task
        if request.operation is ResearchOperation.REFRESH:
            raise RuntimeError("explicit refresh remains owned by B2")
        if request.operation is ResearchOperation.REFINE:
            error = _lifecycle_error(
                code="RELIABLE_REFINE_IDENTITY_UNAPPROVED",
                category=ErrorCategory.CONFLICT,
                scope=ErrorScope.REQUEST,
                message="reliable refine identity is not approved; use the legacy policy",
                retryable=False,
            )
            raise ReliableTaskConflict(error)

        return await self._submit_query(request, owner)

    async def _submit_query(
        self, request: ResearchRequest, owner: ReliableTaskOwner
    ) -> ResearchTask:
        """Coalesce equivalent admissions before calling the Workflow port."""

        task_id = stable_research_task_id(request)
        workflow_id = stable_research_workflow_id(task_id)
        loop = asyncio.get_running_loop()
        async with self._admission_lock:
            future = self._inflight_admissions.get(task_id)
            if future is None:
                future = loop.create_future()
                self._inflight_admissions[task_id] = future
                leader = True
            else:
                leader = False
        if not leader:
            return await asyncio.shield(future)

        try:
            existing = await owner.reliable_task(task_id)
            if not self._admission_enabled:
                raise ReliableTaskConflict(
                    _lifecycle_error(
                        code="RELIABLE_ADMISSION_DISABLED",
                        category=ErrorCategory.POLICY_DENIED,
                        scope=ErrorScope.REQUEST,
                        message="reliable task admission is disabled during rollback",
                    )
                )
            if existing is not None and (existing.run_id or existing.status.is_terminal):
                result = existing
            else:
                task = existing or await owner.admit_reliable_task(
                    request,
                    task_id=task_id,
                    workflow_id=workflow_id,
                )
                command = build_workflow_start(
                    request,
                    task_id=task_id,
                    plan_id=task.plan_id or f"plan:{task_id}",
                    turn_id=task.turn_id or "1",
                    config=self._config,
                )
                try:
                    run = await self._workflow.start(command)
                except Exception as exc:
                    error = _lifecycle_error(
                        code="RESEARCH_WORKFLOW_START_FAILED",
                        category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                        scope=ErrorScope.WORKFLOW,
                        message=str(exc),
                        retryable=True,
                    )
                    await owner.finalize_reliable_task(
                        task_id,
                        workflow_id=workflow_id,
                        run_id="unstarted",
                        status=TaskStatus.FAILED,
                        error=error,
                    )
                    raise ReliableDependencyUnavailable(error) from exc
                result = await owner.attach_reliable_run(task_id, run)
            future.set_result(result)
            return result
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                # Mark the exception as observed for the no-waiter case while
                # keeping it available to any concurrent waiter.
                future.exception()
            raise
        finally:
            async with self._admission_lock:
                if self._inflight_admissions.get(task_id) is future:
                    self._inflight_admissions.pop(task_id, None)

    async def cancel(self, task_id: str, reason: str | None = None) -> bool:
        owner = self._require_owner()
        task = await owner.reliable_task(task_id)
        if task is None or task.status.is_terminal or not task.workflow_id:
            return False
        await self._workflow.cancel(task.workflow_id, reason)
        # Temporal cancellation is the executable command.  The worker's
        # cancellation Activity performs the authoritative commit; the owner
        # remains non-terminal until that receipt exists.
        return True

    async def retry(self, task_id: str) -> ResearchTask:
        owner = self._require_owner()
        task = await owner.reliable_task(task_id)
        request = await owner.reliable_request(task_id)
        if task is None or request is None:
            raise LookupError(task_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            return task
        next_turn = _next_retry_turn(task.turn_id)
        command = build_workflow_start(
            request,
            task_id=task_id,
            plan_id=f"plan:{task_id}:turn:{next_turn}",
            turn_id=str(next_turn),
            config=self._config,
        )
        run = await self._workflow.start(command)
        return await owner.attach_reliable_run(task_id, run)

    def _require_owner(self) -> ReliableTaskOwner:
        if self._owner is None:
            raise RuntimeError("reliable policy has no ResearchCoordinator owner")
        return self._owner


def _required_text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ApplicationError(f"{key} must be a non-empty string", type="ValidationError")
    return raw


def _receipt_terminal_status(receipt: Mapping[str, Any], fallback: TaskStatus) -> TaskStatus:
    raw = receipt.get("terminal_status")
    if isinstance(raw, TaskStatus):
        return raw
    if isinstance(raw, str):
        try:
            value = TaskStatus(raw)
        except ValueError:
            return fallback
        return value if value.is_terminal else fallback
    return fallback


def _receipt_payload(receipt: ResultCommitReceipt) -> ContractPayload:
    """Serialize an authority receipt at the Activity JSON boundary."""

    return cast(ContractPayload, receipt.model_dump(mode="json"))


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _next_retry_turn(turn_id: str | None) -> int:
    try:
        return int(turn_id or "0") + 1
    except ValueError:
        return 1


def _lifecycle_error(
    *,
    code: str,
    category: ErrorCategory,
    scope: ErrorScope,
    message: str,
    retryable: bool = False,
) -> ContractError:
    return ContractError(
        code=code,
        category=category,
        scope=scope,
        retryable=retryable,
        terminal=not retryable,
        message=message,
    )


__all__ = [
    "LEGACY_TASK_POLICY_VERSION",
    "RELIABLE_TASK_POLICY_VERSION",
    "RESEARCH_ACTIVITY_VERSION",
    "RESEARCH_CANCEL_ACTIVITY",
    "RESEARCH_CANCEL_SIGNAL",
    "RESEARCH_COMMIT_ACTIVITY",
    "RESEARCH_EXECUTE_ACTIVITY",
    "RESEARCH_FAIL_ACTIVITY",
    "RESEARCH_PROGRESS_ACTIVITY",
    "RESEARCH_PUBLISH_ACTIVITY",
    "RESEARCH_RECONCILE_ACTIVITY",
    "RESEARCH_TASK_QUEUE",
    "RESEARCH_WORKFLOW_TYPE",
    "ReliableDependencyUnavailable",
    "ReliableResearchActivities",
    "InMemoryReliableTaskAuthority",
    "InMemoryReliableTaskEventPublisher",
    "ReliableTaskAuthority",
    "ReliableTaskConfig",
    "ReliableTaskConflict",
    "ReliableTaskEventPublisher",
    "ReliableTaskFailure",
    "ReliableTaskOwner",
    "ResearchExecutor",
    "ResearchWorkflowInput",
    "ResearchWorkflowOutput",
    "ResultCommitReceipt",
    "TemporalReliableResearchPolicy",
    "TemporalResearchWorkflow",
    "build_workflow_start",
    "build_pydantic_ai_research_workflow",
    "pydantic_ai_worker_plugin",
    "stable_research_task_id",
    "stable_research_workflow_id",
    "reliable_plan",
]
