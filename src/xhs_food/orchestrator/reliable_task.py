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
from typing import Any, Protocol, runtime_checkable

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


class ReliableTaskConfig(ContractModel):
    """Versioned Temporal activity policy shared by Research workers."""

    policy_version: str = RELIABLE_TASK_POLICY_VERSION
    task_queue: str = RESEARCH_TASK_QUEUE
    activity_timeout_seconds: int = Field(default=300, ge=1)
    heartbeat_timeout_seconds: int = Field(default=30, ge=1)
    retry_initial_interval_seconds: int = Field(default=1, ge=1)
    retry_maximum_interval_seconds: int = Field(default=30, ge=1)
    retry_backoff_coefficient: float = Field(default=2.0, ge=1.0)
    retry_maximum_attempts: int = Field(default=3, ge=1)
    non_retryable_error_types: tuple[str, ...] = (
        "ValidationError",
        "PolicyDeniedError",
        "NonRetryableApplicationError",
        "ResultCommitRejected",
    )

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
        if self._cancel_requested:
            return await _cancel_research_workflow(value, run_id, config)
        result = await workflow.execute_activity(
            RESEARCH_EXECUTE_ACTIVITY,
            args=[value.model_dump(mode="json"), RESEARCH_ACTIVITY_VERSION],
            **config.activity_config(),
        )
        if not isinstance(result, Mapping):
            raise ApplicationError(
                "research activity returned a non-object", type="ValidationError"
            )
        result_payload = {str(key): item for key, item in result.items()}
        if self._cancel_requested:
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
        raise ApplicationError("authoritative cancellation was not confirmed", type="ResultCommitRejected")
    event_id = f"{value.task_id}:{run_id}:cancelled"
    published = await workflow.execute_activity(
        RESEARCH_PUBLISH_ACTIVITY,
        args=[
            {
                "event_id": event_id,
                "task_id": value.task_id,
                "workflow_id": value.workflow_id,
                "run_id": run_id,
                "turn_id": value.turn_id,
                "status": TaskStatus.CANCELLED.value,
                "result": {"status": TaskStatus.CANCELLED.value},
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
        result={"status": TaskStatus.CANCELLED.value},
    )


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
            result_payload = TypeAdapter(ContractPayload).validate_python(
                {"agent": output_payload}
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
        await self._owner.finalize_reliable_task(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=TaskStatus.COMPLETED,
            result={str(key): item for key, item in result.items()},
        )
        return receipt.model_dump(mode="json")

    @activity.defn(name=RESEARCH_PUBLISH_ACTIVITY)
    async def publish_terminal(self, raw: Mapping[str, Any]) -> bool:
        event_id = _required_text(raw, "event_id")
        task_id = _required_text(raw, "task_id")
        status = TaskStatus(str(raw.get("status")))
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
            raise ApplicationError("terminal event requires a terminal status", type="ValidationError")
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
        await self._owner.finalize_reliable_task(
            task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=TaskStatus.CANCELLED,
        )
        return receipt.model_dump(mode="json")

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
        if not task.status.is_terminal:
            await self._owner.finalize_reliable_task(
                task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status=TaskStatus.COMPLETED,
                result=result,
            )
        return await self.publish_terminal(
            {
                "event_id": f"{task_id}:{run_id}:completed",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "turn_id": task.turn_id,
                "status": TaskStatus.COMPLETED.value,
                "result": result,
                "idempotency_key": f"{task_id}:{run_id}:completed",
            }
        )

    def activities(self) -> tuple[Callable[..., Any], ...]:
        """Return the complete Research worker registration set."""

        return (
            self.execute,
            self.progress,
            self.commit,
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
        self.receipts: dict[str, ResultCommitReceipt] = {}
        self.cancelled: set[str] = set()
        self.fail_commits = False

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
        previous = self.receipts.get(idempotency_key)
        if previous is not None:
            return previous.model_copy(update={"already_committed": True})
        self.results[task_id] = dict(result)
        receipt = ResultCommitReceipt(
            task_id=task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            committed=True,
            result_version=f"result:{task_id}:{run_id}",
        )
        self.receipts[idempotency_key] = receipt
        return receipt

    async def commit_cancelled(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        previous = self.receipts.get(idempotency_key)
        if previous is not None:
            return previous.model_copy(update={"already_committed": True})
        self.cancelled.add(task_id)
        receipt = ResultCommitReceipt(
            task_id=task_id,
            workflow_id=workflow_id,
            run_id=run_id,
            committed=True,
            result_version=None,
        )
        self.receipts[idempotency_key] = receipt
        return receipt

    async def reconcile(
        self, task_id: str, workflow_id: str, run_id: str
    ) -> ContractPayload | None:
        del workflow_id, run_id
        return self.results.get(task_id)


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

    def bind_owner(self, owner: ReliableTaskOwner) -> None:
        """Bind the Coordinator after Composition Root construction."""

        if self._owner is not None and self._owner is not owner:
            raise RuntimeError("reliable policy cannot change its task owner")
        self._owner = owner

    @property
    def config(self) -> ReliableTaskConfig:
        return self._config

    async def submit(self, request: ResearchRequest) -> ResearchTask:
        owner = self._require_owner()
        if request.operation is ResearchOperation.RECOVER:
            if request.target_task_id is None:
                raise ValueError("recover operation requires target_task_id")
            task = await owner.reliable_task(request.target_task_id)
            if task is None:
                raise LookupError(request.target_task_id)
            return task
        if request.operation is ResearchOperation.REFRESH:
            raise RuntimeError("explicit refresh remains owned by B2")

        task_id = stable_research_task_id(request)
        workflow_id = stable_research_workflow_id(task_id)
        existing = await owner.reliable_task(task_id)
        if existing is not None:
            # A task identity is single-flight even if Temporal is briefly
            # unavailable for a describe call.  Returning the projection is
            # safer than starting a second workflow.
            return existing

        task = await owner.admit_reliable_task(
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
        return await owner.attach_reliable_run(task_id, run)

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
        command = build_workflow_start(
            request,
            task_id=task_id,
            plan_id=task.plan_id or f"plan:{task_id}",
            turn_id=task.turn_id or "1",
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


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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
