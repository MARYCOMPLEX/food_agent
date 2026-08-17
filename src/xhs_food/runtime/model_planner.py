"""Optional model-backed planner using typed Responses output."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .models import AgentRunContext, Plan
from .reviewer import ReviewDecision


class OpenAIPlanPlanner:
    """Generate and revise plans without exposing provider details."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def plan(self, context: AgentRunContext, capabilities: Sequence[Any] = ()) -> Plan:
        return await self._run(context, previous=None, reason="initial plan", capabilities=capabilities)

    async def replan(
        self,
        context: AgentRunContext,
        previous: Plan,
        reason: str,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        return await self._run(context, previous=previous, reason=reason, capabilities=capabilities)

    async def _run(
        self,
        context: AgentRunContext,
        *,
        previous: Plan | None,
        reason: str,
        capabilities: Sequence[Any],
    ) -> Plan:
        manifest_data = [
            capability.model_dump() if hasattr(capability, "model_dump") else capability
            for capability in capabilities
        ]
        prompt = json.dumps(
            {
                "goal": context.user_input,
                "conversation": context.conversation[-10:],
                "working_memory": context.working_memory,
                "capabilities": manifest_data,
                "previous_plan": previous.model_dump() if previous else None,
                "replan_reason": reason,
            },
            ensure_ascii=False,
            default=str,
        )
        instructions = (
            "你是后端任务规划器。只输出符合 Plan schema 的 DAG。"
            "只能使用 capabilities 中的名称；为每步填写 id、capability、args、"
            "depends_on、expected_output。不要创建 asyncio 任务，不要执行 HTTP/SQL。"
        )
        return await self._runtime.run_structured(
            name="food-agent-planner",
            instructions=instructions,
            input_text=prompt,
            output_type=Plan,
        )


class OpenAIReviewPlanner:
    """Typed reviewer adapter kept separate from the deterministic policy."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def review(self, context: AgentRunContext, plan: Plan, report: Any) -> ReviewDecision:
        prompt = json.dumps(
            {
                "goal": context.user_input,
                "plan": plan.model_dump(),
                "report": getattr(report, "__dict__", report),
            },
            ensure_ascii=False,
            default=str,
        )
        return await self._runtime.run_structured(
            name="food-agent-reviewer",
            instructions="判断任务是否完成。只输出 ReviewDecision schema。若证据不足，replan=true。",
            input_text=prompt,
            output_type=ReviewDecision,
        )
