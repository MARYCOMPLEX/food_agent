"""Deterministic typed-DAG scheduler for shared research plans."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import Field

from xhs_food.contracts import (
    ContractError,
    ContractModel,
    ErrorCategory,
    ErrorScope,
    PlanStatus,
    PlanStepStatus,
    ResearchPlan,
    ResearchPlanStep,
    ToolCall,
    ToolGateway,
    ToolResult,
)


class ScheduledStep(ContractModel):
    step_id: str
    result: ToolResult


class ScheduleResult(ContractModel):
    plan: ResearchPlan
    completed: tuple[ScheduledStep, ...] = ()
    error: ContractError | None = None
    tool_calls_used: int = Field(default=0, ge=0)
    cost_units_used: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class _StepExecution:
    step: ResearchPlanStep
    result: ToolResult | None = None
    error: ContractError | None = None


class StepScheduler:
    def __init__(
        self,
        tool_gateway: ToolGateway,
        *,
        max_concurrency: int = 1,
        concurrency: int | None = None,
    ) -> None:
        if (
            concurrency is not None
            and max_concurrency != 1
            and concurrency != max_concurrency
        ):
            raise ValueError("max_concurrency and concurrency must agree")
        configured_concurrency = concurrency if concurrency is not None else max_concurrency
        if configured_concurrency < 1:
            raise ValueError("scheduler max_concurrency must be at least one")
        self._tool_gateway = tool_gateway
        self._max_concurrency = configured_concurrency

    async def execute(self, plan: ResearchPlan) -> ScheduleResult:
        preflight_error = _execution_preflight_error(plan)
        if preflight_error is not None:
            return ScheduleResult(plan=plan, error=preflight_error)
        current = plan.model_copy(update={"status": PlanStatus.RUNNING})
        completed: list[ScheduledStep] = []
        calls_used = 0
        cost_used = 0
        first_failure: ContractError | None = None

        while True:
            pending = tuple(
                step
                for step in current.steps
                if step.status in {PlanStepStatus.PENDING, PlanStepStatus.READY}
            )
            if not pending:
                final_status, terminal_error = _terminal_state(current)
                return ScheduleResult(
                    plan=current.model_copy(update={"status": final_status}),
                    completed=tuple(completed),
                    error=first_failure or terminal_error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )

            ready = _ready_steps(current)
            if not ready:
                error = _schedule_error(
                    "PLAN_BLOCKED",
                    ErrorCategory.CONFLICT,
                    "no plan step can advance after a dependency failed or was cancelled",
                )
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=first_failure or error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )

            wave: list[ResearchPlanStep] = []
            wave_cost = 0
            budget_blocked: list[tuple[ResearchPlanStep, ContractError]] = []
            for candidate in ready:
                budget_error = _budget_error(
                    current,
                    candidate,
                    calls_used + len(wave),
                    cost_used + wave_cost,
                )
                if budget_error is not None:
                    budget_blocked.append((candidate, budget_error))
                    continue
                wave.append(candidate)
                wave_cost += _step_cost(candidate)
                if len(wave) >= self._max_concurrency:
                    break

            # A step-local budget failure must not starve unrelated ready
            # steps. Mark those steps failed and let the normal dependency
            # reduction skip only their descendants. Plan-wide deadline/call
            # exhaustion is terminal for the whole scheduler and is handled
            # after any runnable wave has completed.
            plan_budget_blocked = [
                (step, error)
                for step, error in budget_blocked
                if error.code in {"PLAN_DEADLINE_EXCEEDED", "PLAN_TOOL_BUDGET_EXHAUSTED"}
            ]
            if not wave:
                if plan_budget_blocked:
                    return ScheduleResult(
                        plan=_terminalize_blocked_plan(current),
                        completed=tuple(completed),
                        error=first_failure or plan_budget_blocked[0][1],
                        tool_calls_used=calls_used,
                        cost_units_used=cost_used,
                    )
                for step, error in budget_blocked:
                    current = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                    first_failure = first_failure or error
                if budget_blocked:
                    continue
                # Defensive guard: a ready set should always produce either a
                # runnable wave or an explicit budget failure.
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=first_failure,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )
            for step, error in budget_blocked:
                if error.code not in {"PLAN_DEADLINE_EXCEEDED", "PLAN_TOOL_BUDGET_EXHAUSTED"}:
                    current = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                    first_failure = first_failure or error

            running = _replace_steps(
                current,
                {
                    step.step_id: PlanStepStatus.RUNNING
                    for step in wave
                },
            )
            calls_used += len(wave)
            cost_used += wave_cost
            executions = await self._execute_wave(
                running,
                wave,
                call_offset=calls_used - len(wave),
            )

            first_error: ContractError | None = None
            for execution in executions:
                step = execution.step
                if execution.result is None:
                    current = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                    first_error = first_error or execution.error
                    continue
                result = execution.result
                if _deadline_expired(current, step):
                    current = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                    first_error = first_error or _schedule_error(
                        "STEP_DEADLINE_EXCEEDED",
                        ErrorCategory.BUDGET_EXHAUSTED,
                        f"step {step.step_id!r} completed after its deadline",
                    )
                    continue
                if not result.success:
                    current = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                    first_error = first_error or result.error or _schedule_error(
                        "TOOL_EXECUTION_FAILED",
                        ErrorCategory.INTERNAL,
                        f"tool {step.capability!r} failed without a ContractError",
                    )
                    continue
                current = _replace_step(current, step.step_id, PlanStepStatus.COMPLETED)
                completed.append(ScheduledStep(step_id=step.step_id, result=result))

            if first_error is not None:
                # A failed action only blocks its descendants. Continue with
                # independent roots so one provider failure does not starve
                # unrelated research work in the same plan.
                first_failure = first_failure or first_error

    async def _execute_wave(
        self,
        running_plan: ResearchPlan,
        steps: tuple[ResearchPlanStep, ...] | list[ResearchPlanStep],
        *,
        call_offset: int,
    ) -> tuple[_StepExecution, ...]:
        """Execute one ready wave with structured, sibling-isolated tasks."""

        step_numbers = {
            step.step_id: index + 1
            for index, step in enumerate(sorted(steps, key=lambda item: item.step_id))
        }

        async def execute_one(step: ResearchPlanStep) -> _StepExecution:
            call = ToolCall(
                call_id=(
                    f"{running_plan.task_id}:{step.step_id}:"
                    f"{call_offset + step_numbers[step.step_id]}"
                ),
                tool_name=step.capability,
                arguments=step.inputs,
                task_id=running_plan.task_id,
                timeout_ms=_step_timeout(step),
            )
            timeout = _call_timeout_seconds(running_plan, step)
            try:
                if timeout is None:
                    result = await self._tool_gateway.execute(call)
                else:
                    result = await asyncio.wait_for(
                        self._tool_gateway.execute(call), timeout=timeout
                    )
                if not isinstance(result, ToolResult):
                    result = ToolResult.model_validate(result)
                if result.call_id != call.call_id:
                    raise ValueError(
                        f"tool result call_id {result.call_id!r} does not match "
                        f"request {call.call_id!r}"
                    )
                return _StepExecution(step=step, result=result)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                return _StepExecution(
                    step=step,
                    error=_schedule_error(
                        "STEP_DEADLINE_EXCEEDED",
                        ErrorCategory.BUDGET_EXHAUSTED,
                        f"step {step.step_id!r} exceeded its execution deadline",
                        scope=ErrorScope.TOOL,
                    ),
                )
            except Exception as exc:
                return _StepExecution(
                    step=step,
                    error=_schedule_error(
                        "TOOL_GATEWAY_FAILURE",
                        ErrorCategory.DEPENDENCY_UNAVAILABLE,
                        str(exc),
                        scope=ErrorScope.TOOL,
                    ),
                )

        results: dict[str, _StepExecution] = {}
        async with asyncio.TaskGroup() as group:
            tasks = {
                step.step_id: group.create_task(execute_one(step))
                for step in steps
            }
        for step_id, task in tasks.items():
            results[step_id] = task.result()
        return tuple(results[step.step_id] for step in sorted(steps, key=lambda item: item.step_id))


def _ready_steps(plan: ResearchPlan) -> tuple[ResearchPlanStep, ...]:
    statuses = {step.step_id: step.status for step in plan.steps}
    return tuple(
        step
        for step in plan.steps
        if step.status in {PlanStepStatus.PENDING, PlanStepStatus.READY}
        and all(
            statuses.get(dependency) is PlanStepStatus.COMPLETED
            for dependency in step.dependencies
        )
    )


def _replace_step(
    plan: ResearchPlan,
    step_id: str,
    status: PlanStepStatus,
) -> ResearchPlan:
    steps = tuple(
        step.model_copy(update={"status": status}) if step.step_id == step_id else step
        for step in plan.steps
    )
    return ResearchPlan.model_validate(plan.model_copy(update={"steps": steps}).model_dump())


def _replace_steps(
    plan: ResearchPlan,
    statuses: dict[str, PlanStepStatus],
) -> ResearchPlan:
    """Update one ready wave atomically so DAG validation sees valid inputs."""

    steps = tuple(
        step.model_copy(update={"status": statuses[step.step_id]})
        if step.step_id in statuses
        else step
        for step in plan.steps
    )
    return ResearchPlan.model_validate(plan.model_copy(update={"steps": steps}).model_dump())


def _terminalize_blocked_plan(plan: ResearchPlan) -> ResearchPlan:
    has_failure = any(step.status is PlanStepStatus.FAILED for step in plan.steps)
    has_cancellation = any(step.status is PlanStepStatus.CANCELLED for step in plan.steps)
    marked_failure = has_failure
    updated_steps: list[ResearchPlanStep] = []
    for step in plan.steps:
        if step.status in {
            PlanStepStatus.PENDING,
            PlanStepStatus.READY,
            PlanStepStatus.RUNNING,
        }:
            if not marked_failure and not has_cancellation and not step.dependencies:
                updated_steps.append(step.model_copy(update={"status": PlanStepStatus.FAILED}))
                marked_failure = True
            else:
                updated_steps.append(step.model_copy(update={"status": PlanStepStatus.SKIPPED}))
        else:
            updated_steps.append(step)
    if not marked_failure and not has_cancellation:
        # A dependency-free root is the only valid synthetic failure.  A DAG
        # always has one; choosing it keeps the FAILED dependency invariant
        # valid for every skipped descendant.
        for index, step in enumerate(updated_steps):
            if step.status is PlanStepStatus.SKIPPED and not step.dependencies:
                updated_steps[index] = step.model_copy(update={"status": PlanStepStatus.FAILED})
                marked_failure = True
                break
    terminal_status = PlanStatus.FAILED if marked_failure else PlanStatus.CANCELLED
    return ResearchPlan.model_validate(
        plan.model_copy(
            update={"status": terminal_status, "steps": tuple(updated_steps)}
        ).model_dump()
    )


def _budget_error(
    plan: ResearchPlan,
    step: ResearchPlanStep,
    calls_used: int,
    cost_used: int,
) -> ContractError | None:
    step_budget = step.budget
    if step_budget is not None:
        if step_budget.max_steps is not None and step_budget.max_steps < 1:
            return _schedule_error(
                "STEP_BUDGET_EXHAUSTED",
                ErrorCategory.BUDGET_EXHAUSTED,
                "step budget permits no execution step",
            )
        if step_budget.deadline_at is not None and datetime.now(UTC) >= step_budget.deadline_at:
            return _schedule_error(
                "STEP_DEADLINE_EXCEEDED",
                ErrorCategory.BUDGET_EXHAUSTED,
                "step deadline has elapsed",
            )
        if step_budget.max_tool_calls is not None and step_budget.max_tool_calls < 1:
            return _schedule_error(
                "STEP_TOOL_BUDGET_EXHAUSTED",
                ErrorCategory.BUDGET_EXHAUSTED,
                "step tool-call budget permits no call",
            )
        if step_budget.max_cost_units is not None and _step_cost(step) > step_budget.max_cost_units:
            return _schedule_error(
                "STEP_COST_BUDGET_EXHAUSTED",
                ErrorCategory.BUDGET_EXHAUSTED,
                "step cost-unit budget exhausted",
            )
    if plan.budget.deadline_at is not None and datetime.now(UTC) >= plan.budget.deadline_at:
        return _schedule_error(
            "PLAN_DEADLINE_EXCEEDED",
            ErrorCategory.BUDGET_EXHAUSTED,
            "plan deadline has elapsed",
        )
    if plan.budget.max_tool_calls is not None and calls_used >= plan.budget.max_tool_calls:
        return _schedule_error(
            "PLAN_TOOL_BUDGET_EXHAUSTED",
            ErrorCategory.BUDGET_EXHAUSTED,
            "plan tool-call budget exhausted",
        )
    cost = _step_cost(step)
    if plan.budget.max_cost_units is not None and cost_used + cost > plan.budget.max_cost_units:
        return _schedule_error(
            "PLAN_COST_BUDGET_EXHAUSTED",
            ErrorCategory.BUDGET_EXHAUSTED,
            "plan cost-unit budget exhausted",
        )
    return None


def _execution_preflight_error(plan: ResearchPlan) -> ContractError | None:
    if plan.status in {PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED}:
        return _schedule_error(
            "PLAN_ALREADY_TERMINAL",
            ErrorCategory.CONFLICT,
            f"plan is already {plan.status.value}",
        )
    if any(step.status is PlanStepStatus.RUNNING for step in plan.steps):
        return _schedule_error(
            "PLAN_STEP_ALREADY_RUNNING",
            ErrorCategory.CONFLICT,
            "plan contains a step already running",
        )
    step_ids = tuple(step.step_id for step in plan.steps)
    if len(step_ids) != len(set(step_ids)):
        return _schedule_error(
            "PLAN_INVALID_GRAPH",
            ErrorCategory.VALIDATION,
            "plan contains duplicate step ids",
        )
    known_ids = set(step_ids)
    for step in plan.steps:
        unknown = set(step.dependencies) - known_ids
        if unknown:
            return _schedule_error(
                "PLAN_INVALID_GRAPH",
                ErrorCategory.VALIDATION,
                f"step {step.step_id!r} has unknown dependencies: {sorted(unknown)!r}",
            )
    remaining = {step.step_id: len(step.dependencies) for step in plan.steps}
    dependents: dict[str, list[str]] = {step.step_id: [] for step in plan.steps}
    for step in plan.steps:
        for dependency in step.dependencies:
            dependents[dependency].append(step.step_id)
    ready = [step_id for step_id, count in remaining.items() if count == 0]
    visited = 0
    while ready:
        step_id = ready.pop()
        visited += 1
        for dependent in dependents[step_id]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    if visited != len(plan.steps):
        return _schedule_error(
            "PLAN_INVALID_GRAPH",
            ErrorCategory.CONFLICT,
            "plan contains a dependency cycle",
        )
    return None


def _terminal_state(plan: ResearchPlan) -> tuple[PlanStatus, ContractError | None]:
    if any(step.status is PlanStepStatus.FAILED for step in plan.steps):
        return (
            PlanStatus.FAILED,
            _schedule_error(
                "PLAN_FAILED",
                ErrorCategory.CONFLICT,
                "plan contains a failed step",
            ),
        )
    if any(step.status is PlanStepStatus.CANCELLED for step in plan.steps):
        return (PlanStatus.CANCELLED, None)
    return (PlanStatus.COMPLETED, None)


def _deadline_expired(plan: ResearchPlan, step: ResearchPlanStep) -> bool:
    now = datetime.now(UTC)
    return bool(
        (step.budget and step.budget.deadline_at and now >= step.budget.deadline_at)
        or (plan.budget.deadline_at and now >= plan.budget.deadline_at)
    )


def _call_timeout_seconds(plan: ResearchPlan, step: ResearchPlanStep) -> float | None:
    deadlines: list[float] = []
    now = datetime.now(UTC)
    if plan.budget.deadline_at is not None:
        deadlines.append((plan.budget.deadline_at - now).total_seconds())
    if step.budget is not None and step.budget.deadline_at is not None:
        deadlines.append((step.budget.deadline_at - now).total_seconds())
    timeout_ms = _step_timeout(step)
    if timeout_ms is not None:
        deadlines.append(timeout_ms / 1000)
    if not deadlines:
        return None
    return max(min(deadlines), 0.0)


def _step_timeout(step: ResearchPlanStep) -> int | None:
    value = step.inputs.get("timeout_ms")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _step_cost(step: ResearchPlanStep) -> int:
    value = step.inputs.get("cost_units", 1)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 1


def _schedule_error(
    code: str,
    category: ErrorCategory,
    message: str,
    *,
    scope: ErrorScope = ErrorScope.PLAN,
) -> ContractError:
    return ContractError(
        code=code,
        category=category,
        scope=scope,
        message=message,
        terminal=True,
    )


__all__ = ["ScheduleResult", "ScheduledStep", "StepScheduler"]
