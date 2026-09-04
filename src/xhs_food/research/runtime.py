"""Structured-concurrency executor for semantic research actions.

``ResearchRuntime`` is intentionally a small in-process executor.  It owns
action admission, resource limits, lifecycle events, and state reduction; the
injected action handler owns provider/source translation.  No action handler
is an Agent and no handler receives a raw provider tool catalog.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator

from xhs_food.contracts import (
    AnalyzeCommentBatch,
    ContractModel,
    EnrichShopProfile,
    ExpandResearch,
    FetchNoteEvidence,
    ResearchAction,
    ResearchActionResult,
    ResearchEvent,
    ResearchEventType,
    ResearchGap,
    ResearchState,
    ResourceClass,
    SearchNotes,
    SemanticAction,
    SourceEnvelope,
    StopResearch,
    Synthesize,
    initial_research_state,
    parse_semantic_action,
    reduce_research_event,
)

from .resource_limits import (
    BoundedAsyncQueue,
    BudgetController,
    BudgetExceededError,
    BudgetUsage,
    ResourceCallTimeoutError,
    ResourceCircuitOpenError,
    ResourcePool,
    ResourcePoolConfig,
    ResourcePoolSet,
    RuntimeBudget,
)

logger = logging.getLogger(__name__)


class ActionHandler(Protocol):
    async def __call__(self, action: SemanticAction) -> ResearchActionResult | Any: ...


class RuntimeEventSink(Protocol):
    async def __call__(self, event: ResearchEvent) -> None: ...


class RuntimeResourceInvoker:
    """Public resource boundary exposed to composite semantic actions.

    A semantic action may coordinate several provider calls (for example a
    note detail request and an ordered comments cursor).  Such an action must
    not hold a provider semaphore while it invokes its children.  It instead
    uses this invoker so every physical call receives the correct resource
    pool, call budget, deadline, retry, and circuit-breaker policy.
    """

    def __init__(self, runtime: ResearchRuntime) -> None:
        self._runtime = runtime

    async def execute(
        self,
        resource_class: ResourceClass | str,
        operation: Callable[..., Awaitable[Any]] | Awaitable[Any],
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self._runtime.invoke_resource(
            resource_class,
            operation,
            *args,
            timeout=timeout,
            **kwargs,
        )

    call = execute


class ResearchRuntimeConfig(ContractModel):
    """Immutable runtime policy; provider capabilities are pinned per run."""

    queue_size: int = Field(default=8, ge=1)
    max_parallel_actions: int = Field(default=16, ge=1)
    max_replans: int = Field(default=0, ge=0)
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    capability_allow_list: tuple[str, ...] | None = None
    resource_pools: dict[str, ResourcePoolConfig] = Field(default_factory=dict)

    @field_validator("capability_allow_list")
    @classmethod
    def validate_capability_allow_list(
        cls, values: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if values is None:
            return None
        if any(not value for value in values):
            raise ValueError("capability allow-list values must be non-empty")
        if len(values) != len(set(values)):
            raise ValueError("capability allow-list values must be unique")
        return values


ResearchRuntimeConfig.model_rebuild()


RuntimeConfig = ResearchRuntimeConfig


class RuntimePolicyError(ValueError):
    """Raised for invalid semantic action policy before provider dispatch."""


@dataclass(frozen=True, slots=True)
class ActionExecution:
    action: SemanticAction
    result: ResearchActionResult | None = None
    gap: ResearchGap | None = None


class ResearchRuntime:
    """Execute a semantic action DAG with bounded structured concurrency."""

    def __init__(
        self,
        action_handler: ActionHandler | Callable[[SemanticAction], Awaitable[Any]] | Any = None,
        *,
        config: ResearchRuntimeConfig | None = None,
        resource_pools: ResourcePoolSet
        | Mapping[str | ResourceClass, ResourcePool[Any] | ResourcePoolConfig]
        | None = None,
        budget: Any | None = None,
        capabilities: Iterable[str] | None = None,
        capability_allow_list: Iterable[str] | None = None,
        event_sink: RuntimeEventSink | Callable[[ResearchEvent], Awaitable[None]] | None = None,
        initial_state: ResearchState | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._handler = action_handler
        self._budget_spec = budget
        self.config = config or ResearchRuntimeConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._pools = self._build_pools(
            resource_pools if resource_pools is not None else self.config.resource_pools,
            default_max_concurrency=self.config.max_parallel_actions,
        )
        self._budget = self._new_budget(initial_state)
        configured_caps = (
            tuple(capabilities)
            if capabilities is not None
            else self.config.capability_allow_list
        )
        explicit_caps = tuple(capability_allow_list) if capability_allow_list is not None else None
        if configured_caps is not None and explicit_caps is not None:
            configured_caps = tuple(sorted(set(configured_caps) & set(explicit_caps)))
        elif explicit_caps is not None:
            configured_caps = explicit_caps
        self._capabilities = None if configured_caps is None else frozenset(configured_caps)
        self._event_sink = event_sink
        self._state = initial_state
        self._events: list[ResearchEvent] = list(initial_state.events) if initial_state else []
        self._sequence = initial_state.sequence if initial_state is not None else 0
        self._event_lock = asyncio.Lock()
        self._sink_tail: asyncio.Future[None] | None = None
        self._global_semaphore = asyncio.Semaphore(self.config.max_parallel_actions)
        self._work_queue = BoundedAsyncQueue(self.config.queue_size)
        self._dispatch_lock = asyncio.Lock()
        self._dispatch_tasks: dict[str, asyncio.Task[ActionExecution]] = {}
        self._dispatch_results: dict[str, ActionExecution] = {}
        self._dispatch_actions: dict[str, SemanticAction] = {}
        self._finish_task: asyncio.Task[ResearchState] | None = None
        self._run_active = False
        self._run_started = initial_state is not None
        self._finishing = False
        self._finished = False
        self._cancel_requested = False
        self._closed = False
        self._progress_counts: dict[str, int] = {}
        self._action_started_at: dict[str, float] = {}

    def _new_budget(self, state: ResearchState | None = None) -> BudgetController:
        """Create a controller anchored to this run's persisted usage."""

        return BudgetController(
            self._budget_spec if self._budget_spec is not None else self.config.budget,
            wall_clock=self._clock,
            initial_usage=self._budget_usage_from_state(state) if state is not None else None,
        )

    @staticmethod
    def _budget_usage_from_state(state: ResearchState) -> BudgetUsage:
        """Recover the greatest observed usage from a replayable state."""

        snapshots: list[BudgetUsage] = []
        for event in state.events:
            if not event.budget_usage:
                continue
            try:
                snapshots.append(BudgetUsage.model_validate(event.budget_usage))
            except Exception:  # noqa: BLE001 - old snapshots may omit fields
                continue
        if snapshots:
            usage = BudgetUsage(
                actions=max(item.actions for item in snapshots),
                calls=max(item.calls for item in snapshots),
                tokens=max(item.tokens for item in snapshots),
                elapsed_seconds=max(item.elapsed_seconds for item in snapshots),
            )
        else:
            usage = BudgetUsage(
                actions=len(
                    set(state.completed_action_ids)
                    | set(state.failed_action_ids)
                    | set(state.in_flight_action_ids)
                ),
                tokens=state.tokens_used,
            )
        # Result tokens are authoritative even when an older event snapshot
        # was emitted before token reconciliation.
        return usage.model_copy(update={"tokens": max(usage.tokens, state.tokens_used)})

    @staticmethod
    def _build_pools(
        pools: ResourcePoolSet
        | Mapping[str | ResourceClass, ResourcePool[Any] | ResourcePoolConfig]
        | None,
        *,
        default_max_concurrency: int = 1,
    ) -> ResourcePoolSet:
        if isinstance(pools, ResourcePoolSet):
            return pools
        default_config = ResourcePoolConfig(
            resource_class="default",
            max_concurrency=default_max_concurrency,
        )
        if pools is None:
            return ResourcePoolSet(default_config=default_config)
        return ResourcePoolSet(pools, default_config=default_config)

    @property
    def state(self) -> ResearchState | None:
        return self._state

    @property
    def events(self) -> tuple[ResearchEvent, ...]:
        return tuple(self._events)

    @property
    def budget(self) -> BudgetController:
        return self._budget

    @property
    def resource_invoker(self) -> RuntimeResourceInvoker:
        """Return the run-scoped physical-call boundary for injected ports."""

        return RuntimeResourceInvoker(self)

    async def invoke_resource(
        self,
        resource_class: ResourceClass | str,
        operation: Callable[..., Awaitable[Any]] | Awaitable[Any],
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute one physical provider/storage call under runtime policy.

        This method is intentionally separate from :meth:`dispatch`: one
        semantic action can contain many physical calls, and each call must be
        accounted for independently.  Composite handlers use this boundary;
        ordinary handlers continue to receive the action-level pool.
        """

        if self._closed:
            raise RuntimeError("research runtime is closed")
        if self._state is None or not self._run_started:
            raise RuntimeError("call begin(run_id) before invoking a resource")
        remaining = self._budget.remaining_seconds()
        effective_timeout = _minimum_timeout(timeout, remaining)
        if remaining is not None and remaining <= 0:
            raise BudgetExceededError(
                "research run deadline exceeded",
                dimension="deadline",
            )
        pool = self._pools.get(resource_class)
        return await pool.execute(
            operation,
            *args,
            timeout=effective_timeout,
            attempt_callback=lambda: self._budget.reserve(calls=1),
            **kwargs,
        )

    @property
    def resource_pools(self) -> ResourcePoolSet:
        return self._pools

    @property
    def pools(self) -> ResourcePoolSet:
        return self.resource_pools

    @property
    def queue(self) -> BoundedAsyncQueue[Any]:
        return self._work_queue

    @property
    def action_queue(self) -> BoundedAsyncQueue[Any]:
        return self._work_queue

    def begin(
        self,
        run_id: str,
        handler: ActionHandler | Callable[[SemanticAction], Awaitable[Any]] | Any = None,
    ) -> ResearchState:
        """Reset the runtime for one incremental run.

        ``begin`` only resets local state, so it is intentionally synchronous.
        Action execution and event delivery remain asynchronous in
        :meth:`dispatch` and :meth:`finish`.
        """

        if self._closed:
            raise RuntimeError("research runtime is closed")
        if self._run_active or self._finishing:
            raise RuntimeError("cannot begin while a runtime run is active")
        if self._dispatch_lock.locked() or any(
            not task.done() for task in self._dispatch_tasks.values()
        ):
            raise RuntimeError("cannot begin while actions are still running")
        if handler is not None:
            self._handler = handler
        self._state = initial_research_state(run_id)
        self._events = []
        self._sequence = 0
        self._budget = self._new_budget()
        self._work_queue = BoundedAsyncQueue(self.config.queue_size)
        self._dispatch_tasks.clear()
        self._dispatch_results.clear()
        self._dispatch_actions.clear()
        self._finish_task = None
        self._run_started = True
        self._finishing = False
        self._finished = False
        self._cancel_requested = False
        self._progress_counts = {}
        self._action_started_at = {}
        self._sink_tail = None
        return self._state

    async def dispatch(
        self,
        action: SemanticAction | Mapping[str, Any],
    ) -> ResearchActionResult:
        """Execute one validated action without emitting a run terminal event.

        Re-dispatching the same action id and idempotency key reuses its
        in-flight or completed execution.  This makes a workflow free to
        submit one comment batch at a time while retaining one runtime state.
        """

        self._require_incremental_run()
        typed_action = self._coerce_action(action)
        self._validate_action_graph((typed_action,), allow_external_dependencies=True)
        async with self._dispatch_lock:
            self._require_incremental_run()
            existing = self._dispatch_actions.get(typed_action.action_id)
            if existing is not None and existing != typed_action:
                raise RuntimePolicyError(
                    f"action_id {typed_action.action_id!r} was already dispatched"
                )
            existing_key = next(
                (
                    action_id
                    for action_id, dispatched in self._dispatch_actions.items()
                    if dispatched.idempotency_key == typed_action.idempotency_key
                    and action_id != typed_action.action_id
                ),
                None,
            )
            if existing_key is not None:
                raise RuntimePolicyError(
                    f"idempotency_key {typed_action.idempotency_key!r} was already dispatched"
                )
            cached = self._dispatch_results.get(typed_action.action_id)
            if cached is not None:
                return self._execution_result(cached)
            task = self._dispatch_tasks.get(typed_action.action_id)
            owns_task = task is None
            if task is None:
                self._dispatch_actions[typed_action.action_id] = typed_action
                task = asyncio.create_task(self._dispatch_one(typed_action))
                self._dispatch_tasks[typed_action.action_id] = task
        try:
            # The first caller owns the shared task; cancelling it is an
            # explicit request to stop this incremental action.  Later
            # callers own only their await, so cancelling one duplicate
            # waiter cannot cancel the provider call for everybody else.
            execution = await (task if owns_task else asyncio.shield(task))
        except asyncio.CancelledError:
            cancellation_gap = self._gap(
                typed_action,
                "action_cancelled",
                "incremental action was cancelled before completion",
            )
            if task.cancelled() and (
                self._state_or_raise().in_flight_action_ids
                and typed_action.action_id
                in self._state_or_raise().in_flight_action_ids
            ):
                # _dispatch_one records the lifecycle gap when its own task
                # is cancelled.  Keep this fallback for cancellation that
                # happens before that coroutine reaches its handler.
                await asyncio.shield(self._emit_progress(typed_action, gap=cancellation_gap))
                await asyncio.shield(self._emit_gap(typed_action, cancellation_gap))
            async with self._dispatch_lock:
                if task.cancelled():
                    self._dispatch_results[typed_action.action_id] = ActionExecution(
                        action=typed_action,
                        gap=cancellation_gap,
                    )
                    self._dispatch_tasks.pop(typed_action.action_id, None)
            raise
        except Exception:
            async with self._dispatch_lock:
                self._dispatch_tasks.pop(typed_action.action_id, None)
            raise
        async with self._dispatch_lock:
            self._dispatch_results[typed_action.action_id] = execution
            self._dispatch_tasks.pop(typed_action.action_id, None)
        return self._execution_result(execution)

    async def finish(self) -> ResearchState:
        """Wait for incremental actions and emit the single run terminal event."""

        self._require_incremental_run(allow_finishing=True)
        async with self._dispatch_lock:
            if self._finished:
                return self._state_or_raise()
            if self._finish_task is None:
                self._finishing = True
                tasks = tuple(self._dispatch_tasks.values())
                self._finish_task = asyncio.create_task(self._finish_impl(tasks))
            task = self._finish_task
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancellation of the caller represents cancellation of the
            # incremental run, not merely cancellation of one waiter.  Mark
            # the terminal boundary and let the shielded finisher publish the
            # corresponding RUN_CANCELLED event exactly once.
            self._cancel_requested = True
            await asyncio.shield(self.cancel())
            raise

    async def _finish_impl(
        self,
        tasks: tuple[asyncio.Task[ActionExecution], ...],
    ) -> ResearchState:
        terminal_emitted = False
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            unexpected = tuple(
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            )
            if unexpected:
                raise unexpected[0]
            if self._cancel_requested:
                await self._emit_run_terminal(ResearchEventType.RUN_CANCELLED)
            else:
                await self._emit_run_terminal(
                    ResearchEventType.RUN_COMPLETED,
                    payload={
                        "pending_action_count": len(
                            self._state_or_raise().in_flight_action_ids
                        )
                    },
                )
            terminal_emitted = True
            return self._state_or_raise()
        finally:
            async with self._dispatch_lock:
                self._finished = terminal_emitted or self._cancel_requested
                self._finishing = False

    async def cancel(self) -> ResearchState | None:
        """Cancel the current run and publish one irreversible terminal event.

        The method is safe to call from workflow cleanup, a cancelled
        ``finish`` waiter, or an explicit API cancellation endpoint.  Already
        completed runs are left untouched; late provider events are retained
        in the audit log by the reducer without reviving the outcome.
        """

        if self._state is None:
            return None
        self._cancel_requested = True
        async with self._dispatch_lock:
            tasks = tuple(self._dispatch_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        state = self._state_or_raise()
        for action_id in sorted(state.in_flight_action_ids):
            action = self._dispatch_actions.get(action_id)
            if action is None:
                continue
            await self._emit_gap(
                action,
                self._gap(
                    action,
                    "action_cancelled",
                    "research run was cancelled before action completion",
                ),
            )
        if not any(
            event.event_type
            in {ResearchEventType.RUN_COMPLETED, ResearchEventType.RUN_CANCELLED}
            for event in self._events
        ):
            await self._emit_run_terminal(ResearchEventType.RUN_CANCELLED)
        self._finishing = False
        self._finished = True
        return self._state_or_raise()

    def _require_incremental_run(self, *, allow_finishing: bool = False) -> None:
        if self._closed:
            raise RuntimeError("research runtime is closed")
        if self._state is None or not self._run_started:
            raise RuntimeError("call begin(run_id) before incremental dispatch")
        if self._run_active:
            raise RuntimeError("research runtime has a full run in progress")
        if (self._finished and not allow_finishing) or (
            self._finishing and not allow_finishing
        ):
            raise RuntimeError("research runtime run is already finishing or finished")

    @staticmethod
    def _coerce_action(action: SemanticAction | Mapping[str, Any]) -> SemanticAction:
        if isinstance(action, Mapping):
            return parse_semantic_action(action)
        return action

    @staticmethod
    def _execution_result(execution: ActionExecution) -> ResearchActionResult:
        if execution.result is not None:
            return execution.result
        if execution.gap is None:
            raise RuntimeError("action execution has neither result nor gap")
        return ResearchActionResult(
            action_id=execution.action.action_id,
            success=False,
            completeness="partial",
            gaps=(execution.gap,),
        )

    async def _dispatch_one(self, action: SemanticAction) -> ActionExecution:
        try:
            await self._emit_start(action)
            state = self._state_or_raise()
            missing = set(action.dependencies) - set(state.completed_action_ids)
            if missing:
                code = (
                    "dependency_failed"
                    if missing.intersection(state.failed_action_ids)
                    else "dependency_blocked"
                )
                gap = self._gap(
                    action,
                    code,
                    f"action dependencies are not complete: {sorted(missing)!r}",
                )
                execution = ActionExecution(action=action, gap=gap)
                await self._emit_progress(action, gap=gap)
                await self._emit_gap(action, gap)
                return execution
            execution = await self._execute_action(action)
            if execution.result is not None:
                await self._emit_progress(action, execution.result)
                await self._emit_completion(action, execution.result)
            elif execution.gap is not None:
                await self._emit_progress(action, gap=execution.gap)
                await self._emit_gap(action, execution.gap)
            return execution
        except asyncio.CancelledError:
            gap = self._gap(
                action,
                "action_cancelled",
                "incremental action was cancelled before completion",
            )
            await asyncio.shield(self._emit_progress(action, gap=gap))
            await asyncio.shield(self._emit_gap(action, gap))
            raise

    async def run(
        self,
        actions: Sequence[SemanticAction | ResearchAction | Mapping[str, Any]],
        *,
        run_id: str | None = None,
        state: ResearchState | None = None,
    ) -> ResearchState:
        """Run actions until all reachable work is complete or blocked."""

        if self._closed:
            raise RuntimeError("research runtime is closed")
        if self._run_active:
            raise RuntimeError("research runtime is already running")
        if any(not task.done() for task in self._dispatch_tasks.values()):
            raise RuntimeError("cannot start a full run while incremental actions are active")
        if self._finished or self._finishing:
            raise RuntimeError("call begin(run_id) before starting another runtime run")
        action_list = tuple(self._coerce_action(action) for action in actions)
        if state is not None:
            self._state = state
            self._events = list(state.events)
            self._sequence = state.sequence
        if self._state is None:
            if not run_id:
                raise ValueError("run_id is required for a new research runtime run")
            self._state = initial_research_state(run_id)
        elif run_id is not None and self._state.run_id != run_id:
            raise ValueError("run_id does not match the supplied research state")

        # Re-anchor the controller at the beginning of every full run.  A
        # resumed state carries the usage snapshots above; a fresh state starts
        # with a clean budget regardless of object construction time.
        self._budget = self._new_budget(self._state)

        known_dependencies = set(self._state.completed_action_ids) | set(
            self._state.failed_action_ids
        )
        action_by_id = self._validate_action_graph(
            action_list,
            known_dependencies=known_dependencies,
        )
        completed = set(self._state.completed_action_ids)
        failed = set(self._state.failed_action_ids)
        pending = set(action_by_id) - completed - failed

        self._run_started = True
        self._run_active = True
        self._cancel_requested = False
        self._progress_counts = {}
        self._action_started_at = {}
        try:
            while pending:
                available = tuple(
                    action_by_id[action_id]
                    for action_id in sorted(pending)
                    if set(action_by_id[action_id].dependencies).issubset(completed)
                )
                if not available:
                    for action_id in sorted(pending):
                        action = action_by_id[action_id]
                        blocked_code = (
                            "dependency_failed"
                            if any(
                                dependency in failed
                                for dependency in action.dependencies
                            )
                            else "dependency_blocked"
                        )
                        gap = self._gap(
                            action,
                            blocked_code,
                            "action dependencies did not complete successfully",
                        )
                        await self._emit_gap(action, gap)
                    pending.clear()
                    break

                # Limit the number of child tasks created by one wave.  The
                # resource pools bound provider concurrency; this separate
                # bound protects the runtime from an oversized ready set.
                ready = available[: self.config.max_parallel_actions]

                for action in ready:
                    pending.discard(action.action_id)
                    await self._emit_start(action)

                # TaskGroup gives cancellation and child-task lifetime a clear
                # scope.  Each child converts ordinary failures into a typed
                # result, so one note/action does not cancel its siblings.
                executions: list[ActionExecution] = []
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(self._execute_action(action)) for action in ready]
                for task in tasks:
                    executions.append(task.result())

                # Results are reduced as lifecycle events arrive.  Sorting is
                # only for stable handling of the same wave; independent data
                # itself is de-duplicated and sorted by the reducer.
                for execution in sorted(executions, key=lambda item: item.action.action_id):
                    action = execution.action
                    if execution.result is not None:
                        await self._emit_progress(action, execution.result)
                        await self._emit_completion(action, execution.result)
                        if execution.result.success:
                            # A partial result is usable and therefore unlocks
                            # dependents.  Its typed gaps still make the run
                            # partial, but do not make the action dependency
                            # fail.
                            completed.add(action.action_id)
                        else:
                            failed.add(action.action_id)
                    elif execution.gap is not None:
                        failed.add(action.action_id)
                        await self._emit_progress(action, gap=execution.gap)
                        await self._emit_gap(action, execution.gap)

                # Any failed dependency is explicitly surfaced and descendants
                # are skipped without invoking a provider.
                blocked = tuple(
                    action_by_id[action_id]
                    for action_id in sorted(pending)
                    if any(dependency in failed for dependency in action_by_id[action_id].dependencies)
                )
                for action in blocked:
                    pending.discard(action.action_id)
                    gap = self._gap(
                        action,
                        "dependency_failed",
                        "action dependency failed; provider call was skipped",
                    )
                    failed.add(action.action_id)
                    await self._emit_gap(action, gap)

            await self._emit_run_terminal(
                ResearchEventType.RUN_COMPLETED,
                payload={"pending_action_count": len(pending)},
            )
            self._finished = True
            return self._state_or_raise()
        except asyncio.CancelledError:
            self._cancel_requested = True
            for action_id in sorted(self._state_or_raise().in_flight_action_ids):
                action = action_by_id.get(action_id)
                if action is None:
                    continue
                gap = self._gap(
                    action,
                    "action_cancelled",
                    "research run was cancelled before action completion",
                )
                await self._emit_gap(action, gap)
            await self._emit_run_terminal(ResearchEventType.RUN_CANCELLED)
            self._finished = True
            raise
        finally:
            self._run_active = False

    execute = run

    async def submit(
        self,
        action: SemanticAction | ResearchAction | Mapping[str, Any],
        *,
        run_id: str,
    ) -> ResearchState:
        """Convenience API for a one-action run."""

        return await self.run((action,), run_id=run_id)

    async def aclose(self) -> None:
        # Close is also the workflow's cancellation safety net.  If a caller
        # exits before ``finish`` publishes a terminal event, cancel the run
        # first so no in-flight action remains semantically open.
        cancellation: asyncio.CancelledError | None = None
        if self._state is not None and not self._finished:
            try:
                await self.cancel()
            except asyncio.CancelledError as exc:
                # Preserve task cancellation, but continue draining the
                # shielded finisher before the owning session is closed.
                cancellation = exc

        # ``finish`` shields its finisher from waiter cancellation so the
        # terminal event can still be reduced exactly once.  The finisher is
        # not part of ``_dispatch_tasks``; wait for it explicitly before the
        # owning workflow closes its provider session.
        finish_task = self._finish_task
        if finish_task is not None:
            try:
                await _wait_for_task_cleanup(finish_task)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc

        self._closed = True
        async with self._dispatch_lock:
            tasks = tuple(self._dispatch_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            try:
                await _wait_for_task_cleanup(
                    asyncio.gather(*tasks, return_exceptions=True)
                )
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
        await self._work_queue.close()
        if cancellation is not None:
            raise cancellation

    async def close(self) -> None:
        await self.aclose()

    def _state_or_raise(self) -> ResearchState:
        if self._state is None:
            raise RuntimeError("research runtime has no state")
        return self._state

    def _validate_action_graph(
        self,
        actions: Sequence[SemanticAction],
        *,
        allow_external_dependencies: bool = False,
        known_dependencies: Collection[str] = (),
    ) -> dict[str, SemanticAction]:
        action_by_id: dict[str, SemanticAction] = {}
        idempotency_keys: dict[str, str] = {}
        for action in actions:
            if not isinstance(action, (
                SearchNotes,
                FetchNoteEvidence,
                AnalyzeCommentBatch,
                ExpandResearch,
                EnrichShopProfile,
                Synthesize,
                StopResearch,
            )):
                raise RuntimePolicyError(
                    f"unsupported semantic action type: {type(action).__name__}"
                )
            if action.action_id in action_by_id:
                raise RuntimePolicyError(f"duplicate action_id: {action.action_id}")
            previous_action_id = idempotency_keys.get(action.idempotency_key)
            if previous_action_id is not None:
                raise RuntimePolicyError(
                    f"idempotency_key {action.idempotency_key!r} is shared by "
                    f"actions {previous_action_id!r} and {action.action_id!r}"
                )
            if self._capabilities is not None and action.capability not in self._capabilities:
                # Keep the action in the graph.  It is converted to a typed
                # policy gap at execution time, allowing independent actions
                # to continue.
                pass
            action_by_id[action.action_id] = action
            idempotency_keys[action.idempotency_key] = action.action_id
        if not allow_external_dependencies:
            for action in action_by_id.values():
                known = set(action_by_id) | set(known_dependencies)
                unknown = set(action.dependencies) - known
                if unknown:
                    raise RuntimePolicyError(
                        f"action {action.action_id!r} has unknown dependencies: {sorted(unknown)!r}"
                    )
                if action.action_id in action.dependencies:
                    raise RuntimePolicyError(f"action {action.action_id!r} depends on itself")
        self._reject_cycles(action_by_id)
        return action_by_id

    @staticmethod
    def _reject_cycles(actions: Mapping[str, SemanticAction]) -> None:
        # Incremental dispatch may refer to an action completed by an earlier
        # dispatch call.  Only edges inside this local graph participate in
        # cycle detection; external dependencies are checked against state by
        # the action executor.
        remaining = {
            key: sum(dependency in actions for dependency in value.dependencies)
            for key, value in actions.items()
        }
        dependents: dict[str, list[str]] = {key: [] for key in actions}
        for action in actions.values():
            for dependency in action.dependencies:
                if dependency in dependents:
                    dependents[dependency].append(action.action_id)
        ready = [key for key, count in remaining.items() if count == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for dependent in dependents[current]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        if visited != len(actions):
            raise RuntimePolicyError(
                "semantic action dependency cycle: "
                + ", ".join(sorted(key for key, count in remaining.items() if count))
            )

    async def _execute_action(self, action: SemanticAction) -> ActionExecution:
        try:
            if self._capabilities is not None and action.capability not in self._capabilities:
                return ActionExecution(
                    action=action,
                    gap=self._gap(
                        action,
                        "capability_unavailable",
                        f"capability {action.capability!r} is absent from the pinned catalog",
                    ),
                )
            token_estimate = (
                action.token_estimate
                if isinstance(action, AnalyzeCommentBatch)
                else 0
            )
            await self._budget.reserve(actions=1, tokens=token_estimate)
            pool = self._pools.get(action.resource_class)
            action_timeout = _action_timeout_seconds(action)
            remaining_budget = self._budget.remaining_seconds()
            if remaining_budget is not None and remaining_budget <= 0:
                raise BudgetExceededError(
                    "research run deadline exceeded",
                    dimension="deadline",
                )
            timeout = _minimum_timeout(action_timeout, remaining_budget)
            if self._handler_manages_resources(action):
                # Composite handlers own their child resource calls.  Holding
                # the action's provider pool here would deadlock when a child
                # uses the same capability (the common SearchNotes case).
                output = await self._invoke_composite(action, timeout=timeout)
            else:
                async with self._global_semaphore:
                    output = await pool.execute(
                        self._dispatch,
                        action,
                        timeout=timeout,
                        attempt_callback=lambda: self._budget.reserve(calls=1),
                    )
            result = self._normalize_result(action, output)
            if result.tokens_used > token_estimate:
                try:
                    await self._budget.reconcile_tokens(
                        reserved_tokens=token_estimate,
                        actual_tokens=result.tokens_used,
                    )
                except BudgetExceededError as exc:
                    # The provider result is already available. Preserve it as
                    # partial data rather than dropping evidence because the
                    # planner's estimate was lower than actual usage.
                    result = result.model_copy(
                        update={
                            "completeness": "partial",
                            "continuation": {
                                **dict(result.continuation),
                                "budget_exhausted": True,
                                "budget_dimension": exc.dimension,
                            },
                            "gaps": tuple(
                                _unique_gaps(
                                    (*result.gaps, self._gap(action, _error_code(exc), str(exc)))
                                )
                            ),
                        }
                    )
            if not result.success and not result.gaps:
                result = result.model_copy(
                    update={
                        "completeness": "partial",
                        "gaps": (
                            self._gap(
                                action,
                                "action_failed",
                                "action returned an unsuccessful result without a typed gap",
                            ),
                        ),
                    }
                )
            return ActionExecution(action=action, result=result)
        except asyncio.CancelledError:
            raise
        except (BudgetExceededError, ResourceCircuitOpenError, ResourceCallTimeoutError) as exc:
            return ActionExecution(action=action, gap=self._gap(action, _error_code(exc), str(exc)))
        except Exception as exc:
            return ActionExecution(action=action, gap=self._gap(action, "action_failed", str(exc)))

    def _handler_manages_resources(self, action: SemanticAction) -> bool:
        handler: Any = self._handler
        marker = getattr(handler, "manages_resources", None)
        if callable(marker):
            try:
                return bool(marker(action))
            except Exception:  # noqa: BLE001 - a marker must never break dispatch
                return False
        return bool(getattr(handler, "managed_resources", False))

    async def _invoke_composite(
        self,
        action: SemanticAction,
        *,
        timeout: float | None,
    ) -> Any:
        """Invoke a composite handler with one bounded action deadline."""

        try:
            if timeout is None:
                return await self._dispatch(action)
            async with asyncio.timeout(timeout):
                return await self._dispatch(action)
        except TimeoutError as exc:
            raise ResourceCallTimeoutError(
                f"resource {action.resource_class.value} exceeded deadline"
            ) from exc

    async def _dispatch(self, action: SemanticAction) -> Any:
        # The handler protocol intentionally supports either a callable or a
        # small object with ``execute``/``dispatch``.  Keep that structural
        # boundary local instead of pretending every implementation has all
        # three methods in its static type.
        handler: Any = self._handler
        if hasattr(handler, "execute"):
            value = handler.execute(action)
        elif hasattr(handler, "dispatch"):
            value = handler.dispatch(action)
        elif callable(handler):
            value = handler(action)
        else:
            raise TypeError("action handler must be callable or expose execute/dispatch")
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _normalize_result(action: SemanticAction, output: Any) -> ResearchActionResult:
        if isinstance(output, ResearchActionResult):
            if output.action_id != action.action_id:
                raise RuntimePolicyError("action result id does not match dispatched action")
            return output
        if isinstance(output, SourceEnvelope):
            return ResearchActionResult(
                action_id=action.action_id,
                source_envelopes=(output,),
                completeness=output.completeness,
            )
        if output is None:
            return ResearchActionResult(action_id=action.action_id)
        if isinstance(output, Mapping):
            payload = dict(output)
            payload.setdefault("action_id", action.action_id)
            return ResearchActionResult.model_validate(payload)
        return ResearchActionResult(action_id=action.action_id, output=output)

    def _gap(self, action: SemanticAction, code: str, message: str) -> ResearchGap:
        return ResearchGap(
            source=action.resource_class.value,
            operation=action.capability,
            code=code,
            message=message,
            retryable=code in {"resource_timeout", "action_failed", "circuit_open"},
            details={"action_id": action.action_id, "idempotency_key": action.idempotency_key},
        )

    async def _emit_start(self, action: SemanticAction) -> None:
        self._action_started_at.setdefault(action.action_id, time.perf_counter())
        await self._emit(
            ResearchEvent(
                event_id=f"{self._state_or_raise().run_id}:action:{action.action_id}:start",
                run_id=self._state_or_raise().run_id,
                sequence=1,
                event_type=ResearchEventType.ACTION_STARTED,
                action_id=action.action_id,
                resource_class=action.resource_class,
                budget_usage=self._budget.snapshot().model_dump(mode="json"),
                payload={
                    "phase": "started",
                    "capability": action.capability,
                    "duration_ms": 0,
                },
            )
        )

    async def _emit_gap(self, action: SemanticAction, gap: ResearchGap) -> None:
        await self._emit(
            ResearchEvent(
                event_id=(
                    f"{self._state_or_raise().run_id}:action:{action.action_id}:gap:{gap.code}"
                ),
                run_id=self._state_or_raise().run_id,
                sequence=1,
                event_type=ResearchEventType.ACTION_GAP,
                action_id=action.action_id,
                resource_class=action.resource_class,
                budget_usage=self._budget.snapshot().model_dump(mode="json"),
                gap=gap,
                payload={"phase": "gap", "duration_ms": self._duration_ms(action)},
            )
        )

    async def _emit_completion(
        self,
        action: SemanticAction,
        result: ResearchActionResult,
    ) -> None:
        await self._emit(
            ResearchEvent(
                event_id=f"{self._state_or_raise().run_id}:action:{action.action_id}:complete",
                run_id=self._state_or_raise().run_id,
                sequence=1,
                event_type=ResearchEventType.ACTION_COMPLETED,
                action_id=action.action_id,
                resource_class=action.resource_class,
                item_count=result.item_count,
                completeness=result.completeness,
                budget_usage=self._budget.snapshot().model_dump(mode="json"),
                result=result,
                payload={
                    "phase": "completed",
                    "duration_ms": self._duration_ms(action),
                },
            )
        )

    async def _emit_progress(
        self,
        action: SemanticAction,
        result: ResearchActionResult | None = None,
        *,
        gap: ResearchGap | None = None,
        item_count: int | None = None,
        completeness: str | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> None:
        progress_index = self._progress_counts.get(action.action_id, 0)
        self._progress_counts[action.action_id] = progress_index + 1
        payload: dict[str, Any] = {
            "phase": "in_progress",
            "progress_index": progress_index,
            "duration_ms": self._duration_ms(action),
        }
        if event_payload is not None:
            payload.update(dict(event_payload))
        if result is not None:
            payload.update(
                {
                    "success": result.success,
                    "gap_count": len(result.gaps),
                }
            )
        if gap is not None:
            payload.update({"success": False, "gap_code": gap.code})
        effective_completeness: Literal["complete", "partial", "unknown"]
        if result is not None:
            effective_completeness = result.completeness
        elif completeness in {"complete", "partial", "unknown"}:
            effective_completeness = completeness  # type: ignore[assignment]
        else:
            effective_completeness = "unknown"
        await self._emit(
            ResearchEvent(
                event_id=(
                    f"{self._state_or_raise().run_id}:action:{action.action_id}:"
                    f"progress:{progress_index}"
                ),
                run_id=self._state_or_raise().run_id,
                sequence=1,
                event_type=ResearchEventType.ACTION_PROGRESS,
                action_id=action.action_id,
                resource_class=action.resource_class,
                budget_usage=self._budget.snapshot().model_dump(mode="json"),
                item_count=(
                    result.item_count
                    if result is not None
                    else item_count
                    if item_count is not None
                    else 0
                ),
                completeness=effective_completeness,
                payload=payload,
            )
        )

    async def report_progress(
        self,
        action: SemanticAction,
        *,
        item_count: int = 0,
        completeness: str = "unknown",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish an in-flight progress point from a composite action.

        Source adapters use this boundary after each accepted page/item.  It
        keeps the runtime event stream honest without making provider ports
        aware of event contracts.
        """

        if item_count < 0:
            raise ValueError("progress item_count cannot be negative")
        await self._emit_progress(
            action,
            item_count=item_count,
            completeness=completeness,
            event_payload=payload,
        )

    def _duration_ms(self, action: SemanticAction) -> int:
        started = self._action_started_at.get(action.action_id)
        if started is None:
            return 0
        return max(0, int((time.perf_counter() - started) * 1000))

    async def _emit_run_terminal(
        self,
        event_type: ResearchEventType,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        state = self._state_or_raise()
        event_id = f"{state.run_id}:run:{event_type.value}"
        await self._emit(
            ResearchEvent(
                event_id=event_id,
                run_id=state.run_id,
                sequence=1,
                event_type=event_type,
                budget_usage=self._budget.snapshot().model_dump(mode="json"),
                payload=dict(payload or {}),
            )
        )

    async def _emit(self, event: ResearchEvent) -> None:
        sink: RuntimeEventSink | Callable[[ResearchEvent], Awaitable[None]] | None
        previous_sink: asyncio.Future[None] | None = None
        sink_completion: asyncio.Future[None] | None = None
        async with self._event_lock:
            if event.event_id in self._state_or_raise().applied_event_ids:
                return
            self._sequence += 1
            event = event.model_copy(update={"sequence": self._sequence, "occurred_at": self._clock()})
            self._events.append(event)
            self._state = reduce_research_event(self._state_or_raise(), event)
            sink = self._event_sink
            if sink is not None:
                # Chain deliveries in sequence order.  The state reducer stays
                # lock-protected, while the sink itself remains outside that
                # lock so a telemetry callback can inspect runtime state.
                loop = asyncio.get_running_loop()
                previous_sink = self._sink_tail
                sink_completion = loop.create_future()
                self._sink_tail = sink_completion
        if sink is not None:
            try:
                if previous_sink is not None:
                    await asyncio.shield(previous_sink)
                try:
                    value = sink(event) if callable(sink) else sink
                    if inspect.isawaitable(value):
                        await value
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - observability cannot drop data
                    logger.exception("research runtime event sink failed")
            finally:
                if sink_completion is not None and not sink_completion.done():
                    sink_completion.set_result(None)


def _error_code(error: BaseException) -> str:
    if isinstance(error, BudgetExceededError):
        return f"budget_{error.dimension}_exhausted"
    if isinstance(error, ResourceCircuitOpenError):
        return "circuit_open"
    if isinstance(error, ResourceCallTimeoutError):
        return "resource_timeout"
    return "action_failed"


def _action_timeout_seconds(action: SemanticAction) -> float | None:
    """Read an optional per-action timeout without trusting arbitrary input."""

    value = action.inputs.get("timeout_ms")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value / 1000
    return None


def _minimum_timeout(*values: float | None) -> float | None:
    bounded = [value for value in values if value is not None]
    return min(bounded) if bounded else None


async def _wait_for_task_cleanup(task: asyncio.Future[Any]) -> None:
    """Drain a shielded task while preserving caller cancellation.

    Cleanup must not return while a shielded finisher can still publish a
    terminal event.  If the cleanup caller is cancelled again, keep waiting
    for the child and re-raise that cancellation after the child is settled.
    Exceptions from the child are consumed here because cleanup must not mask
    the operation that caused the workflow to unwind.
    """

    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:
            break
    with suppress(BaseException):
        task.result()
    if cancellation is not None:
        raise cancellation


def _unique_gaps(values: Iterable[ResearchGap]) -> tuple[ResearchGap, ...]:
    """Deduplicate typed gaps without requiring mappings to be hashable."""

    output: list[ResearchGap] = []
    for value in values:
        if not any(existing == value for existing in output):
            output.append(value)
    return tuple(output)


__all__ = [
    "ActionExecution",
    "ActionHandler",
    "ResearchRuntime",
    "ResearchRuntimeConfig",
    "RuntimeResourceInvoker",
    "RuntimeConfig",
    "RuntimeEventSink",
    "RuntimePolicyError",
]
