"""Observe → plan → execute → review → replan supervisor."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .executor import ExecutionReport, PlanExecutor
from .models import AgentRunContext, AgentRunResult, Evidence, LoopPhase, Plan
from .planner import Planner
from .reviewer import Reviewer


@dataclass(frozen=True)
class AgentLoopConfig:
    max_iterations: int = 8
    max_replans: int = 3
    max_total_seconds: float = 180.0
    max_steps: int = 64


EventSink = Callable[[str, dict[str, Any]], Any]


class AgentLoop:
    """Application-agnostic agent loop.

    The loop never creates arbitrary tasks on behalf of a model.  All
    concurrency is delegated to :class:`PlanExecutor`, and all external
    effects go through the configured invoker/capability gateway.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        executor: PlanExecutor,
        reviewer: Reviewer,
        config: AgentLoopConfig | None = None,
        memory: Any = None,
        capabilities: Sequence[Any] = (),
        event_sink: EventSink | None = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._reviewer = reviewer
        self._config = config or AgentLoopConfig()
        self._memory = memory
        self._capabilities = tuple(capabilities)
        self._event_sink = event_sink

    async def run(
        self,
        context: AgentRunContext,
        initial_plan: Plan | None = None,
    ) -> AgentRunResult:
        if context.deadline_at is None:
            context.deadline_at = time.time() + self._config.max_total_seconds
        plan = initial_plan
        executions = []
        evidence: list[Evidence] = []
        outputs: dict[str, Any] = {}
        answer: Any = None
        last_reason = ""

        await self._emit(LoopPhase.OBSERVE, {"run_id": context.run_id})
        await self._observe(context)

        try:
            for iteration in range(1, self._config.max_iterations + 1):
                context.iteration = iteration
                if self._deadline_exceeded(context):
                    return self._failure(context, plan, executions, outputs, evidence, "budget exceeded")

                if plan is None:
                    await self._emit(LoopPhase.PLAN, {"iteration": iteration})
                    plan = await self._planner.plan(context, self._capabilities)
                    self._check_plan_size(plan)
                    await self._emit(
                        LoopPhase.PLAN,
                        {"plan_id": plan.id, "revision": plan.revision, "steps": len(plan.steps)},
                    )

                if plan.completed or not plan.steps:
                    decision = await self._reviewer.review(context, plan, ExecutionReport())
                else:
                    await self._emit(
                        LoopPhase.EXECUTE,
                        {"plan_id": plan.id, "iteration": iteration},
                    )
                    report = await self._executor.execute(plan, context)
                    executions.extend(report.executions)
                    outputs.update(report.outputs)
                    await self._emit(
                        LoopPhase.REVIEW,
                        {
                            "plan_id": plan.id,
                            "failed": report.failed,
                            "blocked": report.blocked,
                        },
                    )
                    decision = await self._reviewer.review(context, plan, report)

                last_reason = decision.reason
                answer = decision.answer if decision.answer is not None else answer
                evidence.extend(decision.evidence)
                if decision.done:
                    await self._emit(LoopPhase.COMPLETE, {"reason": decision.reason})
                    result = AgentRunResult(
                        run_id=context.run_id,
                        session_id=context.session_id,
                        turn_id=context.turn_id,
                        status="completed",
                        phase=LoopPhase.COMPLETE,
                        answer=answer,
                        plan=plan,
                        outputs=outputs,
                        evidence=evidence,
                        executions=executions,
                        iterations=iteration,
                        stopped_reason=decision.reason,
                    )
                    await self._commit_memory(context, result)
                    return result

                if not decision.replan:
                    return self._failure(
                        context, plan, executions, outputs, evidence, decision.reason or "review rejected"
                    )
                if context.replan_count >= self._config.max_replans:
                    return self._failure(
                        context, plan, executions, outputs, evidence, "maximum replans exceeded"
                    )

                context.replan_count += 1
                await self._emit(
                    LoopPhase.REPLAN,
                    {"reason": decision.reason, "replan_count": context.replan_count},
                )
                replacement = await self._planner.replan(
                    context,
                    plan,
                    decision.reason,
                    self._capabilities,
                )
                self._check_plan_size(replacement)
                plan = plan.replace_pending(replacement)

            return self._failure(
                context, plan, executions, outputs, evidence, last_reason or "maximum iterations exceeded"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - runtime boundary
            return self._failure(context, plan, executions, outputs, evidence, str(exc))

    async def _observe(self, context: AgentRunContext) -> None:
        if self._memory is None:
            return
        try:
            if hasattr(self._memory, "recall"):
                records = self._memory.recall(context.user_input, context.session_id)
            elif hasattr(self._memory, "search"):
                records = self._memory.search(context.user_input, session_id=context.session_id)
            else:
                return
            if inspect.isawaitable(records):
                records = await records
            context.working_memory["memory"] = records or []
        except Exception as exc:  # noqa: BLE001 - memory is best effort
            context.metadata.setdefault("warnings", []).append(f"memory recall failed: {exc}")

    async def _commit_memory(self, context: AgentRunContext, result: AgentRunResult) -> None:
        if self._memory is None or not hasattr(self._memory, "commit_turn"):
            return
        try:
            value = self._memory.commit_turn(context, result)
            if inspect.isawaitable(value):
                await value
        except Exception as exc:  # noqa: BLE001 - persistence must not hide result
            context.metadata.setdefault("warnings", []).append(f"memory commit failed: {exc}")

    async def _emit(self, phase: LoopPhase, data: dict[str, Any]) -> None:
        if self._event_sink is None:
            return
        value = self._event_sink(phase.value, data)
        if inspect.isawaitable(value):
            await value

    def _check_plan_size(self, plan: Plan) -> None:
        if len(plan.steps) > self._config.max_steps:
            raise ValueError(f"plan has {len(plan.steps)} steps; limit is {self._config.max_steps}")

    @staticmethod
    def _deadline_exceeded(context: AgentRunContext) -> bool:
        remaining = context.remaining_seconds()
        return remaining is not None and remaining <= 0

    @staticmethod
    def _failure(
        context: AgentRunContext,
        plan: Plan | None,
        executions: list,
        outputs: dict[str, Any],
        evidence: list[Evidence],
        reason: str,
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=context.run_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            status="failed",
            phase=LoopPhase.FAILED,
            plan=plan,
            outputs=outputs,
            evidence=evidence,
            executions=executions,
            iterations=context.iteration,
            stopped_reason=reason,
        )


def new_context(
    *,
    session_id: str,
    user_input: str,
    turn_id: int = 1,
    conversation: list[dict[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentRunContext:
    """Create a context with a stable run id for API adapters."""

    return AgentRunContext(
        run_id=str(uuid.uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        user_input=user_input,
        conversation=conversation or [],
        metadata=metadata or {},
    )
