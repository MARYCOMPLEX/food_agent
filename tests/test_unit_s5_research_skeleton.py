"""S5 shared research skeleton contracts and legacy differential gates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from xhs_food.contracts import (
    AgentDependencies,
    AgentOutput,
    AgentRunRequest,
    AgentRunResult,
    AgentToolDefinition,
    ContractError,
    ErrorCategory,
    ErrorScope,
    PlanBudget,
    PlanStatus,
    PlanStepStatus,
    RecoverViewPort,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchPlan,
    ResearchPlanStep,
    ResearchRequest,
    ResearchTaskAdmission,
    TaskStatus,
    ToolResult,
)
from xhs_food.orchestrator.agent_runtime import (
    AgentBudgetExceededError,
    AgentOutputValidationError,
    AgentProviderError,
    AgentRuntimeDisabledError,
    AgentToolPolicyError,
    AgentToolValidationError,
    PydanticAIAgentRuntime,
    ScriptedAgentRuntime,
)
from xhs_food.orchestrator.coordinator import ResearchCoordinator
from xhs_food.orchestrator.projections import InMemoryTaskProgressProjectionStore
from xhs_food.orchestrator.review import (
    EvidenceReviewDecision,
    EvidenceReviewRequest,
    EvidenceReviewShell,
    ReplanRequest,
    ReplanShell,
    StoppingConditionShell,
    StoppingContext,
)
from xhs_food.orchestrator.scheduler import ScheduleResult, StepScheduler

NOW = datetime(2026, 8, 21, tzinfo=UTC)


class _Gateway:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.delay = delay

    async def execute(self, call):  # type: ignore[no-untyped-def]
        self.calls.append(call.tool_name)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=ContractError(
                    code="TOOL_FAILURE",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    scope=ErrorScope.TOOL,
                    retryable=True,
                ),
            )
        return ToolResult(call_id=call.call_id, success=True, output={"tool": call.tool_name})

    async def health(self, tool_name: str) -> bool:
        return True


class _CapturingAgentRuntime:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            request_id=request.request_id,
            output=AgentOutput(summary="captured", final_output={}),
        )


class _ReplanReviewer:
    async def review(self, request: EvidenceReviewRequest) -> EvidenceReviewDecision:
        return EvidenceReviewDecision(accepted=True, replan_required=True)


class _GoalReplanner:
    async def replan(self, request: ReplanRequest) -> ResearchPlan:
        return request.current_plan.model_copy(update={"goal": "replanned"})


class _LegacyPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.status_value = "loading"

    async def start_new(self, query: str) -> ResearchTaskAdmission:
        self.calls.append(("start_new", query))
        return ResearchTaskAdmission(
            task_id="session-1",
            session_id="session-1",
            operation=ResearchOperation.QUERY,
            stream_ref="/v1/search/stream/session-1",
            turn_id=1,
        )

    async def refine(self, session_id: str, query: str) -> ResearchTaskAdmission:
        self.calls.append(("refine", session_id, query))
        return ResearchTaskAdmission(
            task_id=session_id,
            session_id=session_id,
            operation=ResearchOperation.REFINE,
            stream_ref=f"/v1/search/stream/{session_id}",
            turn_id=2,
        )

    async def recover(self, session_id: str) -> dict:
        self.calls.append(("recover", session_id))
        return {"success": True, "data": {"sessionId": session_id, "status": self.status_value}}

    async def status(self, session_id: str) -> dict:
        self.calls.append(("status", session_id))
        return {"sessionId": session_id, "status": self.status_value, "loadingSteps": []}

    async def results(self, session_id: str) -> dict:
        self.calls.append(("results", session_id))
        return {"sessionId": session_id, "restaurants": []}


class _UniqueLegacyPort(_LegacyPort):
    def __init__(self) -> None:
        super().__init__()
        self.next_id = 0

    async def start_new(self, query: str) -> ResearchTaskAdmission:
        self.next_id += 1
        session_id = f"session-{self.next_id}"
        self.calls.append(("start_new", query))
        return ResearchTaskAdmission(
            task_id=session_id,
            session_id=session_id,
            operation=ResearchOperation.QUERY,
            stream_ref=f"/v1/search/stream/{session_id}",
            turn_id=1,
        )


class _FailingAgent:
    async def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("provider unavailable")


class _ValueErrorAgent:
    async def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("provider rejected request")


class _SlowAgent:
    async def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.1)
        return type("Result", (), {"output": AgentOutput(summary="late")})()


class _RacingLegacyPort(_LegacyPort):
    def __init__(self) -> None:
        super().__init__()
        self.first_status_started = asyncio.Event()
        self.release_first_status = asyncio.Event()
        self.status_calls = 0

    async def status(self, session_id: str) -> dict:
        self.status_calls += 1
        if self.status_calls == 1:
            self.first_status_started.set()
            await self.release_first_status.wait()
            value = "loading"
        else:
            value = "completed"
        return {"sessionId": session_id, "status": value, "loadingSteps": []}


def _plan() -> ResearchPlan:
    return ResearchPlan(
        plan_id="plan-1",
        task_id="task-1",
        goal="fixture",
        steps=(
            ResearchPlanStep(step_id="one", capability="tool.one"),
            ResearchPlanStep(
                step_id="two",
                capability="tool.two",
                dependencies=("one",),
            ),
        ),
    )


@pytest.mark.unit
async def test_scheduler_executes_typed_dag_only_through_gateway() -> None:
    gateway = _Gateway()
    result = await StepScheduler(gateway).execute(_plan())

    assert gateway.calls == ["tool.one", "tool.two"]
    assert result.error is None
    assert result.plan.status.value == "completed"
    assert [step.status.value for step in result.plan.steps] == ["completed", "completed"]


@pytest.mark.unit
async def test_scheduler_isolates_tool_failure_and_reports_stable_error() -> None:
    result = await StepScheduler(_Gateway(fail=True)).execute(_plan())

    assert result.plan.status.value == "failed"
    assert result.error is not None
    assert result.error.scope is ErrorScope.TOOL
    assert result.error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE


@pytest.mark.unit
async def test_scheduler_enforces_step_budget_and_terminal_inputs() -> None:
    gateway = _Gateway()
    budget_plan = ResearchPlan(
        plan_id="budget-plan",
        task_id="budget-task",
        goal="fixture",
        steps=(
            ResearchPlanStep(
                step_id="one",
                capability="tool.one",
                budget=PlanBudget(max_steps=0),
            ),
        ),
    )
    budget_result = await StepScheduler(gateway).execute(budget_plan)
    assert budget_result.error is not None
    assert budget_result.error.code == "STEP_BUDGET_EXHAUSTED"
    assert gateway.calls == []

    terminal_plan = ResearchPlan(
        plan_id="terminal-plan",
        task_id="terminal-task",
        goal="fixture",
        status=PlanStatus.CANCELLED,
        steps=(
            ResearchPlanStep(step_id="one", capability="tool.one", status=PlanStepStatus.CANCELLED),
        ),
    )
    terminal_result = await StepScheduler(gateway).execute(terminal_plan)
    assert terminal_result.plan.status is PlanStatus.CANCELLED
    assert terminal_result.error is not None
    assert terminal_result.error.code == "PLAN_ALREADY_TERMINAL"


@pytest.mark.unit
async def test_scheduler_blocks_cancelled_dependency_without_invalid_plan_state() -> None:
    plan = ResearchPlan(
        plan_id="blocked-plan",
        task_id="blocked-task",
        goal="fixture",
        steps=(
            ResearchPlanStep(
                step_id="cancelled", capability="tool.cancel", status=PlanStepStatus.CANCELLED
            ),
            ResearchPlanStep(
                step_id="dependent",
                capability="tool.dependent",
                dependencies=("cancelled",),
            ),
        ),
    )
    result = await StepScheduler(_Gateway()).execute(plan)
    assert result.error is not None
    assert result.error.code == "PLAN_BLOCKED"
    assert result.plan.status is PlanStatus.CANCELLED
    assert result.plan.steps[1].status is PlanStepStatus.SKIPPED


@pytest.mark.unit
async def test_scheduler_enforces_execution_deadline() -> None:
    plan = ResearchPlan(
        plan_id="deadline-plan",
        task_id="deadline-task",
        goal="fixture",
        budget=PlanBudget(deadline_at=datetime.now(UTC) + timedelta(milliseconds=15)),
        steps=(ResearchPlanStep(step_id="one", capability="tool.one"),),
    )
    result = await StepScheduler(_Gateway(delay=0.1)).execute(plan)
    assert result.error is not None
    assert result.error.code == "STEP_DEADLINE_EXCEEDED"
    assert result.plan.status is PlanStatus.FAILED


@pytest.mark.unit
async def test_coordinator_projection_counts_completed_steps_from_resumed_plan() -> None:
    plan = ResearchPlan(
        plan_id="resumed-plan",
        task_id="resumed-task",
        goal="fixture",
        steps=(
            ResearchPlanStep(
                step_id="one",
                capability="tool.one",
                status=PlanStepStatus.COMPLETED,
            ),
            ResearchPlanStep(
                step_id="two",
                capability="tool.two",
                dependencies=("one",),
            ),
        ),
    )
    result = await StepScheduler(_Gateway()).execute(plan)
    coordinator = ResearchCoordinator(_LegacyPort(), clock=lambda: NOW)

    await coordinator._record_schedule(  # noqa: SLF001 - projection regression fixture
        ScheduleResult(
            plan=result.plan,
            completed=result.completed,
            error=result.error,
        )
    )

    projection = await coordinator.progress("resumed-task")
    assert projection is not None
    assert projection.progress == 1.0
    assert projection.completed_step_ids == ("one", "two")


@pytest.mark.unit
async def test_projection_store_is_query_only_and_monotonic() -> None:
    store = InMemoryTaskProgressProjectionStore()
    from xhs_food.contracts import TaskProgressProjection

    projection = TaskProgressProjection(
        task_id="task-1",
        status=TaskStatus.RUNNING,
        updated_at=NOW,
    )
    await store.put(projection)
    assert await store.get("task-1") == projection
    with pytest.raises(ValueError, match="backwards"):
        await store.put(projection.model_copy(update={"updated_at": NOW.replace(day=20)}))
    with pytest.raises(ValidationError):
        TaskProgressProjection.model_validate(
            {**projection.model_dump(), "executable_checkpoint": True}
        )

    completed = projection.model_copy(update={"status": TaskStatus.COMPLETED, "progress": 1.0})
    assert await store.put(completed) == completed
    stale_terminal = completed.model_copy(update={"status": TaskStatus.FAILED, "progress": 0.0})
    assert await store.put(stale_terminal) == completed

    next_turn = completed.model_copy(
        update={"turn_id": "2", "status": TaskStatus.RUNNING, "progress": 0.0}
    )
    assert await store.put(next_turn) == next_turn
    assert await store.put(completed) == next_turn


@pytest.mark.unit
async def test_refine_starts_a_new_projection_turn_after_terminal_state() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)
    await coordinator.start_new("first")
    legacy.status_value = "completed"
    await coordinator.status("session-1")

    admission = await coordinator.refine("session-1", "second")
    projection = await coordinator.progress("session-1")

    assert admission.turn_id == 2
    assert projection is not None
    assert projection.turn_id == "2"
    assert projection.status is TaskStatus.RUNNING
    assert projection.progress == 0.0


@pytest.mark.unit
async def test_schedule_cannot_overwrite_completed_projection_with_failure() -> None:
    coordinator = ResearchCoordinator(_LegacyPort(), clock=lambda: NOW)
    admission = await coordinator.start_new("fixture")
    completed_plan = ResearchPlan(
        plan_id="completed-plan",
        task_id=admission.task_id,
        goal="fixture",
        status=PlanStatus.COMPLETED,
        steps=(
            ResearchPlanStep(
                step_id="one",
                capability="tool.one",
                status=PlanStepStatus.COMPLETED,
            ),
        ),
    )
    failed_plan = completed_plan.model_copy(
        update={
            "plan_id": "failed-plan",
            "status": PlanStatus.FAILED,
            "steps": (
                ResearchPlanStep(
                    step_id="one",
                    capability="tool.one",
                    status=PlanStepStatus.FAILED,
                ),
            ),
        }
    )
    await coordinator._record_schedule(  # noqa: SLF001 - projection regression fixture
        ScheduleResult(plan=completed_plan)
    )
    await coordinator._record_schedule(  # noqa: SLF001 - projection regression fixture
        ScheduleResult(
            plan=failed_plan,
            error=ContractError(
                code="FAILED",
                category=ErrorCategory.INTERNAL,
                scope=ErrorScope.PLAN,
            ),
        )
    )
    projection = await coordinator.progress(admission.task_id)
    assert projection is not None
    assert projection.status is TaskStatus.COMPLETED
    task = await coordinator.task(admission.task_id)
    assert task is not None and task.status is TaskStatus.COMPLETED
    stored_plan = await coordinator.plan(admission.task_id)
    assert stored_plan is not None and stored_plan.status is PlanStatus.COMPLETED


@pytest.mark.unit
async def test_coordinator_delegates_legacy_operations_and_records_projection() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)

    admission = await coordinator.start_new("自贡美食")
    assert admission.task_id == "session-1"
    task = await coordinator.task("session-1")
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert (await coordinator.plan("session-1")).steps[0].status.value == "running"  # type: ignore[union-attr]

    legacy.status_value = "completed"
    status = await coordinator.status("session-1")
    assert status == {
        "sessionId": "session-1",
        "status": "completed",
        "loadingSteps": [],
    }
    projection = await coordinator.progress("session-1")
    assert projection is not None
    assert projection.status is TaskStatus.COMPLETED
    assert len(projection.completed_step_ids) == 6
    assert projection.last_event_id == "session-1:1:accepted"


@pytest.mark.unit
async def test_coordinator_preserves_unique_legacy_duplicate_start_semantics() -> None:
    legacy = _UniqueLegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)

    first, second = await asyncio.gather(
        coordinator.start_new("same query"),
        coordinator.start_new("same query"),
    )

    assert first.task_id != second.task_id
    assert await coordinator.task(first.task_id) is not None
    assert await coordinator.task(second.task_id) is not None


@pytest.mark.unit
async def test_coordinator_projects_legacy_failure_terminal_without_changing_payload() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)
    await coordinator.start_new("fixture")
    legacy.status_value = "error"

    payload = await coordinator.status("session-1")
    projection = await coordinator.progress("session-1")
    task = await coordinator.task("session-1")

    assert payload == {"sessionId": "session-1", "status": "error", "loadingSteps": []}
    assert projection is not None and projection.status is TaskStatus.FAILED
    assert task is not None and task.status is TaskStatus.FAILED


@pytest.mark.unit
async def test_coordinator_keeps_legacy_admission_for_whitespace_query() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)

    admission = await coordinator.start_new("   ")

    assert admission.task_id == "session-1"
    assert (await coordinator.plan("session-1")).goal == "legacy research"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_projection_does_not_regress_after_terminal_status() -> None:
    legacy = _RacingLegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)
    await coordinator.start_new("fixture")

    stale_status = asyncio.create_task(coordinator.status("session-1"))
    await legacy.first_status_started.wait()
    await coordinator.status("session-1")
    legacy.release_first_status.set()
    await stale_status

    projection = await coordinator.progress("session-1")
    assert projection is not None
    assert projection.status is TaskStatus.COMPLETED
    assert projection.progress == 1.0


@pytest.mark.unit
async def test_agent_scope_uses_plan_id_index_and_rejects_cross_task_requests() -> None:
    legacy = _LegacyPort()
    runtime = _CapturingAgentRuntime()
    coordinator = ResearchCoordinator(
        legacy,
        agent_runtime=runtime,
        agent_runtime_enabled=True,
        clock=lambda: NOW,
    )
    admission = await coordinator.start_new("fixture")
    plan = await coordinator.plan(admission.task_id)
    assert plan is not None

    request = AgentRunRequest(
        request_id="agent-request",
        prompt="fixture",
        dependencies=AgentDependencies(
            task_id=admission.task_id,
            plan_id=plan.plan_id,
            domain="food",
        ),
        output_schema={"type": "object"},
    )
    await coordinator.run_agent(request)
    assert runtime.requests[0].dependencies.allowed_step_ids == plan.ready_step_ids()
    assert runtime.requests[0].dependencies.allowed_step_ids is not None
    assert runtime.requests[0].dependencies.allowed_evidence_refs == ()

    with pytest.raises(ValueError, match="task_id"):
        await coordinator.run_agent(
            request.model_copy(
                update={
                    "request_id": "cross-task",
                    "dependencies": request.dependencies.model_copy(update={"task_id": "other"}),
                }
            )
        )
    with pytest.raises(LookupError, match="unknown Agent plan"):
        await coordinator.run_agent(
            request.model_copy(
                update={
                    "request_id": "unknown-plan",
                    "dependencies": request.dependencies.model_copy(update={"plan_id": "missing"}),
                }
            )
        )


@pytest.mark.unit
async def test_submit_persists_request_identity_and_recover_view_event_cursor() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)
    request = ResearchRequest(
        request_id="client-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="fixture",
        identity=RequestIdentity(),
        policy=RequestPolicy(policy_version="test/v1", compatibility_version="legacy/v1"),
    )

    submitted = await coordinator.submit(request)
    stored = await coordinator.task("session-1")
    view = await coordinator.recover_view("session-1")

    assert submitted.request_id == "client-request"
    assert stored is not None and stored.request_id == "client-request"
    assert view.last_event_id == "session-1:1:accepted"


@pytest.mark.unit
async def test_submit_preserves_legacy_admission_when_shadow_bookkeeping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)

    async def fail_record(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("projection backend unavailable")

    monkeypatch.setattr(coordinator, "_record_admission", fail_record)
    request = ResearchRequest(
        request_id="client-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="fixture",
        identity=RequestIdentity(),
        policy=RequestPolicy(policy_version="test/v1", compatibility_version="legacy/v1"),
    )

    submitted = await coordinator.submit(request)

    assert submitted.task_id == "session-1"
    assert submitted.request_id == "client-request"
    stored = await coordinator.task("session-1")
    assert stored is not None and stored.request_id == "client-request"


@pytest.mark.unit
async def test_recover_view_preserves_session_turn_and_query_only_projection() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)
    await coordinator.start_new("自贡美食")

    view = await coordinator.recover_view("session-1")

    assert view.session_id == "session-1"
    assert view.turn_id == "1"
    assert view.executable_checkpoint is False
    assert view.projection is not None
    assert view.projection.executable_checkpoint is False
    assert view.payload["data"]["sessionId"] == "session-1"  # type: ignore[index]
    assert isinstance(coordinator, RecoverViewPort)


@pytest.mark.unit
async def test_coordinator_does_not_call_disabled_agent_or_scheduler() -> None:
    legacy = _LegacyPort()
    scripted = ScriptedAgentRuntime([])
    coordinator = ResearchCoordinator(legacy, agent_runtime=scripted)
    request = AgentRunRequest(
        request_id="request-1",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object"},
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await coordinator.run_agent(request)
    assert scripted.requests == []
    with pytest.raises(RuntimeError, match="disabled"):
        await coordinator.execute_plan(_plan())
    assert await coordinator.cancel("task-1") is False
    with pytest.raises(RuntimeError, match="disabled"):
        await coordinator.retry("task-1")


@pytest.mark.unit
async def test_legacy_policy_preserves_duplicate_concurrent_start_behavior() -> None:
    legacy = _LegacyPort()
    coordinator = ResearchCoordinator(legacy, clock=lambda: NOW)

    first, second = await asyncio.gather(
        coordinator.start_new("same query"),
        coordinator.start_new("same query"),
    )

    assert first == second
    assert legacy.calls == [
        ("start_new", "same query"),
        ("start_new", "same query"),
    ]
    assert len(await coordinator.events("session-1")) == 2


@pytest.mark.unit
async def test_scripted_runtime_validates_output_without_live_provider() -> None:
    output = AgentOutput(summary="ok", final_output={"ok": True})
    scripted = ScriptedAgentRuntime([AgentRunResult(request_id="request-1", output=output)])
    request = AgentRunRequest(
        request_id="request-1",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object", "required": ["ok"]},
    )
    result = await scripted.run(request)
    assert result.output.final_output == {"ok": True}


@pytest.mark.unit
async def test_pydantic_ai_adapter_disabled_path_is_stable() -> None:
    runtime = PydanticAIAgentRuntime(tool_gateway=_Gateway())
    request = AgentRunRequest(
        request_id="request-1",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object"},
    )
    with pytest.raises(AgentRuntimeDisabledError) as exc_info:
        await runtime.run(request)
    assert exc_info.value.error.code == "AGENT_RUNTIME_DISABLED"
    assert runtime.temporal_binding.enabled is False


@pytest.mark.unit
async def test_pydantic_ai_adapter_uses_structured_fake_output() -> None:
    runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        model=TestModel(
            call_tools=[],
            custom_output_args={"summary": "ok", "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-1",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object", "required": ["ok"]},
    )
    result = await runtime.run(request)
    assert result.output.final_output == {"ok": True}


@pytest.mark.unit
async def test_pydantic_ai_tool_calls_are_routed_through_gateway() -> None:
    gateway = _Gateway()
    runtime = PydanticAIAgentRuntime(
        tool_gateway=gateway,
        model=TestModel(
            call_tools=["gateway_execute"],
            custom_output_args={"summary": "ok", "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-1",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        tools=(
            AgentToolDefinition(
                name="a",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
        ),
        output_schema={"type": "object", "required": ["ok"]},
    )
    result = await runtime.run(request)
    assert result.tool_calls
    assert gateway.calls == ["a"]


@pytest.mark.unit
async def test_agent_budget_and_provider_failures_are_stable() -> None:
    gateway = _Gateway()
    zero_budget = AgentRunRequest(
        request_id="budget",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object"},
        budget=PlanBudget(max_steps=0),
    )
    runtime = PydanticAIAgentRuntime(tool_gateway=gateway, agent=_FailingAgent(), enabled=True)
    with pytest.raises(AgentBudgetExceededError) as budget_error:
        await runtime.run(zero_budget)
    assert budget_error.value.error.category is ErrorCategory.BUDGET_EXHAUSTED

    provider_request = zero_budget.model_copy(update={"budget": PlanBudget(max_steps=1)})
    with pytest.raises(AgentProviderError) as provider_error:
        await runtime.run(provider_request)
    assert provider_error.value.error.scope is ErrorScope.PROVIDER
    assert provider_error.value.error.retryable is True

    value_error_runtime = PydanticAIAgentRuntime(
        tool_gateway=gateway,
        agent=_ValueErrorAgent(),
        enabled=True,
    )
    with pytest.raises(AgentProviderError) as value_error:
        await value_error_runtime.run(provider_request)
    assert value_error.value.error.code == "AGENT_PROVIDER_FAILURE"


@pytest.mark.unit
async def test_agent_maps_provider_output_behavior_and_enforces_deadline() -> None:
    malformed_runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        model=TestModel(
            call_tools=[],
            custom_output_args={"summary": None, "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="malformed",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object"},
    )
    with pytest.raises(AgentOutputValidationError) as malformed_error:
        await malformed_runtime.run(request)
    assert malformed_error.value.error.code == "AGENT_OUTPUT_INVALID"

    deadline_request = request.model_copy(
        update={
            "request_id": "deadline",
            "budget": PlanBudget(deadline_at=datetime.now(UTC) + timedelta(milliseconds=10)),
        }
    )
    deadline_runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        agent=_SlowAgent(),
        enabled=True,
    )
    with pytest.raises(AgentBudgetExceededError) as deadline_error:
        await deadline_runtime.run(deadline_request)
    assert deadline_error.value.error.category is ErrorCategory.BUDGET_EXHAUSTED


@pytest.mark.unit
async def test_agent_preflights_duplicate_and_invalid_tool_schemas() -> None:
    duplicate_runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        model=TestModel(call_tools=[]),
        enabled=True,
    )
    base_request = AgentRunRequest(
        request_id="schema",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object"},
        tools=(
            AgentToolDefinition(name="a", input_schema={}, output_schema={}),
            AgentToolDefinition(name="a", input_schema={}, output_schema={}),
        ),
    )
    with pytest.raises(AgentToolPolicyError) as policy_error:
        await duplicate_runtime.run(base_request)
    assert policy_error.value.error.code == "TOOL_POLICY_DENIED"

    invalid_request = base_request.model_copy(
        update={
            "request_id": "invalid-schema",
            "tools": (
                AgentToolDefinition(
                    name="a",
                    input_schema={"type": "not-a-json-schema-type"},
                    output_schema={},
                ),
            ),
        }
    )
    with pytest.raises(AgentToolValidationError) as schema_error:
        await duplicate_runtime.run(invalid_request)
    assert schema_error.value.error.code == "TOOL_SCHEMA_INVALID"


@pytest.mark.unit
async def test_agent_rejects_malformed_tool_input_before_gateway() -> None:
    gateway = _Gateway()
    runtime = PydanticAIAgentRuntime(
        tool_gateway=gateway,
        model=TestModel(
            call_tools=["gateway_execute"],
            custom_output_args={"summary": "ok", "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-input",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        tools=(
            AgentToolDefinition(
                name="a",
                input_schema={"type": "object", "required": ["required"]},
                output_schema={"type": "object"},
            ),
        ),
        output_schema={"type": "object", "required": ["ok"]},
    )
    with pytest.raises(AgentToolValidationError) as exc_info:
        await runtime.run(request)
    assert exc_info.value.error.code == "TOOL_INPUT_INVALID"
    assert gateway.calls == []


@pytest.mark.unit
async def test_agent_rejects_malformed_tool_output_after_gateway() -> None:
    gateway = _Gateway()
    runtime = PydanticAIAgentRuntime(
        tool_gateway=gateway,
        model=TestModel(
            call_tools=["gateway_execute"],
            custom_output_args={"summary": "ok", "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-output",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        tools=(
            AgentToolDefinition(
                name="a",
                input_schema={"type": "object"},
                output_schema={"type": "string"},
            ),
        ),
        output_schema={"type": "object", "required": ["ok"]},
    )
    with pytest.raises(AgentToolValidationError) as exc_info:
        await runtime.run(request)
    assert exc_info.value.error.code == "TOOL_OUTPUT_INVALID"
    assert gateway.calls == ["a"]


@pytest.mark.unit
async def test_agent_rejects_malformed_final_output() -> None:
    runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        model=TestModel(
            call_tools=[],
            custom_output_args={"summary": "bad", "final_output": {}},
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-final",
        prompt="fixture",
        dependencies=AgentDependencies(task_id="task-1", plan_id="plan-1", domain="food"),
        output_schema={"type": "object", "required": ["ok"]},
    )
    with pytest.raises(AgentOutputValidationError) as exc_info:
        await runtime.run(request)
    assert exc_info.value.error.code == "AGENT_OUTPUT_INVALID"


@pytest.mark.unit
async def test_agent_rejects_output_steps_outside_declared_plan_scope() -> None:
    runtime = PydanticAIAgentRuntime(
        tool_gateway=_Gateway(),
        model=TestModel(
            call_tools=[],
            custom_output_args={
                "summary": "ok",
                "proposed_step_ids": ["unknown"],
                "final_output": {"ok": True},
            },
        ),
        enabled=True,
    )
    request = AgentRunRequest(
        request_id="request-plan-scope",
        prompt="fixture",
        dependencies=AgentDependencies(
            task_id="task-1",
            plan_id="plan-1",
            domain="food",
            allowed_step_ids=("allowed",),
        ),
        output_schema={"type": "object", "required": ["ok"]},
    )

    with pytest.raises(AgentOutputValidationError) as exc_info:
        await runtime.run(request)

    assert exc_info.value.error.code == "AGENT_PLAN_OUTPUT_INVALID"


@pytest.mark.unit
async def test_review_and_stopping_shells_preserve_legacy_when_disabled() -> None:
    review = await EvidenceReviewShell().review(
        EvidenceReviewRequest(task_id="task", plan_id="plan", evidence_refs=("e1",))
    )
    assert review.accepted is True
    assert review.reason == "legacy_delegate"
    stop = await StoppingConditionShell().evaluate(StoppingContext(task_id="task", plan=_plan()))
    assert stop.stop is False
    assert stop.reason == "legacy_delegate"
    assert (
        await ReplanShell().replan(
            ReplanRequest(task_id="task", current_plan=_plan(), review=review)
        )
        == _plan()
    )


@pytest.mark.unit
async def test_coordinator_publishes_replanned_plan_to_queries() -> None:
    coordinator = ResearchCoordinator(
        _LegacyPort(),
        evidence_review=EvidenceReviewShell(_ReplanReviewer(), enabled=True),
        replanner=ReplanShell(_GoalReplanner(), enabled=True),
        clock=lambda: NOW,
    )
    admission = await coordinator.start_new("fixture")
    current = await coordinator.plan(admission.task_id)
    assert current is not None

    _review, replanned = await coordinator.review_and_replan(
        EvidenceReviewRequest(
            task_id=admission.task_id,
            plan_id=current.plan_id,
        )
    )

    assert replanned.goal == "replanned"
    assert await coordinator.plan(admission.task_id) == replanned
