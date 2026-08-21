"""Deterministic typed-DAG scheduler for shared research plans."""

from __future__ import annotations

import asyncio
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


class StepScheduler:
    def __init__(self, tool_gateway: ToolGateway) -> None:
        self._tool_gateway = tool_gateway

    async def execute(self, plan: ResearchPlan) -> ScheduleResult:
        preflight_error = _execution_preflight_error(plan)
        if preflight_error is not None:
            return ScheduleResult(plan=plan, error=preflight_error)
        current = plan.model_copy(update={"status": PlanStatus.RUNNING})
        completed: list[ScheduledStep] = []
        calls_used = 0
        cost_used = 0

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
                    error=terminal_error,
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
                    error=error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )

            step = ready[0]
            budget_error = _budget_error(current, step, calls_used, cost_used)
            if budget_error is not None:
                failed = _replace_step(current, step.step_id, PlanStepStatus.FAILED)
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(failed),
                    completed=tuple(completed),
                    error=budget_error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )

            running = _replace_step(current, step.step_id, PlanStepStatus.RUNNING)
            call = ToolCall(
                call_id=f"{plan.task_id}:{step.step_id}:{calls_used + 1}",
                tool_name=step.capability,
                arguments=step.inputs,
                task_id=plan.task_id,
                timeout_ms=_step_timeout(step),
            )
            calls_used += 1
            cost_used += _step_cost(step)
            timeout = _call_timeout_seconds(current, step)
            try:
                if timeout is None:
                    result = await self._tool_gateway.execute(call)
                else:
                    result = await asyncio.wait_for(
                        self._tool_gateway.execute(call), timeout=timeout
                    )
            except TimeoutError:
                current = _replace_step(running, step.step_id, PlanStepStatus.FAILED)
                error = _schedule_error(
                    "STEP_DEADLINE_EXCEEDED",
                    ErrorCategory.BUDGET_EXHAUSTED,
                    f"step {step.step_id!r} exceeded its execution deadline",
                )
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )
            except Exception as exc:
                current = _replace_step(running, step.step_id, PlanStepStatus.FAILED)
                error = _schedule_error(
                    "TOOL_GATEWAY_FAILURE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    str(exc),
                )
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )
            if _deadline_expired(current, step):
                current = _replace_step(running, step.step_id, PlanStepStatus.FAILED)
                error = _schedule_error(
                    "STEP_DEADLINE_EXCEEDED",
                    ErrorCategory.BUDGET_EXHAUSTED,
                    f"step {step.step_id!r} completed after its deadline",
                )
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )
            if not result.success:
                current = _replace_step(running, step.step_id, PlanStepStatus.FAILED)
                error = result.error or _schedule_error(
                    "TOOL_EXECUTION_FAILED",
                    ErrorCategory.INTERNAL,
                    f"tool {step.capability!r} failed without a ContractError",
                )
                return ScheduleResult(
                    plan=_terminalize_blocked_plan(current),
                    completed=tuple(completed),
                    error=error,
                    tool_calls_used=calls_used,
                    cost_units_used=cost_used,
                )

            current = _replace_step(running, step.step_id, PlanStepStatus.COMPLETED)
            completed.append(ScheduledStep(step_id=step.step_id, result=result))


def _ready_steps(plan: ResearchPlan) -> tuple[ResearchPlanStep, ...]:
    statuses = {step.step_id: step.status for step in plan.steps}
    return tuple(
        step
        for step in plan.steps
        if step.status in {PlanStepStatus.PENDING, PlanStepStatus.READY}
        and all(
            statuses[dependency] is PlanStepStatus.COMPLETED for dependency in step.dependencies
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
    return int(value) if isinstance(value, int) and value > 0 else None


def _step_cost(step: ResearchPlanStep) -> int:
    value = step.inputs.get("cost_units", 1)
    return value if isinstance(value, int) and value >= 0 else 1


def _schedule_error(
    code: str,
    category: ErrorCategory,
    message: str,
) -> ContractError:
    return ContractError(
        code=code,
        category=category,
        scope=ErrorScope.PLAN,
        message=message,
        terminal=True,
    )


__all__ = ["ScheduleResult", "ScheduledStep", "StepScheduler"]
