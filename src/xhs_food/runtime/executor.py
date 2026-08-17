"""Concurrent, policy-neutral execution of a typed Plan DAG."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from .models import AgentRunContext, Plan, PlanStep, PlanStepStatus, StepExecution

CapabilityInvoker = Callable[[str, Mapping[str, Any], AgentRunContext], Any | Awaitable[Any]]
EventSink = Callable[[str, dict[str, Any]], Any | Awaitable[Any]]


@dataclass
class ExecutionReport:
    executions: list[StepExecution] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    failed: bool = False
    blocked: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.failed and not self.blocked


class PlanExecutor:
    """Run ready DAG nodes concurrently while enforcing runtime limits.

    The model only describes dependencies.  This executor owns asyncio task
    creation, global/per-capability concurrency, retries, timeouts and
    idempotency keys.
    """

    def __init__(
        self,
        invoker: CapabilityInvoker,
        *,
        max_concurrency: int = 8,
        capability_concurrency: Mapping[str, int] | None = None,
        default_timeout_seconds: float = 60.0,
        event_sink: EventSink | None = None,
        idempotency_store: MutableMapping[str, Any] | None = None,
        capability_idempotency: Mapping[str, bool] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._invoker = invoker
        self._global = asyncio.Semaphore(max_concurrency)
        self._limits = {
            name: asyncio.Semaphore(max(1, limit))
            for name, limit in (capability_concurrency or {}).items()
        }
        self._default_timeout = default_timeout_seconds
        self._event_sink = event_sink
        self._idempotency = idempotency_store if idempotency_store is not None else {}
        self._capability_idempotency = dict(capability_idempotency or {})

    async def execute(self, plan: Plan, context: AgentRunContext) -> ExecutionReport:
        report = ExecutionReport()
        if not plan.steps:
            return report

        while True:
            ready = plan.ready_steps()
            if not ready:
                pending = [step for step in plan.steps if step.status == PlanStepStatus.PENDING]
                blocked = plan.blocked_steps()
                report.blocked.extend(step.id for step in blocked)
                if pending and not blocked:
                    report.blocked.extend(step.id for step in pending)
                report.failed = bool(report.blocked) or any(
                    step.status == PlanStepStatus.FAILED for step in plan.steps
                )
                return report

            for step in ready:
                step.status = PlanStepStatus.RUNNING
            results = await asyncio.gather(
                *(self._run_step(step, context) for step in ready),
                return_exceptions=False,
            )
            for step, execution in zip(ready, results, strict=True):
                report.executions.append(execution)
                if execution.success:
                    step.status = PlanStepStatus.SUCCEEDED
                    step.result = execution.output
                    step.error = None
                    report.outputs[step.output_key or step.id] = execution.output
                    context.working_memory[step.output_key or step.id] = execution.output
                else:
                    step.status = PlanStepStatus.FAILED
                    step.error = execution.error
                    report.failed = True
                await self._emit(
                    "step_finished",
                    {
                        "step_id": step.id,
                        "capability": step.capability,
                        "success": execution.success,
                        "attempts": execution.attempts,
                        "error": execution.error,
                    },
                )

            # Run all currently-ready independent steps in a batch; a failure
            # intentionally does not cancel unrelated read-only work.
            if report.failed:
                return report

    async def _run_step(self, step: PlanStep, context: AgentRunContext) -> StepExecution:
        start = time.time()
        # A run id changes when the same turn is resumed. Keep the key stable
        # across those retries so an already-completed idempotent step is not
        # sent to an external provider twice.
        key = f"{context.session_id}:{context.turn_id}:{step.id}"
        is_idempotent = step.idempotent and self._capability_idempotency.get(
            step.capability,
            True,
        )
        if is_idempotent and key in self._idempotency:
            output = self._idempotency[key]
            return StepExecution(
                step_id=step.id,
                capability=step.capability,
                success=True,
                output=output,
                idempotency_key=key,
                started_at=start,
                finished_at=time.time(),
            )

        args = self._resolve_args(step.args, context.working_memory)
        attempts = 0
        error: str | None = None
        output: Any = None
        while attempts < step.max_attempts:
            attempts += 1
            step.attempts = attempts
            try:
                async with self._global:
                    semaphore = self._limits.setdefault(
                        step.capability, asyncio.Semaphore(1_000_000)
                    )
                    async with semaphore:
                        timeout = step.timeout_seconds or self._default_timeout
                        remaining = context.remaining_seconds()
                        if remaining is not None:
                            if remaining <= 0:
                                timeout = 0.0
                                raise TimeoutError
                            timeout = min(timeout, remaining)
                        value = self._invoker(step.capability, args, context)
                        if inspect.isawaitable(value):
                            output = await asyncio.wait_for(value, timeout=timeout)
                        else:
                            output = value
                if is_idempotent:
                    self._idempotency[key] = output
                return StepExecution(
                    step_id=step.id,
                    capability=step.capability,
                    success=True,
                    attempts=attempts,
                    output=output,
                    idempotency_key=key,
                    started_at=start,
                    finished_at=time.time(),
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                error = f"capability timed out after {timeout:.3f}s"
                if attempts < step.max_attempts:
                    await asyncio.sleep(min(0.05 * (2 ** (attempts - 1)), 1.0))
            except (PermissionError, ValueError) as exc:
                error = str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - capability boundary
                error = str(exc)
                if attempts < step.max_attempts:
                    await asyncio.sleep(min(0.05 * (2 ** (attempts - 1)), 1.0))

        return StepExecution(
            step_id=step.id,
            capability=step.capability,
            success=False,
            attempts=attempts,
            error=error or "capability execution failed",
            idempotency_key=key,
            started_at=start,
            finished_at=time.time(),
        )

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._event_sink is None:
            return
        value = self._event_sink(event, data)
        if inspect.isawaitable(value):
            await value

    @staticmethod
    def _resolve_args(value: Any, memory: Mapping[str, Any]) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return memory.get(str(value["$ref"]))
            return {key: PlanExecutor._resolve_args(item, memory) for key, item in value.items()}
        if isinstance(value, list):
            return [PlanExecutor._resolve_args(item, memory) for item in value]
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return memory.get(value[2:-1], value)
        return value
