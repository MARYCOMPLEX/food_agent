"""The single comment-first Food Research Agent workflow."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal, cast
from uuid import uuid4

from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.agents.intent_parser import IntentParserAgent
from xhs_food.contracts import (
    AgentToolExecutionContext,
    AnalyzeCommentBatch,
    CommentEvidence,
    CommentInsight,
    EnrichShopProfile,
    FetchNoteEvidence,
    PlatformChannel,
    ResearchActionResult,
    ResearchEvent,
    ResearchGap,
    ResearchOutcome,
    ResearchRunResult,
    ResearchState,
    ResourceClass,
    ShopProfile,
    ShopProfileRepositoryPort,
    SourceEnvelope,
    Synthesize,
)
from xhs_food.domain_packs.food.decision import FoodDecisionPolicy
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.schemas import (
    ConversationContext,
    MustTryItem,
    RestaurantRecommendation,
    XHSFoodResponse,
)

from .aggregation import EntityControversyAggregator
from .evidence import EvidenceLedger, evidence_ref
from .mcp import ManagedMcpToolSession, UnavailableMcpToolSession
from .planner import PlannerDecision, ResearchPlanner
from .profile_service import (
    ShopProfileRefreshPlan,
    ShopProfileRefreshPolicy,
    ShopProfileService,
    ShopProfileSyncResult,
)
from .repository import InMemoryShopProfileRepository, merge_profiles
from .resource_limits import (
    BudgetExceededError,
    QueueClosedError,
    ResourceCallTimeoutError,
    ResourceCircuitOpenError,
    ResourcePoolConfig,
)
from .runtime import ResearchRuntime, ResearchRuntimeConfig
from .sources import (
    DianpingMcpSource,
    DianpingShopEnricher,
    EnrichmentResult,
    LeadCollectionResult,
    XhsCommentLeadCollector,
    XhsMcpSource,
)

SessionFactory = Callable[[], ManagedMcpToolSession]
ProgressSink = Callable[[Mapping[str, Any]], Any]
RuntimeFactory = Callable[..., ResearchRuntime]


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    response: XHSFoodResponse
    run: ResearchRunResult
    intent: FoodSearchIntent | None = None


@dataclass(frozen=True, slots=True)
class _NoteProcessingResult:
    """One note's evidence, analysis, and raw output in collection order."""

    note: Any
    evidence_refs: tuple[str, ...] = ()
    recommendations: tuple[RestaurantRecommendation, ...] = ()
    insights: tuple[CommentInsight, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    raw_payload: Any = None


@dataclass(frozen=True, slots=True)
class _ProfileWaveResult:
    """Merged cache/enrichment output for one streaming research run."""

    plan: ShopProfileRefreshPlan
    enrichment: EnrichmentResult
    sync: ShopProfileSyncResult


class _ProfileEnrichmentCoordinator:
    """Start bounded profile work as soon as comment analysis finds a name."""

    def __init__(
        self,
        *,
        service: ShopProfileService,
        enricher: DianpingShopEnricher,
        runtime: ResearchRuntime,
        router: _WorkflowActionRouter,
        intent: FoodSearchIntent,
        run_id: str,
        max_profiles: int,
        enabled: bool,
    ) -> None:
        self._service = service
        self._enricher = enricher
        self._runtime = runtime
        self._router = router
        self._intent = intent
        self._run_id = run_id
        self._max_profiles = max(1, max_profiles)
        self._enabled = enabled
        self._seen: set[str] = set()
        self._names: list[str] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._plans: dict[str, ShopProfileRefreshPlan] = {}
        self._results: dict[str, EnrichmentResult] = {}
        self._extra_gaps: list[ResearchGap] = []
        self._closed = False

    async def submit(self, candidates: Sequence[str]) -> None:
        """Schedule unseen candidates without waiting for their provider I/O."""

        if self._closed:
            return
        for value in candidates:
            name = str(value).strip()
            if not name or name in self._seen or len(self._names) >= self._max_profiles:
                continue
            self._seen.add(name)
            self._names.append(name)
            self._tasks.append(asyncio.create_task(self._prepare(name, len(self._names) - 1)))

    async def close(self) -> None:
        """Cancel and drain profile preparation tasks during workflow teardown."""

        if self._closed and not self._tasks:
            return
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        await _wait_for_tasks_cleanup(tasks)

    cancel = close

    async def finish(self) -> _ProfileWaveResult:
        if self._closed:
            raise RuntimeError("profile enrichment coordinator is closed")
        if self._tasks:
            values = await asyncio.gather(*self._tasks, return_exceptions=True)
            for name, value in zip(self._names, values, strict=False):
                if isinstance(value, BaseException):
                    self._extra_gaps.append(
                        ResearchGap(
                            source="shop_profile",
                            operation="profile.wave",
                            code="profile_wave_exception",
                            message=type(value).__name__,
                            retryable=True,
                            details={"name": name},
                        )
                    )

        plans = [self._plans[name] for name in self._names if name in self._plans]
        merged_plan = _merge_profile_plans(self._names, plans)
        refreshed: list[ShopProfile] = []
        enrichment_gaps: list[ResearchGap] = list(self._extra_gaps)
        raw_payload: dict[str, Any] = {"candidates": {}}
        for name in self._names:
            result = self._results.get(name)
            if result is None:
                continue
            refreshed.extend(result.profiles)
            enrichment_gaps.extend(result.gaps)
            raw_payload["candidates"][name] = result.raw_payload

        # Commit once after all per-candidate tasks settle.  The repository
        # remains the sole durable profile authority and can use its batch
        # upsert contract without touching the evidence ledger.  A runtime
        # policy failure must not erase the cache or the profiles already
        # fetched for this turn: expose them as a partial projection and keep
        # the typed gap for retry/observability.
        try:
            sync = await self._runtime.invoke_resource(
                ResourceClass.PERSISTENCE,
                self._service.commit,
                merged_plan,
                tuple(refreshed),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - preserve a usable projection
            sync = ShopProfileSyncResult(
                profiles=_merge_profile_projection(
                    merged_plan.candidates,
                    (*merged_plan.cached_profiles, *refreshed),
                ),
                gaps=(*merged_plan.gaps, _profile_commit_gap(exc)),
            )
        enrichment = EnrichmentResult(
            profiles=sync.profiles,
            gaps=_dedupe_gaps((*enrichment_gaps, *sync.gaps)),
            raw_payload=raw_payload,
        )
        return _ProfileWaveResult(plan=merged_plan, enrichment=enrichment, sync=sync)

    async def _prepare(self, name: str, index: int) -> None:
        plan = await self._runtime.invoke_resource(
            ResourceClass.PERSISTENCE,
            self._service.plan,
            (name,),
        )
        self._plans[name] = plan
        if not self._enabled or not plan.refresh_candidates:
            return

        action = EnrichShopProfile(
            action_id=f"{self._run_id}:profile:{index}:{_safe_action_part(name)}",
            idempotency_key=f"{self._run_id}:profile:{index}:{_safe_action_part(name)}",
            resource_class=ResourceClass.DIANPING_SEARCH,
            capability="places.search",
            shop_name=name,
            inputs={"city": self._intent.location, "candidate_index": index},
            reason="enrich a candidate after it crosses the comment evidence threshold",
        )

        async def execute(_: Any, *, _name: str = name, _action: EnrichShopProfile = action) -> ResearchActionResult:
            try:
                result = await self._enricher.enrich((_name,), self._intent)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate one candidate
                gap = ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="profile_pipeline_exception",
                    message=type(exc).__name__,
                    retryable=True,
                    details={"candidate": _name},
                )
                result = EnrichmentResult(profiles=(), gaps=(gap,))
            self._results[_name] = result
            return ResearchActionResult(
                action_id=_action.action_id,
                success=bool(result.profiles) or not result.gaps,
                profiles=result.profiles,
                gaps=result.gaps,
                completeness="partial" if result.gaps else "complete",
                output={"candidate": _name, "profile_count": len(result.profiles)},
                metadata={"candidate": _name},
            )

        self._router.register(
            action.action_id,
            execute,
            manages_resources=True,
            action=action,
        )
        try:
            result = await self._runtime.dispatch(action)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - preserve one candidate gap
            self._extra_gaps.append(
                ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="profile_dispatch_exception",
                    message=type(exc).__name__,
                    retryable=True,
                    details={"candidate": name},
                )
            )
            return
        if not result.success:
            self._extra_gaps.extend(result.gaps)


class _WorkflowActionRouter:
    """Map validated semantic action ids to ordinary workflow callbacks."""

    def __init__(self) -> None:
        self._callbacks: dict[str, Callable[[Any], Any]] = {}
        self._managed_actions: set[str] = set()
        self._actions: dict[str, Any] = {}

    def register(
        self,
        action_id: str,
        callback: Callable[[Any], Any],
        *,
        manages_resources: bool = False,
        action: Any | None = None,
    ) -> None:
        existing = self._callbacks.get(action_id)
        if existing is not None and existing is not callback:
            raise ValueError(f"semantic action callback already registered: {action_id}")
        self._callbacks[action_id] = callback
        if action is not None:
            self._actions[action_id] = action
        if manages_resources:
            self._managed_actions.add(action_id)

    def manages_resources(self, action: Any) -> bool:
        return action.action_id in self._managed_actions

    @property
    def actions(self) -> tuple[Any, ...]:
        """Return registered semantic actions in deterministic id order."""

        return tuple(self._actions[key] for key in sorted(self._actions))

    async def __call__(self, action: Any) -> Any:
        callback = self._callbacks.get(action.action_id)
        if callback is None:
            raise ValueError(f"no workflow callback registered for {action.action_id}")
        value = callback(action)
        if inspect.isawaitable(value):
            return await value
        return value


class CommentFirstResearchWorkflow:
    """Coordinate one research turn through explicit injected collaborators.

    Every user turn enters this same method with the full conversation context.
    There is no follow-up classifier and no alternate shortcut for an existing
    result set.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        intent_parser: IntentParserAgent | None = None,
        analyzer: AnalyzerAgent | None = None,
        evidence: EvidenceLedger | None = None,
        profiles: ShopProfileRepositoryPort | None = None,
        profile_service: ShopProfileService | None = None,
        planner: ResearchPlanner | None = None,
        aggregator: EntityControversyAggregator | None = None,
        runtime_config: ResearchRuntimeConfig | None = None,
        runtime_factory: RuntimeFactory | None = None,
        max_notes: int = 30,
        max_restaurants: int = 10,
        analysis_concurrency: int = 3,
        note_queue_size: int | None = None,
        profile_concurrency: int = 3,
        profile_refresh_after: timedelta = timedelta(days=7),
        partial_profile_retry_after: timedelta = timedelta(hours=12),
    ) -> None:
        if profiles is not None and profile_service is not None:
            raise ValueError("inject profiles or profile_service, not both")
        self._session_factory = session_factory or UnavailableMcpToolSession
        self._intent_parser = intent_parser or IntentParserAgent()
        self._analyzer = analyzer or AnalyzerAgent()
        self._evidence = evidence or EvidenceLedger()
        # EvidenceLedger is intentionally a small in-process index.  A single
        # run can analyze notes concurrently, but its multi-step lifecycle
        # write must remain atomic from the ledger's point of view.
        self._evidence_write_lock = asyncio.Lock()
        profile_repository = profiles or InMemoryShopProfileRepository()
        self._profile_service = profile_service or ShopProfileService(
            profile_repository,
            policy=ShopProfileRefreshPolicy(
                refresh_after=profile_refresh_after,
                partial_retry_after=partial_profile_retry_after,
            ),
            concurrency=profile_concurrency,
        )
        self._max_notes = max(1, max_notes)
        self._max_restaurants = max(1, max_restaurants)
        self._note_processing_concurrency = max(1, analysis_concurrency)
        self._analysis_semaphore = asyncio.Semaphore(self._note_processing_concurrency)
        self._note_queue_size = max(
            1,
            note_queue_size
            if note_queue_size is not None
            else self._note_processing_concurrency * 2,
        )
        self._profile_concurrency = max(1, profile_concurrency)
        self._planner = planner or ResearchPlanner(max_replans=1)
        self._aggregator = aggregator or EntityControversyAggregator()
        self._runtime_config = runtime_config
        self._runtime_factory = runtime_factory
        self._decision = FoodDecisionPolicy()

    @property
    def evidence(self) -> EvidenceLedger:
        return self._evidence

    @property
    def profiles(self) -> ShopProfileRepositoryPort:
        return self._profile_service.repository

    async def execute(
        self,
        user_input: str,
        context: ConversationContext,
        *,
        tool_context: AgentToolExecutionContext | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> WorkflowExecution:
        context.add_user_message(user_input)
        parse_result = await self._intent_parser.parse(user_input, context)
        if not parse_result.success:
            response = XHSFoodResponse(
                status="clarify" if parse_result.need_clarify else "error",
                clarify_questions=parse_result.questions,
                error_message=None if parse_result.need_clarify else parse_result.error,
                summary="需要更多信息以继续研究" if parse_result.need_clarify else "意图解析失败",
            )
            return WorkflowExecution(response=response, run=ResearchRunResult(outcome=ResearchOutcome.FAILED))
        intent = parse_result.intent
        if intent is None:
            response = XHSFoodResponse(status="error", error_message="意图解析缺少结构化结果")
            return WorkflowExecution(response=response, run=ResearchRunResult(outcome=ResearchOutcome.FAILED))

        context.last_intent = intent.to_dict()
        context.target_city = intent.location
        context.turn_count += 1
        await _notify_progress(
            progress_sink,
            "intent_parsed",
            location=intent.location,
            food_type=intent.food_type,
            turn_count=context.turn_count,
        )
        authority = tool_context or AgentToolExecutionContext(
            tenant_ref="local-anonymous",
            platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        )
        session = self._session_factory()
        runtime_for_cleanup: ResearchRuntime | None = None
        profile_coordinator: _ProfileEnrichmentCoordinator | None = None
        try:
            await session.open(authority)
            run_id = f"food-research:{uuid4().hex}"
            router = _WorkflowActionRouter()

            async def runtime_event_sink(event: ResearchEvent) -> None:
                await _notify_progress(
                    progress_sink,
                    "runtime_event",
                    event_type=event.event_type.value,
                    run_id=event.run_id,
                    action_id=event.action_id,
                    resource_class=(
                        event.resource_class.value if event.resource_class is not None else None
                    ),
                    sequence=event.sequence,
                    item_count=event.item_count,
                    completeness=event.completeness,
                    budget_usage=dict(event.budget_usage),
                    gap=(event.gap.model_dump(mode="json") if event.gap else None),
                )

            runtime = self._new_runtime(
                router,
                capabilities=_snapshot_capabilities(session),
                event_sink=runtime_event_sink,
            )
            runtime_for_cleanup = runtime
            runtime.begin(run_id, handler=router)
            planner_decision = self._planner.initial(intent, run_id=run_id)
            lifecycle_error_start = len(self._evidence.lifecycle_errors)
            xhs_platform = (
                PlatformChannel.XHS_PC
                if PlatformChannel.XHS_PC in authority.platforms
                else PlatformChannel.XHS_CREATOR
            )
            collector = XhsCommentLeadCollector(
                XhsMcpSource(
                    session,
                    platform=xhs_platform,
                    resource_executor=runtime.resource_invoker,
                ),
                max_notes=self._max_notes,
            )
            profile_enricher = DianpingShopEnricher(
                DianpingMcpSource(
                    session,
                    resource_executor=runtime.resource_invoker,
                ),
                max_profiles=1,
                concurrency=self._profile_concurrency,
                candidate_concurrency=self._profile_concurrency,
                search_concurrency=self._profile_concurrency,
                detail_concurrency=self._profile_concurrency,
                reviews_concurrency=self._profile_concurrency,
            )
            profile_coordinator = _ProfileEnrichmentCoordinator(
                service=self._profile_service,
                enricher=profile_enricher,
                runtime=runtime,
                router=router,
                intent=intent,
                run_id=run_id,
                max_profiles=self._max_restaurants,
                enabled=PlatformChannel.DIANPING in authority.platforms,
            )
            (
                notes,
                evidence_refs,
                recommendations,
                analysis_gaps,
                analysis_raw,
                collection_error,
                comment_insights,
                collection_snapshot,
            ) = await self._collect_and_analyze(
                collector,
                intent,
                runtime=runtime,
                router=router,
                planner_decision=planner_decision,
                profile_coordinator=profile_coordinator,
                progress_sink=progress_sink,
            )
            stream_result = collection_snapshot or getattr(collector, "last_stream_result", None)
            if stream_result is None:
                # This fallback is only for custom collector implementations
                # that expose the iterator contract without the aggregate
                # snapshot.  The individual note payloads remain available.
                collected = LeadCollectionResult(
                    notes=tuple(notes),
                    raw_payload={
                        "notes": [note.raw_payload for note in notes],
                    },
                )
            else:
                collected = LeadCollectionResult(
                    notes=tuple(notes),
                    gaps=stream_result.gaps,
                    raw_payload=_with_stream_notes(stream_result.raw_payload, notes),
                )
            aggregation = self._aggregator.aggregate(comment_insights)
            recommendations, filtered_count = self._decision.rank_and_filter(
                self._decision.merge_and_validate(recommendations),
                context.excluded_shops,
            )
            recommendations = recommendations[: self._max_restaurants]
            _attach_evidence(recommendations, notes, evidence_refs)

            profile_wave = await profile_coordinator.finish()
            profile_plan = profile_wave.plan
            enrichment = profile_wave.enrichment
            profile_sync = profile_wave.sync
            shop_profiles = profile_sync.profiles
            _attach_profiles(recommendations, shop_profiles)
            await _notify_progress(
                progress_sink,
                "profiles_enriched",
                profile_count=len(shop_profiles),
                refreshed_count=len(profile_plan.refresh_candidates),
            )
            # Synthesis is an explicit semantic boundary even though the
            # current food pack uses a deterministic composer.  Keeping it in
            # the runtime makes evidence validation, terminal status, and a
            # future model-backed composer observable without introducing a
            # second Agent or duplicating source calls.
            synthesis_action = Synthesize(
                action_id=f"{run_id}:synthesize",
                idempotency_key=f"{run_id}:synthesize",
                dependencies=(
                    tuple(
                        sorted(
                            runtime.state.completed_action_ids
                            if runtime.state is not None
                            else ()
                        )
                    )
                ),
                evidence_refs=tuple(evidence_refs),
                inputs={
                    "insight_count": len(aggregation.insights),
                    "profile_count": len(shop_profiles),
                    "composer": "deterministic-food-pack-v1",
                },
                reason="validate evidence citations and freeze the research projection",
            )

            async def synthesize_action(
                dispatched: Any,
                *,
                _action: Synthesize = synthesis_action,
            ) -> ResearchActionResult:
                await runtime.report_progress(
                    _action,
                    item_count=len(aggregation.insights) + len(shop_profiles),
                    completeness="unknown",
                    payload={"phase": "evidence_validation"},
                )
                known_refs = set(evidence_refs)
                validation_gaps: list[ResearchGap] = []
                for insight in aggregation.insights:
                    missing = tuple(
                        ref for ref in insight.evidence_refs if ref not in known_refs
                    )
                    if missing:
                        validation_gaps.append(
                            ResearchGap(
                                source="agent",
                                operation="research.synthesize",
                                code="synthesis_evidence_missing",
                                message="an insight references evidence absent from the committed ledger",
                                retryable=True,
                                details={
                                    "insight": insight.evidence_key,
                                    "missing_refs": list(missing),
                                },
                            )
                        )
                return ResearchActionResult(
                    action_id=_action.action_id,
                    success=True,
                    insights=aggregation.insights,
                    profiles=tuple(shop_profiles),
                    claims=aggregation.claims,
                    entities=tuple(aggregation.entities),
                    controversies=tuple(aggregation.controversies),
                    gaps=tuple(_dedupe_gaps(validation_gaps)),
                    item_count=len(aggregation.insights) + len(shop_profiles),
                    completeness="partial" if validation_gaps else "complete",
                    output={
                        "validated_evidence_refs": len(known_refs),
                        "insight_count": len(aggregation.insights),
                        "profile_count": len(shop_profiles),
                    },
                    metadata={"composer": "deterministic-food-pack-v1"},
                )

            router.register(
                synthesis_action.action_id,
                synthesize_action,
                manages_resources=True,
                action=synthesis_action,
            )
            synthesis_result = await runtime.dispatch(synthesis_action)
            runtime_state = await runtime.finish()

            gaps = _dedupe_gaps(
                (
                    *collected.gaps,
                    *(gap for note in notes for gap in note.gaps),
                    *tuple(
                        ResearchGap(
                            source="evidence",
                            operation="canonical.write",
                            code=str(item.get("code") or "evidence_lifecycle_write_failed"),
                            message=str(item.get("message") or "evidence lifecycle write failed"),
                            retryable=True,
                            details={"note_id": item.get("note_id")},
                        )
                        for item in self._evidence.lifecycle_errors[lifecycle_error_start:]
                    ),
                    *analysis_gaps,
                    *(
                        (
                            ResearchGap(
                                source="xhs",
                                operation="notes.stream",
                                code="stream_exception",
                                message=type(collection_error).__name__,
                                retryable=True,
                            ),
                        )
                        if collection_error is not None
                        else ()
                    ),
                    *profile_plan.gaps,
                    *enrichment.gaps,
                    *profile_sync.gaps,
                    *(
                        synthesis_result.gaps
                        if synthesis_result is not None
                        else ()
                    ),
                    *runtime_state.gaps,
                )
            )
            outcome = _outcome(notes, recommendations, gaps)
            run = ResearchRunResult(
                notes=notes,
                profiles=shop_profiles,
                insights=tuple(
                    insight.model_dump(mode="json") for insight in aggregation.insights
                ),
                claims=tuple(
                    claim.model_dump(mode="json") for claim in aggregation.claims
                ),
                entities=tuple(aggregation.entities),
                controversies=tuple(aggregation.controversies),
                evidence_refs=evidence_refs,
                gaps=gaps,
                outcome=outcome,
                raw_payload={
                    "xhs": collected.raw_payload,
                    "analysis": analysis_raw,
                    "insights": [
                        insight.model_dump(mode="json") for insight in aggregation.insights
                    ],
                    "claims": [
                        claim.model_dump(mode="json") for claim in aggregation.claims
                    ],
                    "entities": list(aggregation.entities),
                    "controversies": list(aggregation.controversies),
                    "dianping": enrichment.raw_payload,
                    "shop_profile_cache": {
                        "hits": list(profile_plan.fresh_cache_hits),
                        "refresh_candidates": list(profile_plan.refresh_candidates),
                    },
                    "runtime": _runtime_projection(runtime_state),
                    "actions": [
                        action.model_dump(mode="json")
                        for action in router.actions
                    ],
                    "synthesis": (
                        synthesis_result.model_dump(mode="json")
                        if synthesis_result is not None
                        else None
                    ),
                    "planner": {
                        "reason": planner_decision.reason,
                        "actions": [
                            action.model_dump(mode="json")
                            for action in planner_decision.actions
                        ],
                    },
                },
            )
            context.last_notes = [note.model_dump(mode="json") for note in notes]
            context.last_recommendations = {
                recommendation.name: recommendation.to_dict()
                for recommendation in recommendations
            }
            summary = _summary(intent, notes, recommendations, outcome)
            response = XHSFoodResponse(
                status="ok" if outcome is not ResearchOutcome.FAILED else "error",
                recommendations=recommendations,
                filtered_count=filtered_count,
                error_message="小红书评论证据采集失败" if outcome is ResearchOutcome.FAILED else None,
                summary=summary,
                research_metadata={
                    "strategy": "comment_first_runtime/v1",
                    "outcome": outcome.value,
                    "runId": run_id,
                    "noteCount": len(notes),
                    "commentEvidenceCount": len(evidence_refs),
                    "commentInsightCount": len(aggregation.insights),
                    "claimCount": len(aggregation.claims),
                    "controversyCount": len(aggregation.controversies),
                    "shopProfileCount": len(shop_profiles),
                    "shopProfileCacheHits": len(profile_plan.fresh_cache_hits),
                    "shopProfileRefreshCount": len(profile_plan.refresh_candidates),
                },
                gaps=[gap.model_dump(mode="json") for gap in gaps],
            )
            await _notify_progress(
                progress_sink,
                "research_completed",
                outcome=outcome.value,
                note_count=len(notes),
                recommendation_count=len(recommendations),
                gap_count=len(gaps),
            )
            return WorkflowExecution(response=response, run=run, intent=intent)
        finally:
            try:
                if profile_coordinator is not None:
                    await profile_coordinator.close()
            finally:
                try:
                    if runtime_for_cleanup is not None:
                        await runtime_for_cleanup.aclose()
                finally:
                    # ``open`` can fail after allocating provider resources;
                    # close is intentionally attempted for that partial-open
                    # state as well as for a fully initialized session.
                    await session.close()

    async def _collect_and_analyze(
        self,
        collector: XhsCommentLeadCollector,
        intent: FoodSearchIntent,
        *,
        runtime: ResearchRuntime,
        router: _WorkflowActionRouter,
        planner_decision: PlannerDecision,
        profile_coordinator: _ProfileEnrichmentCoordinator | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> tuple[
        tuple[Any, ...],
        tuple[str, ...],
        list[RestaurantRecommendation],
        tuple[ResearchGap, ...],
        tuple[Any, ...],
        BaseException | None,
        tuple[CommentInsight, ...],
        LeadCollectionResult | None,
    ]:
        """Stream notes into a bounded evidence/analysis worker pool.

        The collector is allowed to continue fetching source pages while a
        bounded number of completed notes are being persisted and analyzed.
        Results are merged by the producer sequence rather than completion
        time, so concurrency does not change response ordering.
        """

        # Use the runtime-owned bounded queue so the same backpressure and
        # shutdown semantics are visible in action telemetry and cleanup.
        queue = runtime.queue
        processed: dict[int, _NoteProcessingResult] = {}
        collection_error: BaseException | None = None
        search_action = planner_decision.actions[0] if planner_decision.actions else None
        search_results: list[ResearchActionResult] = []
        stream_results: list[LeadCollectionResult] = []
        seen_note_ids: set[str] = set()
        accepted_note_ids: set[str] = set()
        authoritative_note_ids: set[str] | None = None
        superseded_processing: list[_NoteProcessingResult] = []
        next_sequence = 0
        consumer_count = self._note_processing_concurrency
        queue_sentinel = object()
        sentinels_enqueued = False

        async def signal_producer_done() -> None:
            """Close the producer side without racing a pending queue read."""

            nonlocal sentinels_enqueued
            if sentinels_enqueued:
                return
            # Sentinels travel through the same bounded queue as notes.  If a
            # worker is slow, this await applies normal backpressure instead
            # of dropping the final item or waking consumers prematurely.
            for _ in range(consumer_count):
                await queue.put(queue_sentinel)
            sentinels_enqueued = True

        async def collect_search(
            action: Any,
            *,
            replan_index: int = 0,
        ) -> ResearchActionResult:
            """Run the source iterator behind the runtime's search action."""

            nonlocal collection_error, next_sequence
            emitted: list[Any] = []
            stream_error: BaseException | None = None
            queries = _action_queries(action)
            try:
                async for note in _collector_iter_notes(collector, intent, queries):
                    stream_sequence = len(emitted)
                    note = _annotate_collection_order(
                        note,
                        replan_index=replan_index,
                        stream_sequence=stream_sequence,
                    )
                    emitted.append(note)
                    accepted = False
                    note_id = str(getattr(note, "note_id", ""))
                    if note_id and note_id not in seen_note_ids:
                        seen_note_ids.add(note_id)
                        if len(accepted_note_ids) < self._max_notes:
                            accepted_note_ids.add(note_id)
                            sequence = next_sequence
                            next_sequence += 1
                            await queue.put((sequence, note, action.action_id))
                            accepted = True
                    if not accepted:
                        sequence = stream_sequence
                    await runtime.report_progress(
                        action,
                        item_count=len(emitted),
                        completeness="partial",
                        payload={
                            "phase": "note_collected",
                            "note_id": note.note_id,
                            "sequence": sequence,
                            "accepted": accepted,
                            "queue_size": queue.qsize,
                        },
                    )
                    await _notify_progress(
                        progress_sink,
                        "note_collected",
                        note_id=note.note_id,
                        sequence=sequence,
                        comment_count=len(note.comments),
                    )
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - source failure is typed below
                stream_error = exc
                if collection_error is None:
                    collection_error = exc

            stream_result = getattr(collector, "last_stream_result", None)
            if stream_result is None and stream_results:
                # Structural collectors may only expose the iterator.  The
                # action callback still records its terminal projection for
                # the reconciliation pass.
                stream_result = stream_results[-1]
            source_gaps: list[ResearchGap] = list(
                getattr(stream_result, "gaps", ()) or ()
            )
            if stream_error is not None:
                source_gaps.append(
                    ResearchGap(
                        source="xhs",
                        operation="notes.stream",
                        code="stream_exception",
                        message=type(stream_error).__name__,
                        retryable=True,
                    )
                )
            raw_payload = getattr(stream_result, "raw_payload", None)
            if raw_payload is None:
                raw_payload = {"notes": [note.raw_payload for note in emitted]}
            final_notes = tuple(
                _annotate_collection_order(
                    note,
                    replan_index=replan_index,
                    stream_sequence=index,
                )
                for index, note in enumerate(
                    tuple(getattr(stream_result, "notes", ()) or emitted)
                )
            )

            # ``iter_notes`` may emit an early slot before a slower search
            # wave finishes.  The collector then exposes a deterministic final
            # top-k snapshot and can yield compensation notes that were not
            # admitted by the early global slot budget.  Admit those final
            # notes before the producer sends sentinels so their evidence and
            # analysis are never raw-only.  The collector itself bounds this
            # list; the queue still applies normal backpressure.
            for compensation_note in final_notes:
                compensation_id = str(getattr(compensation_note, "note_id", ""))
                if not compensation_id or compensation_id in accepted_note_ids:
                    continue
                accepted_note_ids.add(compensation_id)
                seen_note_ids.add(compensation_id)
                sequence = next_sequence
                next_sequence += 1
                await queue.put((sequence, compensation_note, action.action_id))
                emitted.append(compensation_note)
                await runtime.report_progress(
                    action,
                    item_count=len(emitted),
                    completeness="partial",
                    payload={
                        "phase": "note_compensated",
                        "note_id": compensation_id,
                        "sequence": sequence,
                        "accepted": True,
                        "queue_size": queue.qsize,
                    },
                )
            envelope = _source_envelope(
                source="xhs",
                operation="notes.search",
                normalized_items=tuple(
                    note.model_dump(mode="json") for note in emitted
                ),
                raw_payload=raw_payload,
                completeness="partial" if source_gaps else "complete",
                provenance={"queries": list(queries)},
            )
            result = ResearchActionResult(
                action_id=action.action_id,
                success=not (stream_error is not None and not emitted),
                source_envelopes=(envelope,),
                gaps=tuple(_dedupe_gaps(source_gaps)),
                item_count=len(emitted),
                completeness="partial" if source_gaps else "complete",
                output={"queries": list(queries), "note_count": len(emitted)},
                metadata={
                    "query_count": len(queries),
                    "replan_index": replan_index,
                },
            )
            stream_results.append(
                LeadCollectionResult(
                    notes=final_notes,
                    gaps=tuple(_dedupe_gaps(source_gaps)),
                    raw_payload=raw_payload,
                )
            )
            return result

        async def dispatch_search() -> ResearchActionResult | None:
            nonlocal collection_error
            if search_action is None:
                await signal_producer_done()
                return None
            router.register(
                search_action.action_id,
                collect_search,
                manages_resources=True,
                action=search_action,
            )
            try:
                initial_result = await runtime.dispatch(search_action)
                search_results.append(initial_result)

                # Replanning is deliberately a single incremental wave.  It
                # is enabled only when both policy layers grant a positive
                # budget and the completed collection action exposed a typed,
                # retryable gap.  Consumer failures cannot accidentally turn
                # into another source sweep while this producer is active.
                planner_budget = max(0, int(getattr(self._planner, "max_replans", 0)))
                runtime_budget = max(0, int(getattr(runtime.config, "max_replans", 0)))
                can_expand = min(planner_budget, runtime_budget, 1) > 0
                retryable_gap = any(gap.retryable for gap in initial_result.gaps)
                if can_expand and retryable_gap:
                    state = runtime.state
                    if state is not None:
                        try:
                            expansion = self._planner.replan(
                                intent,
                                state,
                                run_id=state.run_id,
                            )
                        except asyncio.CancelledError:
                            raise
                        except BaseException as exc:  # noqa: BLE001 - planner is isolated
                            if collection_error is None:
                                collection_error = exc
                            expansion = None
                        if expansion is not None and expansion.actions:
                            action = expansion.actions[0]
                            router.register(
                                action.action_id,
                                lambda dispatched, _action=action, _index=expansion.replan_index: collect_search(
                                    _action,
                                    replan_index=_index,
                                ),
                                manages_resources=True,
                                action=action,
                            )
                            expansion_result = await runtime.dispatch(action)
                            search_results.append(expansion_result)
                return initial_result
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - preserve as typed gap
                if collection_error is None:
                    collection_error = exc
                return None
            finally:
                # A policy rejection or planner failure still has to wake all
                # consumers.  Sentinels are emitted only after the optional
                # expansion wave, so no consumer can exit before its notes.
                with suppress(asyncio.CancelledError, QueueClosedError):
                    await signal_producer_done()

        async def consume() -> None:
            while True:
                try:
                    item = await queue.get()
                except QueueClosedError:
                    return
                if item is queue_sentinel:
                    queue.task_done()
                    return
                try:
                    sequence, note, origin_action_id = item
                    run_prefix = runtime.state.run_id if runtime.state else "run"
                    action_prefix = f"{run_prefix}:note:{sequence}:{note.note_id}"
                    fetch_action = FetchNoteEvidence(
                        action_id=f"{action_prefix}:evidence",
                        idempotency_key=f"{action_prefix}:evidence",
                        note_id=note.note_id,
                        dependencies=(),
                        inputs={
                            "search_action_id": origin_action_id,
                            "note_sequence": sequence,
                        },
                        reason="persist one completed note's canonical comment evidence",
                    )
                    analyze_action = AnalyzeCommentBatch(
                        action_id=f"{action_prefix}:analysis",
                        idempotency_key=f"{action_prefix}:analysis",
                        note_id=note.note_id,
                        batch_index=0,
                        comment_ids=tuple(
                            dict.fromkeys(item.comment_id for item in note.comments)
                        ),
                        token_estimate=_comment_token_estimate(note),
                        inputs={
                            "search_action_id": origin_action_id,
                            "note_sequence": sequence,
                        },
                        reason="interpret every available comment for shop and controversy clues",
                    )
                    holder: dict[str, Any] = {
                        "evidence_refs": (),
                        "recommendations": (),
                        "insights": (),
                        "gaps": [],
                        "raw_payload": {
                            "note_id": note.note_id,
                            "raw_output": None,
                            "raw_comments": None,
                        },
                    }

                    async def persist_action(
                        dispatched: Any,
                        *,
                        _note: Any = note,
                        _action: FetchNoteEvidence = fetch_action,
                        _sequence: int = sequence,
                        _holder: dict[str, Any] = holder,
                    ) -> ResearchActionResult:
                        await runtime.report_progress(
                            _action,
                            item_count=len(_note.comments),
                            completeness="partial"
                            if _note.comment_completeness == "partial"
                            else "unknown",
                            payload={
                                "phase": "evidence_ready",
                                "note_id": _note.note_id,
                            },
                        )
                        local_gaps: list[ResearchGap] = []
                        try:
                            refs = await self._record_evidence(_note, runtime=runtime)
                        except asyncio.CancelledError:
                            raise
                        except BaseException as exc:  # noqa: BLE001 - isolate one note
                            refs = tuple(
                                ref
                                for ref in (evidence_ref(item) for item in _note.comments)
                                if self._evidence.get(ref) is not None
                            )
                            local_gaps.append(
                                ResearchGap(
                                    source="evidence",
                                    operation="canonical.write",
                                    code="evidence_record_failed",
                                    message=type(exc).__name__,
                                    retryable=True,
                                    details={"note_id": _note.note_id},
                                )
                            )
                        _holder["evidence_refs"] = tuple(refs)
                        _holder["gaps"].extend(local_gaps)
                        return ResearchActionResult(
                            action_id=_action.action_id,
                            success=True,
                            notes=(_note,),
                            gaps=tuple(local_gaps),
                            source_envelopes=(
                                _source_envelope(
                                    source="xhs",
                                    operation="comments.search",
                                    normalized_items=tuple(
                                        item.model_dump(mode="json")
                                        for item in _note.comments
                                    ),
                                    raw_payload=_note.raw_payload,
                                    completeness=(
                                        "partial"
                                        if _note.gaps
                                        or _note.comment_completeness == "partial"
                                        else "complete"
                                    ),
                                    cursor=_note.comment_cursor,
                                    next_cursor=_note.comment_cursor,
                                    has_more=bool(_note.comment_has_more and _note.comment_cursor),
                                    provenance={"note_id": _note.note_id},
                                ),
                            ),
                            item_count=len(_note.comments),
                            completeness="partial"
                            if local_gaps or _note.comment_completeness == "partial"
                            else "complete",
                            output={
                                "note_id": _note.note_id,
                                "evidence_refs": list(refs),
                            },
                            metadata={"sequence": _sequence},
                        )

                    async def analyze_action_handler(
                        dispatched: Any,
                        *,
                        _note: Any = note,
                        _action: AnalyzeCommentBatch = analyze_action,
                        _sequence: int = sequence,
                        _holder: dict[str, Any] = holder,
                    ) -> ResearchActionResult:
                        await runtime.report_progress(
                            _action,
                            item_count=len(_note.comments),
                            completeness="unknown",
                            payload={
                                "phase": "analysis_started",
                                "note_id": _note.note_id,
                                "batch_index": _action.batch_index,
                            },
                        )
                        local_gaps: list[ResearchGap] = []
                        try:
                            analysis = await self._analyze_note(
                                _note,
                                intent,
                                runtime=runtime,
                            )
                        except asyncio.CancelledError:
                            raise
                        except BaseException as exc:  # noqa: BLE001 - isolate one batch
                            analysis = None
                            local_gaps.append(
                                ResearchGap(
                                    source="agent",
                                    operation="comments.analyze",
                                    code="analysis_exception",
                                    message=type(exc).__name__,
                                    retryable=True,
                                    details={"note_id": _note.note_id},
                                )
                            )
                        recommendations: tuple[RestaurantRecommendation, ...] = ()
                        insights: tuple[CommentInsight, ...] = ()
                        raw_output: Any = None
                        raw_comments: Any = None
                        if analysis is not None:
                            raw_output = getattr(analysis, "raw_output", None)
                            raw_comments = getattr(analysis, "raw_comments", None)
                            insights = tuple(getattr(analysis, "insights", ()) or ())
                            local_gaps.extend(tuple(getattr(analysis, "gaps", ()) or ()))
                            if getattr(analysis, "success", False):
                                recommendations = tuple(
                                    getattr(analysis, "restaurants", ()) or ()
                                )
                            else:
                                local_gaps.append(
                                    ResearchGap(
                                        source="agent",
                                        operation="comments.analyze",
                                        code="analysis_failed",
                                        message=(
                                            getattr(analysis, "error", None)
                                            or "comment analysis failed"
                                        ),
                                        retryable=True,
                                        details={"note_id": _note.note_id},
                                    )
                                )
                        _holder["recommendations"] = recommendations
                        _holder["insights"] = insights
                        _holder["gaps"].extend(local_gaps)
                        _holder["raw_payload"] = {
                            "note_id": _note.note_id,
                            "raw_output": raw_output,
                            "raw_comments": raw_comments,
                        }
                        return ResearchActionResult(
                            action_id=_action.action_id,
                            # A failed interpretation is a usable partial
                            # action: raw comments/evidence remain available
                            # and the runtime must not block unrelated notes.
                            success=True,
                            insights=insights,
                            gaps=tuple(local_gaps),
                            item_count=len(_note.comments),
                            completeness="partial" if local_gaps else "complete",
                            output=cast(Any, {
                                "note_id": _note.note_id,
                                "recommendations": [
                                    _recommendation_payload(recommendation)
                                    for recommendation in recommendations
                                ],
                                "raw_output": raw_output,
                            }),
                            tokens_used=_action.token_estimate,
                            metadata={
                                "sequence": _sequence,
                                "batch_index": _action.batch_index,
                            },
                        )

                    router.register(
                        fetch_action.action_id,
                        persist_action,
                        manages_resources=True,
                        action=fetch_action,
                    )
                    router.register(
                        analyze_action.action_id,
                        analyze_action_handler,
                        manages_resources=True,
                        action=analyze_action,
                    )
                    fetch_result, analyze_result = await asyncio.gather(
                        runtime.dispatch(fetch_action),
                        runtime.dispatch(analyze_action),
                        return_exceptions=True,
                    )
                    action_gaps: list[ResearchGap] = list(holder["gaps"])
                    for action_result, action_name in (
                        (fetch_result, "evidence"),
                        (analyze_result, "analysis"),
                    ):
                        if isinstance(action_result, asyncio.CancelledError):
                            raise action_result
                        if isinstance(action_result, BaseException):
                            action_gaps.append(
                                ResearchGap(
                                    source="agent" if action_name == "analysis" else "evidence",
                                    operation=(
                                        "comments.analyze"
                                        if action_name == "analysis"
                                        else "canonical.write"
                                    ),
                                    code="action_dispatch_exception",
                                    message=type(action_result).__name__,
                                    retryable=True,
                                    details={"note_id": note.note_id},
                                )
                            )
                        elif not action_result.success:
                            action_gaps.extend(action_result.gaps)
                    local = _NoteProcessingResult(
                        note=note,
                        evidence_refs=tuple(holder["evidence_refs"]),
                        recommendations=tuple(holder["recommendations"]),
                        insights=tuple(holder["insights"]),
                        gaps=_dedupe_gaps(action_gaps),
                        raw_payload=holder["raw_payload"],
                    )
                    if profile_coordinator is not None:
                        candidate_names = tuple(
                            dict.fromkeys(
                                (
                                    *(recommendation.name for recommendation in local.recommendations),
                                    *(
                                        name
                                        for insight in local.insights
                                        for name in insight.mentioned_shops
                                    ),
                                )
                            )
                        )
                        await profile_coordinator.submit(
                            candidate_names
                        )
                    processed[sequence] = local
                    await _notify_progress(
                        progress_sink,
                        "note_analyzed",
                        note_id=note.note_id,
                        sequence=sequence,
                        recommendation_count=len(processed[sequence].recommendations),
                        gap_count=len(processed[sequence].gaps),
                    )
                finally:
                    queue.task_done()

        tasks = [
            asyncio.create_task(dispatch_search()),
            *(
                asyncio.create_task(consume())
                for _ in range(self._note_processing_concurrency)
            ),
        ]
        try:
            # A worker failure is not an item-level source gap: it means the
            # bounded pipeline cannot make progress safely.  Let gather
            # cancel the sibling tasks and propagate the failure after their
            # cleanup, while source failures remain isolated inside workers.
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        async def reconcile_stream_notes() -> None:
            """Process comments discovered after an early note snapshot.

            The collector intentionally yields as soon as one note is ready,
            while slower search variants can still add duplicate hits.  The
            final collector snapshot is the authoritative projection for
            fields and comments; only comments absent from the already
            processed note are sent through the evidence/analyzer actions.
            """

            nonlocal authoritative_note_ids
            stream_result = getattr(collector, "last_stream_result", None)
            if stream_result is None and stream_results:
                stream_result = stream_results[-1]
            # A bounded replan runs a second collector wave on the same
            # source object.  Merge every wave's final note projection before
            # comparing it with the early snapshot; otherwise a duplicate
            # note's late comments could remain raw-only and never reach the
            # evidence ledger or insight reducer.
            snapshots: list[Any] = [
                note
                for result in stream_results
                for note in result.notes
            ]
            if stream_result is not None:
                snapshots.extend(tuple(getattr(stream_result, "notes", ()) or ()))
            final_notes = _merge_note_snapshots(snapshots)
            if not final_notes:
                return

            # A collector that completed its stream has an authoritative
            # candidate projection.  Keep it separate from the early work
            # ledger: superseded notes remain auditable, but must not leak into
            # the normalized note list returned by this run.
            authoritative_note_ids = {
                str(getattr(note, "note_id", ""))
                for note in final_notes
                if str(getattr(note, "note_id", ""))
            }

            final_by_note: dict[str, Any] = {}
            for final_note in final_notes:
                note_id = str(getattr(final_note, "note_id", ""))
                if note_id:
                    final_by_note.setdefault(note_id, final_note)

            for sequence, current in sorted(
                processed.items(),
                key=lambda pair: _note_processing_sort_key(pair[0], pair[1]),
            ):
                final_note = final_by_note.get(str(current.note.note_id))
                if final_note is None:
                    continue
                known_comments = {
                    str(comment.comment_id): comment for comment in current.note.comments
                }
                changed_comments = tuple(
                    comment
                    for comment in final_note.comments
                    if (
                        str(comment.comment_id) not in known_comments
                        or _comment_snapshot_fingerprint(
                            known_comments[str(comment.comment_id)]
                        )
                        != _comment_snapshot_fingerprint(comment)
                    )
                )
                if not changed_comments:
                    if final_note != current.note:
                        processed[sequence] = replace(current, note=final_note)
                    continue

                delta_note = final_note.model_copy(update={"comments": changed_comments})
                run_prefix = runtime.state.run_id if runtime.state else "run"
                action_prefix = (
                    f"{run_prefix}:note:{sequence}:"
                    f"{_safe_action_part(final_note.note_id)}:reconciliation"
                )
                fetch_action = FetchNoteEvidence(
                    action_id=f"{action_prefix}:evidence",
                    idempotency_key=f"{action_prefix}:evidence",
                    note_id=final_note.note_id,
                    dependencies=(
                        (search_action.action_id,) if search_action is not None else ()
                    ),
                    inputs={
                        "reconciliation": True,
                        "note_sequence": sequence,
                        "comment_ids": [comment.comment_id for comment in changed_comments],
                    },
                    reason="persist comments discovered by a late search variant",
                )
                analyze_action = AnalyzeCommentBatch(
                    action_id=f"{action_prefix}:analysis",
                    idempotency_key=f"{action_prefix}:analysis",
                    note_id=final_note.note_id,
                    batch_index=1,
                    comment_ids=tuple(comment.comment_id for comment in changed_comments),
                    token_estimate=_comment_token_estimate(delta_note),
                    dependencies=(fetch_action.action_id,),
                    inputs={
                        "reconciliation": True,
                        "note_sequence": sequence,
                        "evidence_action_id": fetch_action.action_id,
                    },
                    reason="analyze comments discovered after the early note snapshot",
                )
                holder: dict[str, Any] = {
                    "evidence_refs": (),
                    "recommendations": (),
                    "insights": (),
                    "gaps": [],
                    "raw_payload": {
                        "note_id": final_note.note_id,
                        "raw_output": None,
                        "raw_comments": None,
                    },
                }

                async def persist_reconciliation(
                    _: Any,
                    *,
                    _note: Any = delta_note,
                    _action: FetchNoteEvidence = fetch_action,
                    _holder: dict[str, Any] = holder,
                ) -> ResearchActionResult:
                    local_gaps: list[ResearchGap] = []
                    try:
                        refs = await self._record_evidence(_note, runtime=runtime)
                    except asyncio.CancelledError:
                        raise
                    except BaseException as exc:  # noqa: BLE001 - keep delta usable
                        refs = tuple(
                            ref
                            for ref in (
                                evidence_ref(comment) for comment in _note.comments
                            )
                            if self._evidence.get(ref) is not None
                        )
                        local_gaps.append(
                            ResearchGap(
                                source="evidence",
                                operation="canonical.write",
                                code="evidence_reconciliation_failed",
                                message=type(exc).__name__,
                                retryable=True,
                                details={"note_id": _note.note_id},
                            )
                        )
                    _holder["evidence_refs"] = tuple(refs)
                    _holder["gaps"].extend(local_gaps)
                    return ResearchActionResult(
                        action_id=_action.action_id,
                        success=True,
                        notes=(_note,),
                        gaps=tuple(local_gaps),
                        source_envelopes=(
                            _source_envelope(
                                source="xhs",
                                operation="comments.search",
                                normalized_items=tuple(
                                    comment.model_dump(mode="json")
                                    for comment in _note.comments
                                ),
                                raw_payload=_note.raw_payload,
                                completeness=(
                                    "partial"
                                    if _note.gaps
                                    or _note.comment_completeness == "partial"
                                    else "complete"
                                ),
                                cursor=_note.comment_cursor,
                                next_cursor=_note.comment_cursor,
                                has_more=bool(
                                    _note.comment_has_more and _note.comment_cursor
                                ),
                                provenance={
                                    "note_id": _note.note_id,
                                    "reconciliation": True,
                                },
                            ),
                        ),
                        item_count=len(_note.comments),
                        completeness=(
                            "partial"
                            if local_gaps or _note.comment_completeness == "partial"
                            else "complete"
                        ),
                        output={
                            "note_id": _note.note_id,
                            "evidence_refs": list(refs),
                            "reconciliation": True,
                        },
                    )

                async def analyze_reconciliation(
                    _: Any,
                    *,
                    _note: Any = delta_note,
                    _action: AnalyzeCommentBatch = analyze_action,
                    _holder: dict[str, Any] = holder,
                    _sequence: int = sequence,
                ) -> ResearchActionResult:
                    local_gaps: list[ResearchGap] = []
                    try:
                        analysis = await self._analyze_note(
                            _note,
                            intent,
                            runtime=runtime,
                        )
                    except asyncio.CancelledError:
                        raise
                    except BaseException as exc:  # noqa: BLE001 - isolate delta
                        analysis = None
                        local_gaps.append(
                            ResearchGap(
                                source="agent",
                                operation="comments.analyze",
                                code="analysis_reconciliation_exception",
                                message=type(exc).__name__,
                                retryable=True,
                                details={"note_id": _note.note_id},
                            )
                        )

                    recommendations: tuple[RestaurantRecommendation, ...] = ()
                    insights: tuple[CommentInsight, ...] = ()
                    raw_output: Any = None
                    raw_comments: Any = None
                    if analysis is not None:
                        raw_output = getattr(analysis, "raw_output", None)
                        raw_comments = getattr(analysis, "raw_comments", None)
                        insights = tuple(getattr(analysis, "insights", ()) or ())
                        local_gaps.extend(tuple(getattr(analysis, "gaps", ()) or ()))
                        if getattr(analysis, "success", False):
                            recommendations = tuple(
                                getattr(analysis, "restaurants", ()) or ()
                            )
                        else:
                            local_gaps.append(
                                ResearchGap(
                                    source="agent",
                                    operation="comments.analyze",
                                    code="analysis_reconciliation_failed",
                                    message=(
                                        getattr(analysis, "error", None)
                                        or "comment reconciliation analysis failed"
                                    ),
                                    retryable=True,
                                    details={"note_id": _note.note_id},
                                )
                            )
                    _holder["recommendations"] = recommendations
                    _holder["insights"] = insights
                    _holder["gaps"].extend(local_gaps)
                    _holder["raw_payload"] = {
                        "note_id": _note.note_id,
                        "raw_output": raw_output,
                        "raw_comments": raw_comments,
                        "reconciliation": True,
                    }
                    return ResearchActionResult(
                        action_id=_action.action_id,
                        # Raw delta comments remain usable when interpretation
                        # is partial, so unrelated work stays independent.
                        success=True,
                        insights=insights,
                        gaps=tuple(local_gaps),
                        item_count=len(_note.comments),
                        completeness="partial" if local_gaps else "complete",
                        output=cast(Any, {
                            "note_id": _note.note_id,
                            "recommendations": [
                                _recommendation_payload(recommendation)
                                for recommendation in recommendations
                            ],
                            "raw_output": raw_output,
                            "reconciliation": True,
                        }),
                        tokens_used=_action.token_estimate,
                        metadata={
                            "sequence": _sequence,
                            "batch_index": _action.batch_index,
                            "reconciliation": True,
                        },
                    )

                router.register(
                    fetch_action.action_id,
                    persist_reconciliation,
                    manages_resources=True,
                    action=fetch_action,
                )
                router.register(
                    analyze_action.action_id,
                    analyze_reconciliation,
                    manages_resources=True,
                    action=analyze_action,
                )

                delta_gaps: list[ResearchGap] = []
                try:
                    fetch_result = await runtime.dispatch(fetch_action)
                    delta_gaps.extend(fetch_result.gaps)
                    analysis_result: ResearchActionResult | None = None
                    if fetch_result.success:
                        analysis_result = await runtime.dispatch(analyze_action)
                        delta_gaps.extend(analysis_result.gaps)
                    else:
                        delta_gaps.append(
                            ResearchGap(
                                source="agent",
                                operation="comments.analyze",
                                code="analysis_reconciliation_skipped",
                                message="evidence reconciliation did not complete",
                                retryable=True,
                                details={"note_id": final_note.note_id},
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:  # noqa: BLE001 - isolate one delta
                    delta_gaps.append(
                        ResearchGap(
                            source="agent",
                            operation="comments.reconcile",
                            code="reconciliation_dispatch_exception",
                            message=type(exc).__name__,
                            retryable=True,
                            details={"note_id": final_note.note_id},
                        )
                    )

                delta_refs = tuple(holder["evidence_refs"])
                delta_recommendations = tuple(holder["recommendations"])
                delta_insights = tuple(holder["insights"])
                delta_gaps.extend(holder["gaps"])
                current_raw = current.raw_payload
                reconciliation_raw = holder["raw_payload"]
                if isinstance(current_raw, Mapping):
                    merged_raw: Any = dict(current_raw)
                    merged_raw["reconciliation"] = reconciliation_raw
                else:
                    merged_raw = {
                        "initial": current_raw,
                        "reconciliation": reconciliation_raw,
                    }
                processed[sequence] = replace(
                    current,
                    note=final_note,
                    evidence_refs=tuple(
                        dict.fromkeys((*current.evidence_refs, *delta_refs))
                    ),
                    recommendations=tuple(
                        (*current.recommendations, *delta_recommendations)
                    ),
                    insights=tuple((*current.insights, *delta_insights)),
                    gaps=_dedupe_gaps((*current.gaps, *delta_gaps)),
                    raw_payload=merged_raw,
                )
                if profile_coordinator is not None:
                    candidate_names = tuple(
                        dict.fromkeys(
                            (
                                *(recommendation.name for recommendation in delta_recommendations),
                                *(
                                    name
                                    for insight in delta_insights
                                    for name in insight.mentioned_shops
                                ),
                            )
                        )
                    )
                    await profile_coordinator.submit(candidate_names)
                await _notify_progress(
                    progress_sink,
                    "note_reconciled",
                    note_id=final_note.note_id,
                    sequence=sequence,
                    comment_count=len(changed_comments),
                    gap_count=len(delta_gaps),
                )

        await reconcile_stream_notes()

        if authoritative_note_ids is not None:
            # Preserve superseded work for the audit projection and evidence
            # references, while using only the collector's final candidate
            # set for normalized notes.  This keeps the top-k contract stable
            # without deleting an early note's captured evidence.
            for sequence, item in tuple(processed.items()):
                note_id = str(getattr(item.note, "note_id", ""))
                if note_id not in authoritative_note_ids:
                    superseded_processing.append(item)
                    processed.pop(sequence, None)

        ordered = [
            item
            for _, item in sorted(
                processed.items(),
                key=lambda pair: _note_processing_sort_key(pair[0], pair[1]),
            )
        ]
        notes = tuple(item.note for item in ordered)
        refs: list[str] = []
        recommendations: list[RestaurantRecommendation] = []
        gaps: list[ResearchGap] = []
        raw_analysis: list[Any] = []
        insights: list[CommentInsight] = []
        # Superseded notes are intentionally excluded from the normalized note
        # projection, but their references, interpretations, gaps, and raw
        # provider payload remain part of this run's audit surface.
        all_items = (*superseded_processing, *ordered)
        for item in all_items:
            refs.extend(item.evidence_refs)
            recommendations.extend(item.recommendations)
            insights.extend(item.insights)
            gaps.extend(item.gaps)
            if item.raw_payload is not None:
                if item in superseded_processing and isinstance(item.raw_payload, Mapping):
                    raw_analysis.append({**dict(item.raw_payload), "superseded": True})
                else:
                    raw_analysis.append(item.raw_payload)
        for result in search_results:
            gaps.extend(result.gaps)
        collection_snapshot = (
            LeadCollectionResult(
                notes=notes,
                gaps=_dedupe_gaps(
                    tuple(gap for result in stream_results for gap in result.gaps)
                ),
                raw_payload=_merge_stream_payloads(stream_results),
            )
            if stream_results
            else None
        )
        return (
            notes,
            tuple(dict.fromkeys(refs)),
            recommendations,
            _dedupe_gaps(gaps),
            tuple(raw_analysis),
            collection_error,
            tuple(insights),
            collection_snapshot,
        )

    async def _record_evidence(
        self,
        note: Any,
        *,
        runtime: ResearchRuntime | None = None,
    ) -> tuple[str, ...]:
        """Serialize ledger mutations while allowing analysis to overlap."""

        async with self._evidence_write_lock:
            if runtime is None:
                return await self._evidence.record(note)
            value = await runtime.invoke_resource(
                ResourceClass.PERSISTENCE,
                self._evidence.record,
                note,
            )
            return tuple(value)

    def _new_runtime(
        self,
        router: _WorkflowActionRouter,
        *,
        capabilities: tuple[str, ...] | None,
        event_sink: Callable[[ResearchEvent], Any],
    ) -> ResearchRuntime:
        """Build one run-scoped runtime with explicit resource classes."""

        config = self._runtime_config or ResearchRuntimeConfig(
            queue_size=self._note_queue_size,
            max_parallel_actions=max(
                2,
                self._note_processing_concurrency + 1,
                self._profile_concurrency + 1,
            ),
            resource_pools={
                ResourceClass.XHS_SEARCH.value: ResourcePoolConfig(
                    resource_class=ResourceClass.XHS_SEARCH,
                    max_concurrency=1,
                ),
                ResourceClass.XHS_DETAIL.value: ResourcePoolConfig(
                    resource_class=ResourceClass.XHS_DETAIL,
                    max_concurrency=self._note_processing_concurrency,
                ),
                ResourceClass.XHS_COMMENTS.value: ResourcePoolConfig(
                    resource_class=ResourceClass.XHS_COMMENTS,
                    max_concurrency=self._note_processing_concurrency,
                ),
                ResourceClass.LLM.value: ResourcePoolConfig(
                    resource_class=ResourceClass.LLM,
                    max_concurrency=self._note_processing_concurrency,
                ),
                ResourceClass.DIANPING_SEARCH.value: ResourcePoolConfig(
                    resource_class=ResourceClass.DIANPING_SEARCH,
                    max_concurrency=self._profile_concurrency,
                ),
                ResourceClass.DIANPING_DETAIL.value: ResourcePoolConfig(
                    resource_class=ResourceClass.DIANPING_DETAIL,
                    max_concurrency=self._profile_concurrency,
                ),
                ResourceClass.DIANPING_REVIEWS.value: ResourcePoolConfig(
                    resource_class=ResourceClass.DIANPING_REVIEWS,
                    max_concurrency=self._profile_concurrency,
                ),
                ResourceClass.PERSISTENCE.value: ResourcePoolConfig(
                    resource_class=ResourceClass.PERSISTENCE,
                    max_concurrency=1,
                ),
            },
        )
        if self._runtime_factory is not None:
            return self._runtime_factory(
                action_handler=router,
                config=config,
                capabilities=capabilities,
                event_sink=event_sink,
            )
        return ResearchRuntime(
            router,
            config=config,
            capabilities=capabilities,
            event_sink=event_sink,
        )

    async def _analyze_note(
        self,
        note: Any,
        intent: FoodSearchIntent,
        *,
        runtime: ResearchRuntime | None = None,
    ) -> Any:
        comments = [
            {
                "id": item.comment_id,
                "comment_id": item.comment_id,
                "text": item.text,
                "likes": item.likes,
                "sub_comment_count": item.replies,
                "user": _author_name(item.author),
                "raw_payload": item.raw_payload,
            }
            for item in note.comments
        ]
        async with self._analysis_semaphore:
            if isinstance(self._analyzer, AnalyzerAgent):
                return await self._analyzer.analyze(
                    note.title,
                    note.summary,
                    comments,
                    intent.exclude_keywords,
                    note.note_id,
                    resource_executor=(runtime.resource_invoker if runtime else None),
                )
            if runtime is not None:
                value = await runtime.invoke_resource(
                    ResourceClass.LLM,
                    self._analyzer.analyze,
                    note.title,
                    note.summary,
                    comments,
                    intent.exclude_keywords,
                    note.note_id,
                )
                return value
            analyzer: Any = self._analyzer
            return await analyzer.analyze(
                note.title,
                note.summary,
                comments,
                intent.exclude_keywords,
                note.note_id,
            )


def _action_queries(action: Any) -> tuple[str, ...]:
    """Read planner queries from a validated search or expansion action."""

    queries = getattr(action, "queries", ()) or getattr(action, "query_variants", ()) or ()
    query = getattr(action, "query", None)
    values = tuple(str(item).strip() for item in queries if str(item).strip())
    if query and str(query).strip() and str(query).strip() not in values:
        values = (*values, str(query).strip())
    return values


async def _collector_iter_notes(
    collector: Any,
    intent: FoodSearchIntent,
    queries: Sequence[str],
) -> AsyncIterator[Any]:
    """Invoke the query-aware note stream exposed by the collector."""

    iterator_factory = collector.iter_notes
    # The production collector exposes the query-aware signature.  Structural
    # test/application doubles may still implement the original one-argument
    # stream; detect that at the boundary without swallowing errors raised by
    # the iterator itself.
    try:
        parameters = inspect.signature(iterator_factory).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "queries" in parameters:
        iterator = iterator_factory(intent, queries=tuple(queries))
    else:
        iterator = iterator_factory(intent)
    async for note in iterator:
        yield note


def _source_envelope(
    *,
    source: str,
    operation: str,
    normalized_items: Sequence[Any],
    raw_payload: Any,
    completeness: Literal["complete", "partial", "unknown"],
    provenance: Mapping[str, Any] | None = None,
    cursor: str | None = None,
    next_cursor: str | None = None,
    has_more: bool = False,
) -> SourceEnvelope:
    """Create a lossless envelope while normalizing provider pagination flags."""

    effective_has_more = bool(has_more and next_cursor)
    effective_completeness: Literal["complete", "partial", "unknown"] = completeness
    if effective_completeness == "complete" and effective_has_more:
        effective_completeness = "partial"
    return SourceEnvelope(
        source=source,
        operation=operation,
        normalized_items=tuple(normalized_items),
        provider_response=raw_payload,
        raw_payload=raw_payload,
        cursor=cursor,
        next_cursor=next_cursor if effective_has_more else None,
        has_more=effective_has_more,
        completeness=effective_completeness,
        provenance=dict(provenance or {}),
    )


def _snapshot_capabilities(session: ManagedMcpToolSession) -> tuple[str, ...] | None:
    """Extract the pinned MCP capability set without coupling to its DTO class."""

    snapshot = getattr(session, "snapshot", None)
    projection = getattr(snapshot, "projection", None)
    if projection is None:
        # Unconfigured/custom sessions enforce their own fail-closed behavior.
        return None
    capabilities: set[str] = set()
    for item in projection:
        capability = getattr(item, "capability", None)
        if capability:
            capabilities.add(str(capability))
    # These are local semantic stages, not remote MCP tools.
    capabilities.update({"comments.analyze", "research.synthesize", "research.stop"})
    return tuple(sorted(capabilities))


def _runtime_projection(state: ResearchState) -> dict[str, Any]:
    """Expose compact run telemetry while keeping raw source data elsewhere."""

    return {
        "schema_version": state.schema_version,
        "run_id": state.run_id,
        "outcome": state.outcome.value,
        "completed_action_ids": list(state.completed_action_ids),
        "failed_action_ids": list(state.failed_action_ids),
        "in_flight_action_ids": list(state.in_flight_action_ids),
        "sequence": state.sequence,
        "tokens_used": state.tokens_used,
        "replans": state.replans,
        "event_count": len(state.events),
        "gap_count": len(state.gaps),
    }


def _safe_action_part(value: str) -> str:
    """Keep semantic action ids readable and bounded for arbitrary shop names."""

    normalized = "".join(char if char.isalnum() else "_" for char in value)
    return normalized[:64] or "candidate"


def _recommendation_payload(value: RestaurantRecommendation) -> Mapping[str, Any]:
    """Serialize the domain dataclass at the workflow JSON boundary.

    The food schema intentionally remains framework-neutral and exposes
    ``to_dict`` rather than Pydantic's ``model_dump``.  Keeping this adapter at
    the runtime boundary prevents transport serialization details from
    leaking into the analyzer or the semantic action contracts.
    """

    payload = value.to_dict()
    if not isinstance(payload, Mapping):
        raise TypeError("RestaurantRecommendation.to_dict() must return a mapping")
    return payload


def _attach_evidence(
    recommendations: Sequence[RestaurantRecommendation],
    notes: Sequence[Any],
    evidence_refs: Sequence[str],
) -> None:
    # Build the relation from the typed notes instead of parsing a transport
    # reference string.  Provider IDs may legally contain ``:`` and should
    # never be mis-associated by a delimiter heuristic.
    allowed_refs = set(evidence_refs)
    refs_by_note: dict[str, list[str]] = {
        note.note_id: [
            ref
            for item in note.comments
            if (ref := evidence_ref(item)) in allowed_refs
        ]
        for note in notes
    }
    notes_by_id = {note.note_id: note for note in notes}
    for recommendation in recommendations:
        refs: list[str] = []
        source_gaps: list[dict[str, Any]] = []
        comment_count = 0
        for note_id in recommendation.source_notes:
            refs.extend(refs_by_note.get(note_id, ()))
            note = notes_by_id.get(note_id)
            if note is not None:
                comment_count += len(note.comments)
                source_gaps.extend(gap.model_dump(mode="json") for gap in note.gaps)
        recommendation.evidence_refs = list(dict.fromkeys(refs))
        recommendation.evidence_summary = {
            "commentCount": comment_count,
            "noteCount": len(set(recommendation.source_notes)),
        }
        recommendation.source_gaps = source_gaps


def _attach_profiles(
    recommendations: Sequence[RestaurantRecommendation],
    profiles: Sequence[ShopProfile],
) -> None:
    for recommendation in recommendations:
        profile = _profile_for_name(recommendation.name, profiles)
        if profile is None:
            continue
        recommendation.location = profile.address or profile.region or recommendation.location
        recommendation.tags = list(dict.fromkeys((*recommendation.tags, *profile.tags)))
        if not recommendation.must_try:
            recommendation.must_try = [MustTryItem(name=item) for item in profile.recommended_dishes]
        projection = {
            "providerRefs": dict(profile.provider_refs),
            "name": profile.name,
            "alias": profile.alias,
            "url": profile.url,
            "sourceUrl": profile.source_url,
            "imageUrl": profile.image_url,
            "images": list(profile.images),
            "address": profile.address,
            "city": profile.city,
            "district": profile.district,
            "region": profile.region,
            "businessArea": profile.business_area,
            "location": profile.location,
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "coordinateSystem": profile.coordinate_system,
            "geo": dict(profile.geo),
            "phone": profile.phone,
            "rating": profile.rating,
            "reviewCount": profile.review_count,
            "averagePrice": profile.average_price,
            "category": profile.category,
            "openingHours": profile.opening_hours,
            "recommendedDishes": list(profile.recommended_dishes),
            "promotions": list(profile.promotions),
            "tags": list(profile.tags),
            "attributes": dict(profile.attributes),
            "reviewCompleteness": dict(profile.review_completeness),
            "profileOutcome": profile.outcome.value,
            "profileGaps": [gap.model_dump(mode="json") for gap in profile.gaps],
        }
        recommendation.shop_profile = projection


def _profile_for_name(name: str, profiles: Sequence[ShopProfile]) -> ShopProfile | None:
    target = _normalise_name(name)
    if not target:
        return None
    matches: list[ShopProfile] = []
    for profile in profiles:
        names = {
            _normalise_name(profile.name),
            *(
                _normalise_name(alias)
                for alias in (profile.alias or "").split(",")
                if alias
            ),
        }
        if target in names:
            matches.append(profile)
    return matches[0] if len(matches) == 1 else None


def _merge_profile_plans(
    names: Sequence[str],
    plans: Sequence[ShopProfileRefreshPlan],
) -> ShopProfileRefreshPlan:
    """Merge per-candidate cache decisions without guessing identities."""

    by_name = {candidate: plan for plan in plans for candidate in plan.candidates}
    cached: list[ShopProfile] = []
    cached_keys: set[str] = set()
    refresh: list[str] = []
    hits: list[str] = []
    gaps: list[ResearchGap] = []
    for name in names:
        plan = by_name.get(name)
        if plan is None:
            refresh.append(name)
            gaps.append(
                ResearchGap(
                    source="shop_profile",
                    operation="cache.lookup",
                    code="profile_plan_missing",
                    message="profile cache decision was not returned for candidate",
                    retryable=True,
                    details={"candidate": name},
                )
            )
            continue
        gaps.extend(plan.gaps)
        if name in plan.refresh_candidates:
            refresh.append(name)
        if name in plan.fresh_cache_hits:
            hits.append(name)
        for profile in plan.cached_profiles:
            provider_ref = str(profile.provider_refs.get("dianping") or "").strip()
            key = f"dianping:{provider_ref}" if provider_ref else f"name:{_normalise_name(profile.name)}"
            if key in cached_keys:
                continue
            cached_keys.add(key)
            cached.append(profile)
    return ShopProfileRefreshPlan(
        candidates=tuple(names),
        cached_profiles=tuple(cached),
        refresh_candidates=tuple(dict.fromkeys(refresh)),
        fresh_cache_hits=tuple(dict.fromkeys(hits)),
        gaps=tuple(_dedupe_gaps(gaps)),
    )


def _merge_profile_projection(
    candidates: Sequence[str], profiles: Sequence[ShopProfile]
) -> tuple[ShopProfile, ...]:
    """Build a deterministic, non-destructive view when persistence is unavailable."""

    by_identity: dict[tuple[str, str], ShopProfile] = {}
    for profile in profiles:
        provider_ref = str(profile.provider_refs.get("dianping") or "").strip()
        identity = (
            ("dianping", provider_ref)
            if provider_ref
            else ("name", _normalise_name(profile.name))
        )
        if not identity[1]:
            continue
        previous = by_identity.get(identity)
        by_identity[identity] = (
            merge_profiles(previous, profile) if previous is not None else profile
        )

    remaining = list(by_identity.values())
    ordered: list[ShopProfile] = []
    for candidate in candidates:
        normalized = _normalise_name(candidate)
        matches = [
            profile
            for profile in remaining
            if normalized and normalized == _normalise_name(profile.name)
        ]
        if len(matches) == 1:
            ordered.append(matches[0])
            remaining.remove(matches[0])
    ordered.extend(
        sorted(
            remaining,
            key=lambda profile: (
                _normalise_name(profile.name),
                str(profile.provider_refs.get("dianping") or ""),
            ),
        )
    )
    return tuple(ordered)


def _profile_commit_gap(exc: Exception) -> ResearchGap:
    """Classify a persistence-boundary failure without hiding its cause."""

    details: dict[str, Any] = {}
    if isinstance(exc, BudgetExceededError):
        code = "profile_commit_budget_exhausted"
        details["dimension"] = exc.dimension
    elif isinstance(exc, ResourceCallTimeoutError):
        code = "profile_commit_timeout"
    elif isinstance(exc, ResourceCircuitOpenError):
        code = "profile_commit_circuit_open"
        details["resource_class"] = exc.resource_class
    else:
        code = "profile_commit_failed"
    return ResearchGap(
        source="shop_profile",
        operation="profile.commit",
        code=code,
        message=str(exc) or type(exc).__name__,
        retryable=True,
        details=details,
    )


def _comment_token_estimate(note: Any) -> int:
    """Estimate one note's model budget from every comment-bearing field.

    The estimate is deliberately conservative and deterministic.  It is only
    used for admission; the analyzer still reports actual usage and the
    runtime preserves a provider result when that usage exceeds the estimate.
    """

    title = str(getattr(note, "title", "") or "")
    summary = str(getattr(note, "summary", "") or "")
    comments = getattr(note, "comments", ()) or ()
    text_size = len(title) + len(summary)
    for comment in comments:
        text_size += len(str(getattr(comment, "text", "") or ""))
        text_size += len(str(getattr(comment, "author", "") or ""))
    if text_size <= 0:
        return 0
    # Chinese text is commonly close to one token per character; this
    # factor leaves room for labels and structured output without making the
    # estimate depend on a provider-specific tokenizer.
    return max(1, (text_size * 3 + 1) // 2)


def _comment_snapshot_fingerprint(comment: Any) -> str:
    """Compare the complete normalized comment, including raw provenance."""

    dumper = getattr(comment, "model_dump_json", None)
    if callable(dumper):
        try:
            return str(dumper())
        except Exception:  # noqa: BLE001 - custom evidence implementations
            pass
    try:
        return json.dumps(
            comment,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:  # noqa: BLE001 - deterministic fallback for opaque rows
        return repr(comment)


def _normalise_name(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _author_name(author: Mapping[str, Any]) -> str:
    for key in ("nickname", "name", "user_name", "userName"):
        value = author.get(key)
        if value:
            return str(value)
    return ""


def _dedupe_gaps(values: Sequence[ResearchGap]) -> tuple[ResearchGap, ...]:
    output: list[ResearchGap] = []
    seen: set[str] = set()
    for gap in values:
        marker = gap.model_dump_json()
        if marker not in seen:
            seen.add(marker)
            output.append(gap)
    return tuple(output)


def _with_stream_notes(raw_payload: Any, notes: Sequence[Any]) -> Any:
    """Add the streamed note projections without replacing source envelopes."""

    note_payloads = [note.raw_payload for note in notes]
    if isinstance(raw_payload, Mapping):
        payload = dict(raw_payload)
        payload["notes"] = note_payloads
        return payload
    return {
        "collector": raw_payload,
        "notes": note_payloads,
    }


def _merge_stream_payloads(results: Sequence[LeadCollectionResult]) -> Any:
    """Merge wave snapshots without flattening away provider-specific fields."""

    if not results:
        return None
    if len(results) == 1:
        return _with_stream_notes(results[0].raw_payload, results[0].notes)

    waves = [result.raw_payload for result in results]
    payload: dict[str, Any] = {
        "waves": waves,
        "notes": [note.raw_payload for result in results for note in result.notes],
    }
    queries: list[Any] = []
    searches: list[Any] = []
    for raw in waves:
        if not isinstance(raw, Mapping):
            continue
        values = raw.get("queries")
        if isinstance(values, (list, tuple)):
            queries.extend(values)
        values = raw.get("search")
        if isinstance(values, (list, tuple)):
            searches.extend(values)
    if queries:
        payload["queries"] = queries
    if searches:
        payload["search"] = searches
    return payload


def _merge_note_snapshots(values: Sequence[Any]) -> tuple[Any, ...]:
    """Merge note projections from all collection waves without losing fields."""

    by_note: dict[str, Any] = {}
    for value in values:
        note_id = str(getattr(value, "note_id", "") or "").strip()
        if not note_id:
            continue
        previous = by_note.get(note_id)
        by_note[note_id] = (
            value if previous is None else _merge_note_snapshot(previous, value)
        )
    return tuple(
        by_note[key]
        for key in sorted(
            by_note,
            key=lambda note_id: _note_snapshot_order(by_note[note_id], note_id),
        )
    )


def _merge_note_snapshot(left: Any, right: Any) -> Any:
    """Merge duplicate note snapshots while keeping a single normalized item."""

    comments = _merge_comment_snapshots(
        (*tuple(getattr(left, "comments", ()) or ()), *tuple(getattr(right, "comments", ()) or ()))
    )
    left_gaps = tuple(getattr(left, "gaps", ()) or ())
    right_gaps = tuple(getattr(right, "gaps", ()) or ())
    gaps = _dedupe_gaps((*left_gaps, *right_gaps))
    left_raw = getattr(left, "raw_payload", None)
    right_raw = getattr(right, "raw_payload", None)
    raw_payload = _merge_raw_snapshots(left_raw, right_raw)
    left_metadata = getattr(left, "metadata", {})
    right_metadata = getattr(right, "metadata", {})
    metadata = {
        **(dict(left_metadata) if isinstance(left_metadata, Mapping) else {}),
        **(dict(right_metadata) if isinstance(right_metadata, Mapping) else {}),
    }
    left_order = _workflow_collection_order(left_metadata)
    right_order = _workflow_collection_order(right_metadata)
    if left_order is not None or right_order is not None:
        metadata["workflow_collection_order"] = list(
            min(order for order in (left_order, right_order) if order is not None)
        )
    has_more = bool(
        getattr(left, "comment_has_more", False)
        or getattr(right, "comment_has_more", False)
    )
    cursor = (
        getattr(right, "comment_cursor", None)
        or getattr(left, "comment_cursor", None)
        if has_more
        else None
    )
    completeness_values = {
        str(getattr(left, "comment_completeness", "unknown")),
        str(getattr(right, "comment_completeness", "unknown")),
    }
    completeness = (
        "partial"
        if "partial" in completeness_values or gaps
        else "complete"
        if "complete" in completeness_values
        else "unknown"
    )
    outcome = (
        ResearchOutcome.PARTIAL
        if gaps
        or any(
            getattr(value, "outcome", ResearchOutcome.COMPLETE)
            is not ResearchOutcome.COMPLETE
            for value in (left, right)
        )
        else ResearchOutcome.COMPLETE
    )
    return left.model_copy(
        update={
            "title": _prefer_text(getattr(left, "title", ""), getattr(right, "title", "")),
            "summary": _prefer_text(
                getattr(left, "summary", ""), getattr(right, "summary", "")
            ),
            "url": getattr(right, "url", None) or getattr(left, "url", None),
            "comment_count": max(
                int(getattr(left, "comment_count", 0) or 0),
                int(getattr(right, "comment_count", 0) or 0),
                len(comments),
            ),
            "comment_expected_count": _max_optional_int(
                getattr(left, "comment_expected_count", None),
                getattr(right, "comment_expected_count", None),
                len(comments),
            ),
            "comment_collected_count": len(comments),
            "comment_has_more": has_more,
            "comment_cursor": cursor,
            "comment_pages": max(
                int(getattr(left, "comment_pages", 0) or 0),
                int(getattr(right, "comment_pages", 0) or 0),
            ),
            "comment_completeness": completeness,
            "comments": comments,
            "queries": tuple(
                dict.fromkeys(
                    (
                        *tuple(getattr(left, "queries", ()) or ()),
                        *tuple(getattr(right, "queries", ()) or ()),
                    )
                )
            ),
            "outcome": outcome,
            "gaps": gaps,
            "raw_payload": raw_payload,
            "metadata": metadata,
        }
    )


def _merge_comment_snapshots(values: Sequence[Any]) -> tuple[CommentEvidence, ...]:
    """Deduplicate normalized comments while retaining richer raw occurrences."""

    by_id: dict[str, CommentEvidence] = {}
    for value in values:
        if not isinstance(value, CommentEvidence):
            continue
        key = str(value.comment_id)
        previous = by_id.get(key)
        if previous is None or len(value.model_dump_json()) > len(previous.model_dump_json()):
            by_id[key] = value
    return tuple(by_id[key] for key in sorted(by_id))


def _merge_raw_snapshots(left: Any, right: Any) -> Any:
    if left == right:
        return left
    values: list[Any] = []
    for value in (left, right):
        if value not in (None, {}, [], ()):
            values.append(value)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return {"waves": values}


def _prefer_text(left: Any, right: Any) -> str:
    left_text = str(left or "")
    right_text = str(right or "")
    if not left_text:
        return right_text
    if not right_text:
        return left_text
    return right_text if len(right_text) > len(left_text) else left_text


def _max_optional_int(*values: Any) -> int | None:
    integers = [int(value) for value in values if value is not None]
    return max(integers) if integers else None


def _annotate_collection_order(
    note: Any,
    *,
    replan_index: int,
    stream_sequence: int,
) -> Any:
    """Attach a run-level wave order without changing the source metadata contract."""

    copier = getattr(note, "model_copy", None)
    if not callable(copier):
        return note
    metadata = getattr(note, "metadata", {})
    updated = dict(metadata) if isinstance(metadata, Mapping) else {}
    source_order = updated.get("collector_order")
    try:
        if isinstance(source_order, (list, tuple)) and len(source_order) >= 2:
            order = (
                int(replan_index),
                int(source_order[0]),
                int(source_order[1]),
                int(stream_sequence),
            )
        else:
            raise ValueError
    except (TypeError, ValueError):
        order = (int(replan_index), 10**9, int(stream_sequence), int(stream_sequence))
    updated["workflow_collection_order"] = list(order)
    try:
        return copier(update={"metadata": updated})
    except Exception:  # noqa: BLE001 - custom note implementations may be immutable
        return note


def _workflow_collection_order(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    order = value.get("workflow_collection_order")
    if not isinstance(order, (list, tuple)) or len(order) < 4:
        return None
    try:
        return tuple(int(item) for item in order[:4])  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _note_snapshot_order(value: Any, note_id: str) -> tuple[int, int, int, int, str]:
    metadata = getattr(value, "metadata", {})
    workflow_order = _workflow_collection_order(metadata)
    if workflow_order is not None:
        return (0, *workflow_order[:3], note_id)
    order = metadata.get("collector_order") if isinstance(metadata, Mapping) else None
    if isinstance(order, (list, tuple)) and len(order) >= 2:
        try:
            return (1, int(order[0]), int(order[1]), 0, note_id)
        except (TypeError, ValueError):
            pass
    return (2, 10**9, 10**9, 0, note_id)


def _note_processing_sort_key(
    sequence: int,
    item: _NoteProcessingResult,
) -> tuple[int, int, int, int, int, str]:
    """Prefer source order while retaining a deterministic custom-collector fallback."""

    metadata = getattr(item.note, "metadata", {})
    workflow_order = _workflow_collection_order(metadata)
    if workflow_order is not None:
        return (0, *workflow_order[:3], sequence, str(getattr(item.note, "note_id", "")))
    collector_order = metadata.get("collector_order") if isinstance(metadata, Mapping) else None
    if isinstance(collector_order, (list, tuple)) and len(collector_order) >= 2:
        try:
            return (
                1,
                int(collector_order[0]),
                int(collector_order[1]),
                0,
                sequence,
                str(getattr(item.note, "note_id", "")),
            )
        except (TypeError, ValueError):
            pass
    return (2, 0, 0, 0, sequence, str(getattr(item.note, "note_id", "")))


async def _notify_progress(
    sink: ProgressSink | None,
    kind: str,
    **payload: Any,
) -> None:
    """Send observability-only progress without changing research outcomes."""

    if sink is None:
        return
    message = {"kind": kind, **payload}
    try:
        value = sink(message)
        if inspect.isawaitable(value):
            await value
    except Exception:  # noqa: BLE001 - telemetry must never drop evidence
        # A broken UI/event sink cannot be allowed to change source coverage.
        return


async def _wait_for_tasks_cleanup(tasks: Sequence[asyncio.Task[Any]]) -> None:
    """Cancel and drain owned tasks while preserving caller cancellation."""

    if not tasks:
        return
    for task in tasks:
        if not task.done():
            task.cancel()
    waiter = asyncio.gather(*tasks, return_exceptions=True)
    cancellation: asyncio.CancelledError | None = None
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException:
            break
    with suppress(BaseException):
        waiter.result()
    if cancellation is not None:
        raise cancellation


def _outcome(
    notes: Sequence[Any],
    recommendations: Sequence[RestaurantRecommendation],
    gaps: Sequence[ResearchGap],
) -> ResearchOutcome:
    if not notes and gaps:
        return ResearchOutcome.FAILED
    if not notes:
        return ResearchOutcome.EMPTY
    if gaps:
        return ResearchOutcome.PARTIAL
    return ResearchOutcome.COMPLETE


def _summary(
    intent: FoodSearchIntent,
    notes: Sequence[Any],
    recommendations: Sequence[RestaurantRecommendation],
    outcome: ResearchOutcome,
) -> str:
    if outcome is ResearchOutcome.FAILED:
        return "小红书评论证据采集失败，未生成不可靠的空推荐"
    if not notes:
        return f"未在{intent.location}找到可分析的小红书评论证据"
    suffix = "，部分来源存在可审计缺口" if outcome is ResearchOutcome.PARTIAL else ""
    return (
        f"基于 {len(notes)} 篇小红书笔记的评论证据，"
        f"在{intent.location}识别到 {len(recommendations)} 家候选店铺{suffix}"
    )


__all__ = ["CommentFirstResearchWorkflow", "WorkflowExecution"]
