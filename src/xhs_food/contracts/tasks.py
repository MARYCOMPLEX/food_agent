"""Domain-neutral research request, plan, task, and event contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from .base import (
    ContractModel,
    ContractPayload,
    NonEmptyStr,
    SchemaVersion,
    Timestamp,
    VersionedContract,
)
from .errors import ContractError

RESEARCH_PLAN_SCHEMA_VERSION = "research-plan/v1"
"""Current named wire schema for :class:`ResearchPlan`.

``VersionedContract`` originally exposed the generic ``"1.0"`` value for
plans.  That value remains accepted below so a plan persisted by the S1
contracts can still be read during the migration.  Newly-created plans use
the named version, which makes the DAG rules explicit to a consumer.
"""

# ``"1.0"`` is the S1 generic version and remains a read-compatible value.
ResearchPlanSchemaVersion = Literal[
    "research-plan/v1",
    "1.0",
]


class ResearchOperation(StrEnum):
    QUERY = "query"
    REFINE = "refine"
    REFRESH = "refresh"
    RECOVER = "recover"


class TaskStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


_STEP_TERMINAL_STATUSES = frozenset(
    {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.FAILED,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.CANCELLED,
    }
)
_STEP_REQUIRES_COMPLETED_DEPENDENCIES = frozenset(
    {
        PlanStepStatus.READY,
        PlanStepStatus.RUNNING,
        PlanStepStatus.COMPLETED,
        PlanStepStatus.FAILED,
    }
)
_STEP_REQUIRES_TERMINAL_DEPENDENCIES = frozenset(
    {
        PlanStepStatus.SKIPPED,
        PlanStepStatus.CANCELLED,
    }
)


class RequestIdentity(ContractModel):
    """Opaque identity context kept separate from public query semantics."""

    subject_ref: str | None = None
    session_ref: str | None = None
    tenant_ref: str | None = None
    authorization_refs: tuple[str, ...] = ()


class RequestPolicy(ContractModel):
    """Versioned policy inputs interpreted by the owning use case."""

    policy_version: NonEmptyStr
    compatibility_version: NonEmptyStr
    options: ContractPayload = Field(default_factory=dict)


class ResearchRequest(VersionedContract):
    """Command envelope for query, refine, refresh, and recovery operations."""

    request_id: NonEmptyStr
    operation: ResearchOperation
    domain: NonEmptyStr
    query: str | None = None
    target_task_id: str | None = None
    query_family_id: str | None = None
    last_event_id: str | None = None
    public_inputs: ContractPayload = Field(default_factory=dict)
    identity: RequestIdentity
    policy: RequestPolicy


class PlanBudget(ContractModel):
    """Optional hard ceilings; unset dimensions are not silently invented."""

    max_steps: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_cost_units: int | None = Field(default=None, ge=0)
    deadline_at: Timestamp | None = None


class ResearchPlanStep(ContractModel):
    step_id: NonEmptyStr
    capability: NonEmptyStr
    # These two collections remain structurally loose at the child boundary so
    # a persisted S1 ``schema_version=1.0`` plan can still be decoded.  The
    # named ``research-plan/v1`` parent schema applies the stricter DAG rules.
    dependencies: tuple[str, ...] = ()
    status: PlanStepStatus = PlanStepStatus.PENDING
    inputs: ContractPayload = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    budget: PlanBudget | None = None


class ResearchPlan(VersionedContract):
    # Accept the original generic version while making the named plan schema
    # the default for all newly-created values.
    schema_version: ResearchPlanSchemaVersion = RESEARCH_PLAN_SCHEMA_VERSION
    plan_id: NonEmptyStr
    task_id: NonEmptyStr
    goal: NonEmptyStr
    status: PlanStatus = PlanStatus.DRAFT
    steps: tuple[ResearchPlanStep, ...] = ()
    budget: PlanBudget = Field(default_factory=PlanBudget)
    evidence_refs: tuple[str, ...] = ()
    contract_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("schema_version", mode="before")
    @classmethod
    def normalize_legacy_schema_version(cls, value: object) -> object:
        if isinstance(value, SchemaVersion):
            return str(value)
        return value

    @model_validator(mode="after")
    def validate_typed_dag(self) -> Self:
        """Validate all cross-step invariants at the contract boundary.

        The plan is immutable, so validating the complete graph once at
        construction prevents schedulers and adapters from having subtly
        different interpretations of dependencies or evidence ownership.
        """

        # S1 emitted the generic ``1.0`` schema and intentionally had no DAG
        # invariants.  Keep that payload readable while the named schema owns
        # the stricter validation below.
        if self.schema_version == "1.0":
            return self

        _reject_nonempty_values(self.evidence_refs, "plan evidence_refs")
        _reject_duplicate_values(self.evidence_refs, "plan evidence_refs")

        step_ids = tuple(step.step_id for step in self.steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        steps_by_id = {step.step_id: step for step in self.steps}

        if self.budget.max_steps is not None and len(self.steps) > self.budget.max_steps:
            raise ValueError(
                "plan contains more steps than budget.max_steps "
                f"({len(self.steps)} > {self.budget.max_steps})"
            )

        for step in self.steps:
            _reject_nonempty_values(step.dependencies, f"step {step.step_id!r} dependencies")
            _reject_duplicate_values(step.dependencies, f"step {step.step_id!r} dependencies")
            _reject_nonempty_values(step.evidence_refs, f"step {step.step_id!r} evidence_refs")
            _reject_duplicate_values(step.evidence_refs, f"step {step.step_id!r} evidence_refs")
            for dependency_id in step.dependencies:
                if dependency_id == step.step_id:
                    raise ValueError(f"step {step.step_id!r} cannot depend on itself")
                if dependency_id not in steps_by_id:
                    raise ValueError(
                        f"step {step.step_id!r} has unknown dependency {dependency_id!r}"
                    )

        _reject_dependency_cycles(steps_by_id)
        for key, value in self.contract_versions.items():
            if not key or not value:
                raise ValueError("contract_versions keys and values must be non-empty")
        self._validate_dependency_statuses(steps_by_id)
        self._validate_evidence_references()
        self._validate_plan_status()
        return self

    def _validate_dependency_statuses(
        self,
        steps_by_id: dict[str, ResearchPlanStep],
    ) -> None:
        for step in self.steps:
            if not step.dependencies:
                continue
            dependency_statuses = tuple(
                steps_by_id[dependency_id].status for dependency_id in step.dependencies
            )
            if step.status in _STEP_REQUIRES_COMPLETED_DEPENDENCIES:
                if any(status is not PlanStepStatus.COMPLETED for status in dependency_statuses):
                    raise ValueError(
                        f"step {step.step_id!r} with status {step.status.value!r} "
                        "requires all dependencies to be completed"
                    )
            elif step.status in _STEP_REQUIRES_TERMINAL_DEPENDENCIES and any(
                status not in _STEP_TERMINAL_STATUSES for status in dependency_statuses
            ):
                raise ValueError(
                    f"step {step.step_id!r} with status {step.status.value!r} "
                    "requires all dependencies to be terminal"
                )

    def _validate_evidence_references(self) -> None:
        step_evidence_refs: list[str] = []
        for step in self.steps:
            step_evidence_refs.extend(step.evidence_refs)

        if set(self.evidence_refs) != set(step_evidence_refs):
            raise ValueError(
                "plan evidence_refs must exactly match the union of step evidence_refs"
            )

    def _validate_plan_status(self) -> None:
        if not self.steps:
            return
        step_statuses = tuple(step.status for step in self.steps)
        if self.status is PlanStatus.COMPLETED and any(
            status not in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED}
            for status in step_statuses
        ):
            raise ValueError("a completed plan requires every step to be completed or skipped")
        if self.status in {PlanStatus.FAILED, PlanStatus.CANCELLED} and any(
            status not in _STEP_TERMINAL_STATUSES for status in step_statuses
        ):
            raise ValueError(f"a {self.status.value} plan requires every step to be terminal")
        if self.status is PlanStatus.FAILED and PlanStepStatus.FAILED not in step_statuses:
            raise ValueError("a failed plan requires at least one failed step")
        if self.status is PlanStatus.CANCELLED and PlanStepStatus.CANCELLED not in step_statuses:
            raise ValueError("a cancelled plan requires at least one cancelled step")

    def ready_step_ids(self) -> tuple[str, ...]:
        """Return pending/ready steps whose dependencies have completed."""
        completed = {step.step_id for step in self.steps if step.status is PlanStepStatus.COMPLETED}
        return tuple(
            step.step_id
            for step in self.steps
            if step.status in {PlanStepStatus.PENDING, PlanStepStatus.READY}
            and set(step.dependencies).issubset(completed)
        )

    def step(self, step_id: str) -> ResearchPlanStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(f"unknown research plan step: {step_id}")


def _reject_duplicate_values(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


def _reject_nonempty_values(values: tuple[str, ...], field_name: str) -> None:
    if any(not value for value in values):
        raise ValueError(f"{field_name} must contain non-empty values")


def _reject_dependency_cycles(steps_by_id: dict[str, ResearchPlanStep]) -> None:
    """Reject cycles without depending on Python's recursion limit."""

    remaining_dependencies = {
        step_id: len(step.dependencies) for step_id, step in steps_by_id.items()
    }
    dependents: dict[str, list[str]] = {step_id: [] for step_id in steps_by_id}
    for step_id, step in steps_by_id.items():
        for dependency_id in step.dependencies:
            dependents[dependency_id].append(step_id)

    ready = [
        step_id
        for step_id, dependency_count in remaining_dependencies.items()
        if dependency_count == 0
    ]
    visited_count = 0
    while ready:
        step_id = ready.pop()
        visited_count += 1
        for dependent_id in dependents[step_id]:
            remaining_dependencies[dependent_id] -= 1
            if remaining_dependencies[dependent_id] == 0:
                ready.append(dependent_id)

    if visited_count != len(steps_by_id):
        cyclic_ids = sorted(
            step_id
            for step_id, dependency_count in remaining_dependencies.items()
            if dependency_count > 0
        )
        raise ValueError(f"dependency cycle detected among steps {cyclic_ids!r}")


class TaskProgressProjection(VersionedContract):
    """Query-only business projection; it can never be an execution checkpoint."""

    task_id: NonEmptyStr
    session_id: str | None = None
    turn_id: str | None = None
    status: TaskStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    current_step_id: str | None = None
    completed_step_ids: tuple[str, ...] = ()
    last_event_id: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    updated_at: Timestamp
    projection_kind: Literal["business_query_only"] = "business_query_only"
    executable_checkpoint: Literal[False] = False


class RecoverView(VersionedContract):
    """Read-only recovery view; it is never an executable checkpoint."""

    task_id: NonEmptyStr
    session_id: str | None = None
    turn_id: str | None = None
    last_event_id: str | None = None
    projection: TaskProgressProjection | None = None
    payload: ContractPayload = Field(default_factory=dict)
    replay: Literal["available", "expired", "not_found"] = "available"
    executable_checkpoint: Literal[False] = False


class ResearchTask(VersionedContract):
    task_id: NonEmptyStr
    request_id: NonEmptyStr
    operation: ResearchOperation
    domain: NonEmptyStr
    status: TaskStatus = TaskStatus.CREATED
    turn_id: str | None = None
    plan_id: str | None = None
    query_family_id: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    progress_projection: TaskProgressProjection | None = None
    terminal_error: ContractError | None = None
    created_at: Timestamp
    updated_at: Timestamp


class ResultCommitReceipt(VersionedContract):
    """Durable result/cancellation receipt returned by the task authority."""

    task_id: NonEmptyStr
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    committed: bool
    already_committed: bool = False
    result_version: str | None = None
    terminal_status: TaskStatus | None = None


class TaskEvent(VersionedContract):
    """Internal event envelope mapped to external SSE only at the boundary."""

    event_id: NonEmptyStr
    task_id: NonEmptyStr
    event_type: NonEmptyStr
    occurred_at: Timestamp
    turn_id: str | None = None
    status: TaskStatus | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    step_id: str | None = None
    error: ContractError | None = None
    payload: ContractPayload = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return bool(self.status and self.status.is_terminal)


__all__ = [
    "RESEARCH_PLAN_SCHEMA_VERSION",
    "PlanBudget",
    "PlanStatus",
    "PlanStepStatus",
    "RequestIdentity",
    "RequestPolicy",
    "ResearchOperation",
    "ResearchPlan",
    "ResearchPlanSchemaVersion",
    "ResearchPlanStep",
    "ResearchRequest",
    "ResearchTask",
    "ResultCommitReceipt",
    "RecoverView",
    "TaskEvent",
    "TaskProgressProjection",
    "TaskStatus",
]
