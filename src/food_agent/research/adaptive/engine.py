"""Rolling-horizon Plan -> Act -> Observe -> Critique engine."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast

from pydantic import ConfigDict, Field, PrivateAttr, field_validator

from food_agent.contracts import (
    ContractModel,
    ContractPayload,
    InvestigationBudget,
    Objective,
    PlanProposal,
    PlanProposalStatus,
    ResearchGap,
    ResearchOutcome,
    SourceCall,
    Termination,
)
from food_agent.contracts import (
    InvestigationState as CanonicalInvestigationState,
)
from food_agent.contracts import (
    ObservationKind as TelemetryObservationKind,
)
from food_agent.contracts import (
    ObservationOutcome as TelemetryObservationOutcome,
)
from food_agent.contracts.adaptive_investigation import (
    CritiqueDecision as CanonicalCritiqueDecision,
)
from food_agent.contracts.adaptive_investigation import (
    CritiqueDisposition,
    InvestigationStatus,
    ObservationCompleteness,
    ObservationEnvelope,
    ObservationKind,
    ObservationOutcome,
    TerminationReason,
    ToolCapabilityMetadata,
)

from .critic import AdaptiveCritic, CriticDecision, parse_critic_decision
from .planner import (
    ActionSpec,
    AdaptivePlanner,
    PlannerDecision,
    attach_model_usage,
    coerce_action,
    parse_planner_decision,
    stable_json,
)
from .scheduler import (
    ActionObservation,
    ActionScheduler,
    ActionStatus,
    ToolPort,
    WaveResult,
)


class InvestigationRequest(ContractModel):
    """Input envelope for one single-Agent investigation."""

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    goal: str | Mapping[str, Any]
    run_id: str = Field(default="run", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

class InvestigationRound(ContractModel):
    """Complete audit record for one rolling horizon."""

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    round_index: int = Field(ge=0)
    plan: PlannerDecision
    observations: tuple[ActionObservation, ...] = ()
    wave: WaveResult | None = None
    critique: CriticDecision | None = None
    raw_tool_returns: tuple[Any, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Provider returns can be SDK objects that cannot be represented in the
    # canonical state JSON. Keep them available to the in-memory audit/run
    # projection without allowing them into ``model_dump_json``.
    _native_raw_tool_returns: tuple[Any, ...] = PrivateAttr(default=())

    @field_validator("evidence_refs")
    @classmethod
    def _unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("round evidence references must be non-empty")
        return tuple(dict.fromkeys(values))

    @property
    def native_raw_tool_returns(self) -> tuple[Any, ...]:
        """Original provider returns retained only in the process audit."""

        return self._native_raw_tool_returns

# The adaptive runtime has one state authority.  This alias is deliberately
# kept in the engine module so existing composition imports continue to point
# at the canonical contract rather than a second model.
InvestigationState = CanonicalInvestigationState
InvestigationResult = CanonicalInvestigationState
AdaptiveInvestigationState = CanonicalInvestigationState


class InvestigationLoop:
    """One Agent that replans from observed evidence until a bounded stop."""

    def __init__(
        self,
        planner: AdaptivePlanner | Any,
        critic: AdaptiveCritic | Any,
        scheduler: ActionScheduler | None = None,
        *,
        executor: Any | None = None,
        tool_port: ToolPort | Any | None = None,
        capabilities: Sequence[str] | None = None,
        max_rounds: int = 5,
        budget: InvestigationBudget | Mapping[str, Any] | None = None,
        max_concurrency: int = 4,
        resource_limits: Mapping[str, int] | None = None,
        tool_snapshot_ref: str | None = None,
        tool_capabilities: Sequence[ToolCapabilityMetadata | Mapping[str, Any]] | None = None,
        observation_recorder: Any | None = None,
    ) -> None:
        if planner is None:
            raise ValueError("an adaptive planner is required")
        if critic is None:
            raise ValueError("an adaptive critic is required")
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        self.planner = planner
        self.critic = critic
        budget_was_provided = budget is not None
        effective_budget = (
            getattr(scheduler, "budget", None)
            if budget is None and scheduler is not None
            else budget
        )
        if effective_budget is None:
            effective_budget = InvestigationBudget()
        elif not isinstance(effective_budget, InvestigationBudget):
            effective_budget = InvestigationBudget.model_validate(effective_budget)
        self.max_rounds = max_rounds
        self.budget = effective_budget
        self._budget_was_provided = budget_was_provided
        self._scheduler = scheduler
        self._executor = executor
        self._tool_port = tool_port
        self._capabilities = capabilities
        self._tool_snapshot_ref = tool_snapshot_ref or _read_snapshot_ref(scheduler, tool_port)
        self._tool_capabilities = _coerce_capabilities(tool_capabilities, capabilities)
        self._max_concurrency = max_concurrency
        self._resource_limits = resource_limits
        self._observation_recorder = observation_recorder
        self._state: InvestigationState | None = None
        self._run_task: asyncio.Task[InvestigationState] | None = None
        self._active_scheduler: ActionScheduler | None = None

    @property
    def state(self) -> InvestigationState | None:
        return self._state

    @property
    def scheduler(self) -> ActionScheduler | None:
        return self._active_scheduler or self._scheduler

    @property
    def rounds(self) -> tuple[InvestigationRound, ...]:
        return self._state.rounds if self._state is not None else ()

    async def run(
        self,
        goal: str | Mapping[str, Any] | InvestigationRequest,
        *,
        run_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> InvestigationState:
        """Run the bounded loop and return the complete audit state."""

        if self._run_task is not None and not self._run_task.done():
            raise RuntimeError("an investigation is already running")
        request = self._request(goal, run_id=run_id, metadata=metadata)
        objective = _objective_for(request)
        self._state = InvestigationState(
            investigation_id=request.run_id,
            status=InvestigationStatus.PLANNING,
            objective=objective,
            budget=self.budget,
            tool_capabilities=self._tool_capabilities,
            tool_snapshot_ref=self._tool_snapshot_ref,
            metadata=_json_safe(request.metadata),
            raw_payload=_json_safe(request.goal),
        )
        scheduler = self._get_scheduler(request.run_id)
        self._active_scheduler = scheduler
        self._run_task = asyncio.current_task()
        try:
            await self._run_loop(request, scheduler)
        except asyncio.CancelledError:
            # Drain the scheduler first so provider tasks have a terminal
            # observation before the run exposes its cancelled state.
            await scheduler.close()
            self._capture_scheduler_tail(scheduler)
            self._finish_state(
                status=InvestigationStatus.CANCELLED,
                outcome=ResearchOutcome.PARTIAL if self._has_evidence() else ResearchOutcome.FAILED,
                reason="investigation cancelled",
                continuation={
                    "cancelled": True,
                    "next_round": self._next_round_index(),
                },
            )
            raise
        finally:
            release = getattr(scheduler, "release_run", None)
            if callable(release):
                release(request.run_id)
            self._run_task = None
        return cast(InvestigationState, self._state)

    investigate = run
    execute = run

    async def aclose(self) -> None:
        """Cancel the active run and close its scheduler exactly once."""

        if self._run_task is not None and self._run_task is not asyncio.current_task():
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
        scheduler = self._active_scheduler or self._scheduler
        if scheduler is not None:
            await scheduler.close()

    async def _run_loop(self, request: InvestigationRequest, scheduler: ActionScheduler) -> None:
        state = cast(InvestigationState, self._state)
        for round_index in range(self.max_rounds):
            if self._model_budget_dimensions(scheduler):
                self._finish_budget(scheduler, round_index)
                return
            state = cast(InvestigationState, self._state)
            self._set_state_status(InvestigationStatus.RUNNING)
            mode = "initial" if round_index == 0 else "replan"
            # The canonical state critique is the model-facing contract.  A
            # round also keeps the permissive adapter decision for audit, but
            # feeding that legacy shape back into the next planner loses the
            # disposition (`decision`) and creates two competing vocabularies.
            previous_critique = state.critique
            try:
                plan = await self._plan(
                    request.goal,
                    state=state,
                    run_id=request.run_id,
                    round_index=round_index,
                    mode=mode,
                    critique=previous_critique,
                    tool_capabilities=self._tool_capabilities,
                    tool_snapshot_ref=self._tool_snapshot_ref,
                )
                await scheduler.record_usage(plan.raw_output)
            except Exception as exc:  # noqa: BLE001 - model boundary becomes typed gap
                self._append_gap(
                    self._model_gap("planner", exc),
                )
                self._finish_state(
                    status=InvestigationStatus.PARTIAL if self._has_evidence() else InvestigationStatus.FAILED,
                    outcome=self._outcome_for_state(),
                    reason="planner model failed",
                    continuation={"round_index": round_index, "model_error": True},
                )
                return
            self._append_gaps(plan.gaps)
            try:
                canonical_plan = self._canonical_plan(plan, request, round_index)
            except Exception as exc:  # noqa: BLE001 - stale plan becomes typed gap
                self._append_gap(self._model_gap("planner", exc, code="plan_identity_invalid"))
                self._finish_state(
                    status=InvestigationStatus.PARTIAL if self._has_evidence() else InvestigationStatus.FAILED,
                    outcome=self._outcome_for_state(),
                    reason="planner returned a stale or invalid plan",
                    continuation={"round_index": round_index, "plan_rejected": True},
                )
                return
            self._record_plan(canonical_plan)
            if self._model_budget_dimensions(scheduler):
                self._finish_budget(scheduler, round_index)
                return
            if plan.stop:
                self._finish_state(
                    status=InvestigationStatus.STOPPED,
                    outcome=self._outcome_for_state(),
                    reason=plan.reason or "planner requested stop",
                    continuation={"round_index": round_index, "planner_stop": True},
                )
                return
            actions = self._normalize_actions(plan.all_actions, request.run_id, round_index)
            if not actions:
                self._finish_state(
                    status=InvestigationStatus.PARTIAL if self._has_evidence() else InvestigationStatus.EMPTY,
                    outcome=self._outcome_for_state(),
                    reason=plan.reason or "planner returned no actions",
                    continuation={"round_index": round_index, "no_actions": True},
                )
                return
            wave = await scheduler.execute(
                actions,
                round_index=round_index,
                context=self._execution_context(
                    request, cast(InvestigationState, self._state)
                ),
            )
            self._observe_wave(wave)
            if self._budget_dimensions(scheduler):
                self._finish_budget(scheduler, round_index)
                return
            observations = wave.observations
            try:
                critique = await self._critique(
                    request.goal,
                    state=cast(InvestigationState, self._state),
                    observations=observations,
                    round_index=round_index,
                    previous_critique=previous_critique,
                    tool_capabilities=self._tool_capabilities,
                    tool_snapshot_ref=self._tool_snapshot_ref,
                )
            except Exception as exc:  # noqa: BLE001 - model boundary becomes typed gap
                critique = CriticDecision(
                    stop=True,
                    reason="critic model failed",
                    gaps=(self._model_gap("critic", exc),),
                    raw_output={"error": str(exc)},
                )
            await scheduler.record_usage(critique.raw_output)
            self._append_gaps(critique.gaps)
            self._append_findings(critique)
            self._set_canonical_critique(critique, wave, round_index)
            self._record_round(round_index, plan, wave, critique)
            if self._budget_dimensions(scheduler):
                self._finish_budget(scheduler, round_index)
                return
            if critique.stop:
                self._finish_state(
                    status=InvestigationStatus.STOPPED,
                    outcome=self._outcome_for_state(),
                    reason=critique.reason or "critic requested stop",
                    continuation={"round_index": round_index, "critic_stop": True},
                )
                return
            direct = self._normalize_actions(critique.appended_actions, request.run_id, round_index + 1)
            if direct:
                direct_wave = await scheduler.execute(
                    direct,
                    round_index=round_index,
                    context=self._execution_context(request, cast(InvestigationState, self._state)),
                )
                self._observe_wave(direct_wave)
                self._extend_last_round(direct_wave)
                if self._budget_dimensions(scheduler):
                    self._finish_budget(scheduler, round_index)
                    return
            if not critique.replan_required and not direct:
                self._finish_state(
                    status=InvestigationStatus.COMPLETED if self._has_evidence() and not self._has_failures() else InvestigationStatus.PARTIAL,
                    outcome=self._outcome_for_state(),
                    reason=critique.reason or "critic found no further action",
                    continuation={"round_index": round_index, "no_replan": True},
                )
                return
        self._finish_state(
            status=InvestigationStatus.PARTIAL if self._has_evidence() else InvestigationStatus.FAILED,
            outcome=self._outcome_for_state(),
            reason="maximum investigation rounds reached",
            continuation={"max_rounds": self.max_rounds, "next_round": self.max_rounds},
        )

    def _budget_dimensions(self, scheduler: ActionScheduler) -> tuple[str, ...]:
        return scheduler.budget.exhausted_dimensions(scheduler.usage)

    def _model_budget_dimensions(self, scheduler: ActionScheduler) -> tuple[str, ...]:
        """Return ceilings that must stop a future planner/critic call."""

        return tuple(
            dimension
            for dimension in self._budget_dimensions(scheduler)
            if dimension in {"iterations", "tokens", "cost_units", "wall_time_seconds", "deadline"}
        )

    def _finish_budget(self, scheduler: ActionScheduler, round_index: int) -> None:
        dimensions = self._budget_dimensions(scheduler)
        if not dimensions:
            return
        self._replace_state(
            budget_usage=scheduler.usage,
            updated_at=datetime.now(UTC),
        )
        dimension = dimensions[0]
        reason = (
            "investigation deadline exceeded"
            if dimension == "deadline"
            else "wall time budget exhausted"
            if dimension == "wall_time_seconds"
            else f"{dimension} budget exhausted"
        )
        self._finish_state(
            status=InvestigationStatus.PARTIAL if self._has_evidence() else InvestigationStatus.FAILED,
            outcome=self._outcome_for_state(),
            reason=reason,
            continuation={
                "round_index": round_index,
                "budget_exhausted": dimensions,
                "budget_usage": scheduler.usage.model_dump(mode="json"),
                "next_round": round_index,
            },
        )

    def _capture_scheduler_tail(self, scheduler: ActionScheduler) -> None:
        """Append observations produced before scheduler cancellation escaped."""

        state = cast(InvestigationState, self._state)
        known = {item.action_id for item in state.observations}
        tail = tuple(item for item in scheduler.observations if item.action_id not in known)
        if tail:
            wave = WaveResult(
                round_index=len(state.rounds),
                observations=tail,
                budget_usage=scheduler.usage,
            )
            self._observe_wave(wave)
            self._extend_last_round(wave)
        else:
            self._replace_state(
                budget_usage=scheduler.usage,
                updated_at=datetime.now(UTC),
            )

    def _next_round_index(self) -> int:
        state = cast(InvestigationState, self._state)
        return len(state.rounds)

    def _get_scheduler(self, run_id: str) -> ActionScheduler:
        if self._scheduler is not None:
            acquire = getattr(self._scheduler, "acquire_run", None)
            if callable(acquire):
                acquire(run_id)
            else:
                self._scheduler.reset(run_id=run_id)
            if self._budget_was_provided:
                self._scheduler.budget = self.budget
            if self._tool_port is not None and self._scheduler.executor is None:
                self._scheduler.bind_tool_port(self._tool_port, self._capabilities)
            return self._scheduler
        return ActionScheduler(
            executor=self._executor,
            tool_port=self._tool_port,
            capabilities=self._capabilities,
            max_concurrency=self._max_concurrency,
            resource_limits=self._resource_limits,
            budget=self.budget,
            run_id=run_id,
        )

    def _request(
        self,
        goal: str | Mapping[str, Any] | InvestigationRequest,
        *,
        run_id: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> InvestigationRequest:
        if isinstance(goal, InvestigationRequest):
            if run_id is None and metadata is None:
                return goal
            return goal.model_copy(
                update={
                    "run_id": run_id or goal.run_id,
                    "metadata": dict(metadata or goal.metadata),
                }
            )
        return InvestigationRequest(goal=goal, run_id=run_id or "run", metadata=dict(metadata or {}))

    async def _plan(self, goal: Any, **kwargs: Any) -> PlannerDecision:
        method = getattr(self.planner, "plan", None)
        if method is None:
            method = getattr(self.planner, "initial_plan" if kwargs.get("mode") == "initial" else "replan", None)
        if method is None:
            raise TypeError("planner must provide plan/initial_plan/replan")
        started = monotonic()
        try:
            raw = _invoke_component(method, goal, kwargs)
            raw = await raw if inspect.isawaitable(raw) else raw
            decision = (
                raw
                if isinstance(raw, PlannerDecision)
                else attach_model_usage(
                    parse_planner_decision(
                        raw,
                        run_id=str(kwargs.get("run_id", "run")),
                        round_index=int(kwargs.get("round_index", 0)),
                    ),
                    raw,
                )
            )
        except asyncio.CancelledError:
            self._record_model_call(
                "planner",
                started,
                "timeout",
            )
            raise
        except Exception as exc:
            self._record_model_call(
                "planner",
                started,
                "error",
                error_class=type(exc).__name__,
            )
            raise
        self._record_model_call(
            "planner",
            started,
            "partial" if decision.gaps else "ok",
        )
        return decision

    async def _critique(self, goal: Any, **kwargs: Any) -> CriticDecision:
        method = getattr(self.critic, "critique", None) or getattr(self.critic, "review", None)
        if method is None:
            raise TypeError("critic must provide critique/review")
        started = monotonic()
        try:
            raw = _invoke_component(method, goal, kwargs)
            raw = await raw if inspect.isawaitable(raw) else raw
            decision = (
                raw
                if isinstance(raw, CriticDecision)
                else attach_model_usage(parse_critic_decision(raw), raw)
            )
        except asyncio.CancelledError:
            self._record_model_call("critic", started, "timeout")
            raise
        except Exception as exc:
            self._record_model_call(
                "critic",
                started,
                "error",
                error_class=type(exc).__name__,
            )
            raise
        self._record_model_call(
            "critic",
            started,
            "partial" if decision.gaps else "ok",
        )
        return decision

    def _record_model_call(
        self,
        role: str,
        started: float,
        outcome: str,
        **attributes: Any,
    ) -> None:
        recorder = self._observation_recorder
        emit = getattr(recorder, "emit", None)
        if not callable(emit):
            return
        try:
            outcome_value = {
                "ok": TelemetryObservationOutcome.OK,
                "partial": TelemetryObservationOutcome.PARTIAL,
                "timeout": TelemetryObservationOutcome.TIMEOUT,
                "error": TelemetryObservationOutcome.ERROR,
            }.get(outcome, TelemetryObservationOutcome.ERROR)
            emit(
                TelemetryObservationKind.MODEL_CALL,
                "adaptive.model.call",
                outcome=outcome_value,
                duration_ms=(monotonic() - started) * 1000,
                correlation={"model_role": role},
                attributes={
                    "operation": "plan" if role == "planner" else "critique",
                    "status": outcome,
                    **attributes,
                },
            )
        except Exception:
            # Observation is explicitly non-authoritative for the Agent loop.
            return

    def _normalize_actions(self, actions: Sequence[Any], run_id: str, round_index: int) -> tuple[Any, ...]:
        normalized: list[Any] = []
        for position, action in enumerate(actions):
            # Preserve existing typed semantic actions for domain executors;
            # mappings and generic action values become local ActionSpec.
            if isinstance(action, ActionSpec) or _has_action_identity(action):
                normalized.append(action)
            else:
                normalized.append(
                    coerce_action(action, run_id=run_id, round_index=round_index, position=position)
                )
        return tuple(normalized)

    def _execution_context(self, request: InvestigationRequest, state: InvestigationState) -> dict[str, Any]:
        return {
            "run_id": request.run_id,
            "goal": request.goal,
            "metadata": dict(request.metadata),
            "state": state.model_dump(mode="json"),
        }

    def _canonical_plan(
        self,
        decision: PlannerDecision,
        request: InvestigationRequest,
        round_index: int,
    ) -> PlanProposal:
        """Pin a model decision to the current investigation revision."""

        state = cast(InvestigationState, self._state)
        expected_revision = state.revision + 1
        if decision.investigation_id and decision.investigation_id != request.run_id:
            raise ValueError("planner investigation_id does not match the active run")
        if decision.objective_id and decision.objective_id != state.objective.objective_id:
            raise ValueError("planner objective_id does not match the active objective")
        if (
            decision.tool_snapshot_ref != self._tool_snapshot_ref
            and (decision.tool_snapshot_ref is not None or self._tool_snapshot_ref is not None)
        ):
            raise ValueError("planner tool snapshot is stale or missing")
        # ``0`` was accepted by the prototype as an omitted revision, but on
        # a rolling state it is a stale proposal and must not bypass the
        # revision fence.  Keep that compatibility only for the initial state,
        # where the expected next revision is one.
        if (
            decision.revision is not None
            and decision.revision != expected_revision
            and not (state.revision == 0 and decision.revision == 0)
        ):
            raise ValueError("planner revision does not match the active state revision")
        if decision.base_revision is not None and decision.base_revision != state.revision:
            raise ValueError("planner base_revision does not match the active state revision")
        actions = tuple(
            coerce_action(
                item,
                run_id=request.run_id,
                round_index=round_index,
                position=position,
            )
            for position, item in enumerate(decision.all_actions)
        )
        # A rolling plan may intentionally depend on an action completed in a
        # previous horizon.  The canonical graph validator only sees the
        # current proposal, so project those external dependencies as already
        # satisfied while retaining the original action payload for the
        # scheduler/audit trail.
        current_ids = {item.action_id for item in actions}
        completed_ids = {
            str(item.action_id).split(":observation:", 1)[-1]
            for item in state.observations
            if item.outcome in {ObservationOutcome.SUCCESS, ObservationOutcome.PARTIAL}
        }
        actions = tuple(
            item.model_copy(
                update={
                    "depends_on": tuple(
                        dependency
                        for dependency in item.depends_on
                        if dependency in current_ids
                        or dependency not in completed_ids
                    )
                }
            )
            for item in actions
        )
        return PlanProposal(
            proposal_id=f"{request.run_id}:plan:{round_index}",
            investigation_id=request.run_id,
            objective_id=state.objective.objective_id,
            revision=expected_revision,
            base_revision=state.revision,
            status=PlanProposalStatus.ACCEPTED,
            actions=actions,
            rationale=decision.reason or f"adaptive {decision.mode if hasattr(decision, 'mode') else 'rolling'} plan",
            target_question_ids=(),
            target_hypothesis_ids=(),
            based_on_observation_ids=tuple(item.observation_id for item in state.observations),
            tool_snapshot_ref=self._tool_snapshot_ref,
            budget=self.budget,
            evidence_refs=state.evidence_refs,
            raw_payload=_json_safe(decision.raw_output),
        )

    def _record_plan(self, plan: PlanProposal) -> None:
        state = cast(InvestigationState, self._state)
        self._replace_state(
            revision=plan.revision,
            plan=plan,
            plan_history=(*state.plan_history, plan),
            critique=None,
            updated_at=datetime.now(UTC),
        )

    def _set_state_status(self, status: InvestigationStatus) -> None:
        state = cast(InvestigationState, self._state)
        if state.status is status or state.is_terminal:
            return
        self._replace_state(status=status, updated_at=datetime.now(UTC))

    def _set_canonical_critique(
        self,
        critique: CriticDecision,
        wave: WaveResult,
        round_index: int,
    ) -> None:
        state = cast(InvestigationState, self._state)
        if critique.stop:
            disposition = CritiqueDisposition.TERMINATE
        elif critique.replan_required:
            disposition = CritiqueDisposition.REPLAN
        elif critique.appended_actions:
            disposition = CritiqueDisposition.REQUEST_EVIDENCE
        else:
            disposition = CritiqueDisposition.CONTINUE
        canonical = CanonicalCritiqueDecision(
            decision_id=f"{state.investigation_id}:critique:{round_index}",
            investigation_id=state.investigation_id,
            decision=disposition,
            rationale=critique.reason or "adaptive evidence review completed",
            plan_revision=state.plan.revision if state.plan is not None else state.revision,
            observation_ids=tuple(
                dict.fromkeys(
                    f"{state.investigation_id}:observation:{item.action_id}"
                    for item in wave.observations
                )
            ),
            evidence_refs=critique.evidence_refs,
            confidence=critique.confidence,
            raw_payload=_json_safe(critique.raw_output),
        )
        self._replace_state(critique=canonical, updated_at=datetime.now(UTC))

    def _observe_wave(self, wave: WaveResult) -> None:
        state = cast(InvestigationState, self._state)
        existing_ids = {item.observation_id for item in state.observations}
        accepted: list[ObservationEnvelope] = []
        canonical_gaps: list[ResearchGap] = []
        for item in wave.observations:
            canonical = _canonical_observation(item, state.investigation_id)
            if canonical.gap is not None:
                canonical_gaps.append(canonical.gap)
            # Scheduler replays and conflicting duplicate preflight records
            # may carry the same semantic observation id.  State is append-only
            # and must retain the first raw payload rather than creating an
            # invalid duplicate; the wave's gap is still merged below.
            if canonical.observation_id in existing_ids:
                continue
            existing_ids.add(canonical.observation_id)
            accepted.append(canonical)
        observations = (*state.observations, *accepted)
        refs = tuple(sorted({*state.evidence_refs, *wave.evidence_refs}))
        gaps = _merge_gaps(
            (
                *state.gaps,
                *wave.gaps,
                *(item.gap for item in wave.observations if item.gap is not None),
                *canonical_gaps,
            )
        )
        self._replace_state(
            observations=observations,
            evidence_refs=refs,
            gaps=gaps,
            budget_usage=wave.budget_usage,
            updated_at=datetime.now(UTC),
        )

    def _record_round(
        self,
        round_index: int,
        plan: PlannerDecision,
        wave: WaveResult,
        critique: CriticDecision,
    ) -> None:
        state = cast(InvestigationState, self._state)
        native_returns = tuple(wave.raw_returns)
        safe_wave = _safe_wave(wave)
        round_record = InvestigationRound(
            round_index=round_index,
            plan=_safe_planner_decision(plan),
            observations=safe_wave.observations,
            wave=safe_wave,
            critique=_safe_critic_decision(critique),
            raw_tool_returns=safe_wave.raw_returns,
            evidence_refs=safe_wave.evidence_refs,
            gaps=_merge_gaps((*plan.gaps, *wave.gaps, *critique.gaps)),
        )
        object.__setattr__(round_record, "_native_raw_tool_returns", native_returns)
        self._replace_state(
            rounds=(*state.rounds, round_record),
            updated_at=datetime.now(UTC),
        )

    def _extend_last_round(self, wave: WaveResult) -> None:
        state = cast(InvestigationState, self._state)
        if not state.rounds:
            return
        last = state.rounds[-1]
        native_returns = (
            *getattr(last, "native_raw_tool_returns", ()),
            *wave.raw_returns,
        )
        safe_observations = (
            *getattr(last, "observations", ()),
            *tuple(_safe_action_observation(item) for item in wave.observations),
        )
        safe_raw_returns = tuple(_json_safe(item) for item in native_returns)
        merged = InvestigationRound(
            round_index=last.round_index,
            plan=last.plan,
            observations=safe_observations,
            wave=WaveResult(
                round_index=last.round_index,
                observations=safe_observations,
                raw_returns=safe_raw_returns,
                budget_usage=wave.budget_usage,
            ),
            critique=last.critique,
            raw_tool_returns=safe_raw_returns,
            evidence_refs=tuple(sorted({*last.evidence_refs, *wave.evidence_refs})),
            gaps=_merge_gaps((*last.gaps, *wave.gaps)),
            occurred_at=last.occurred_at,
        )
        object.__setattr__(merged, "_native_raw_tool_returns", native_returns)
        self._replace_state(rounds=(*state.rounds[:-1], merged))

    def _append_gap(self, gap: ResearchGap) -> None:
        state = cast(InvestigationState, self._state)
        self._replace_state(gaps=_merge_gaps((*state.gaps, gap)))

    def _append_gaps(self, gaps: Sequence[ResearchGap]) -> None:
        if gaps:
            state = cast(InvestigationState, self._state)
            self._replace_state(gaps=_merge_gaps((*state.gaps, *gaps)))

    def _append_findings(self, critique: CriticDecision) -> None:
        state = cast(InvestigationState, self._state)
        findings = (*state.findings, *(_json_safe(item) for item in critique.findings))
        controversies = (
            *state.controversies,
            *(_json_safe(item) for item in critique.new_controversies),
        )
        refs = tuple(sorted({*state.evidence_refs, *critique.evidence_refs}))
        self._replace_state(
            findings=findings,
            controversies=controversies,
            evidence_refs=refs,
        )

    def _finish_state(
        self,
        *,
        status: InvestigationStatus,
        outcome: ResearchOutcome,
        reason: str,
        continuation: Mapping[str, Any],
    ) -> None:
        state = cast(InvestigationState, self._state)
        self._replace_state(
            status=status,
            outcome=outcome,
            stop_reason=reason,
            continuation=_json_safe({**state.continuation, **dict(continuation)}),
            termination=Termination(
                termination_id=f"{state.investigation_id}:termination:{state.revision + 1}",
                investigation_id=state.investigation_id,
                reason=_termination_reason(
                    reason,
                    continuation,
                    has_evidence=self._has_evidence(),
                    has_failures=self._has_failures(),
                ),
                summary=reason or "investigation terminated",
                evidence_refs=state.evidence_refs,
                continuation=_json_safe({**state.continuation, **dict(continuation)}),
                resumable=bool(continuation.get("next_round") is not None),
                raw_payload=_json_safe(dict(continuation)),
            ),
            revision=state.revision + 1,
            updated_at=datetime.now(UTC),
        )

    def _replace_state(self, **updates: Any) -> None:
        """Apply one update through the canonical contract validator.

        Pydantic's ``model_copy(update=...)`` intentionally skips validation.
        Runtime state is security- and audit-sensitive, so every transition is
        rebuilt and validated before it becomes observable to the caller.
        """

        state = cast(InvestigationState, self._state)
        payload = {
            name: getattr(state, name)
            for name in type(state).model_fields
        }
        payload.update(updates)
        self._state = InvestigationState.model_validate(payload)

    def _has_evidence(self) -> bool:
        state = cast(InvestigationState, self._state)
        return bool(state.evidence_refs or any(item.raw_payload is not None for item in state.observations))

    def _has_failures(self) -> bool:
        state = cast(InvestigationState, self._state)
        return any(
            item.outcome in {
                ObservationOutcome.FAILURE,
                ObservationOutcome.REJECTED,
                ObservationOutcome.SKIPPED,
            }
            for item in state.observations
        ) or bool(state.gaps)

    def _outcome_for_state(self) -> ResearchOutcome:
        if self._has_failures():
            return ResearchOutcome.PARTIAL if self._has_evidence() else ResearchOutcome.FAILED
        return ResearchOutcome.COMPLETE if self._has_evidence() else ResearchOutcome.EMPTY

    @staticmethod
    def _model_gap(role: str, exc: Exception, *, code: str = "model_error") -> ResearchGap:
        return ResearchGap(
            source="adaptive",
            operation=role,
            code=code,
            message=str(exc) or exc.__class__.__name__,
            retryable=True,
            details={"exception_type": exc.__class__.__name__},
        )


AdaptiveInvestigationAgent = InvestigationLoop
AdaptiveAgent = InvestigationLoop
RollingInvestigationLoop = InvestigationLoop


def _json_safe(value: Any) -> Any:
    """Convert provider/model values to the canonical JSON payload shape."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in {float("inf"), float("-inf")} else str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, bytes, bytearray)):
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, (str, int, float, bool)) or enum_value is None:
            return _json_safe(enum_value)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _safe_action_observation(item: ActionObservation) -> ActionObservation:
    """Snapshot an execution observation without an opaque provider object."""

    return item.model_copy(
        update={
            "action": _json_safe(item.action),
            "result": _json_safe(item.result),
            "raw_return": _json_safe(item.raw_return),
            "metadata": _json_safe(item.metadata),
        }
    )


def _safe_wave(wave: WaveResult) -> WaveResult:
    observations = tuple(_safe_action_observation(item) for item in wave.observations)
    return WaveResult(
        round_index=wave.round_index,
        observations=observations,
        action_ids=wave.action_ids,
        evidence_refs=wave.evidence_refs,
        raw_returns=tuple(_json_safe(item) for item in wave.raw_returns),
        gaps=wave.gaps,
        budget_usage=wave.budget_usage,
    )


def _safe_planner_decision(decision: PlannerDecision) -> PlannerDecision:
    return decision.model_copy(
        update={
            "actions": tuple(_safe_plan_action(item) for item in decision.actions),
            "append_actions": tuple(
                _safe_plan_action(item) for item in decision.append_actions
            ),
            "raw_output": _json_safe(decision.raw_output),
        }
    )


def _safe_critic_decision(decision: CriticDecision) -> CriticDecision:
    return decision.model_copy(
        update={
            "actions": tuple(_safe_plan_action(item) for item in decision.actions),
            "additional_actions": tuple(
                _safe_plan_action(item) for item in decision.additional_actions
            ),
            "findings": tuple(_json_safe(item) for item in decision.findings),
            "new_controversies": tuple(
                _json_safe(item) for item in decision.new_controversies
            ),
            "raw_output": _json_safe(decision.raw_output),
        }
    )


def _safe_plan_action(action: Any) -> Any:
    if hasattr(action, "model_copy"):
        return action.model_copy(
            update={"raw_payload": _json_safe(getattr(action, "raw_payload", None))}
        )
    return _json_safe(action)


def _objective_for(request: InvestigationRequest) -> Objective:
    goal = request.goal
    if isinstance(goal, Mapping):
        statement = goal.get("objective") or goal.get("statement") or goal.get("description") or goal.get("goal")
        objective_id = goal.get("objective_id") or f"{request.run_id}:objective"
        success_criteria = goal.get("success_criteria", ())
        constraints = goal.get("constraints", {})
    else:
        statement = goal
        objective_id = f"{request.run_id}:objective"
        success_criteria = ()
        constraints = {}
    text = str(statement or "investigate the user request").strip()
    criteria = (str(success_criteria),) if isinstance(success_criteria, str) else tuple(str(item) for item in success_criteria or ())
    return Objective(
        objective_id=str(objective_id),
        statement=text,
        success_criteria=criteria,
        constraints=_json_safe(constraints),
        raw_payload=_json_safe(goal),
    )


def _coerce_capabilities(
    descriptors: Sequence[ToolCapabilityMetadata | Mapping[str, Any]] | None,
    names: Sequence[str] | None,
) -> tuple[ToolCapabilityMetadata, ...]:
    if descriptors is not None:
        result: list[ToolCapabilityMetadata] = []
        for descriptor in descriptors:
            result.append(
                descriptor
                if isinstance(descriptor, ToolCapabilityMetadata)
                else ToolCapabilityMetadata.model_validate(descriptor)
            )
        return tuple(result)
    return tuple(
        ToolCapabilityMetadata(name=str(name), capability=str(name))
        for name in (names or ())
    )


def _read_snapshot_ref(scheduler: Any, tool_port: Any) -> str | None:
    for owner in (scheduler, getattr(scheduler, "tool_port", None), tool_port):
        if owner is None:
            continue
        value = getattr(owner, "snapshot_ref", None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                value = None
        if value:
            return str(value)
    return None


def _canonical_observation(item: ActionObservation, investigation_id: str) -> ObservationEnvelope:
    status = item.status
    outcome = {
        ActionStatus.COMPLETED: ObservationOutcome.SUCCESS if item.success else ObservationOutcome.FAILURE,
        ActionStatus.FAILED: ObservationOutcome.FAILURE,
        ActionStatus.REJECTED: ObservationOutcome.REJECTED,
        ActionStatus.SKIPPED: ObservationOutcome.SKIPPED,
    }.get(status, ObservationOutcome.FAILURE)
    result = _json_safe(item.result)
    # ``SourceCall`` is the Gateway result envelope.  The canonical
    # observation must expose the provider payload itself as ``raw_payload``;
    # storing the serialized transport wrapper there would blur normalized
    # data and untouched source data for downstream reducers.
    raw_value = item.raw_return
    if isinstance(raw_value, SourceCall):
        # Some project/custom tool ports predate the lossless SourceCall
        # contract and only populate ``data``.  Treat that provider return as
        # the raw boundary value when no distinct raw payload exists; otherwise
        # a valid result would fail ObservationEnvelope validation and discard
        # the whole investigation round.
        provider_payload = (
            raw_value.raw_payload
            if raw_value.raw_payload is not None
            else raw_value.data
        )
        raw_payload = _json_safe(provider_payload)
        source_metadata = {
            "source_call": _json_safe(raw_value.model_dump(mode="python")),
        }
    else:
        raw_payload = _json_safe(raw_value)
        source_metadata = {}
    next_cursor, provider_has_more, completeness_value, continuation = _continuation_metadata(
        result,
        raw_value,
    )
    has_more = provider_has_more and bool(next_cursor)
    # The canonical contract cannot claim a continuation without a cursor. Do
    # not silently turn that provider signal into a complete result: retain a
    # partial marker and the original signal in continuation metadata so the
    # critic can request a bounded repair or surface the gap.
    if provider_has_more and not next_cursor:
        continuation["has_more_without_cursor"] = True
        if completeness_value in (None, "complete", "completed"):
            completeness_value = "partial"
    try:
        completeness = ObservationCompleteness(str(completeness_value))
    except ValueError:
        completeness = (
            ObservationCompleteness.PARTIAL
            if has_more
            else ObservationCompleteness.COMPLETE
            if outcome is ObservationOutcome.SUCCESS
            else ObservationCompleteness.UNKNOWN
        )
    capability = str(item.capability)
    source = _observation_source(capability, raw_value)
    canonical_gap = item.gap
    if canonical_gap is None and provider_has_more and not next_cursor:
        canonical_gap = ResearchGap(
            source="adaptive",
            operation=capability,
            code="continuation_missing_cursor",
            message="provider indicated more results but did not return a continuation cursor",
            retryable=False,
            details={
                "action_id": item.action_id,
                "has_more": True,
                "next_cursor": None,
            },
        )
    gap = canonical_gap.model_dump(mode="json") if canonical_gap is not None else None
    metadata: dict[str, Any] = {
        "status": status.value,
        "success": item.success,
        "action": _json_safe(item.action),
        **source_metadata,
        "usage": {
            "tool_calls": item.tool_calls,
            "tokens_used": item.tokens_used,
            "cost_units": item.cost_units,
        },
    }
    if gap is not None:
        metadata["gap"] = gap
    return ObservationEnvelope(
        observation_id=f"{investigation_id}:observation:{item.action_id}",
        investigation_id=investigation_id,
        action_id=item.action_id,
        kind=ObservationKind.TOOL_RESULT,
        outcome=outcome,
        observed_at=item.completed_at,
        source=source,
        capability=capability,
        data=result,
        raw_payload=raw_payload,
        evidence_refs=tuple(dict.fromkeys(item.evidence_refs)),
        cursor=(
            str(continuation.get("cursor"))
            if continuation.get("cursor") not in (None, "")
            else None
        ),
        next_cursor=str(next_cursor) if next_cursor else None,
        has_more=has_more,
        completeness=completeness,
        continuation=cast(ContractPayload, _json_safe(continuation)),
        provenance={"scheduler": "adaptive-action-scheduler/v1"},
        metadata=metadata,
    )


def _continuation_metadata(*values: Any) -> tuple[Any, bool, Any, dict[str, Any]]:
    """Read pagination signals from normalized or wrapped provider results."""

    queue: list[tuple[Any, int]] = [(value, 0) for value in values if value is not None]
    nodes: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    while queue:
        value, depth = queue.pop(0)
        if depth > 6:
            continue
        if isinstance(value, SourceCall):
            # SourceCall keeps normalized data and the untouched provider
            # envelope in separate attributes. Inspect both for cursors.
            queue.extend(
                (child, depth + 1)
                for child in (value.data, value.raw_payload, value.metadata)
                if child is not None
            )
            continue
        if hasattr(value, "model_dump") and not isinstance(value, (str, bytes, bytearray)):
            try:
                dumped = value.model_dump(mode="python")
            except TypeError:
                dumped = value.model_dump()
            if dumped is not value:
                queue.append((dumped, depth + 1))
            continue
        if isinstance(value, Mapping):
            marker = id(value)
            if marker in seen:
                continue
            seen.add(marker)
            nodes.append(value)
            for key in (
                "data",
                "output",
                "result",
                "payload",
                "response",
                "structuredContent",
                "structured_content",
                "structured",
                "content",
                "json",
                "pagination",
                "page_info",
                "pageInfo",
                "metadata",
            ):
                child = value.get(key)
                if isinstance(child, (Mapping, list, tuple)):
                    queue.append((child, depth + 1))
        elif isinstance(value, (list, tuple)):
            for child in value:
                if isinstance(child, (Mapping, list, tuple)):
                    queue.append((child, depth + 1))

    next_cursor: Any = None
    has_more = False
    completeness: Any = None
    continuation: dict[str, Any] = {}
    for node in nodes:
        if next_cursor is None:
            for key in (
                "next_cursor",
                "nextCursor",
                "next_page_token",
                "nextPageToken",
                "next_offset",
                "next_start_index",
                "cursor",
            ):
                candidate = node.get(key)
                if candidate not in (None, ""):
                    next_cursor = candidate
                    break
        if not has_more:
            for key in ("has_more", "hasMore", "has_next", "hasNext", "more"):
                if isinstance(node.get(key), bool):
                    has_more = bool(node[key])
                    break
        if completeness is None and node.get("completeness") not in (None, ""):
            raw_completeness = node.get("completeness")
            completeness = (
                raw_completeness.get("status", raw_completeness.get("state"))
                if isinstance(raw_completeness, Mapping)
                else raw_completeness
            )
        for key in (
            "cursor",
            "next_cursor",
            "nextCursor",
            "page",
            "offset",
            "page_size",
            "expected_count",
            "total",
        ):
            if key in node and node[key] not in (None, ""):
                continuation.setdefault(key, _json_safe(node[key]))
    if next_cursor is not None:
        continuation.setdefault("next_cursor", _json_safe(next_cursor))
    continuation.setdefault("provider_has_more", has_more)
    return next_cursor, has_more, completeness, continuation


def _observation_source(capability: str, raw_value: Any) -> str:
    """Keep provider identity while normalizing the two Food channels."""

    raw_source = getattr(raw_value, "source", None)
    if isinstance(raw_value, Mapping):
        raw_source = raw_source or raw_value.get("source") or raw_value.get("provider")
    if raw_source:
        normalized = str(raw_source).casefold().replace("-", "_")
        if normalized in {"xhs", "xhs_pc", "xiaohongshu"}:
            return "xhs"
        if normalized in {"dianping", "dp"}:
            return "dianping"
        return str(raw_source)
    if capability.startswith(("notes.", "comments.")):
        return "xhs"
    if capability.startswith(("places.", "reviews.")):
        return "dianping"
    return "adaptive"


def _termination_reason(
    reason: str,
    continuation: Mapping[str, Any],
    *,
    has_evidence: bool = False,
    has_failures: bool = False,
) -> TerminationReason:
    """Map a terminal event to a reason without inventing evidence sufficiency.

    ``evidence_sufficient`` is reserved for an explicit evidence/coverage
    conclusion backed by observed evidence.  Generic planner/critic stops,
    empty plans, and model failures remain operationally distinguishable.
    """

    text = f"{reason} {stable_json(continuation)}".casefold()
    if "cancel" in text:
        return TerminationReason.CANCELLED
    if "deadline" in text:
        return TerminationReason.DEADLINE_EXCEEDED
    if (
        "budget" in text
        or "wall_time" in text
        or "budget_exhausted" in continuation
        or "max_rounds" in continuation
        or "maximum investigation rounds" in text
    ):
        return TerminationReason.BUDGET_EXHAUSTED
    if "policy" in text or "capability" in text:
        return TerminationReason.POLICY_DENIED
    if (
        ("model" in text and ("fail" in text or "error" in text))
        or continuation.get("plan_rejected")
        or has_failures
    ):
        return TerminationReason.FAILED
    if "user" in text and ("request" in text or "stop" in text or "cancel" in text):
        return TerminationReason.USER_REQUESTED
    if "no progress" in text or "no action" in text or continuation.get("no_replan"):
        return TerminationReason.NO_PROGRESS
    explicit_evidence_semantics = any(
        marker in text
        for marker in (
            "evidence sufficient",
            "sufficient evidence",
            "enough evidence",
            "evidence collected",
            "evidence complete",
            "coverage met",
            "coverage complete",
            "meets threshold",
            "verified",
            "supported by evidence",
            "证据充分",
            "证据足够",
            "证据收集",
            "证据完成",
            "证据支持",
            "覆盖满足",
            "已核实",
        )
    )
    if has_evidence and explicit_evidence_semantics:
        return TerminationReason.EVIDENCE_SUFFICIENT
    return TerminationReason.NO_PROGRESS


def _invoke_component(method: Callable[..., Any], first: Any, values: Mapping[str, Any]) -> Any:
    """Call planner/critic fakes with only the parameters they declare."""

    try:
        signature = inspect.signature(method)
        params = list(signature.parameters.values())
    except (TypeError, ValueError):
        return method(first)
    names = {item.name for item in params}
    accepts_var_kwargs = any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in params
    )
    kwargs = (
        dict(values)
        if accepts_var_kwargs
        else {name: value for name, value in values.items() if name in names}
    )
    if "goal" in names:
        kwargs["goal"] = first
        return method(**kwargs)
    if params and params[0].name in {"request", "input", "prompt", "query"}:
        kwargs[params[0].name] = first
        return method(**kwargs)
    if "state" in names or "observations" in names:
        # Critic ports commonly expose ``critique(state, observations)`` and
        # intentionally do not receive the goal a second time.
        return method(**kwargs)
    if params and not kwargs:
        if any(item.name in names for item in ("state", "observations")):
            # Critic fakes often accept ``(state, observations)``.
            ordered = [values[name] for name in ("state", "observations") if name in names]
            return method(*ordered)
        return method(first)
    return method(first, **kwargs)


def _has_action_identity(value: Any) -> bool:
    return bool(getattr(value, "action_id", None) or getattr(value, "id", None))


def _merge_gaps(gaps: Sequence[ResearchGap]) -> tuple[ResearchGap, ...]:
    by_key: dict[str, ResearchGap] = {}
    for gap in gaps:
        key = stable_json(gap.model_dump(mode="json"))
        by_key[key] = gap
    return tuple(by_key[key] for key in sorted(by_key))


__all__ = [
    "AdaptiveAgent",
    "AdaptiveInvestigationAgent",
    "AdaptiveInvestigationState",
    "InvestigationLoop",
    "InvestigationRequest",
    "InvestigationResult",
    "InvestigationRound",
    "InvestigationState",
    "InvestigationStatus",
    "RollingInvestigationLoop",
]
