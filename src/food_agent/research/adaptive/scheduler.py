"""Bounded DAG scheduling for one adaptive investigation Agent.

This module is intentionally provider-blind.  ``ActionScheduler`` accepts
typed semantic actions and calls only an injected ``ActionExecutor`` or
``ToolPort``.  It can therefore be used with MCP, an HTTP adapter, or a pure
in-memory fake without importing any provider client.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from food_agent.contracts import (
    BudgetUsage,
    ContractModel,
    InvestigationBudget,
    ResearchActionResult,
    ResearchGap,
)

from .planner import ActionSpec, coerce_action, stable_json

AdaptiveBudget = InvestigationBudget
RunBudget = InvestigationBudget


class ActionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ActionObservation(ContractModel):
    """One lossless observation of a scheduled action."""

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    action_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    kind: str = Field(default="generic", min_length=1)
    capability: str = Field(default="generic", min_length=1)
    round_index: int = Field(default=0, ge=0)
    status: ActionStatus = ActionStatus.COMPLETED
    success: bool = True
    action: Any = None
    result: Any = None
    raw_return: Any = Field(
        default=None,
        validation_alias=AliasChoices("raw_return", "raw_result", "raw_output"),
    )
    evidence_refs: tuple[str, ...] = ()
    gap: ResearchGap | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    tool_calls: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_units: float = Field(default=0.0, ge=0.0)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("evidence references must be non-empty")
        if len(values) != len(set(values)):
            raise ValueError("evidence references must be unique")
        return values

    @property
    def raw_result(self) -> Any:
        return self.raw_return

    @property
    def completed(self) -> bool:
        return self.status is ActionStatus.COMPLETED and self.success


ActionResult = ActionObservation


class WaveResult(ContractModel):
    """Deterministically ordered output from one scheduler drain."""

    round_index: int = Field(default=0, ge=0)
    observations: tuple[ActionObservation, ...] = ()
    action_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    raw_returns: tuple[Any, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def _derive(self) -> WaveResult:
        observations = tuple(sorted(self.observations, key=lambda item: item.action_id))
        if not self.action_ids:
            object.__setattr__(self, "action_ids", tuple(item.action_id for item in observations))
        if not self.evidence_refs:
            refs = sorted({ref for item in observations for ref in item.evidence_refs})
            object.__setattr__(self, "evidence_refs", tuple(refs))
        if not self.raw_returns:
            object.__setattr__(self, "raw_returns", tuple(item.raw_return for item in observations))
        if not self.gaps:
            gaps = tuple(item.gap for item in observations if item.gap is not None)
            object.__setattr__(self, "gaps", gaps)
        object.__setattr__(self, "observations", observations)
        return self

    @property
    def results(self) -> tuple[ActionObservation, ...]:
        return self.observations


SchedulerResult = WaveResult


class SchedulerState(ContractModel):
    """Serializable scheduler snapshot supplied to planner/critic context."""

    run_id: str = "run"
    pending_action_ids: tuple[str, ...] = ()
    completed_action_ids: tuple[str, ...] = ()
    failed_action_ids: tuple[str, ...] = ()
    rejected_action_ids: tuple[str, ...] = ()
    observations: tuple[ActionObservation, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @property
    def raw_returns(self) -> tuple[Any, ...]:
        return tuple(item.raw_return for item in self.observations)


InvestigationSchedulerState = SchedulerState


@runtime_checkable
class ActionExecutor(Protocol):
    async def execute(self, action: Any, context: Mapping[str, Any] | None = None) -> Any: ...


@runtime_checkable
class ToolPort(Protocol):
    async def call(
        self,
        capability: str,
        arguments: Mapping[str, Any],
        action: Any | None = None,
    ) -> Any: ...


class ActionScheduler:
    """Execute independent semantic actions in bounded concurrent waves."""

    def __init__(
        self,
        executor: ActionExecutor | Callable[..., Any] | None = None,
        *,
        tool_port: ToolPort | Any | None = None,
        capabilities: Iterable[str] | None = None,
        max_concurrency: int = 4,
        resource_limits: Mapping[str, int] | None = None,
        budget: InvestigationBudget | Mapping[str, Any] | None = None,
        run_id: str = "run",
    ) -> None:
        if executor is None and tool_port is None:
            raise ValueError("an ActionExecutor or ToolPort is required")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if budget is None:
            effective_budget = InvestigationBudget()
        elif isinstance(budget, InvestigationBudget):
            effective_budget = budget
        else:
            effective_budget = InvestigationBudget.model_validate(budget)
        self.executor = executor
        self.tool_port = tool_port
        advertised = _advertised_capabilities(tool_port) if capabilities is None else None
        self._capabilities = (
            frozenset(str(item) for item in capabilities)
            if capabilities is not None
            else advertised
        )
        self.max_concurrency = max_concurrency
        self._resource_limits = {
            str(name): max(1, int(value)) for name, value in (resource_limits or {}).items()
        }
        self.budget = effective_budget
        self.run_id = run_id
        self._actions: dict[str, Any] = {}
        self._keys: dict[str, str] = {}
        self._pending: set[str] = set()
        self._terminal: dict[str, ActionObservation] = {}
        self._observations: dict[str, ActionObservation] = {}
        self._usage = BudgetUsage()
        self._usage_lock = asyncio.Lock()
        self._started_monotonic = time.monotonic()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._resource_semaphores: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(limit) for name, limit in self._resource_limits.items()
        }
        self._preflight: list[ActionObservation] = []
        self._rounds_started: set[int] = set()
        self._running_tasks: dict[str, asyncio.Task[ActionObservation]] = {}
        # A scheduler may be injected into more than one loop/workflow.  The
        # lease covers the whole run, including model planning time, because
        # ``_running_tasks`` is empty before the first tool wave and is not a
        # sufficient concurrency guard by itself.
        self._run_lease: str | None = None
        # Token/cost/call estimates are held separately while a task is in
        # flight.  BudgetUsage remains an actual-consumption snapshot.
        self._reservations: dict[str, tuple[int, int, float]] = {}
        self._reserved_tool_calls = 0
        self._reserved_tokens = 0
        self._reserved_cost_units = 0.0

    @property
    def state(self) -> SchedulerState:
        self._refresh_elapsed()
        completed = sorted(
            action_id
            for action_id, item in self._terminal.items()
            if item.status is ActionStatus.COMPLETED and item.success
        )
        failed = sorted(
            action_id
            for action_id, item in self._terminal.items()
            if item.status is ActionStatus.FAILED
        )
        rejected = sorted(
            action_id
            for action_id, item in self._terminal.items()
            if item.status is ActionStatus.REJECTED
        )
        observations = tuple(self._observations[key] for key in sorted(self._observations))
        evidence_refs = tuple(sorted({ref for item in observations for ref in item.evidence_refs}))
        gaps = tuple(
            item.gap for item in observations if item.gap is not None
        )
        return SchedulerState(
            run_id=self.run_id,
            pending_action_ids=tuple(sorted(self._pending)),
            completed_action_ids=tuple(completed),
            failed_action_ids=tuple(failed),
            rejected_action_ids=tuple(rejected),
            observations=observations,
            evidence_refs=evidence_refs,
            gaps=gaps,
            budget_usage=self._usage,
        )

    @property
    def usage(self) -> BudgetUsage:
        self._refresh_elapsed()
        return self._usage

    async def record_usage(
        self,
        value: Any = None,
        *,
        iterations: int = 0,
        actions: int = 0,
        tool_calls: int | None = None,
        tokens: int | None = None,
        cost_units: float | None = None,
        observations: int = 0,
    ) -> BudgetUsage:
        """Record actual usage reported by a model or gateway adapter.

        ``value`` may be a mapping, a project contract, or an SDK response
        exposing ``usage``/``metadata``.  Explicit keyword values take
        precedence and make this method convenient for adapters that already
        normalize their provider response.
        """

        (
            reported_tokens,
            reported_cost,
            reported_calls,
            _has_tokens,
            _has_cost,
            _has_calls,
        ) = _actual_usage_details(value)
        if tokens is None:
            tokens = reported_tokens
        if cost_units is None:
            cost_units = reported_cost
        if tool_calls is None:
            tool_calls = reported_calls
        async with self._usage_lock:
            self._refresh_elapsed()
            self._usage = self._usage.model_copy(
                update={
                    "iterations": self._usage.iterations + max(0, int(iterations)),
                    "actions": self._usage.actions + max(0, int(actions)),
                    "tool_calls": self._usage.tool_calls + max(0, int(tool_calls or 0)),
                    "tokens": self._usage.tokens + max(0, int(tokens or 0)),
                    "cost_units": self._usage.cost_units + max(0.0, float(cost_units or 0.0)),
                    "observations": self._usage.observations + max(0, int(observations)),
                }
            )
            return self._usage

    report_usage = record_usage

    @property
    def observations(self) -> tuple[ActionObservation, ...]:
        return self.state.observations

    @property
    def capabilities(self) -> frozenset[str] | None:
        return self._capabilities

    @property
    def run_lease(self) -> str | None:
        """Investigation id currently owning this scheduler, if any."""

        return self._run_lease

    def bind_tool_port(
        self,
        tool_port: ToolPort | Any,
        capabilities: Iterable[str] | None = None,
    ) -> None:
        """Bind a run-scoped tool port through the public scheduler boundary.

        A workflow may reuse an ``ActionScheduler`` instance while replacing
        the managed session for each run.  Binding is intentionally refused
        while actions are in flight; changing the port underneath an action
        would make its audit record impossible to attribute to one session.
        When no explicit capability set is supplied, the port's advertised
        snapshot is used and an unavailable advertisement remains fail-open
        for backwards-compatible custom ports.
        """

        if tool_port is None:
            raise ValueError("tool_port is required")
        if self._running_tasks:
            raise RuntimeError("cannot bind a tool port while actions are running")
        self.tool_port = tool_port
        if capabilities is not None:
            self._capabilities = frozenset(str(item) for item in capabilities)
        else:
            advertised = _advertised_capabilities(tool_port)
            if advertised is not None:
                self._capabilities = advertised

    def acquire_run(self, run_id: str) -> None:
        """Claim this scheduler for one investigation run.

        Resetting a shared scheduler while another loop is planning or
        executing would erase that run's pending actions, observations, and
        budget counters.  A synchronous claim is enough here: callers are in
        one event loop and no await occurs between this check and the reset.
        """

        normalized = str(run_id)
        if not normalized:
            raise ValueError("run_id must be non-empty")
        if self._run_lease is not None:
            raise RuntimeError(
                f"scheduler is already leased by investigation {self._run_lease}"
            )
        if self._running_tasks:
            raise RuntimeError("cannot acquire a scheduler while actions are running")
        self.reset(run_id=normalized)
        self._run_lease = normalized

    def release_run(self, run_id: str | None = None) -> None:
        """Release the run lease after the owning loop has fully stopped."""

        if self._run_lease is None:
            return
        if run_id is not None and str(run_id) != self._run_lease:
            raise RuntimeError("scheduler run lease belongs to another investigation")
        if self._running_tasks:
            raise RuntimeError("cannot release a scheduler while actions are running")
        self._run_lease = None

    def reset(self, *, run_id: str | None = None) -> None:
        """Clear a scheduler for a new run without retaining provider state."""

        if self._run_lease is not None:
            raise RuntimeError(
                f"scheduler is leased by investigation {self._run_lease}; release it before reset"
            )
        if self._running_tasks:
            raise RuntimeError("cannot reset a scheduler while actions are running")
        if run_id is not None:
            self.run_id = run_id
        self._actions.clear()
        self._keys.clear()
        self._pending.clear()
        self._terminal.clear()
        self._observations.clear()
        self._preflight.clear()
        self._usage = BudgetUsage()
        self._started_monotonic = time.monotonic()
        self._rounds_started.clear()
        self._running_tasks.clear()
        self._reservations.clear()
        self._reserved_tool_calls = 0
        self._reserved_tokens = 0
        self._reserved_cost_units = 0.0

    def add_actions(
        self,
        actions: Iterable[Any],
        *,
        round_index: int = 0,
    ) -> tuple[str, ...]:
        """Append typed actions idempotently and return newly accepted ids."""

        accepted: list[str] = []
        for position, original in enumerate(actions):
            action = self._coerce_action(original, round_index=round_index, position=position)
            action_id = _action_id(action)
            idem = _idempotency_key(action)
            if action_id in self._actions:
                previous = self._actions[action_id]
                if _stable_action(previous) == _stable_action(action):
                    # A completed idempotent action is already represented in
                    # the append-only scheduler state.  Re-emitting its prior
                    # observation would make a replay look like a new tool
                    # result to the planner/critic.
                    continue
                self._record_preflight(action, self._gap(action, "duplicate_action", "action id was already registered"), round_index)
                continue
            previous_id = self._keys.get(idem)
            if previous_id is not None and previous_id != action_id:
                self._record_preflight(action, self._gap(action, "duplicate_idempotency_key", "idempotency key was already registered"), round_index)
                continue
            self._actions[action_id] = action
            self._keys[idem] = action_id
            self._pending.add(action_id)
            accepted.append(action_id)
        return tuple(accepted)

    append_actions = add_actions
    add = add_actions

    async def execute(
        self,
        actions: Iterable[Any] | None = None,
        *,
        round_index: int = 0,
        context: Mapping[str, Any] | None = None,
    ) -> WaveResult:
        """Append actions and drain all currently reachable dependency waves."""

        if actions is not None:
            self.add_actions(actions, round_index=round_index)
        before = set(self._observations)
        all_new: list[ActionObservation] = []
        while self._pending:
            ready, rejected = self._ready_actions()
            for action_id, gap in rejected:
                observation = self._reject(action_id, gap, round_index)
                all_new.append(observation)
            if not ready:
                if self._pending:
                    # No ready node with pending actions means a dependency
                    # cycle.  Rejecting all cycle members is deterministic and
                    # retains a typed reason for every lost action.
                    for action_id in sorted(self._pending):
                        action = self._actions[action_id]
                        observation = self._reject(
                            action_id,
                            self._gap(action, "dependency_cycle", "action dependency graph contains a cycle"),
                            round_index,
                        )
                        all_new.append(observation)
                break
            try:
                await self._reserve_round(round_index)
            except _BudgetReservationError as exc:
                for action_id in ready:
                    all_new.append(
                        self._reject(
                            action_id,
                            self._gap(
                                self._actions[action_id],
                                "budget_exhausted",
                                f"{exc.dimension} budget exhausted",
                                details={"dimension": exc.dimension},
                            ),
                            round_index,
                        )
                    )
                break
            tasks = self._start_action_tasks(ready, round_index, context)
            try:
                wave = await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                await self._cancel_tasks(tasks)
                await self._record_cancelled(ready, round_index)
                raise
            finally:
                self._forget_tasks(tasks)
            all_new.extend(wave)
        # Preflight records are generated synchronously by add_actions and may
        # have no pending action.  Include them once in the returned wave.
        if self._preflight:
            all_new.extend(self._preflight)
            self._preflight.clear()
        if not all_new:
            all_new = [self._observations[key] for key in sorted(set(self._observations) - before)]
        return WaveResult(
            round_index=round_index,
            observations=tuple(all_new),
            budget_usage=self.usage,
        )

    run = execute
    schedule = execute

    async def run_wave(
        self,
        actions: Iterable[Any] | None = None,
        *,
        round_index: int = 0,
        context: Mapping[str, Any] | None = None,
    ) -> WaveResult:
        """Execute one currently-ready wave, leaving dependent actions queued."""

        if actions is not None:
            self.add_actions(actions, round_index=round_index)
        ready, rejected = self._ready_actions()
        observations: list[ActionObservation] = [
            self._reject(action_id, gap, round_index) for action_id, gap in rejected
        ]
        if ready:
            try:
                await self._reserve_round(round_index)
            except _BudgetReservationError as exc:
                observations.extend(
                    self._reject(
                        action_id,
                        self._gap(
                            self._actions[action_id],
                            "budget_exhausted",
                            f"{exc.dimension} budget exhausted",
                            details={"dimension": exc.dimension},
                        ),
                        round_index,
                    )
                    for action_id in ready
                )
                ready = ()
            if ready:
                tasks = self._start_action_tasks(ready, round_index, context)
                try:
                    observations.extend(await asyncio.gather(*tasks))
                except asyncio.CancelledError:
                    await self._cancel_tasks(tasks)
                    await self._record_cancelled(ready, round_index)
                    raise
                finally:
                    self._forget_tasks(tasks)
        if self._preflight:
            observations.extend(self._preflight)
            self._preflight.clear()
        return WaveResult(round_index=round_index, observations=tuple(observations), budget_usage=self.usage)

    async def close(self) -> None:
        """Cancel in-flight work and make every abandoned action terminal."""

        tasks = tuple(self._running_tasks.values())
        if tasks:
            await self._cancel_tasks(tasks)
        await self._record_cancelled(tuple(sorted(self._pending)), 0)
        self._pending.clear()

    def _start_action_tasks(
        self,
        action_ids: Sequence[str],
        round_index: int,
        context: Mapping[str, Any] | None,
    ) -> list[asyncio.Task[ActionObservation]]:
        tasks: list[asyncio.Task[ActionObservation]] = []
        for action_id in action_ids:
            task = _create_eager_task(
                self._execute_one(self._actions[action_id], round_index, context),
                name=f"adaptive-action:{action_id}",
            )
            self._running_tasks[action_id] = task
            tasks.append(task)
        return tasks

    async def _cancel_tasks(self, tasks: Sequence[asyncio.Task[ActionObservation]]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _forget_tasks(self, tasks: Sequence[asyncio.Task[ActionObservation]]) -> None:
        for task in tasks:
            for action_id, current in tuple(self._running_tasks.items()):
                if current is task:
                    self._running_tasks.pop(action_id, None)

    async def _record_cancelled(self, action_ids: Sequence[str], round_index: int) -> None:
        for action_id in sorted(set(action_ids)):
            if action_id in self._observations:
                continue
            action = self._actions.get(action_id)
            if action is None:
                continue
            had_reservation = action_id in self._reservations
            usage = await self._reconcile_actual_usage(None, action)
            self._pending.discard(action_id)
            observation = self._failed_observation(
                action,
                round_index,
                self._gap(
                    action,
                    "cancelled",
                    "action cancelled before a terminal provider result",
                ),
                status=ActionStatus.REJECTED,
                started=datetime.now(UTC),
                metadata={"cancelled": True},
                usage=usage,
            )
            self._terminal[action_id] = observation
            self._observations[action_id] = observation
            if not had_reservation:
                self._count_unreserved_observation()

    def _refresh_elapsed(self) -> None:
        elapsed = max(0.0, time.monotonic() - self._started_monotonic)
        if elapsed > self._usage.elapsed_seconds:
            self._usage = self._usage.model_copy(update={"elapsed_seconds": elapsed})

    def _ensure_time_available(self) -> None:
        """Reject new work once either time ceiling is reached."""

        if (
            self.budget.max_wall_time_seconds is not None
            and self._usage.elapsed_seconds >= self.budget.max_wall_time_seconds
        ):
            raise _BudgetReservationError("wall_time_seconds")
        if self.budget.deadline_at is not None and datetime.now(UTC) >= self.budget.deadline_at:
            raise _BudgetReservationError("deadline")

    async def _reconcile_actual_usage(
        self,
        value: Any,
        action: Any,
    ) -> tuple[int, int, float]:
        """Release one reservation and record the provider's actual usage."""

        action_id = _action_id(action)
        async with self._usage_lock:
            reservation = self._reservations.pop(action_id, None)
            if reservation is None:
                return (0, 0, 0.0)
            reserved_calls, reserved_tokens, reserved_cost = reservation
            actual_tokens, actual_cost, actual_calls, has_tokens, has_cost, has_calls = _actual_usage_details(value)
            settled_tokens = actual_tokens if has_tokens else reserved_tokens
            settled_cost = actual_cost if has_cost else reserved_cost
            settled_calls = actual_calls if has_calls else reserved_calls
            self._reserved_tool_calls = max(0, self._reserved_tool_calls - reserved_calls)
            self._reserved_tokens = max(0, self._reserved_tokens - reserved_tokens)
            self._reserved_cost_units = max(0.0, self._reserved_cost_units - reserved_cost)
            self._usage = self._usage.model_copy(
                update={
                    "tool_calls": self._usage.tool_calls + settled_calls,
                    "tokens": self._usage.tokens + settled_tokens,
                    "cost_units": self._usage.cost_units + settled_cost,
                }
            )
        return (settled_calls, settled_tokens, settled_cost)

    def _coerce_action(self, action: Any, *, round_index: int, position: int) -> Any:
        if isinstance(action, Mapping):
            return coerce_action(action, run_id=self.run_id, round_index=round_index, position=position)
        if isinstance(action, ActionSpec):
            return action
        if not _action_id_or_none(action):
            return coerce_action(action, run_id=self.run_id, round_index=round_index, position=position)
        return action

    def _ready_actions(self) -> tuple[tuple[str, ...], tuple[tuple[str, ResearchGap], ...]]:
        ready: list[str] = []
        rejected: list[tuple[str, ResearchGap]] = []
        terminal = set(self._terminal)
        for action_id in sorted(self._pending):
            action = self._actions[action_id]
            dependencies = _dependencies(action)
            unknown = sorted(dep for dep in dependencies if dep not in self._actions and dep not in terminal)
            if unknown:
                rejected.append((action_id, self._gap(action, "dependency_unknown", f"unknown dependencies: {unknown!r}")))
                continue
            failed = sorted(
                dep
                for dep in dependencies
                if dep in self._terminal and not self._terminal[dep].completed
            )
            if failed:
                rejected.append((action_id, self._gap(action, "dependency_failed", f"dependencies failed: {failed!r}")))
                continue
            if all(dep in self._terminal for dep in dependencies):
                ready.append(action_id)
        return tuple(ready), tuple(rejected)

    async def _reserve_round(self, round_index: int) -> None:
        if round_index in self._rounds_started:
            return
        async with self._usage_lock:
            self._refresh_elapsed()
            maximum = self.budget.max_iterations
            if maximum is not None and self._usage.iterations + 1 > maximum:
                # The engine normally enforces round ceilings, but scheduler
                # users deserve a typed observation rather than an exception.
                raise _BudgetReservationError("iterations")
            self._ensure_time_available()
            self._usage = self._usage.model_copy(
                update={"iterations": self._usage.iterations + 1}
            )
            self._rounds_started.add(round_index)

    async def _reserve_action(self, action: Any) -> None:
        estimated_tokens = _token_estimate(action)
        estimated_calls = _call_estimate(action)
        estimated_cost = _cost_estimate(action)
        async with self._usage_lock:
            self._refresh_elapsed()
            checks = (
                ("actions", self.budget.max_actions, self._usage.actions + 1),
                (
                    "tool_calls",
                    self.budget.max_tool_calls,
                    self._usage.tool_calls + self._reserved_tool_calls + estimated_calls,
                ),
                (
                    "tokens",
                    self.budget.max_tokens,
                    self._usage.tokens + self._reserved_tokens + estimated_tokens,
                ),
                (
                    "cost_units",
                    self.budget.max_cost_units,
                    self._usage.cost_units + self._reserved_cost_units + estimated_cost,
                ),
                (
                    "observations",
                    self.budget.max_observations,
                    self._usage.observations + 1,
                ),
            )
            for dimension, maximum, value in checks:
                if maximum is not None and value > maximum:
                    raise _BudgetReservationError(dimension)
            self._ensure_time_available()
            self._usage = self._usage.model_copy(
                update={
                    "actions": self._usage.actions + 1,
                    "observations": self._usage.observations + 1,
                }
            )
            self._reservations[_action_id(action)] = (
                estimated_calls,
                estimated_tokens,
                estimated_cost,
            )
            self._reserved_tool_calls += estimated_calls
            self._reserved_tokens += estimated_tokens
            self._reserved_cost_units += estimated_cost

    async def _execute_one(
        self,
        action: Any,
        round_index: int,
        context: Mapping[str, Any] | None,
    ) -> ActionObservation:
        action_id = _action_id(action)
        self._pending.discard(action_id)
        started = datetime.now(UTC)
        capability = _capability(action)
        if not self._capability_allowed(capability):
            observation = self._failed_observation(
                action,
                round_index,
                self._gap(action, "unknown_capability", f"capability is unavailable: {capability}"),
                status=ActionStatus.REJECTED,
                started=started,
            )
            self._terminal[action_id] = observation
            self._observations[action_id] = observation
            self._count_unreserved_observation()
            return observation
        try:
            await self._reserve_action(action)
        except _BudgetReservationError as exc:
            observation = self._failed_observation(
                action,
                round_index,
                self._gap(action, "budget_exhausted", f"{exc.dimension} budget exhausted", details={"dimension": exc.dimension}),
                status=ActionStatus.REJECTED,
                started=started,
            )
            self._terminal[action_id] = observation
            self._observations[action_id] = observation
            self._count_unreserved_observation()
            return observation
        resource = _resource(action)
        semaphore = self._resource_semaphores.get(resource)
        try:
            async with self._semaphore:
                if semaphore is None:
                    semaphore = self._resource_semaphores.setdefault(
                        resource,
                        asyncio.Semaphore(self._resource_limits.get(resource, self.max_concurrency)),
                    )
                async with semaphore:
                    raw = await self._invoke(action, context)
            usage = await self._reconcile_actual_usage(raw, action)
            success = _result_success(raw)
            gap = _result_gap(raw, action) if not success else None
            status = ActionStatus.COMPLETED if success else ActionStatus.FAILED
            observation = ActionObservation(
                action_id=action_id,
                idempotency_key=_idempotency_key(action),
                kind=_kind(action),
                capability=capability,
                round_index=round_index,
                status=status,
                success=success,
                action=action,
                result=_normalized_result(raw),
                raw_return=raw,
                evidence_refs=_evidence_refs(raw, action),
                gap=gap,
                started_at=started,
                completed_at=datetime.now(UTC),
                tool_calls=usage[0],
                tokens_used=usage[1],
                cost_units=usage[2],
            )
        except _BudgetReservationError as exc:
            observation = self._failed_observation(
                action,
                round_index,
                self._gap(action, "budget_exhausted", f"{exc.dimension} budget exhausted", details={"dimension": exc.dimension}),
                status=ActionStatus.REJECTED,
                started=started,
            )
        except asyncio.CancelledError:
            usage = await self._reconcile_actual_usage(None, action)
            observation = self._failed_observation(
                action,
                round_index,
                self._gap(
                    action,
                    "cancelled",
                    "action cancelled before a terminal provider result",
                ),
                status=ActionStatus.REJECTED,
                started=started,
                metadata={"cancelled": True},
                usage=usage,
            )
            self._terminal[action_id] = observation
            self._observations[action_id] = observation
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors become typed gaps
            usage = await self._reconcile_actual_usage(None, action)
            observation = self._failed_observation(
                action,
                round_index,
                self._exception_gap(action, exc),
                status=ActionStatus.FAILED,
                started=started,
                usage=usage,
            )
        self._terminal[action_id] = observation
        self._observations[action_id] = observation
        return observation

    async def _invoke(self, action: Any, context: Mapping[str, Any] | None) -> Any:
        target = self.executor
        if target is not None:
            method = getattr(target, "execute", None)
            if method is None and callable(target):
                method = target
            if method is None:
                raise TypeError("action executor must provide execute")
            value = _invoke_callable(
                method,
                action=action,
                context=context,
                capability=_capability(action),
                arguments=_inputs(action),
                action_id=_action_id(action),
                idempotency_key=_idempotency_key(action),
            )
        else:
            target = self.tool_port
            method = None
            for name in ("call", "invoke", "execute"):
                method = getattr(target, name, None)
                if method is not None:
                    break
            if method is None and callable(target):
                method = target
            if method is None:
                raise TypeError("tool port must provide call/invoke/execute")
            value = _invoke_callable(
                method,
                action=action,
                context=context,
                capability=_capability(action),
                arguments=_inputs(action),
                action_id=_action_id(action),
                idempotency_key=_idempotency_key(action),
            )
        return await value if inspect.isawaitable(value) else value

    def _capability_allowed(self, capability: str) -> bool:
        if self._capabilities is None:
            return True
        return any(
            capability == allowed
            or capability.startswith(allowed + ".")
            or allowed == "*"
            for allowed in self._capabilities
        )

    def _record_preflight(self, action: Any, gap: ResearchGap, round_index: int) -> None:
        observation = self._failed_observation(
            action,
            round_index,
            gap,
            status=ActionStatus.REJECTED,
            started=datetime.now(UTC),
        )
        # A conflicting re-emission can have the same action id as an already
        # completed action.  Keep the original terminal observation as the
        # authoritative state; otherwise a rejected replay would overwrite a
        # successful result and make dependency resolution non-deterministic.
        action_id = _action_id(action)
        if action_id not in self._observations:
            self._terminal[action_id] = observation
            self._observations[action_id] = observation
        self._count_unreserved_observation()
        self._preflight.append(observation)

    def _reject(self, action_id: str, gap: ResearchGap, round_index: int) -> ActionObservation:
        action = self._actions[action_id]
        self._pending.discard(action_id)
        observation = self._failed_observation(
            action,
            round_index,
            gap,
            status=ActionStatus.REJECTED,
            started=datetime.now(UTC),
        )
        self._terminal[action_id] = observation
        self._observations[action_id] = observation
        self._count_unreserved_observation()
        return observation

    def _count_unreserved_observation(self) -> None:
        """Count a terminal record that did not reserve an action slot.

        Action execution reserves its observation budget before calling the
        provider. Policy, dependency, duplicate, and cancellation records
        can terminate before that reservation; they still consume an
        observation slot and must participate in the hard ceiling.
        """

        self._usage = self._usage.model_copy(
            update={"observations": self._usage.observations + 1}
        )

    def _failed_observation(
        self,
        action: Any,
        round_index: int,
        gap: ResearchGap,
        *,
        status: ActionStatus,
        started: datetime,
        metadata: Mapping[str, Any] | None = None,
        usage: tuple[int, int, float] = (0, 0, 0.0),
    ) -> ActionObservation:
        return ActionObservation(
            action_id=_action_id(action),
            idempotency_key=_idempotency_key(action),
            kind=_kind(action),
            capability=_capability(action),
            round_index=round_index,
            status=status,
            success=False,
            action=action,
            result=None,
            raw_return=None,
            evidence_refs=tuple(_action_evidence_refs(action)),
            gap=gap,
            started_at=started,
            completed_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
            tool_calls=usage[0],
            tokens_used=usage[1],
            cost_units=usage[2],
        )

    def _gap(
        self,
        action: Any,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> ResearchGap:
        return ResearchGap(
            source="adaptive",
            operation=_capability(action),
            code=code,
            message=message,
            retryable=code in {"action_failed", "provider_error", "timeout"},
            details={"action_id": _action_id(action), **dict(details or {})},
        )

    def _exception_gap(self, action: Any, exc: Exception) -> ResearchGap:
        code = str(getattr(exc, "code", "") or "action_failed")
        if code == "action_failed" and isinstance(exc, TimeoutError):
            code = "timeout"
        retryable = bool(getattr(exc, "retryable", False)) or isinstance(exc, (TimeoutError, ConnectionError, OSError))
        return ResearchGap(
            source="adaptive",
            operation=_capability(action),
            code=code,
            message=str(exc) or exc.__class__.__name__,
            retryable=retryable,
            details={"action_id": _action_id(action), "exception_type": exc.__class__.__name__},
        )


# Descriptive aliases for composition code.
InvestigationScheduler = ActionScheduler
BoundedActionScheduler = ActionScheduler


class _BudgetReservationError(RuntimeError):
    def __init__(self, dimension: str) -> None:
        super().__init__(f"{dimension} budget exhausted")
        self.dimension = dimension


def _create_eager_task(coro: Awaitable[ActionObservation], *, name: str) -> asyncio.Task[ActionObservation]:
    """Start an action coroutine immediately when Python 3.12 permits it.

    The eager start is part of the scheduler's observable wave contract: an
    integration that yields once after dispatch can inspect which independent
    calls actually began.  The project requires Python 3.12+, but retaining a
    small fallback keeps this helper usable by lightweight embedding hosts.
    """

    try:
        return asyncio.Task(
            coro,
            loop=asyncio.get_running_loop(),
            name=name,
            eager_start=True,
        )
    except (AttributeError, TypeError):  # pragma: no cover - compatibility for older hosts
        return asyncio.create_task(coro, name=name)


def _invoke_callable(method: Callable[..., Any], **values: Any) -> Any:
    """Adapt a small family of executor/tool signatures without SDK coupling."""

    try:
        params = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        params = []
    names = {item.name for item in params}
    if "action" in names and not ("capability" in names or "tool_name" in names):
        kwargs = {"action": values["action"]}
        for name in ("context", "idempotency_key", "action_id"):
            if name in names:
                kwargs[name] = values.get(name)
        for name in ("arguments", "inputs", "args", "payload"):
            if name in names:
                kwargs[name] = values["arguments"]
        return method(**kwargs)
    if "capability" in names or "tool_name" in names:
        first = "capability" if "capability" in names else "tool_name"
        kwargs = {first: values["capability"]}
        for name in ("arguments", "inputs", "args", "payload"):
            if name in names:
                kwargs[name] = values["arguments"]
                break
        if "context" in names:
            kwargs["context"] = values.get("context")
        for name in ("action", "idempotency_key", "action_id"):
            if name in names:
                kwargs[name] = values.get(name)
        return method(**kwargs)
    required = [item for item in params if item.default is inspect.Parameter.empty]
    if len(required) <= 1:
        return method(values["action"])
    if len(required) == 2:
        return method(values["capability"], values["arguments"])
    return method(values["action"], values.get("context"), values["capability"], values["arguments"])


def _action_id_or_none(action: Any) -> str | None:
    value = getattr(action, "action_id", None) or getattr(action, "id", None)
    return str(value) if value else None


def _advertised_capabilities(tool_port: Any) -> frozenset[str] | None:
    """Read a synchronous capability snapshot when an adapter exposes one."""

    if tool_port is None:
        return None
    value = getattr(tool_port, "capabilities", None)
    if callable(value):
        try:
            value = value()
        except TypeError:
            return None
    if isinstance(value, Mapping):
        return frozenset(str(item) for item in value)
    if isinstance(value, (str, bytes)):
        return frozenset({str(value)})
    if isinstance(value, Iterable):
        return frozenset(str(item) for item in value)
    return None


def _action_id(action: Any) -> str:
    value = _action_id_or_none(action)
    if value:
        return value
    raise ValueError("typed action must expose action_id or id")


def _idempotency_key(action: Any) -> str:
    value = getattr(action, "idempotency_key", None) or _action_id(action)
    return str(value)


def _kind(action: Any) -> str:
    value = getattr(action, "kind", None) or getattr(action, "type", None) or getattr(action, "action_type", None)
    return str(getattr(value, "value", value) or "generic")


def _capability(action: Any) -> str:
    value = getattr(action, "capability", None) or getattr(action, "tool", None) or _kind(action)
    return str(getattr(value, "value", value) or "generic")


def _resource(action: Any) -> str:
    value = getattr(action, "resource_class", None) or getattr(action, "resource", None) or _capability(action)
    return str(getattr(value, "value", value) or _capability(action))


def _dependencies(action: Any) -> tuple[str, ...]:
    values = getattr(action, "dependencies", ()) or ()
    return tuple(str(item) for item in values)


def _inputs(action: Any) -> Mapping[str, Any]:
    value = getattr(action, "inputs", None)
    if value is None:
        value = getattr(action, "input_contract", None)
    if value is None:
        value = getattr(action, "arguments", None)
    if isinstance(value, Mapping):
        return value
    if hasattr(action, "model_dump"):
        data = action.model_dump(mode="json")
        return data.get("inputs", data.get("arguments", {})) if isinstance(data, Mapping) else {}
    return {}


def _token_estimate(action: Any) -> int:
    value = getattr(action, "token_estimate", 0) or getattr(action, "estimated_tokens", 0) or 0
    budget = getattr(action, "budget", None)
    if not value and budget is not None:
        value = getattr(budget, "estimated_tokens", 0) or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _call_estimate(action: Any) -> int:
    budget = getattr(action, "budget", None)
    value = getattr(action, "estimated_tool_calls", 0) or 0
    if budget is not None:
        value = value or getattr(budget, "estimated_tool_calls", 0) or 0
    # Every admitted semantic action makes at least one gateway call unless a
    # separate executor explicitly reports otherwise.
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _cost_estimate(action: Any) -> float:
    budget = getattr(action, "budget", None)
    value = getattr(action, "cost_units", 0) or getattr(action, "estimated_cost_units", 0) or 0
    if budget is not None:
        value = value or getattr(budget, "estimated_cost_units", 0) or 0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _actual_usage(value: Any) -> tuple[int, float]:
    """Read optional provider usage metadata without coupling to an SDK."""

    tokens, cost, _calls, _has_tokens, _has_cost, _has_calls = _actual_usage_details(value)
    return tokens, cost


def _actual_usage_details(value: Any) -> tuple[int, float, int, bool, bool, bool]:
    """Return ``(tokens, cost, calls, has_*)`` from common adapter shapes."""

    def as_mapping(candidate: Any) -> Mapping[str, Any] | None:
        if isinstance(candidate, Mapping):
            return candidate
        if hasattr(candidate, "model_dump"):
            try:
                dumped = candidate.model_dump(mode="python")
            except TypeError:
                dumped = candidate.model_dump()
            if isinstance(dumped, Mapping):
                return dumped
        try:
            attrs = vars(candidate)
        except TypeError:
            return None
        return attrs if isinstance(attrs, Mapping) else None

    if value is None:
        return (0, 0.0, 0, False, False, False)
    payload = as_mapping(value)

    candidates: list[Mapping[str, Any]] = []
    if payload is not None:
        nested_candidates: list[Mapping[str, Any]] = []
        for key in ("metadata", "usage", "token_usage", "billing"):
            nested = as_mapping(payload.get(key))
            if nested is not None:
                nested_candidates.append(nested)
        metadata = as_mapping(payload.get("metadata"))
        if metadata is not None:
            for key in ("usage", "token_usage", "billing"):
                nested = as_mapping(metadata.get(key))
                if nested is not None:
                    nested_candidates.append(nested)
        # Provider-specific usage metadata is more authoritative than a
        # compatibility field such as ``tokens_used=0`` on an envelope.
        candidates.extend(nested_candidates)
        candidates.append(payload)
    else:
        candidates.append({
            key: getattr(value, key)
            for key in (
                "tokens_used",
                "tokens",
                "total_tokens",
                "input_tokens",
                "output_tokens",
                "prompt_tokens",
                "completion_tokens",
                "cost_units",
                "cost",
                "total_cost",
                "tool_calls",
                "calls",
            )
            if hasattr(value, key)
        })

    token_value: Any = 0
    cost_value: Any = 0.0
    calls_value: Any = 0
    has_tokens = has_cost = has_calls = False
    for candidate in candidates:
        if not has_tokens:
            for key in ("tokens_used", "tokens", "total_tokens", "totalTokens"):
                if key in candidate:
                    token_value = candidate[key]
                    has_tokens = True
                    break
            if not has_tokens:
                input_value = candidate.get("input_tokens", candidate.get("prompt_tokens"))
                output_value = candidate.get("output_tokens", candidate.get("completion_tokens"))
                if input_value is not None or output_value is not None:
                    token_value = (input_value or 0) + (output_value or 0)
                    has_tokens = True
        if not has_cost:
            for key in ("cost_units", "cost", "total_cost", "price"):
                if key in candidate:
                    cost_value = candidate[key]
                    has_cost = True
                    break
        if not has_calls:
            for key in ("tool_calls", "calls", "total_tool_calls"):
                if key in candidate:
                    calls_value = candidate[key]
                    has_calls = True
                    break

    try:
        tokens = max(0, int(token_value or 0))
    except (TypeError, ValueError):
        tokens = 0
    try:
        cost = max(0.0, float(cost_value or 0.0))
    except (TypeError, ValueError):
        cost = 0.0
    try:
        calls = max(0, int(calls_value or 0))
    except (TypeError, ValueError):
        calls = 0
    return tokens, cost, calls, has_tokens, has_cost, has_calls


def _action_evidence_refs(action: Any) -> tuple[str, ...]:
    value = getattr(action, "evidence_refs", ()) or ()
    return tuple(str(item) for item in value if str(item))


def _stable_action(action: Any) -> str:
    if hasattr(action, "model_dump"):
        return stable_json(action.model_dump(mode="json"))
    if isinstance(action, Mapping):
        return stable_json(action)
    return stable_json({name: getattr(action, name) for name in dir(action) if not name.startswith("_") and name in {"action_id", "kind", "dependencies", "idempotency_key", "capability", "inputs"}})


def _result_success(value: Any) -> bool:
    if isinstance(value, ActionObservation):
        return value.success
    if isinstance(value, ResearchActionResult):
        return value.success
    if value is None:
        return False
    if isinstance(value, Mapping):
        if "success" in value:
            return value["success"] is True and _has_result_payload(value)
        # Compatibility adapters commonly omit ``success`` for a successful
        # payload, but the payload must still expose a recognized result
        # shape.  Arbitrary dictionaries are not successful results.
        return any(
            key in value
            for key in (
                "output",
                "data",
                "value",
                "result",
                "source_envelopes",
                "notes",
                "insights",
                "profiles",
                "claims",
                "entities",
                "controversies",
                "items",
                "evidence_refs",
                "evidence_ref",
                "citations",
                "references",
                "refs",
            )
        )
    success = getattr(value, "success", None)
    if success is not None:
        return success is True and _has_result_payload(value)
    return any(
        getattr(value, key, None) is not None
        for key in (
            "output",
            "data",
            "value",
            "result",
            "source_envelopes",
            "notes",
            "insights",
            "profiles",
            "claims",
            "entities",
            "controversies",
            "evidence_refs",
            "evidence_ref",
            "citations",
            "references",
            "refs",
        )
    )


def _normalized_result(value: Any) -> Any:
    if isinstance(value, ActionObservation):
        return value.result
    if isinstance(value, ResearchActionResult):
        return value
    if isinstance(value, Mapping):
        for key in ("output", "data", "value", "result"):
            if key in value:
                return value[key]
    for key in ("output", "data", "value", "result"):
        item = getattr(value, key, None)
        if item is not None:
            return item
    return value


def _result_gap(value: Any, action: Any) -> ResearchGap:
    if isinstance(value, ResearchActionResult) and value.gaps:
        return value.gaps[0]
    if value is None:
        return ResearchGap(
            source="adaptive",
            operation=_capability(action),
            code="missing_result",
            message="action returned no result",
            retryable=True,
            details={"action_id": _action_id(action), "result_type": "none"},
        )
    if isinstance(value, Mapping):
        gap = value.get("gap")
        if isinstance(gap, ResearchGap):
            return gap
        if isinstance(gap, Mapping):
            return ResearchGap.model_validate(gap)
        if not _supported_result_mapping(value):
            return ResearchGap(
                source="adaptive",
                operation=_capability(action),
                code="unsupported_result_shape",
                message="action returned an unsupported result shape",
                retryable=False,
                details={
                    "action_id": _action_id(action),
                    "result_type": "mapping",
                    "keys": sorted(str(key) for key in value),
                },
            )
        code = value.get("error_code") or value.get("code") or "action_failed"
        message = value.get("error_message") or value.get("message") or "action returned unsuccessful"
    else:
        gap = getattr(value, "gap", None)
        if isinstance(gap, ResearchGap):
            return gap
        if not _supported_result_object(value):
            return ResearchGap(
                source="adaptive",
                operation=_capability(action),
                code="unsupported_result_shape",
                message="action returned an unsupported result shape",
                retryable=False,
                details={
                    "action_id": _action_id(action),
                    "result_type": type(value).__name__,
                },
            )
        code = getattr(value, "error_code", None) or getattr(value, "code", None) or "action_failed"
        message = getattr(value, "error_message", None) or getattr(value, "message", None) or "action returned unsuccessful"
    return ResearchGap(
        source="adaptive",
        operation=_capability(action),
        code=str(code),
        message=str(message),
        retryable=False,
        details={"action_id": _action_id(action)},
    )


def _supported_result_mapping(value: Mapping[str, Any]) -> bool:
    """Return whether a mapping is a recognized adapter result envelope."""

    if "success" in value and value["success"] is not True:
        return True
    return _has_result_payload(value)


def _has_result_payload(value: Any) -> bool:
    keys = (
        "output",
        "data",
        "value",
        "result",
        "source_envelopes",
        "notes",
        "insights",
        "profiles",
        "claims",
        "entities",
        "controversies",
        "gaps",
        "items",
        "evidence_refs",
        "evidence_ref",
        "citations",
        "references",
        "refs",
        "error_code",
        "error_message",
        "gap",
    )
    if isinstance(value, Mapping):
        return any(key in value for key in keys)
    return any(hasattr(value, key) for key in keys)


def _supported_result_object(value: Any) -> bool:
    if hasattr(value, "success") and value.success is not True:
        return True
    return _has_result_payload(value)


def _evidence_refs(value: Any, action: Any) -> tuple[str, ...]:
    refs: set[str] = set(_action_evidence_refs(action))
    if isinstance(value, Mapping):
        for key in ("evidence_refs", "evidence_ref", "citations", "references", "refs"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                refs.add(candidate)
            elif isinstance(candidate, Sequence):
                refs.update(str(item) for item in candidate if str(item))
    else:
        for key in ("evidence_refs", "evidence_ref", "citations", "references", "refs"):
            candidate = getattr(value, key, None)
            if isinstance(candidate, str):
                refs.add(candidate)
            elif isinstance(candidate, Sequence):
                refs.update(str(item) for item in candidate if str(item))
    return tuple(sorted(refs))


class ScriptedToolPort:
    """Deterministic async ToolPort fake with call/concurrency telemetry."""

    def __init__(self, handlers: Mapping[str, Any] | None = None, *, default: Any = None, delay: float = 0.0) -> None:
        self.handlers = dict(handlers or {})
        self.default = default
        self.delay = max(0.0, float(delay))
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self.active = 0
        self.max_active = 0

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.handlers)

    async def call(self, capability: str, arguments: Mapping[str, Any], action: Any | None = None) -> Any:
        self.calls.append((capability, dict(arguments)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            value = self.handlers.get(capability, self.default)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                value = value[0] if value else None
            if callable(value):
                try:
                    value = value(action, arguments)
                except TypeError:
                    value = value(arguments)
            return await value if inspect.isawaitable(value) else value
        finally:
            self.active -= 1


DeterministicFakeTool = ScriptedToolPort
FakeToolPort = ScriptedToolPort


__all__ = [
    "ActionExecutor",
    "ActionObservation",
    "ActionResult",
    "ActionScheduler",
    "ActionStatus",
    "AdaptiveBudget",
    "BoundedActionScheduler",
    "BudgetUsage",
    "DeterministicFakeTool",
    "FakeToolPort",
    "InvestigationBudget",
    "InvestigationScheduler",
    "InvestigationSchedulerState",
    "RunBudget",
    "SchedulerResult",
    "SchedulerState",
    "ScriptedToolPort",
    "ToolPort",
    "WaveResult",
]
