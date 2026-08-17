"""Review contracts for deciding whether an agent loop should stop."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .models import AgentRunContext, Evidence, Plan


class ReviewDecision(BaseModel):
    done: bool = False
    replan: bool = False
    answer: Any = None
    reason: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class Reviewer(Protocol):
    async def review(
        self,
        context: AgentRunContext,
        plan: Plan,
        report: Any,
    ) -> ReviewDecision:
        """Assess execution quality and return a stop/replan decision."""
        ...


AnswerBuilder = Callable[[AgentRunContext, Plan, Any], Any | Awaitable[Any]]


class RuleBasedReviewer:
    """Deterministic review policy used by the search runtime fallback."""

    def __init__(self, answer_builder: AnswerBuilder | None = None) -> None:
        self._answer_builder = answer_builder

    async def review(
        self,
        context: AgentRunContext,
        plan: Plan,
        report: Any,
    ) -> ReviewDecision:
        if getattr(report, "failed", False):
            return ReviewDecision(
                done=False,
                replan=True,
                reason="one or more capability steps failed",
            )

        pending = [step for step in plan.steps if step.status.value == "pending"]
        if pending:
            return ReviewDecision(
                done=False,
                replan=not bool(plan.ready_steps()),
                reason="plan still has pending steps",
            )

        answer: Any = None
        if self._answer_builder is not None:
            answer = self._answer_builder(context, plan, report)
            if inspect.isawaitable(answer):
                answer = await answer
        elif plan.steps:
            answer = plan.steps[-1].result
        else:
            answer = context.working_memory.get("answer")
        return ReviewDecision(done=True, answer=answer, reason="plan completed")
