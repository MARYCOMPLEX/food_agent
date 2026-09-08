"""Production adapter for the adaptive Food investigation loop.

The adaptive engine deliberately knows nothing about MCP or Food.  This
module is the composition boundary for the Food use case:

* :class:`ManagedMcpToolPort` turns a semantic action into one call on the
  already policy-pinned MCP session;
* :class:`AdaptiveFoodResearchWorkflow` owns one session per turn, feeds the
  resulting observations through the Food Domain Pack, and projects the
  lossless run into the existing transport DTOs.

The adapter never interprets a provider payload by replacing it with a
summary.  The normalized Food projection is used for planning and rendering;
the original ``SourceCall`` values remain in ``AdaptiveWorkflowExecution.run``
and in the adaptive state audit payload.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from pydantic import TypeAdapter

from xhs_food.contracts import (
    AgentToolExecutionContext,
    CommentEvidence,
    ContractPayload,
    JsonValue,
    PlatformChannel,
    ResearchGap,
    ResearchOutcome,
    ResearchRunResult,
    ShopProfile,
    SourceCall,
    SourceEnvelope,
    ToolCapabilityMetadata,
    XhsNoteLead,
)
from xhs_food.contracts import (
    ObservationKind as TelemetryObservationKind,
)
from xhs_food.contracts import (
    ObservationOutcome as TelemetryObservationOutcome,
)
from xhs_food.contracts.adaptive_investigation import (
    ObservationEnvelope as CanonicalObservationEnvelope,
)
from xhs_food.domain_packs.food.adaptive_pack import (
    FoodAdaptationResult,
    FoodAdaptivePack,
    FoodEntityType,
    ObservationEnvelope,
)
from xhs_food.domain_packs.food.adaptive_pack import (
    provider_comment_items as food_provider_comment_items,
)
from xhs_food.domain_packs.food.adaptive_pack import (
    provider_items as food_provider_items,
)
from xhs_food.domain_packs.food.adaptive_pack import (
    provider_metadata as food_provider_metadata,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.schemas import (
    ConversationContext,
    RestaurantRecommendation,
    XHSFoodResponse,
)

from ..evidence import EvidenceLedger
from ..mcp import ManagedMcpToolSession
from .critic import AdaptiveCritic
from .engine import InvestigationLoop, InvestigationState
from .planner import AdaptivePlanner
from .scheduler import ActionScheduler
from .telemetry import recorder_for

SessionFactory = Callable[[], ManagedMcpToolSession | Awaitable[ManagedMcpToolSession]]
ProgressSink = Callable[[Mapping[str, Any]], Any]
_JSON_VALUE = TypeAdapter(JsonValue)


class FoodToolSource(StrEnum):
    """Provider selection used by the MCP adapter, never exposed to the model."""

    XHS = "xhs"
    DIANPING = "dianping"


@dataclass(frozen=True, slots=True)
class AdaptiveWorkflowExecution:
    """Result returned by the adaptive workflow transport boundary."""

    response: XHSFoodResponse
    run: ResearchRunResult
    intent: FoodSearchIntent | None = None
    state: InvestigationState | None = None
    adaptation: FoodAdaptationResult | None = None


# The transport facade only relies on these three attributes.  Keeping the
# name discoverable makes migration from the old workflow explicit without
# importing the old implementation back into the new route.
WorkflowExecution = AdaptiveWorkflowExecution


class ManagedMcpToolPort:
    """Route semantic actions through one managed, pinned MCP session.

    A Planner only emits a capability such as ``comments.search``.  It never
    receives a provider tool name, account token, or hidden execution
    context.  The session resolves the approved public tool and performs the
    schema translation at the boundary.
    """

    _XHS_CAPABILITIES = frozenset({
        "notes.search",
        "notes.detail",
        "comments.search",
        "comments.analyze",
    })
    _DIANPING_CAPABILITIES = frozenset({
        "places.search",
        "places.detail",
        "reviews.search",
    })

    def __init__(
        self,
        session: ManagedMcpToolSession,
        *,
        capabilities: Iterable[str] | None = None,
        observation_recorder: Any | None = None,
    ) -> None:
        self.session = session
        self._observation_recorder = observation_recorder
        self._capabilities = (
            frozenset(str(item) for item in capabilities)
            if capabilities is not None
            else None
        )

    @property
    def capabilities(self) -> frozenset[str] | None:
        """The capability snapshot visible to the scheduler's policy guard."""

        return self._capabilities

    @property
    def snapshot_ref(self) -> str | None:
        return self.session.snapshot_ref

    async def call(
        self,
        capability: str,
        arguments: Mapping[str, Any],
        action: Any | None = None,
    ) -> SourceCall:
        platform = self._platform_for(capability, action, arguments)
        started = monotonic()
        try:
            result = await self.session.call(platform, capability, dict(arguments))
        except asyncio.CancelledError:
            self._record_tool_call(
                capability,
                platform,
                started,
                TelemetryObservationOutcome.TIMEOUT,
            )
            raise
        except Exception as exc:
            self._record_tool_call(
                capability,
                platform,
                started,
                TelemetryObservationOutcome.ERROR,
                error_class=type(exc).__name__,
            )
            raise
        self._record_tool_call(
            capability,
            platform,
            started,
            (
                TelemetryObservationOutcome.OK
                if result.success
                else TelemetryObservationOutcome.PARTIAL
            ),
            status="success" if result.success else "failure",
        )
        return result

    def _record_tool_call(
        self,
        capability: str,
        platform: PlatformChannel,
        started: float,
        outcome: TelemetryObservationOutcome,
        **attributes: Any,
    ) -> None:
        recorder = self._observation_recorder
        emit = getattr(recorder, "emit", None)
        if not callable(emit):
            return
        emit(
            TelemetryObservationKind.MCP_TOOL_CALL,
            "adaptive.mcp.tool_call",
            outcome=outcome,
            duration_ms=(monotonic() - started) * 1000,
            correlation={"provider": platform.value},
            attributes={
                "operation": capability,
                "source": platform.value,
                **attributes,
            },
        )

    @classmethod
    def _platform_for(
        cls,
        capability: str,
        action: Any | None,
        arguments: Mapping[str, Any],
    ) -> PlatformChannel:
        explicit = _first_string(
            getattr(action, "source", None),
            arguments.get("source"),
            arguments.get("platform"),
        )
        if explicit:
            normalized = explicit.casefold().replace("-", "_")
            if normalized in {"xhs", "xiaohongshu", "xhs_pc"}:
                return PlatformChannel.XHS_PC
            if normalized in {"dianping", "dp"}:
                return PlatformChannel.DIANPING
            raise ValueError(f"unsupported Food tool source: {explicit}")
        if capability in cls._XHS_CAPABILITIES or capability.startswith("comments."):
            return PlatformChannel.XHS_PC
        if capability in cls._DIANPING_CAPABILITIES or capability.startswith("places."):
            return PlatformChannel.DIANPING
        if capability.startswith("reviews."):
            return PlatformChannel.DIANPING
        raise ValueError(f"cannot infer platform for capability: {capability}")


class _FoodAwarePlanner:
    """Add the current Food projection to each model planning turn."""

    def __init__(self, planner: Any, pack: FoodAdaptivePack) -> None:
        self._planner = planner
        self._pack = pack

    async def plan(self, goal: Any, **kwargs: Any) -> Any:
        return await self._invoke("plan", goal, kwargs)

    async def initial_plan(self, goal: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("mode", "initial")
        return await self._invoke("initial_plan", goal, kwargs)

    async def replan(self, goal: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("mode", "replan")
        return await self._invoke("replan", goal, kwargs)

    async def _invoke(self, method_name: str, goal: Any, kwargs: Mapping[str, Any]) -> Any:
        method = getattr(self._planner, method_name, None) or getattr(self._planner, "plan", None)
        if method is None:
            raise TypeError("Food planner must provide plan/initial_plan/replan")
        state = kwargs.get("state")
        enriched_goal = _enrich_goal(
            goal,
            _adapt_observations(self._pack, _state_observations(state)),
            pack=self._pack,
            run_id=_investigation_id(state, goal),
            existing_action_ids=_state_action_ids(state),
            include_comments=not bool(_state_observations(state)),
        )
        value = _invoke_named(method, enriched_goal, kwargs)
        return await value if inspect.isawaitable(value) else value


class _FoodAwareCritic:
    """Give the Critic normalized Food claims without hiding raw evidence."""

    def __init__(self, critic: Any, pack: FoodAdaptivePack) -> None:
        self._critic = critic
        self._pack = pack

    async def critique(self, goal: Any, **kwargs: Any) -> Any:
        method = getattr(self._critic, "critique", None) or getattr(self._critic, "review", None)
        if method is None:
            raise TypeError("Food critic must provide critique/review")
        state = kwargs.get("state")
        enriched_goal = _enrich_goal(
            goal,
            self._projection(state, kwargs.get("observations")),
            pack=self._pack,
            run_id=_investigation_id(state, goal),
            existing_action_ids=_state_action_ids(state),
            include_comments=not bool(_state_observations(state)),
        )
        value = _invoke_named(method, enriched_goal, kwargs)
        return await value if inspect.isawaitable(value) else value

    review = critique

    def _projection(
        self,
        state: Any,
        observations: Sequence[Any] = (),
    ) -> FoodAdaptationResult | None:
        values = list(_state_observations(state))
        known = {_observation_identity(value) for value in values}
        for observation in observations:
            identity = _observation_identity(observation)
            if identity in known:
                continue
            known.add(identity)
            values.append(observation)
        return _adapt_observations(self._pack, values)


class AdaptiveFoodResearchWorkflow:
    """Single-agent Food workflow backed by the rolling investigation loop."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        planner: AdaptivePlanner | Any,
        critic: AdaptiveCritic | Any,
        scheduler: ActionScheduler | None = None,
        domain_pack: FoodAdaptivePack | None = None,
        max_rounds: int = 5,
        budget: Mapping[str, Any] | Any | None = None,
        max_concurrency: int = 4,
        resource_limits: Mapping[str, int] | None = None,
        capabilities: Iterable[str] | None = None,
        tool_capabilities: Iterable[ToolCapabilityMetadata | Mapping[str, Any]] | None = None,
        evidence: EvidenceLedger | None = None,
        profiles: Any | None = None,
        observation_port: Any | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        if planner is None or critic is None:
            raise ValueError("Adaptive Food workflow requires planner and critic")
        self._session_factory = session_factory
        self._planner = planner
        self._critic = critic
        self._scheduler = scheduler
        self._domain_pack = domain_pack or FoodAdaptivePack()
        self._max_rounds = max_rounds
        self._budget = budget
        self._max_concurrency = max_concurrency
        self._resource_limits = resource_limits
        self._evidence = evidence or EvidenceLedger()
        self._profiles = profiles
        self._observation_port = observation_port
        self._tool_capabilities = tuple(
            item if isinstance(item, ToolCapabilityMetadata)
            else ToolCapabilityMetadata.model_validate(item)
            for item in (tool_capabilities or ())
        )
        self._capabilities = (
            frozenset(str(value) for value in capabilities)
            if capabilities is not None
            else None
        )

    @property
    def domain_pack(self) -> FoodAdaptivePack:
        return self._domain_pack

    async def execute(
        self,
        user_input: str,
        context: ConversationContext,
        *,
        tool_context: AgentToolExecutionContext | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> AdaptiveWorkflowExecution:
        """Execute one turn and preserve the complete adaptive audit result."""

        context.add_user_message(user_input)
        context.turn_count += 1
        authority = tool_context or AgentToolExecutionContext(
            tenant_ref="local-anonymous",
            platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        )
        run_id = f"food-adaptive:{uuid4().hex}"
        recorder = recorder_for(self._observation_port, run_id)
        scheduler: ActionScheduler | None = None
        session: ManagedMcpToolSession | None = None
        started = monotonic()
        recorder.emit(
            TelemetryObservationKind.AGENT_RUN,
            "adaptive.agent.run",
            outcome=TelemetryObservationOutcome.STARTED,
            attributes={"operation": "investigation", "status": "started"},
        )
        try:
            session = await _resolve_session(self._session_factory)
            await session.open(authority)
            capability_names = self._effective_capabilities(session)
            capability_descriptors = self._effective_tool_capabilities(
                session, capability_names
            )
            port = ManagedMcpToolPort(
                session,
                capabilities=capability_names,
                observation_recorder=recorder,
            )
            scheduler = self._scheduler or ActionScheduler(
                tool_port=port,
                capabilities=capability_names,
                max_concurrency=self._max_concurrency,
                resource_limits=self._resource_limits,
                budget=self._budget,
                run_id=run_id,
            )
            _bind_scheduler_port(scheduler, port, capability_names)
            loop = InvestigationLoop(
                _FoodAwarePlanner(self._planner, self._domain_pack),
                _FoodAwareCritic(self._critic, self._domain_pack),
                scheduler,
                max_rounds=self._max_rounds,
                budget=self._budget,
                max_concurrency=self._max_concurrency,
                resource_limits=self._resource_limits,
                tool_snapshot_ref=port.snapshot_ref,
                tool_capabilities=capability_descriptors,
                observation_recorder=recorder,
            )
            await _notify(
                progress_sink,
                "investigation_started",
                run_id=run_id,
                tool_snapshot_ref=port.snapshot_ref,
                capabilities=sorted(capability_names) if capability_names is not None else None,
            )
            goal = self._goal(user_input, context, run_id)
            state = await loop.run(goal, run_id=run_id)
            transform_started = monotonic()
            adaptation = _adapt_observations(self._domain_pack, state.observations)
            adaptation = adaptation or FoodAdaptationResult()
            adaptation = _merge_model_findings(
                self._domain_pack,
                adaptation,
                findings=state.findings,
                controversies=state.controversies,
            )
            adaptation = await self._persist_projection(adaptation)
            recorder.emit(
                TelemetryObservationKind.EVIDENCE_TRANSFORM,
                "adaptive.evidence.transform",
                outcome=TelemetryObservationOutcome.OK,
                duration_ms=(monotonic() - transform_started) * 1000,
                attributes={
                    "operation": "food_projection",
                    "item_count": len(state.observations),
                    "source_count": len(adaptation.entities),
                    "classification": "food_projection",
                },
            )
            execution = self._project(state, adaptation, context, run_id)
            terminal_outcome = _telemetry_outcome(execution.run.outcome)
            recorder.terminal(
                outcome=terminal_outcome,
                status=state.status.value
                if hasattr(state.status, "value")
                else str(state.status),
                duration_ms=(monotonic() - started) * 1000,
                attributes={
                    "operation": "investigation",
                    "item_count": len(state.observations),
                    "source_count": len(execution.run.evidence_refs),
                },
            )
            await _notify(
                progress_sink,
                "investigation_completed",
                run_id=run_id,
                outcome=execution.run.outcome.value,
                observation_count=len(state.observations),
                evidence_count=len(execution.run.evidence_refs),
                gap_count=len(execution.run.gaps),
            )
            return execution
        except asyncio.CancelledError:
            recorder.terminal(
                outcome=TelemetryObservationOutcome.TIMEOUT,
                status="cancelled",
                duration_ms=(monotonic() - started) * 1000,
                attributes={"operation": "investigation"},
            )
            raise
        except Exception as exc:
            recorder.terminal(
                outcome=TelemetryObservationOutcome.ERROR,
                status="failed",
                duration_ms=(monotonic() - started) * 1000,
                attributes={
                    "operation": "investigation",
                    "error_class": type(exc).__name__,
                },
            )
            raise
        finally:
            # Closing an injected scheduler must not close a caller-owned
            # scheduler; it is a queue object, not the MCP session owner.
            if self._scheduler is None and scheduler is not None:
                with suppress(Exception):
                    await scheduler.aclose()
            if session is not None:
                with suppress(Exception):
                    await session.close()

    async def run(self, *args: Any, **kwargs: Any) -> AdaptiveWorkflowExecution:
        """Explicit adapter alias matching the existing workflow boundary."""

        return await self.execute(*args, **kwargs)

    def _effective_capabilities(self, session: ManagedMcpToolSession) -> frozenset[str]:
        snapshot = session.snapshot
        projection = getattr(snapshot, "projection", ())
        snapshot_values = {
            str(item.capability)
            for item in projection
            if getattr(item, "capability", None)
        }
        if self._capabilities is None:
            return frozenset(snapshot_values)
        # An explicit allow-list can narrow a pinned snapshot, but never
        # expand it.  Test/fail-closed sessions without a catalog have no
        # projection, so their injected allow-list remains usable.
        if snapshot_values:
            return frozenset(self._capabilities & snapshot_values)
        return self._capabilities

    def _effective_tool_capabilities(
        self,
        session: ManagedMcpToolSession,
        names: frozenset[str],
    ) -> tuple[ToolCapabilityMetadata, ...]:
        """Project one immutable MCP snapshot into the planner contract."""

        if self._tool_capabilities:
            return tuple(
                descriptor
                for descriptor in self._tool_capabilities
                if descriptor.capability is None or str(descriptor.capability) in names
            )
        snapshot = session.snapshot
        tools_by_name = {
            str(item.name): item
            for item in getattr(snapshot, "tools", ())
            if getattr(item, "name", None)
        }
        values: list[ToolCapabilityMetadata] = []
        for projection in getattr(snapshot, "projection", ()):
            capability = str(getattr(projection, "capability", "") or "")
            public_name = str(getattr(projection, "public_name", "") or capability)
            if not capability or capability not in names:
                continue
            definition = tools_by_name.get(public_name)
            input_schema = _capability_schema(
                definition,
                projection,
                field_name="input_schema",
            )
            output_schema = _capability_schema(
                definition,
                projection,
                field_name="output_schema",
            )
            capability_metadata = _capability_metadata(projection, definition)
            capability_metadata.update(
                {
                    "platform": str(
                        getattr(
                            getattr(projection, "platform", None),
                            "value",
                            getattr(projection, "platform", ""),
                        )
                    ),
                    "public_name": public_name,
                }
            )
            values.append(
                ToolCapabilityMetadata(
                    name=public_name,
                    capability=capability,
                    version=str(getattr(projection, "capability_version", "1.0")),
                    description=str(getattr(definition, "description", "") or ""),
                    input_schema=input_schema,
                    output_schema=output_schema,
                    side_effect=_capability_side_effect(projection, definition),
                    timeout_ms=_capability_int(
                        definition,
                        projection,
                        field_name="timeout_ms",
                        default=30_000,
                    ),
                    cost_units=_capability_float(
                        definition,
                        projection,
                        field_name="cost_units",
                        default=1.0,
                    ),
                    produces_evidence=_capability_bool(
                        definition,
                        projection,
                        capability_metadata,
                        field_name="produces_evidence",
                    ),
                    supports_pagination=_capability_bool(
                        definition,
                        projection,
                        capability_metadata,
                        field_name="supports_pagination",
                    ),
                    metadata=capability_metadata,
                    raw_payload=_capability_raw_payload(definition, projection),
                )
            )
        if values:
            return tuple(values)
        # A test/fail-closed session may advertise an explicit logical
        # allow-list without exposing a catalog object.  Still give Planner
        # and Critic a typed, provider-neutral capability description.
        return tuple(
            ToolCapabilityMetadata(name=name, capability=name)
            for name in sorted(names)
        )

    async def _persist_projection(self, adaptation: FoodAdaptationResult) -> FoodAdaptationResult:
        """Commit each evidence/profile projection through its owning boundary."""

        notes = _notes_from_adaptation(adaptation)
        persistence_gaps: list[ResearchGap] = []
        if notes:
            lifecycle_error_start = len(self._evidence.lifecycle_errors)
            try:
                await self._evidence.record_many(notes)
            except Exception as exc:  # preserve projection; expose the gap
                persistence_gaps.append(
                    ResearchGap(
                        source="evidence",
                        operation="evidence.record",
                        code="evidence_persistence_failed",
                        message=type(exc).__name__,
                        retryable=True,
                    )
                )
            # The ledger lives across turns.  Only lifecycle failures created
            # by this write belong to the current investigation result.
            for error in self._evidence.lifecycle_errors[lifecycle_error_start:]:
                if error.get("code") == "evidence_lifecycle_write_failed":
                    persistence_gaps.append(
                        ResearchGap(
                            source="evidence",
                            operation="evidence.lifecycle",
                            code=str(error.get("code")),
                            message=str(error.get("message") or "evidence lifecycle write failed"),
                            retryable=True,
                            details={"note_id": str(error.get("note_id") or "")},
                        )
                    )
        if self._profiles is not None:
            for raw in adaptation.profiles:
                try:
                    profile = ShopProfile.model_validate(_profile_contract(raw))
                    await self._profiles.upsert(profile)
                except Exception as exc:  # preserve usable response; expose the gap
                    # The raw profile stays in the adaptation and response audit.
                    # A persistence failure must not silently turn into a success.
                    persistence_gaps.append(
                        ResearchGap(
                            source="shop_profile",
                            operation="profile.upsert",
                            code="profile_persistence_failed",
                            message=type(exc).__name__,
                            retryable=True,
                            details={"name": str(raw.get("name") or raw.get("entity_id") or "unknown")},
                        )
                    )
        if not persistence_gaps:
            return adaptation
        return FoodAdaptationResult(
            claims=adaptation.claims,
            entities=adaptation.entities,
            controversies=adaptation.controversies,
            gaps=(*adaptation.gaps, *persistence_gaps),
            comments=adaptation.comments,
            profiles=adaptation.profiles,
            raw_comments=adaptation.raw_comments,
            provider_payload_refs=adaptation.provider_payload_refs,
            raw_provider_payloads=adaptation.raw_provider_payloads,
            evidence_refs=adaptation.evidence_refs,
            coverage=adaptation.coverage,
            observations=adaptation.observations,
        )

    @staticmethod
    def _goal(user_input: str, context: ConversationContext, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "objective": user_input.strip(),
            "user_request": user_input,
            "conversation_history": context.get_history_for_llm(),
            "context": {
                "last_intent": context.last_intent,
                "last_recommendations": context.last_recommendations,
                "excluded_shops": tuple(context.excluded_shops),
                "accumulated_preferences": tuple(context.accumulated_preferences),
                "target_city": context.target_city,
                "turn_count": context.turn_count,
            },
        }

    def _project(
        self,
        state: InvestigationState,
        adaptation: FoodAdaptationResult | None,
        context: ConversationContext,
        run_id: str,
    ) -> AdaptiveWorkflowExecution:
        adaptation = adaptation or FoodAdaptationResult()
        profiles = tuple(_profile_contract(item) for item in adaptation.profiles)
        typed_profiles = tuple(_validate_profile(item) for item in profiles)
        recommendations = _recommendations(adaptation)
        outcome = _outcome(state, adaptation)
        gaps = _merge_gaps((*state.gaps, *adaptation.gaps))
        notes = _notes_from_adaptation(adaptation)
        evidence_refs = tuple(
            sorted({*state.evidence_refs, *adaptation.evidence_refs})
        )
        raw_payload = {
            "adaptive_state": state.model_dump(mode="python"),
            "raw_observations": _raw_observations(state),
            "food_adaptation": adaptation.to_dict(),
        }
        run = ResearchRunResult(
            notes=notes,
            profiles=typed_profiles,
            claims=tuple(cast(JsonValue, item.model_dump(mode="json")) for item in adaptation.claims),
            entities=tuple(cast(JsonValue, item) for item in adaptation.entities),
            controversies=tuple(cast(JsonValue, item) for item in adaptation.controversies),
            evidence_refs=evidence_refs,
            gaps=gaps,
            outcome=outcome,
            raw_payload=raw_payload,
        )
        status = "ok"
        if outcome is ResearchOutcome.FAILED and not state.observations:
            status = "error"
        summary, synthesis = _final_synthesis(
            state,
            adaptation,
            outcome,
            recommendations,
        )
        response = XHSFoodResponse(
            status=status,
            recommendations=recommendations,
            summary=summary,
            error_message=("调查未能获得可用证据" if status == "error" else None),
            research_metadata={
                "strategy": "adaptive_investigation/v1",
                "runId": run_id,
                "outcome": outcome.value,
                "roundCount": len(state.rounds),
                "observationCount": len(state.observations),
                "evidenceCount": len(evidence_refs),
                "coverage": adaptation.coverage.to_dict(),
                "controversyCount": len(adaptation.controversies),
                "shopProfileCount": len(typed_profiles),
                "evidenceSynthesis": synthesis,
            },
            gaps=[gap.model_dump(mode="json") for gap in gaps],
        )
        context.last_intent = context.last_intent or {"query": context.conversation_history[-1]["content"]}
        context.last_notes = [note.model_dump(mode="json") for note in notes]
        context.last_recommendations = {
            item.name: item.to_dict() for item in recommendations
        }
        context.last_summary = summary
        return AdaptiveWorkflowExecution(
            response=response,
            run=run,
            intent=_intent_from_context(context),
            state=state,
            adaptation=adaptation,
        )


def _bind_scheduler_port(
    scheduler: ActionScheduler,
    port: ManagedMcpToolPort,
    capabilities: frozenset[str] | None,
) -> None:
    """Ensure an injected scheduler still uses this run's pinned session."""

    lease = getattr(scheduler, "run_lease", None)
    if lease is not None:
        raise RuntimeError(
            f"injected scheduler is already running investigation {lease}"
        )
    if getattr(scheduler, "executor", None) is None:
        scheduler.bind_tool_port(port, capabilities)


async def _resolve_session(factory: SessionFactory) -> ManagedMcpToolSession:
    value = factory()
    if inspect.isawaitable(value):
        value = await value
    if not isinstance(value, ManagedMcpToolSession):
        raise TypeError("session_factory must return ManagedMcpToolSession")
    return value


def _adapt_observations(
    pack: FoodAdaptivePack,
    observations: Iterable[Any],
) -> FoodAdaptationResult | None:
    envelopes: list[ObservationEnvelope] = []
    for observation in observations:
        if isinstance(observation, CanonicalObservationEnvelope):
            envelopes.append(_canonical_observation_envelope(observation))
            continue
        raw = getattr(observation, "raw_return", observation)
        action = getattr(observation, "action", None)
        envelopes.extend(_observation_envelopes(raw, action, getattr(observation, "action_id", None)))
    if not envelopes:
        return None
    return _demote_unresumable_continuation_gaps(pack.adapt_observation(tuple(envelopes)))


def _demote_unresumable_continuation_gaps(
    adaptation: FoodAdaptationResult,
) -> FoodAdaptationResult:
    """Prevent a missing provider cursor from turning into a page-one retry."""

    if not any(
        bool(envelope.continuation.get("has_more_without_cursor"))
        for envelope in adaptation.observations
    ):
        return adaptation
    gaps: list[ResearchGap] = []
    for gap in adaptation.gaps:
        if gap.code in {"partial_observation", "pagination_incomplete"} and gap.retryable:
            gap = ResearchGap(
                source=gap.source,
                operation=gap.operation,
                code="continuation_missing_cursor",
                message="provider indicated more results but did not return a continuation cursor",
                retryable=False,
                details={
                    **gap.details,
                    "has_more_without_cursor": True,
                    "original_gap_code": gap.code,
                },
            )
        gaps.append(gap)
    deduped = _merge_gaps(gaps)
    missing = tuple(
        sorted(
            {
                item
                for item in adaptation.coverage.missing
                if item not in {"partial_observation", "pagination_incomplete"}
            }
            | {gap.code for gap in deduped if gap.retryable}
        )
    )
    return replace(
        adaptation,
        gaps=deduped,
        coverage=replace(adaptation.coverage, missing=missing),
    )


def _merge_model_findings(
    pack: FoodAdaptivePack,
    adaptation: FoodAdaptationResult,
    *,
    findings: Iterable[Any] = (),
    controversies: Iterable[Any] = (),
) -> FoodAdaptationResult:
    """Project terminal model findings through the Food pack when supported.

    The reducer is deliberately optional so injected legacy packs remain
    usable.  A supported reducer receives the immutable observation
    projection and returns a new projection with auditable candidate entities
    and claims; raw comments and provider payloads remain owned by that
    projection.
    """

    reducer = getattr(pack, "merge_model_findings", None)
    if not callable(reducer):
        reducer = getattr(pack, "reduce_findings", None)
    finding_values = tuple(findings)
    controversy_values = tuple(controversies)
    if not callable(reducer) or not finding_values and not controversy_values:
        return adaptation
    reduced = reducer(
        adaptation,
        findings=finding_values,
        controversies=controversy_values,
    )
    if reduced is None:
        return adaptation
    if not isinstance(reduced, FoodAdaptationResult):
        raise TypeError("Food finding reducer must return FoodAdaptationResult")
    return reduced


def _capability_schema(*sources: Any, field_name: str) -> ContractPayload:
    for source in sources:
        value = _capability_field(source, field_name)
        if isinstance(value, Mapping):
            return cast(ContractPayload, _json_safe(value))
    return {"type": "object"}


def _capability_metadata(*sources: Any) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {}
    for source in sources:
        value = getattr(source, "metadata", None)
        if isinstance(value, Mapping):
            safe = _json_safe(value)
            if isinstance(safe, Mapping):
                metadata.update(cast(dict[str, JsonValue], safe))
    return metadata


def _capability_side_effect(*sources: Any) -> str:
    for source in sources:
        value = _capability_field(source, "side_effect")
        if value is None:
            continue
        normalized = str(getattr(value, "value", value))
        if normalized in {
            "read_only",
            "account_login",
            "account_mutation",
            "publish",
            "upload",
            "shell",
            "credential_export",
        }:
            return normalized
    return "read_only"


def _capability_int(
    *sources: Any,
    field_name: str,
    default: int,
) -> int:
    for source in sources:
        value = _capability_field(source, field_name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return default


def _capability_float(
    *sources: Any,
    field_name: str,
    default: float,
) -> float:
    for source in sources:
        value = _capability_field(source, field_name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return default


def _capability_bool(*sources: Any, field_name: str) -> bool:
    for source in sources:
        value = _capability_field(source, field_name)
        if isinstance(value, bool):
            return value
    return False


def _capability_field(source: Any, field_name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _capability_raw_payload(*sources: Any) -> JsonValue | None:
    for source in sources:
        if source is None:
            continue
        model_dump = getattr(source, "model_dump", None)
        if callable(model_dump):
            try:
                return cast(JsonValue, _json_safe(model_dump(mode="python")))
            except Exception:
                pass
        if isinstance(source, Mapping):
            return cast(JsonValue, _json_safe(source))
    return None


def _canonical_observation_envelope(
    observation: CanonicalObservationEnvelope,
) -> ObservationEnvelope:
    """Project the generic envelope into the Food contract without re-parsing raw data.

    The adaptive state deliberately stores JSON-safe canonical values.  This
    explicit projection keeps source/capability identity, cursors, outcome,
    evidence references, and the provider payload available to the Food pack;
    treating ``raw_payload`` as the whole result would lose normalized fields.
    """

    data = observation.data
    operation = observation.capability or "tool.call"
    provider_metadata = food_provider_metadata(data, operation=operation)
    items = _items_from_data(data, operation=operation)
    gap = observation.gap
    metadata = dict(observation.metadata)
    source_call = metadata.get("source_call")
    source_call_metadata = (
        source_call.get("metadata")
        if isinstance(source_call, Mapping)
        and isinstance(source_call.get("metadata"), Mapping)
        else {}
    )
    for key, value in source_call_metadata.items():
        metadata.setdefault(str(key), _json_safe(value))
    source_call_refs = _string_values(
        source_call_metadata.get("provider_payload_refs")
        or source_call_metadata.get("provider_payload_ref")
        or source_call_metadata.get("payload_ref")
    )
    if source_call_refs:
        metadata.setdefault("provider_payload_refs", source_call_refs)
    source_call_ref = _first_string(
        source_call_metadata.get("provider_payload_ref"),
        source_call_metadata.get("payload_ref"),
    )
    if source_call_ref:
        metadata.setdefault("provider_payload_ref", source_call_ref)
    continuation = dict(observation.continuation)
    missing_cursor = bool(continuation.get("has_more_without_cursor"))
    for key, value in provider_metadata.items():
        if value is not None and not (
            missing_cursor and key in {"cursor", "next_cursor", "has_more", "completeness"}
        ):
            metadata.setdefault(key, _json_safe(value))
    if gap is not None:
        metadata.setdefault("gap", gap.model_dump(mode="json"))
    next_cursor = (
        None
        if missing_cursor
        else observation.next_cursor or provider_metadata.get("next_cursor")
    )
    has_more = (
        False
        if missing_cursor
        else observation.has_more or bool(provider_metadata.get("has_more", False))
    )
    completeness = observation.completeness.value
    derived_completeness = provider_metadata.get("completeness")
    if missing_cursor:
        completeness = "partial"
    elif derived_completeness == "partial" or completeness == "unknown":
        completeness = str(derived_completeness or completeness)
    food_data = (
        _strip_pagination_more_signals(data) if missing_cursor else _json_safe(data)
    )
    if missing_cursor:
        metadata["has_more_without_cursor"] = True
    payload: dict[str, Any] = {
        "observation_id": observation.observation_id,
        "investigation_id": observation.investigation_id,
        "action_id": observation.action_id,
        "source": observation.source or "adaptive",
        "operation": operation,
        "capability": operation,
        "items": items,
        "data": food_data,
        "raw_payload": _json_safe(observation.raw_payload),
        "evidence_refs": tuple(observation.evidence_refs),
        "cursor": observation.cursor,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "completeness": completeness,
        "continuation": _json_safe(continuation),
        "outcome": observation.outcome.value,
        "success": observation.success,
        "metadata": _json_safe(metadata),
        "provenance": _json_safe(observation.provenance),
        "observed_at": observation.observed_at,
    }
    if gap is not None:
        payload.update(
            {
                "error_code": gap.code,
                "error_message": gap.message,
            }
        )
    return ObservationEnvelope.coerce(payload)


def _raw_return_projection(observation: CanonicalObservationEnvelope) -> Any:
    """Expose a typed source call when the canonical state has enough fields.

    ``InvestigationState`` is JSON-safe by design, so an SDK object cannot be
    retained inside it.  Reconstructing the existing ``SourceCall`` contract
    at the compatibility boundary preserves the public shape and, crucially,
    the untouched provider payload instead of returning an opaque summary.
    """

    source = observation.source
    operation = observation.capability
    if not source or not operation:
        return observation.raw_return
    gap = observation.gap
    metadata = dict(observation.metadata)
    metadata.setdefault("observation_id", observation.observation_id)
    metadata.setdefault("investigation_id", observation.investigation_id)
    return SourceCall(
        source=source,
        operation=operation,
        success=observation.success,
        data=cast(JsonValue, _json_safe(observation.data)),
        error_code=gap.code if gap is not None else None,
        error_message=gap.message if gap is not None else None,
        retryable=gap.retryable if gap is not None else False,
        metadata=cast(ContractPayload, _json_safe(metadata)),
        raw_payload=_json_safe(observation.raw_payload),
    )


def _raw_observations(state: InvestigationState) -> tuple[Any, ...]:
    """Return provider returns from the scheduler audit before compatibility projection.

    ``InvestigationState`` stores JSON-safe canonical observations for model
    context.  Its round audit still owns the original scheduler return values,
    so use those values for ``ResearchRunResult.raw_payload`` whenever they
    are available.  This keeps an injected ``SourceCall`` object, including
    metadata and its untouched provider payload, lossless for existing
    consumers.
    """

    raw: list[Any] = []
    for round_record in state.rounds:
        values = getattr(round_record, "native_raw_tool_returns", ())
        if not values:
            values = getattr(round_record, "raw_tool_returns", ())
        if values:
            raw.extend(_restore_raw_return(value) for value in values)
    if raw:
        return tuple(raw)
    return tuple(_raw_return_projection(item) for item in state.observations)


def _restore_raw_return(value: Any) -> Any:
    """Rehydrate a serialized ``SourceCall`` without touching opaque payloads."""

    if isinstance(value, SourceCall):
        return value
    if isinstance(value, Mapping) and {
        "source",
        "operation",
        "success",
    }.issubset(value):
        try:
            return SourceCall.model_validate(value)
        except Exception:
            return value
    return value


def _observation_envelopes(raw: Any, action: Any, action_id: str | None) -> tuple[ObservationEnvelope, ...]:
    if isinstance(raw, SourceEnvelope):
        return (ObservationEnvelope.from_source_envelope(raw),)
    if isinstance(raw, SourceCall):
        return (_source_call_envelope(raw, action, action_id),)
    if hasattr(raw, "source_envelopes"):
        values = raw.source_envelopes or ()
        envelopes = tuple(
            ObservationEnvelope.from_source_envelope(value)
            for value in values
            if isinstance(value, SourceEnvelope)
        )
        if envelopes:
            return envelopes
    if isinstance(raw, Mapping):
        payload = dict(raw)
        if "source" not in payload and "source_id" not in payload:
            payload["source"] = _source_name(action)
        if "operation" not in payload and "op" not in payload and "capability" not in payload:
            payload["operation"] = _action_capability(action)
        if action_id and "action_id" not in payload:
            payload["action_id"] = action_id
        try:
            return (ObservationEnvelope.coerce(payload),)
        except Exception:  # noqa: BLE001 - malformed provider data becomes a raw gap
            return (_fallback_envelope(payload, action, action_id),)
    return (_fallback_envelope({"value": _json_safe(raw)}, action, action_id),)


def _source_call_envelope(call: SourceCall, action: Any, action_id: str | None) -> ObservationEnvelope:
    metadata = dict(call.metadata)
    data = call.data
    provider_metadata = food_provider_metadata(data, operation=call.operation)
    source = _source_name(action)
    if source == "unknown":
        source = _source_name(call)
    raw_payload = call.raw_payload if call.raw_payload is not None else data
    for key, value in provider_metadata.items():
        if value is not None:
            metadata.setdefault(key, _json_safe(value))
    payload: dict[str, Any] = {
        "observation_id": f"{action_id or uuid4().hex}:observation",
        "investigation_id": "adaptive-investigation",
        "action_id": action_id,
        "source": source,
        "operation": call.operation,
        "capability": call.operation,
        "items": _items_from_data(data, operation=call.operation),
        "data": _json_safe(data),
        "raw_payload": _json_safe(raw_payload),
        "provider": call.source,
        "provider_response": _json_safe(raw_payload),
        "provider_payload_refs": _string_values(metadata.get("provider_payload_refs")),
        "provider_payload_ref": _first_string(
            metadata.get("provider_payload_ref"), metadata.get("payload_ref")
        ),
        "success": call.success,
        "error_code": call.error_code,
        "error_message": call.error_message,
        "metadata": metadata,
        "provenance": {"platform": call.source},
        "completeness": metadata.get(
            "completeness",
            provider_metadata.get("completeness", "complete" if call.success else "unknown"),
        ),
        "cursor": metadata.get("cursor", provider_metadata.get("cursor")),
        "next_cursor": metadata.get("next_cursor", provider_metadata.get("next_cursor")),
        "has_more": bool(metadata.get("has_more", provider_metadata.get("has_more", False))),
        "expected_count": metadata.get("expected_count", provider_metadata.get("expected_count")),
    }
    try:
        return ObservationEnvelope.coerce(payload)
    except Exception:  # noqa: BLE001 - preserve call and expose a valid fallback envelope
        return _fallback_envelope(payload, action, action_id)


def _fallback_envelope(payload: Mapping[str, Any], action: Any, action_id: str | None) -> ObservationEnvelope:
    source = _source_name(action)
    if source == "unknown":
        source = str(payload.get("source") or "unknown")
    operation = str(payload.get("operation") or payload.get("capability") or _action_capability(action) or "tool.call")
    safe_data = _json_safe(payload.get("data", payload.get("value")))
    safe_raw = _json_safe(payload.get("raw_payload", payload))
    return ObservationEnvelope(
        observation_id=f"{action_id or uuid4().hex}:observation",
        investigation_id="adaptive-investigation",
        action_id=action_id,
        source=source,
        operation=operation,
        capability=operation,
        items=tuple(_items_from_data(safe_data)),
        data=safe_data,
        raw_payload=safe_raw,
        success=bool(payload.get("success", True)),
        error_code=cast(str | None, payload.get("error_code")),
        error_message=cast(str | None, payload.get("error_message")),
        metadata=cast(ContractPayload, _json_safe(payload.get("metadata", {}))),
        provenance=cast(ContractPayload, {"fallback": True}),
        completeness="unknown",
    )


def _state_observations(state: Any) -> tuple[Any, ...]:
    if state is None:
        return ()
    values = getattr(state, "observations", ())
    return tuple(values) if isinstance(values, Iterable) and not isinstance(values, (str, bytes)) else ()


def _observation_identity(value: Any) -> str | None:
    """Return the stable action identity shared by wave and canonical views."""

    for name in ("action_id", "observation_id", "id"):
        candidate = getattr(value, name, None)
        if candidate:
            return str(candidate).split(":observation:", 1)[-1]
        if isinstance(value, Mapping) and value.get(name):
            return str(value[name]).split(":observation:", 1)[-1]
    return None


def _enrich_goal(
    goal: Any,
    adaptation: FoodAdaptationResult | None,
    *,
    pack: FoodAdaptivePack | None = None,
    run_id: str = "run",
    existing_action_ids: Sequence[str] = (),
    include_comments: bool = True,
) -> Any:
    if adaptation is None and pack is None:
        return goal
    projection = adaptation.to_model_context(include_comments=include_comments) if adaptation is not None else {
        "schema_version": "food-adaptive/v1",
        "claims": [],
        "entities": [],
        "controversies": [],
        "gaps": [],
        "comments": [],
        "profiles": [],
        "provider_payload_refs": [],
        "evidence_refs": [],
        "coverage": {},
    }
    if pack is not None:
        # The declaration is the Food Pack's policy surface.  It is included
        # on the first turn as well as later turns so the model can choose a
        # sensible source order without a fixed search workflow in the engine.
        projection["domain_policy"] = pack.describe().to_dict()
        # The pack supplies bounded, domain-aware candidates as context.  The
        # model still owns the decision to emit them; this is not an implicit
        # second planner or an automatic provider call.
        try:
            projection["follow_up_candidates"] = [
                action.model_dump(mode="json")
                for action in pack.next_actions(
                    adaptation,
                    run_id=run_id,
                    existing_action_ids=existing_action_ids,
                )
            ]
        except Exception:
            # A malformed provider projection must not prevent the generic
            # planner/critic from seeing the valid claims and coverage.
            projection["follow_up_candidates"] = []
    if isinstance(goal, Mapping):
        enriched = dict(goal)
        enriched["food_projection"] = projection
        return enriched
    return {"objective": goal, "food_projection": projection}


def _investigation_id(state: Any, goal: Any) -> str:
    value = getattr(state, "investigation_id", None)
    if value:
        return str(value)
    if isinstance(goal, Mapping) and goal.get("run_id"):
        return str(goal["run_id"])
    return "run"


def _state_action_ids(state: Any) -> tuple[str, ...]:
    if state is None:
        return ()
    values: list[str] = []
    for observation in _state_observations(state):
        action_id = getattr(observation, "action_id", None)
        if action_id:
            values.append(str(action_id))
    plan = getattr(state, "plan", None)
    for action in getattr(plan, "actions", ()):
        action_id = getattr(action, "action_id", None)
        if action_id:
            values.append(str(action_id))
    return tuple(dict.fromkeys(values))


def _invoke_named(method: Callable[..., Any], first: Any, values: Mapping[str, Any]) -> Any:
    try:
        params = list(inspect.signature(method).parameters.values())
    except (TypeError, ValueError):
        return method(first)
    names = {item.name for item in params}
    kwargs = {name: value for name, value in values.items() if name in names}
    if "goal" in names:
        kwargs["goal"] = first
        return method(**kwargs)
    if params and params[0].name in {"request", "input", "prompt", "query"}:
        kwargs[params[0].name] = first
        return method(**kwargs)
    return method(first, **kwargs)


def _source_name(value: Any) -> str:
    explicit = _first_string(getattr(value, "source", None), getattr(value, "provider", None))
    if explicit:
        normalized = explicit.casefold()
        return "xhs" if normalized in {"xhs_pc", "xhs", "xiaohongshu"} else "dianping" if normalized in {"dp", "dianping"} else explicit
    capability = _action_capability(value)
    return "xhs" if capability.startswith(("notes.", "comments.")) else "dianping" if capability.startswith(("places.", "reviews.")) else "unknown"


def _action_capability(action: Any) -> str:
    value = getattr(action, "capability", None) or getattr(action, "tool", None) or getattr(action, "kind", None)
    return str(getattr(value, "value", value) or "tool.call")


def _items_from_data(data: Any, *, operation: str | None = None) -> tuple[Any, ...]:
    return food_provider_items(data, operation=operation)


def _profile_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    profile = dict(value)
    provider_id = profile.get("provider_id")
    source = str(profile.get("source") or "dianping")
    refs = dict(profile.get("provider_refs") or {})
    if provider_id:
        refs.setdefault(source, str(provider_id))
    profile["provider_refs"] = refs
    profile.setdefault("source_payload", value.get("source_payload", value))
    return profile


def _validate_profile(value: Mapping[str, Any]) -> Any:
    from xhs_food.contracts import ShopProfile

    try:
        return ShopProfile.model_validate(value)
    except Exception:
        # A malformed profile must remain visible as a typed gap, but cannot
        # prevent comment evidence and other valid profiles from being returned.
        return ShopProfile(name=str(value.get("name") or value.get("entity_id") or "unknown"), source_payload=value)


def _recommendations(adaptation: FoodAdaptationResult) -> list[RestaurantRecommendation]:
    profiles = {
        str(item.get("entity_id")): item
        for item in adaptation.profiles
        if isinstance(item, Mapping)
    }
    claims_by_entity: dict[str, list[str]] = {}
    for claim in adaptation.claims:
        attributes = claim.attributes
        for name in _string_values(attributes.get("mentioned_shops")):
            entity_id = f"{FoodEntityType.SHOP.value}:{''.join(name.casefold().split())}"
            claims_by_entity.setdefault(entity_id, []).append(claim.text)
    output: list[RestaurantRecommendation] = []
    for entity in adaptation.entities:
        if entity.get("entity_type") != FoodEntityType.SHOP.value or not entity.get("candidate"):
            continue
        entity_id = str(entity.get("entity_id") or "")
        name = str(entity.get("name") or entity_id)
        profile = profiles.get(entity_id)
        claims = list(dict.fromkeys(claims_by_entity.get(entity_id, ())))
        refs = tuple(dict.fromkeys((*_string_values(entity.get("evidence_refs")), *claims_by_entity_refs(adaptation, entity_id))))
        location = _first_string(
            (profile or {}).get("address") if profile else None,
            (profile or {}).get("location") if profile else None,
            (profile or {}).get("district") if profile else None,
            (profile or {}).get("city") if profile else None,
        )
        dishes = _string_values(entity.get("dishes"))
        output.append(
            RestaurantRecommendation(
                name=name,
                location=location,
                features=list(dishes),
                source_notes=list(refs),
                confidence=0.5,
                is_recommended=True,
                shop_profile=dict(profile) if profile else None,
                pros=claims[:5],
                evidence_refs=list(refs),
                evidence_summary={
                    "claimCount": len(claims),
                    "controversyCount": sum(
                        1 for item in adaptation.controversies if str(item.get("entity_id")) == entity_id
                    ),
                    "primarySource": "xhs_comments",
                    "secondarySource": "dianping_profile" if profile else None,
                },
                source_gaps=[gap.model_dump(mode="json") for gap in adaptation.gaps],
            )
        )
    return output


def claims_by_entity_refs(adaptation: FoodAdaptationResult, entity_id: str) -> tuple[str, ...]:
    refs: list[str] = []
    for claim in adaptation.claims:
        if entity_id.split(":", 1)[-1] in _string_values(claim.attributes.get("mentioned_shops")):
            refs.extend(claim.evidence_refs)
    return tuple(dict.fromkeys(refs))


def _notes_from_adaptation(adaptation: FoodAdaptationResult) -> tuple[Any, ...]:
    """Project comment observations into the existing note/evidence contract.

    This is a projection only.  It groups normalized comment rows for the
    transport layer while retaining each row and its provider envelope in the
    adaptive audit payload.  A malformed row is skipped here because the Food
    adapter has already recorded it as a gap; no source payload is discarded.
    """

    grouped: dict[str, dict[str, Any]] = {}
    for envelope in adaptation.observations:
        operation = envelope.operation.casefold()
        if envelope.source.casefold() not in {"xhs", "xiaohongshu", "xhs_pc"}:
            continue
        is_nested_note_observation = operation.startswith("notes.")
        if "comment" not in operation and "review" not in operation and not is_nested_note_observation:
            continue
        items: Iterable[Any] = envelope.items
        if is_nested_note_observation:
            items = food_provider_comment_items(
                (envelope.data, envelope.raw_payload, envelope.items),
                operation=operation,
            )
        for item in items:
            if not isinstance(item, Mapping):
                continue
            note_id = _first_string(
                item.get("note_id"),
                item.get("noteId"),
                item.get("document_id"),
                item.get("documentId"),
            ) or f"observation:{envelope.observation_id}"
            comment_id = _first_string(
                item.get("comment_id"),
                item.get("commentId"),
                item.get("id"),
                item.get("external_id"),
            ) or f"comment:{note_id}:{len(grouped.get(note_id, {}).get('comments', {}))}"
            text = _first_string(item.get("text"), item.get("content"), item.get("comment"), item.get("body")) or ""
            if not text:
                continue
            bucket = grouped.setdefault(
                note_id,
                {
                    "title": _first_string(item.get("note_title"), item.get("title")) or "",
                    "summary": _first_string(item.get("note_summary"), item.get("summary")) or "",
                    "url": _first_string(item.get("note_url"), item.get("url"), item.get("link")),
                    "expected": _int_value(item.get("comment_count"), item.get("total")),
                    "has_more": envelope.has_more,
                    "cursor": envelope.next_cursor,
                    "comments": {},
                    "raw_payload": envelope.raw_payload,
                    "queries": _string_values(envelope.metadata.get("query")),
                },
            )
            bucket["comments"].setdefault(
                comment_id,
                CommentEvidence(
                    source="xhs",
                    note_id=note_id,
                    comment_id=comment_id,
                    text=text,
                    author=cast(ContractPayload, _json_safe(item.get("author", {}))),
                    likes=max(0, _int_value(item.get("likes"), item.get("like_count")) or 0),
                    replies=max(0, _int_value(item.get("replies"), item.get("reply_count")) or 0),
                    raw_payload=_json_safe(item),
                    provenance={
                        "observation_id": envelope.observation_id,
                        "provider_payload_refs": list(envelope.payload_refs),
                    },
                ),
            )
    notes: list[XhsNoteLead] = []
    for note_id in sorted(grouped):
        bucket = grouped[note_id]
        comments = tuple(bucket["comments"].values())
        expected = bucket["expected"]
        collected = len(comments)
        notes.append(
            XhsNoteLead(
                note_id=note_id,
                title=bucket["title"],
                summary=bucket["summary"],
                url=bucket["url"],
                comment_count=max(expected or 0, collected),
                comment_expected_count=expected,
                comment_collected_count=collected,
                comment_has_more=bool(bucket["has_more"]),
                comment_cursor=bucket["cursor"],
                comment_pages=1,
                comment_completeness="partial" if bucket["has_more"] else "complete",
                comments=comments,
                queries=tuple(bucket["queries"]),
                outcome=ResearchOutcome.PARTIAL if bucket["has_more"] else ResearchOutcome.COMPLETE,
                raw_payload=bucket["raw_payload"],
            )
        )
    return tuple(notes)


def _int_value(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _outcome(state: InvestigationState, adaptation: FoodAdaptationResult) -> ResearchOutcome:
    if state.outcome is ResearchOutcome.FAILED and not adaptation.entities:
        return ResearchOutcome.FAILED
    if state.outcome is ResearchOutcome.EMPTY and not adaptation.entities:
        return ResearchOutcome.EMPTY
    if state.gaps or adaptation.gaps:
        return ResearchOutcome.PARTIAL
    return ResearchOutcome.COMPLETE


def _final_synthesis(
    state: InvestigationState,
    adaptation: FoodAdaptationResult,
    outcome: ResearchOutcome,
    recommendations: Sequence[RestaurantRecommendation],
) -> tuple[str, dict[str, Any]]:
    """Build a user-safe conclusion from the immutable adaptive audit.

    The Food DTO keeps its existing shape, so the detailed audit is exposed in
    ``research_metadata`` and the human summary remains concise.  Terminal
    critic/termination text is preferred over counts; counts are the
    deterministic fallback when a model omits a usable conclusion.
    """

    final_critique = _latest_critique(state)
    termination = state.termination
    finding_values = _synthesis_findings(state, final_critique)
    finding_records = tuple(
        _finding_record(index, value) for index, value in enumerate(finding_values)
    )
    evidence_refs = _synthesis_evidence_refs(
        state,
        adaptation,
        termination=termination,
        critique=final_critique,
        findings=finding_values,
    )
    conclusion = _synthesis_conclusion(state, termination, final_critique)

    base = _recommendation_summary(adaptation, outcome, recommendations)
    parts = [base]
    if conclusion:
        parts.append(f"终局结论：{_truncate(conclusion, 180)}")
    finding_texts = tuple(
        _truncate(str(record["text"]), 140)
        for record in finding_records
        if record["text"]
    )
    if finding_texts:
        parts.append(f"关键发现：{'；'.join(finding_texts[:3])}")
    if evidence_refs:
        preview = "、".join(evidence_refs[:3])
        if len(evidence_refs) > 3:
            preview += "…"
        parts.append(f"依据证据：{len(evidence_refs)} 条（{preview}）")

    synthesis = {
        "schemaVersion": "evidence-synthesis/v1",
        "conclusion": conclusion,
        "terminationReason": (
            termination.reason.value if termination is not None else None
        ),
        "terminationSummary": termination.summary if termination is not None else None,
        "critiqueDecision": _enum_value(
            getattr(state.critique, "decision", None)
        ),
        "critiqueConclusion": (
            getattr(final_critique, "reason", None)
            if final_critique is not None
            else None
        ),
        "findings": [_json_safe(value) for value in finding_values],
        "findingRecords": list(finding_records),
        "evidenceRefs": list(evidence_refs),
        "stateRevision": state.revision,
        "roundCount": len(state.rounds),
    }
    return "；".join(parts), synthesis


def _recommendation_summary(
    adaptation: FoodAdaptationResult,
    outcome: ResearchOutcome,
    recommendations: Sequence[RestaurantRecommendation],
) -> str:
    if not recommendations:
        return "未识别到有评论证据支持的候选店铺"
    controversy_count = len(adaptation.unresolved_controversies)
    profile_count = len(adaptation.profiles)
    suffix = f"，保留 {controversy_count} 个待核实争议" if controversy_count else ""
    return (
        f"已从评论证据识别 {len(recommendations)} 家候选店铺，"
        f"补充 {profile_count} 份结构化店铺资料{suffix}（{outcome.value}）"
    )


def _latest_critique(state: InvestigationState) -> Any | None:
    for round_record in reversed(state.rounds):
        critique = getattr(round_record, "critique", None)
        if critique is not None:
            return critique
    return None


def _synthesis_findings(state: InvestigationState, critique: Any | None) -> tuple[Any, ...]:
    values = tuple(state.findings)
    if not values and critique is not None:
        values = tuple(getattr(critique, "findings", ()) or ())
    # State already contains the terminal critic's findings.  The fallback
    # keeps direct/legacy callers useful when a round audit is unavailable.
    unique: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = _stable_synthesis_json(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return tuple(unique)


def _synthesis_conclusion(
    state: InvestigationState,
    termination: Any | None,
    critique: Any | None,
) -> str:
    candidates = (
        getattr(termination, "summary", None),
        getattr(critique, "reason", None),
        state.stop_reason,
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and text.casefold() not in {
            "investigation terminated",
            "critic model failed",
            "planner model failed",
            "critic requested stop",
            "planner requested stop",
        }:
            return text
    return ""


def _synthesis_evidence_refs(
    state: InvestigationState,
    adaptation: FoodAdaptationResult,
    *,
    termination: Any | None,
    critique: Any | None,
    findings: Sequence[Any],
) -> tuple[str, ...]:
    refs: set[str] = {
        str(ref)
        for ref in (
            *state.evidence_refs,
            *adaptation.evidence_refs,
            *(getattr(termination, "evidence_refs", ()) or ()),
            *(getattr(critique, "evidence_refs", ()) or ()),
        )
        if str(ref)
    }
    for finding in findings:
        refs.update(_finding_refs(finding))
    return tuple(sorted(refs))


def _finding_record(index: int, finding: Any) -> dict[str, Any]:
    return {
        "index": index,
        "text": _finding_text(finding),
        "evidenceRefs": list(_finding_refs(finding)),
        "raw": _json_safe(finding),
    }


def _finding_text(finding: Any) -> str:
    if isinstance(finding, str):
        return finding.strip()
    if isinstance(finding, Mapping):
        for key in ("statement", "finding", "claim", "text", "summary", "message"):
            value = finding.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        values = [
            f"{key}={value}"
            for key, value in finding.items()
            if str(key) not in {"evidence_refs", "evidence_ref", "refs", "raw_payload"}
            and value not in (None, "", (), [], {})
        ]
        if values:
            return ", ".join(values)
    if finding is None:
        return ""
    return _stable_synthesis_json(finding)


def _finding_refs(finding: Any) -> tuple[str, ...]:
    if not isinstance(finding, Mapping):
        return ()
    values: list[str] = []
    for key in ("evidence_refs", "evidence_ref", "refs", "references"):
        candidate = finding.get(key)
        if isinstance(candidate, str):
            values.append(candidate)
        elif isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
            values.extend(str(item) for item in candidate if str(item))
    return tuple(sorted({value for value in values if value}))


def _stable_synthesis_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, default=str)


def _truncate(value: str, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value) if value is not None else None


def _telemetry_outcome(outcome: ResearchOutcome) -> TelemetryObservationOutcome:
    """Map the research result vocabulary to the bounded telemetry vocabulary."""

    if outcome is ResearchOutcome.COMPLETE:
        return TelemetryObservationOutcome.OK
    if outcome is ResearchOutcome.PARTIAL:
        return TelemetryObservationOutcome.PARTIAL
    if outcome is ResearchOutcome.FAILED:
        return TelemetryObservationOutcome.ERROR
    return TelemetryObservationOutcome.PARTIAL


def _summary(
    adaptation: FoodAdaptationResult,
    outcome: ResearchOutcome,
    recommendations: Sequence[RestaurantRecommendation],
) -> str:
    """Compatibility spelling for the pre-synthesis count summary."""

    return _recommendation_summary(adaptation, outcome, recommendations)


def _intent_from_context(context: ConversationContext) -> FoodSearchIntent | None:
    if isinstance(context.last_intent, Mapping):
        return FoodSearchIntent.from_dict(dict(context.last_intent))
    return None


def _json_safe(value: Any) -> Any:
    try:
        return _JSON_VALUE.validate_python(value)
    except Exception:
        if isinstance(value, Mapping):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [_json_safe(item) for item in value]
        if isinstance(value, (datetime,)):
            return value.astimezone(UTC).isoformat()
        if hasattr(value, "model_dump"):
            return _json_safe(value.model_dump(mode="python"))
        return repr(value)


def _strip_pagination_more_signals(value: Any) -> Any:
    """Keep normalized rows while moving an unresumable page signal to metadata."""

    if isinstance(value, Mapping):
        return {
            str(key): _strip_pagination_more_signals(item)
            for key, item in value.items()
            if str(key)
            not in {
                "has_more",
                "hasMore",
                "has_next",
                "hasNext",
                "more",
                "is_end",
                "isEnd",
                "complete",
                "is_complete",
                "isComplete",
                "completeness",
                "continuation",
                "pagination",
                "page_info",
                "pageInfo",
            }
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_strip_pagination_more_signals(item) for item in value]
    return _json_safe(value)


def _string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(dict.fromkeys(str(item) for item in value if str(item)))
    return ()


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _notify(sink: ProgressSink | None, kind: str, **payload: Any) -> None:
    if sink is None:
        return
    value = sink({"kind": kind, **payload})
    if inspect.isawaitable(value):
        await value


def _merge_gaps(gaps: Sequence[ResearchGap]) -> tuple[ResearchGap, ...]:
    output: dict[tuple[str, str, str], ResearchGap] = {}
    for gap in gaps:
        output.setdefault((gap.source, gap.operation, gap.code), gap)
    return tuple(output[key] for key in sorted(output))


__all__ = [
    "AdaptiveFoodResearchWorkflow",
    "AdaptiveWorkflowExecution",
    "FoodToolSource",
    "ManagedMcpToolPort",
    "WorkflowExecution",
]
