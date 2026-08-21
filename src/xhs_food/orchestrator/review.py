"""Evidence review, replan, and stopping-condition shells for S5."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from xhs_food.contracts import ContractError, ContractModel, ContractPayload, ResearchPlan


class EvidenceReviewRequest(ContractModel):
    task_id: str
    plan_id: str
    evidence_refs: tuple[str, ...] = ()
    coverage: ContractPayload = Field(default_factory=dict)
    errors: tuple[ContractError, ...] = ()


class EvidenceReviewDecision(ContractModel):
    accepted: bool
    replan_required: bool = False
    accepted_evidence_refs: tuple[str, ...] = ()
    reason: str = ""


class ReplanRequest(ContractModel):
    task_id: str
    current_plan: ResearchPlan
    review: EvidenceReviewDecision


class StoppingContext(ContractModel):
    task_id: str
    plan: ResearchPlan
    completed_steps: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    cost_units_used: int = Field(default=0, ge=0)
    evidence_refs: tuple[str, ...] = ()


class StoppingDecision(ContractModel):
    stop: bool
    reason: str


@runtime_checkable
class EvidenceReviewPort(Protocol):
    async def review(self, request: EvidenceReviewRequest) -> EvidenceReviewDecision: ...


@runtime_checkable
class ReplanPort(Protocol):
    async def replan(self, request: ReplanRequest) -> ResearchPlan: ...


@runtime_checkable
class StoppingConditionPort(Protocol):
    async def evaluate(self, context: StoppingContext) -> StoppingDecision: ...


class EvidenceReviewShell:
    def __init__(
        self, reviewer: EvidenceReviewPort | None = None, *, enabled: bool = False
    ) -> None:
        self._reviewer = reviewer
        self._enabled = enabled

    async def review(self, request: EvidenceReviewRequest) -> EvidenceReviewDecision:
        if not self._enabled:
            return EvidenceReviewDecision(
                accepted=True,
                accepted_evidence_refs=request.evidence_refs,
                reason="legacy_delegate",
            )
        if self._reviewer is None:
            raise RuntimeError("Evidence Review is enabled without a reviewer")
        return await self._reviewer.review(request)


class ReplanShell:
    def __init__(self, replanner: ReplanPort | None = None, *, enabled: bool = False) -> None:
        self._replanner = replanner
        self._enabled = enabled

    async def replan(self, request: ReplanRequest) -> ResearchPlan:
        if not self._enabled or not request.review.replan_required:
            return request.current_plan
        if self._replanner is None:
            raise RuntimeError("replan is enabled without a replanner")
        return await self._replanner.replan(request)


class StoppingConditionShell:
    def __init__(
        self,
        evaluator: StoppingConditionPort | None = None,
        *,
        enabled: bool = False,
    ) -> None:
        self._evaluator = evaluator
        self._enabled = enabled

    async def evaluate(self, context: StoppingContext) -> StoppingDecision:
        if not self._enabled:
            return StoppingDecision(stop=False, reason="legacy_delegate")
        if self._evaluator is None:
            raise RuntimeError("stopping conditions are enabled without an evaluator")
        return await self._evaluator.evaluate(context)


__all__ = [
    "EvidenceReviewDecision",
    "EvidenceReviewPort",
    "EvidenceReviewRequest",
    "EvidenceReviewShell",
    "ReplanPort",
    "ReplanRequest",
    "ReplanShell",
    "StoppingConditionPort",
    "StoppingConditionShell",
    "StoppingContext",
    "StoppingDecision",
]
