"""Typed state models used by the agent loop.

These models are the contract between a planner, the executor and the API
layer.  They intentionally contain no provider-specific objects or asyncio
tasks, so a plan can be persisted and resumed by another worker.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LoopPhase(str, Enum):
    OBSERVE = "observe"
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    REPLAN = "replan"
    COMPLETE = "complete"
    FAILED = "failed"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Evidence(BaseModel):
    """A traceable piece of information used to produce an answer."""

    model_config = ConfigDict(extra="allow")

    source_id: str
    source: str = "unknown"
    title: str = ""
    content: str = ""
    url: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def source_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_id must not be blank")
        return value


class PlanStep(BaseModel):
    """One capability invocation in a typed DAG."""

    model_config = ConfigDict(extra="allow")

    id: str
    capability: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""
    output_key: str | None = None
    status: PlanStepStatus = PlanStepStatus.PENDING
    attempts: int = 0
    max_attempts: int = Field(default=2, ge=1, le=10)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    idempotent: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None

    @field_validator("id", "capability")
    @classmethod
    def names_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("plan step names must not be blank")
        return value


class Plan(BaseModel):
    """A resumable plan DAG.

    A model may propose a plan, but only this model's validation and the
    capability gateway can make it executable.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dag(self) -> Plan:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step ids must be unique")
        known = set(ids)
        for step in self.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(
                    f"step {step.id!r} depends on unknown steps: {sorted(missing)}"
                )
            if step.id in step.depends_on:
                raise ValueError(f"step {step.id!r} cannot depend on itself")
        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        edges = {step.id: set(step.depends_on) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("plan contains a dependency cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in edges[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in edges:
            visit(node)

    @property
    def completed(self) -> bool:
        return bool(self.steps) and all(
            step.status in {PlanStepStatus.SUCCEEDED, PlanStepStatus.SKIPPED}
            for step in self.steps
        )

    @property
    def failed(self) -> bool:
        return any(step.status == PlanStepStatus.FAILED for step in self.steps)

    def ready_steps(self) -> list[PlanStep]:
        """Return independent pending steps whose dependencies succeeded."""
        completed = {
            step.id
            for step in self.steps
            if step.status in {PlanStepStatus.SUCCEEDED, PlanStepStatus.SKIPPED}
        }
        return [
            step
            for step in self.steps
            if step.status == PlanStepStatus.PENDING
            and set(step.depends_on).issubset(completed)
        ]

    def blocked_steps(self) -> list[PlanStep]:
        """Pending steps blocked by a failed dependency."""
        failed = {step.id for step in self.steps if step.status == PlanStepStatus.FAILED}
        return [
            step
            for step in self.steps
            if step.status == PlanStepStatus.PENDING
            and bool(set(step.depends_on) & failed)
        ]

    def step(self, step_id: str) -> PlanStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def replace_pending(self, replacement: Plan) -> Plan:
        """Merge a replan without allowing completed work to be mutated."""
        # Successful/skipped work is immutable.  Failed work is intentionally
        # replaceable so a replan can choose a different capability or retry
        # with corrected arguments.
        completed = {
            step.id: step
            for step in self.steps
            if step.status in {PlanStepStatus.SUCCEEDED, PlanStepStatus.SKIPPED}
        }
        for step_id, step in completed.items():
            if not any(candidate.id == step_id for candidate in replacement.steps):
                replacement.steps.append(step)
            else:
                candidate = replacement.step(step_id)
                if candidate.status == PlanStepStatus.PENDING:
                    replacement.steps[replacement.steps.index(candidate)] = step
        replacement.revision = self.revision + 1
        replacement._assert_acyclic()
        return replacement


class StepExecution(BaseModel):
    """Immutable-ish execution record emitted for observability and replay."""

    model_config = ConfigDict(extra="allow")

    step_id: str
    capability: str
    success: bool
    attempts: int = 0
    output: Any = None
    error: str | None = None
    idempotency_key: str = ""
    started_at: float = Field(default_factory=time.time)
    finished_at: float = Field(default_factory=time.time)


class AgentRunContext(BaseModel):
    """Serializable context passed to every planner and capability."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    run_id: str
    session_id: str
    turn_id: int = Field(default=1, ge=1)
    user_input: str
    conversation: list[dict[str, str]] = Field(default_factory=list)
    working_memory: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    iteration: int = 0
    replan_count: int = 0
    started_at: float = Field(default_factory=time.time)
    deadline_at: float | None = None
    total_cost: float = 0.0

    def remaining_seconds(self) -> float | None:
        if self.deadline_at is None:
            return None
        return max(0.0, self.deadline_at - time.time())


class AgentRunResult(BaseModel):
    """Final result of a loop run, suitable for API/event serialization."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    session_id: str
    turn_id: int
    status: str
    phase: LoopPhase
    answer: Any = None
    plan: Plan | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    executions: list[StepExecution] = Field(default_factory=list)
    iterations: int = 0
    stopped_reason: str | None = None
