"""Shared Research Coordinator with a behavior-preserving legacy policy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from xhs_food.contracts import (
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    ContractPayload,
    PlanBudget,
    PlanStatus,
    PlanStepStatus,
    RecoverView,
    ResearchOperation,
    ResearchPlan,
    ResearchPlanStep,
    ResearchRequest,
    ResearchTask,
    ResearchTaskAdmission,
    ResearchTaskPort,
    TaskEvent,
    TaskProgressProjection,
    TaskProgressProjectionPort,
    TaskStatus,
)
from xhs_food.orchestrator.projections import InMemoryTaskProgressProjectionStore
from xhs_food.orchestrator.review import (
    EvidenceReviewDecision,
    EvidenceReviewRequest,
    EvidenceReviewShell,
    ReplanRequest,
    ReplanShell,
    StoppingConditionShell,
    StoppingContext,
    StoppingDecision,
)
from xhs_food.orchestrator.scheduler import ScheduleResult, StepScheduler

Clock = Callable[[], datetime]

_LEGACY_STEPS = (
    ("legacy.step1", "food.intent.parse"),
    ("legacy.step2", "food.evidence.collect"),
    ("legacy.step3", "food.evidence.analyze"),
    ("legacy.step4", "food.decision.rank"),
    ("legacy.step5", "food.place.enrich"),
    ("legacy.step6", "food.output.build"),
)

_PROJECTION_STATUS_RANK = {
    TaskStatus.CREATED: 0,
    TaskStatus.PLANNING: 1,
    TaskStatus.RUNNING: 2,
    TaskStatus.COMPLETED: 3,
    TaskStatus.FAILED: 3,
    TaskStatus.CANCELLED: 3,
}


@runtime_checkable
class ReliableResearchPolicy(Protocol):
    """B0 extension point registered in S5 but not enabled."""

    async def submit(self, request: ResearchRequest) -> ResearchTask: ...

    async def cancel(self, task_id: str, reason: str | None = None) -> bool: ...

    async def retry(self, task_id: str) -> ResearchTask: ...


class DisabledReliableResearchPolicy:
    async def submit(self, request: ResearchRequest) -> ResearchTask:
        raise RuntimeError("reliable research policy is disabled until B0")

    async def cancel(self, task_id: str, reason: str | None = None) -> bool:
        return False

    async def retry(self, task_id: str) -> ResearchTask:
        raise RuntimeError("reliable research policy is disabled until B0")


class ResearchCoordinator:
    """Own shared task semantics while delegating S5 behavior to legacy code."""

    def __init__(
        self,
        legacy_policy: ResearchTaskPort,
        *,
        agent_runtime: AgentRuntime | None = None,
        scheduler: StepScheduler | None = None,
        projection_store: TaskProgressProjectionPort | None = None,
        evidence_review: EvidenceReviewShell | None = None,
        replanner: ReplanShell | None = None,
        stopping_conditions: StoppingConditionShell | None = None,
        reliable_policy: ReliableResearchPolicy | None = None,
        agent_runtime_enabled: bool = False,
        scheduler_enabled: bool = False,
        reliable_policy_enabled: bool = False,
        clock: Clock | None = None,
    ) -> None:
        if agent_runtime_enabled and agent_runtime is None:
            raise ValueError("agent_runtime_enabled requires one AgentRuntime")
        if scheduler_enabled and scheduler is None:
            raise ValueError("scheduler_enabled requires one StepScheduler")
        if reliable_policy_enabled and reliable_policy is None:
            raise ValueError("reliable_policy_enabled requires a reliable policy")
        self._legacy_policy = legacy_policy
        self._agent_runtime = agent_runtime
        self._scheduler = scheduler
        self._projection_store = projection_store or InMemoryTaskProgressProjectionStore()
        self._evidence_review = evidence_review or EvidenceReviewShell()
        self._replanner = replanner or ReplanShell()
        self._stopping_conditions = stopping_conditions or StoppingConditionShell()
        self._reliable_policy = reliable_policy or DisabledReliableResearchPolicy()
        self._agent_runtime_enabled = agent_runtime_enabled
        self._scheduler_enabled = scheduler_enabled
        self._reliable_policy_enabled = reliable_policy_enabled
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tasks: dict[str, ResearchTask] = {}
        self._plans: dict[str, ResearchPlan] = {}
        self._plans_by_id: dict[str, ResearchPlan] = {}
        self._events: dict[str, list[TaskEvent]] = {}
        self._state_lock = asyncio.Lock()

    @property
    def legacy_policy(self) -> ResearchTaskPort:
        return self._legacy_policy

    @property
    def agent_runtime(self) -> AgentRuntime | None:
        return self._agent_runtime

    @property
    def plans(self) -> Mapping[str, ResearchPlan]:
        return MappingProxyType(self._plans)

    @property
    def tasks(self) -> Mapping[str, ResearchTask]:
        return MappingProxyType(self._tasks)

    def register_agent_runtime(self, runtime: AgentRuntime) -> None:
        if self._agent_runtime is not None and self._agent_runtime is not runtime:
            raise RuntimeError("a ResearchCoordinator may own only one Agent runtime")
        self._agent_runtime = runtime

    async def start_new(self, query: str) -> ResearchTaskAdmission:
        admission = await self._legacy_policy.start_new(query)
        await self._record_admission_safely(admission, query=query)
        return admission

    async def refine(self, session_id: str, query: str) -> ResearchTaskAdmission:
        admission = await self._legacy_policy.refine(session_id, query)
        await self._record_admission_safely(admission, query=query)
        return admission

    async def recover(self, session_id: str) -> ContractPayload:
        expected_turn_id = await self._projection_turn_id(session_id)
        payload = await self._legacy_policy.recover(session_id)
        with suppress(Exception):
            await self._sync_legacy_projection(
                session_id,
                _unwrap_payload(payload),
                expected_turn_id=expected_turn_id,
            )
        return payload

    async def status(self, session_id: str) -> ContractPayload | None:
        expected_turn_id = await self._projection_turn_id(session_id)
        payload = await self._legacy_policy.status(session_id)
        if payload is not None:
            with suppress(Exception):
                await self._sync_legacy_projection(
                    session_id,
                    payload,
                    expected_turn_id=expected_turn_id,
                )
        return payload

    async def results(self, session_id: str) -> ContractPayload | None:
        return await self._legacy_policy.results(session_id)

    async def submit(self, request: ResearchRequest) -> ResearchTask:
        if self._reliable_policy_enabled:
            return await self._reliable_policy.submit(request)
        if request.operation is ResearchOperation.QUERY:
            if request.query is None:
                raise ValueError("query operation requires query")
            admission = await self.start_new(request.query)
        elif request.operation is ResearchOperation.REFINE:
            if request.target_task_id is None or request.query is None:
                raise ValueError("refine operation requires target_task_id and query")
            admission = await self.refine(request.target_task_id, request.query)
        elif request.operation is ResearchOperation.RECOVER:
            if request.target_task_id is None:
                raise ValueError("recover operation requires target_task_id")
            await self.recover(request.target_task_id)
            task = await self.task(request.target_task_id)
            if task is None:
                raise LookupError(request.target_task_id)
            return task
        else:
            raise RuntimeError("explicit refresh remains unbound until B2")
        task = await self.task(admission.task_id)
        if task is None:
            # ``start_new``/``refine`` already accepted and spawned the legacy
            # request.  Reconstruct a minimal query-side task when optional
            # shadow bookkeeping failed so submit remains behavior-preserving.
            await self._record_fallback_task(admission)
            task = await self.task(admission.task_id)
        if task is None:  # pragma: no cover - only malformed legacy admissions reach this path
            task = _legacy_task_snapshot(admission, now=_safe_now(self._clock))
        updated_task = task.model_copy(update={"request_id": request.request_id})
        async with self._state_lock:
            self._tasks[admission.task_id] = updated_task
        return updated_task

    async def cancel(self, task_id: str, reason: str | None = None) -> bool:
        if not self._reliable_policy_enabled:
            return False
        return await self._reliable_policy.cancel(task_id, reason)

    async def retry(self, task_id: str) -> ResearchTask:
        if not self._reliable_policy_enabled:
            raise RuntimeError("retry is disabled under the S5 legacy task policy")
        return await self._reliable_policy.retry(task_id)

    async def task(self, task_id: str) -> ResearchTask | None:
        async with self._state_lock:
            return self._tasks.get(task_id)

    async def plan(self, task_id: str) -> ResearchPlan | None:
        async with self._state_lock:
            return self._plans.get(task_id)

    async def progress(self, task_id: str) -> TaskProgressProjection | None:
        return await self._projection_store.get(task_id)

    async def recover_view(self, task_id: str) -> RecoverView:
        try:
            projection = await self._projection_store.get(task_id)
        except Exception:
            projection = None
        expected_turn_id = projection.turn_id if projection is not None else None
        try:
            payload = await self._legacy_policy.recover(task_id)
        except LookupError:
            return RecoverView(
                task_id=task_id,
                projection=projection,
                replay="not_found",
            )
        with suppress(Exception):
            await self._sync_legacy_projection(
                task_id,
                _unwrap_payload(payload),
                expected_turn_id=expected_turn_id,
            )
        with suppress(Exception):
            projection = await self._projection_store.get(task_id)
        return RecoverView(
            task_id=task_id,
            session_id=projection.session_id if projection else task_id,
            turn_id=projection.turn_id if projection else None,
            last_event_id=projection.last_event_id if projection else None,
            projection=projection,
            payload=payload,
        )

    async def events(self, task_id: str) -> tuple[TaskEvent, ...]:
        async with self._state_lock:
            return tuple(self._events.get(task_id, ()))

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        if not self._agent_runtime_enabled or self._agent_runtime is None:
            raise RuntimeError("Agent runtime is registered but disabled under S5 legacy policy")
        async with self._state_lock:
            plan = self._plans_by_id.get(request.dependencies.plan_id)
        if plan is None:
            raise LookupError(f"unknown Agent plan: {request.dependencies.plan_id}")
        if plan.task_id != request.dependencies.task_id:
            raise ValueError("Agent request task_id does not match the requested plan task_id")
        scoped_dependencies = request.dependencies.model_copy(
            update={
                "allowed_step_ids": plan.ready_step_ids(),
                "allowed_evidence_refs": plan.evidence_refs,
            }
        )
        request = request.model_copy(update={"dependencies": scoped_dependencies})
        return await self._agent_runtime.run(request)

    async def execute_plan(self, plan: ResearchPlan) -> ScheduleResult:
        if not self._scheduler_enabled or self._scheduler is None:
            raise RuntimeError("Step Scheduler is disabled under S5 legacy policy")
        result = await self._scheduler.execute(plan)
        await self._record_schedule(result)
        return result

    async def review_and_replan(
        self,
        request: EvidenceReviewRequest,
    ) -> tuple[EvidenceReviewDecision, ResearchPlan]:
        review = await self._evidence_review.review(request)
        plan = await self.plan(request.task_id)
        if plan is None:
            raise LookupError(request.task_id)
        replanned = await self._replanner.replan(
            ReplanRequest(task_id=request.task_id, current_plan=plan, review=review)
        )
        if replanned.task_id != request.task_id:
            raise ValueError("replanned plan task_id must match the reviewed task")
        async with self._state_lock:
            self._remember_plan(replanned)
            task = self._tasks.get(request.task_id)
            if task is not None:
                self._tasks[request.task_id] = task.model_copy(
                    update={"plan_id": replanned.plan_id, "updated_at": _safe_now(self._clock)}
                )
        return review, replanned

    async def should_stop(self, context: StoppingContext) -> StoppingDecision:
        return await self._stopping_conditions.evaluate(context)

    async def _record_admission_safely(
        self,
        admission: ResearchTaskAdmission,
        *,
        query: str,
    ) -> None:
        """Keep optional S5 bookkeeping from changing legacy admission behavior."""

        try:
            await self._record_admission(admission, query=query)
        except Exception:
            # The legacy facade has already accepted and spawned the request.
            # Projections are additive, so a malformed shadow value must not
            # turn that established response into a new failure mode.
            await self._record_fallback_task(admission)

    async def _record_fallback_task(self, admission: ResearchTaskAdmission) -> None:
        """Keep a minimal task identity when the additive shadow view fails."""

        try:
            task = _legacy_task_snapshot(admission, now=_safe_now(self._clock))
            async with self._state_lock:
                self._tasks.setdefault(admission.task_id, task)
        except Exception:
            # A malformed admission is already outside the legacy port's
            # contract; never mask the original legacy response with shadow
            # bookkeeping errors.
            pass

    async def _record_admission(self, admission: ResearchTaskAdmission, *, query: str) -> None:
        now = _safe_now(self._clock)
        plan = _legacy_plan(admission, query=query)
        event_id = f"{admission.task_id}:{admission.turn_id}:accepted"
        projection = TaskProgressProjection(
            task_id=admission.task_id,
            session_id=admission.session_id,
            turn_id=str(admission.turn_id),
            status=TaskStatus.RUNNING,
            current_step_id=_LEGACY_STEPS[0][0],
            last_event_id=event_id,
            updated_at=now,
        )
        task = ResearchTask(
            task_id=admission.task_id,
            request_id=f"legacy:{admission.task_id}:turn:{admission.turn_id}",
            operation=admission.operation,
            domain="food",
            status=TaskStatus.RUNNING,
            turn_id=str(admission.turn_id),
            plan_id=plan.plan_id,
            progress_projection=projection,
            created_at=now,
            updated_at=now,
        )
        event = TaskEvent(
            event_id=event_id,
            task_id=admission.task_id,
            event_type="task.accepted",
            occurred_at=now,
            turn_id=str(admission.turn_id),
            status=TaskStatus.RUNNING,
            progress=0.0,
            step_id=_LEGACY_STEPS[0][0],
        )
        async with self._state_lock:
            self._tasks[admission.task_id] = task
            self._remember_plan(plan)
            self._events.setdefault(admission.task_id, []).append(event)
        await self._projection_store.put(projection)

    async def _sync_legacy_projection(
        self,
        task_id: str,
        payload: ContractPayload,
        *,
        expected_turn_id: str | None = None,
    ) -> None:
        current = await self._projection_store.get(task_id)
        if current is None:
            return
        if expected_turn_id is not None and current.turn_id != expected_turn_id:
            return
        status = _task_status(str(payload.get("status") or ""))
        if current.status.is_terminal:
            return
        if _PROJECTION_STATUS_RANK[status] < _PROJECTION_STATUS_RANK[current.status]:
            return
        completed, current_step = _step_projection(payload, status)
        progress = len(completed) / len(_LEGACY_STEPS)
        if status is current.status and progress < current.progress:
            completed = current.completed_step_ids
            current_step = current.current_step_id
            progress = current.progress
        payload_event_id = payload.get("lastEventId") or payload.get("last_event_id")
        last_event_id = (
            str(payload_event_id)
            if isinstance(payload_event_id, str) and payload_event_id
            else current.last_event_id
        )
        updated = current.model_copy(
            update={
                "status": status,
                "progress": progress,
                "current_step_id": current_step,
                "completed_step_ids": completed,
                "last_event_id": last_event_id,
                "updated_at": _safe_now(self._clock),
            }
        )
        effective = await self._projection_store.put(updated)
        async with self._state_lock:
            task = self._tasks.get(task_id)
            if task is not None:
                self._tasks[task_id] = task.model_copy(
                    update={
                        "status": effective.status,
                        "progress_projection": effective,
                        "updated_at": effective.updated_at,
                    }
                )

    async def _projection_turn_id(self, task_id: str) -> str | None:
        try:
            projection = await self._projection_store.get(task_id)
        except Exception:
            return None
        return projection.turn_id if projection is not None else None

    async def _record_schedule(self, result: ScheduleResult) -> None:
        now = _safe_now(self._clock)
        completed_ids = tuple(
            step.step_id for step in result.plan.steps if step.status is PlanStepStatus.COMPLETED
        )
        progress_ids = completed_ids + tuple(
            step.step_id for step in result.plan.steps if step.status is PlanStepStatus.SKIPPED
        )
        status = {
            PlanStatus.COMPLETED: TaskStatus.COMPLETED,
            PlanStatus.FAILED: TaskStatus.FAILED,
            PlanStatus.CANCELLED: TaskStatus.CANCELLED,
        }.get(result.plan.status, TaskStatus.RUNNING)
        current = await self._projection_store.get(result.plan.task_id)
        progress = (
            len(progress_ids) / len(result.plan.steps)
            if result.plan.steps
            else (1.0 if status is TaskStatus.COMPLETED else 0.0)
        )
        projection = TaskProgressProjection(
            task_id=result.plan.task_id,
            session_id=current.session_id if current else None,
            turn_id=current.turn_id if current else None,
            status=status,
            progress=progress,
            current_step_id=None,
            completed_step_ids=completed_ids,
            last_event_id=current.last_event_id if current else None,
            updated_at=now,
        )
        effective = await self._projection_store.put(projection)
        accepted = effective == projection
        async with self._state_lock:
            if accepted:
                self._remember_plan(result.plan)
            task = self._tasks.get(result.plan.task_id)
            if task is not None and accepted:
                self._tasks[result.plan.task_id] = task.model_copy(
                    update={
                        "status": status,
                        "progress_projection": effective,
                        "updated_at": now,
                        "terminal_error": result.error,
                    }
                )

    def _remember_plan(self, plan: ResearchPlan) -> None:
        """Update task and plan-id indexes atomically under ``_state_lock``."""

        previous = self._plans.get(plan.task_id)
        if previous is not None and previous.plan_id != plan.plan_id:
            self._plans_by_id.pop(previous.plan_id, None)
        self._plans[plan.task_id] = plan
        self._plans_by_id[plan.plan_id] = plan


def _legacy_task_snapshot(
    admission: ResearchTaskAdmission,
    *,
    now: datetime,
) -> ResearchTask:
    """Build the smallest valid task identity for a shadow-bookkeeping fallback."""

    return ResearchTask(
        task_id=admission.task_id,
        request_id=f"legacy:{admission.task_id}:turn:{admission.turn_id}",
        operation=admission.operation,
        domain="food",
        status=TaskStatus.RUNNING,
        turn_id=str(admission.turn_id),
        created_at=now,
        updated_at=now,
    )


def _safe_now(clock: Clock) -> datetime:
    try:
        value = clock()
    except Exception:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _legacy_plan(admission: ResearchTaskAdmission, *, query: str) -> ResearchPlan:
    steps = tuple(
        ResearchPlanStep(
            step_id=step_id,
            capability=capability,
            dependencies=(_LEGACY_STEPS[index - 1][0],) if index else (),
            status=PlanStepStatus.RUNNING if index == 0 else PlanStepStatus.PENDING,
        )
        for index, (step_id, capability) in enumerate(_LEGACY_STEPS)
    )
    return ResearchPlan(
        plan_id=f"legacy:{admission.task_id}:turn:{admission.turn_id}",
        task_id=admission.task_id,
        # Legacy routes historically accepted whitespace-only queries.  The
        # shadow plan needs a valid non-empty goal without changing admission.
        goal=query.strip() or "legacy research",
        status=PlanStatus.RUNNING,
        steps=steps,
        budget=PlanBudget(max_steps=len(steps), max_tool_calls=0),
        contract_versions={
            "task_policy": "legacy/v1",
            "wire_mapper": "legacy-sse/v1",
        },
    )


def _unwrap_payload(payload: ContractPayload) -> ContractPayload:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _task_status(value: str) -> TaskStatus:
    normalized = value.casefold()
    if normalized in {"completed", "complete", "done", "success"}:
        return TaskStatus.COMPLETED
    if normalized in {"error", "failed", "failure"}:
        return TaskStatus.FAILED
    if normalized in {"cancelled", "canceled"}:
        return TaskStatus.CANCELLED
    if normalized in {"loading", "running", "planning"}:
        return TaskStatus.RUNNING
    return TaskStatus.CREATED


def _step_projection(
    payload: ContractPayload,
    status: TaskStatus,
) -> tuple[tuple[str, ...], str | None]:
    raw_steps = payload.get("loadingSteps") or payload.get("steps")
    if not isinstance(raw_steps, list):
        if status is TaskStatus.COMPLETED:
            return tuple(step_id for step_id, _ in _LEGACY_STEPS), None
        return (), _LEGACY_STEPS[0][0] if status is TaskStatus.RUNNING else None

    completed: list[str] = []
    current: str | None = None
    for index, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("id") or _LEGACY_STEPS[min(index, len(_LEGACY_STEPS) - 1)][0])
        step_status = str(item.get("status") or "").casefold()
        if step_status in {"completed", "complete", "done", "success"}:
            completed.append(step_id)
        elif step_status in {"loading", "running", "active"} and current is None:
            current = step_id
    if status is TaskStatus.COMPLETED:
        completed = [step_id for step_id, _ in _LEGACY_STEPS]
        current = None
    return tuple(completed), current


assert isinstance(DisabledReliableResearchPolicy(), ReliableResearchPolicy)


__all__ = [
    "DisabledReliableResearchPolicy",
    "ReliableResearchPolicy",
    "ResearchCoordinator",
]
