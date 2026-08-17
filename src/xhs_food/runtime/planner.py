"""Planner contracts and a deterministic planner implementation."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any, Protocol

from .models import AgentRunContext, Plan, PlanStep


class Planner(Protocol):
    async def plan(
        self,
        context: AgentRunContext,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        """Create an initial plan for the current user turn."""
        ...

    async def replan(
        self,
        context: AgentRunContext,
        previous: Plan,
        reason: str,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        """Return a replacement plan while preserving completed work."""
        ...


PlanBuilder = Callable[[AgentRunContext, Sequence[Any]], Plan | Awaitable[Plan]]
ReplanBuilder = Callable[
    [AgentRunContext, Plan, str, Sequence[Any]], Plan | Awaitable[Plan]
]


class RuleBasedPlanner:
    """Small adapter for deterministic plans and application skill packs.

    Production model planners can implement :class:`Planner` directly.  This
    adapter is useful for fixed workflows, tests and a safe fallback when the
    model provider is unavailable.
    """

    def __init__(
        self,
        builder: PlanBuilder,
        replan_builder: ReplanBuilder | None = None,
    ) -> None:
        self._builder = builder
        self._replan_builder = replan_builder

    async def plan(
        self,
        context: AgentRunContext,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        result = self._builder(context, capabilities)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Plan):
            raise TypeError("planner builder must return a Plan")
        return result

    async def replan(
        self,
        context: AgentRunContext,
        previous: Plan,
        reason: str,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        if self._replan_builder is None:
            return await self.plan(context, capabilities)
        result = self._replan_builder(context, previous, reason, capabilities)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Plan):
            raise TypeError("replan builder must return a Plan")
        return result


def sequential_plan(
    *,
    plan_id: str,
    goal: str,
    capabilities: Iterable[tuple[str, str, dict[str, Any]]],
) -> Plan:
    """Build a simple sequential plan for a Skill Pack.

    ``capabilities`` contains ``(step_id, capability_name, args)`` tuples.
    This helper keeps fixed workflows declarative without coupling them to the
    Agent Loop implementation.
    """

    steps: list[PlanStep] = []
    previous: str | None = None
    for step_id, capability_name, args in capabilities:
        steps.append(
            PlanStep(
                id=step_id,
                capability=capability_name,
                args=dict(args),
                depends_on=[previous] if previous else [],
            )
        )
        previous = step_id
    return Plan(id=plan_id, goal=goal, steps=steps)
