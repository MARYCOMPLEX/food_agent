"""Domain-neutral research request, plan, task, and event contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import ContractModel, ContractPayload, NonEmptyStr, Timestamp, VersionedContract
from .errors import ContractError


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
    dependencies: tuple[str, ...] = ()
    status: PlanStepStatus = PlanStepStatus.PENDING
    inputs: ContractPayload = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()


class ResearchPlan(VersionedContract):
    plan_id: NonEmptyStr
    task_id: NonEmptyStr
    goal: NonEmptyStr
    status: PlanStatus = PlanStatus.DRAFT
    steps: tuple[ResearchPlanStep, ...] = ()
    budget: PlanBudget = Field(default_factory=PlanBudget)
    evidence_refs: tuple[str, ...] = ()
    contract_versions: dict[str, str] = Field(default_factory=dict)


class TaskProgressProjection(VersionedContract):
    """Query-only business projection; it can never be an execution checkpoint."""

    task_id: NonEmptyStr
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
    "PlanBudget",
    "PlanStatus",
    "PlanStepStatus",
    "RequestIdentity",
    "RequestPolicy",
    "ResearchOperation",
    "ResearchPlan",
    "ResearchPlanStep",
    "ResearchRequest",
    "ResearchTask",
    "TaskEvent",
    "TaskProgressProjection",
    "TaskStatus",
]
