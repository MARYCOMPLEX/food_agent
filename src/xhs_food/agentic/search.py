"""Food search adapter for the generic Agent Loop.

The adapter keeps XHS-specific deterministic work in capabilities while the
runtime handles planning, retries, concurrency, review and memory.  A model
planner can be injected later without changing the API or search tools.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

from xhs_food.agents.intent_parser import IntentParserAgent, IntentParseResult
from xhs_food.capabilities import (
    CapabilityCatalog,
    CapabilityGateway,
    CapabilityManifest,
    LocalCapability,
    mcp_provider_capability,
)
from xhs_food.capabilities.models import SideEffectLevel
from xhs_food.config import settings
from xhs_food.orchestrator.follow_up import FollowUpHandler
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.runtime import (
    AgentLoop,
    AgentLoopConfig,
    AgentRunContext,
    AgentRunResult,
    Evidence,
    Plan,
    PlanExecutor,
    PlanStep,
    RuleBasedReviewer,
)
from xhs_food.schemas import (
    ConversationContext,
    FollowUpType,
    FoodSearchIntent,
    XHSFoodResponse,
)
from xhs_food.skills import FixedWorkflowSkill, SkillDefinition, SkillManifest

logger = logging.getLogger(__name__)


class SearchPlanner:
    """Safe fallback planner that still exposes composable search tools."""

    def __init__(self, context: ConversationContext) -> None:
        self._context = context

    def build(self, runtime_context: AgentRunContext, _capabilities: Sequence[Any]) -> Plan:
        if runtime_context.metadata.get("has_recommendations"):
            return Plan(
                id=f"follow-up-{runtime_context.turn_id}",
                goal=runtime_context.user_input,
                steps=[
                    PlanStep(
                        id="follow_up",
                        capability="food.follow_up",
                        args={},
                        output_key="answer",
                        expected_output="XHSFoodResponse",
                    )
                ],
            )
        return Plan(
            id=f"search-{runtime_context.turn_id}",
            goal=runtime_context.user_input,
            steps=[
                PlanStep(
                    id="parse_intent",
                    capability="food.parse_intent",
                    output_key="intent_result",
                    expected_output="IntentParseResult",
                ),
                PlanStep(
                    id="collect_notes",
                    capability="food.collect_notes",
                    args={"parsed": {"$ref": "intent_result"}},
                    depends_on=["parse_intent"],
                    output_key="collected",
                    expected_output="typed XHS evidence",
                ),
                PlanStep(
                    id="analyze_notes",
                    capability="food.analyze_notes",
                    args={"collected": {"$ref": "collected"}},
                    depends_on=["collect_notes"],
                    output_key="analyzed",
                    expected_output="restaurant candidates",
                ),
                PlanStep(
                    id="rank_candidates",
                    capability="food.rank_candidates",
                    args={"analyzed": {"$ref": "analyzed"}},
                    depends_on=["analyze_notes"],
                    output_key="ranked",
                    expected_output="validated recommendations",
                ),
                PlanStep(
                    id="enrich_poi",
                    capability="food.enrich_poi",
                    args={"ranked": {"$ref": "ranked"}},
                    depends_on=["rank_candidates"],
                    output_key="enriched",
                    expected_output="POI-enriched recommendations",
                ),
                PlanStep(
                    id="compose_response",
                    capability="food.compose_response",
                    args={
                        "ranked": {"$ref": "ranked"},
                        "enriched": {"$ref": "enriched"},
                    },
                    depends_on=["enrich_poi"],
                    output_key="answer",
                    expected_output="XHSFoodResponse",
                ),
            ],
        )

    async def plan(self, context: AgentRunContext, capabilities: Sequence[Any] = ()) -> Plan:
        return self.build(context, capabilities)

    async def replan(
        self,
        context: AgentRunContext,
        previous: Plan,
        reason: str,
        capabilities: Sequence[Any] = (),
    ) -> Plan:
        # If a capability failed, retry the pending part.  Completed steps are
        # merged back by AgentLoop.replace_pending().
        _ = previous, reason
        return self.build(context, capabilities)


class SearchReviewer(RuleBasedReviewer):
    """Attach source provenance to deterministic review decisions."""

    async def review(self, context: AgentRunContext, plan: Plan, report: Any):
        decision = await super().review(context, plan, report)
        if not decision.done:
            return decision
        collected = context.working_memory.get("collected", {})
        notes = collected.get("notes", []) if isinstance(collected, dict) else []
        evidence: list[Evidence] = []
        for index, note in enumerate(notes[:50]):
            if not isinstance(note, dict):
                continue
            source_id = str(note.get("id") or note.get("note_id") or f"note-{index}")
            evidence.append(
                Evidence(
                    source_id=source_id,
                    source="xhs",
                    title=str(note.get("title") or ""),
                    content=str(note.get("desc") or note.get("full_desc") or ""),
                    url=note.get("link") or note.get("url"),
                    metadata={
                        "likes": note.get("likes") or note.get("like_count") or 0,
                        "comments": note.get("comments_count") or note.get("comment_count") or 0,
                    },
                )
            )
        decision.evidence = evidence
        return decision


class AgenticSearchOrchestrator:
    """Run one food search turn through the Agent Loop."""

    def __init__(
        self,
        *,
        xhs_registry: Any,
        llm_service: Any,
        intent_parser: IntentParserAgent,
        analyzer: Any,
        follow_up_handler: FollowUpHandler,
        search_executor: SearchExecutor,
        context: ConversationContext,
        deep_search: bool,
        max_restaurants: int,
        memory: Any = None,
        planner: Any = None,
        reviewer: Any = None,
        model_runtime: Any = None,
        loop_config: AgentLoopConfig | None = None,
    ) -> None:
        self._xhs_registry = xhs_registry
        self._llm_service = llm_service
        self._intent_parser = intent_parser
        self._analyzer = analyzer
        self._follow_up_handler = follow_up_handler
        self._search_executor = search_executor
        self._context = context
        self._deep_search = deep_search
        self._max_restaurants = max_restaurants
        self._memory = memory
        self._loop_config = loop_config or AgentLoopConfig(
            max_iterations=settings.agent_loop_max_iterations,
            max_replans=settings.agent_loop_max_replans,
            max_total_seconds=settings.agent_loop_timeout_seconds,
            max_steps=settings.agent_loop_max_steps,
        )

        self._catalog = CapabilityCatalog()
        self._register_capabilities()
        self._gateway = CapabilityGateway(self._catalog)
        if model_runtime is None and planner is None and settings.agent_model_planner_enabled:
            from xhs_food.runtime.model_runtime import OpenAIAgentsRuntime

            model_runtime = OpenAIAgentsRuntime(
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
                model=settings.default_llm_model,
            )
        self._planner = planner or SearchPlanner(context)
        if model_runtime is not None and planner is None:
            from xhs_food.runtime.model_planner import OpenAIPlanPlanner

            self._planner = OpenAIPlanPlanner(model_runtime)
        self._reviewer = reviewer or SearchReviewer()
        self._last_run: AgentRunResult | None = None
        # The orchestrator is cached per session, so this store survives a new
        # runtime run id while remaining bounded by the orchestrator TTL.
        self._idempotency_store: dict[str, Any] = {}

    @property
    def gateway(self) -> CapabilityGateway:
        return self._gateway

    @property
    def last_run(self) -> AgentRunResult | None:
        return self._last_run

    def reset_context(self) -> None:
        self._search_executor.reset_cache()
        self._idempotency_store.clear()

    async def process(
        self,
        user_input: str,
        *,
        session_id: str = "local",
        turn_id: int | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> XHSFoodResponse:
        result = await self.run(
            user_input,
            session_id=session_id,
            turn_id=turn_id,
            conversation_history=conversation_history,
        )
        if isinstance(result.answer, XHSFoodResponse):
            return result.answer
        if result.status == "completed":
            return XHSFoodResponse(status="ok", summary=str(result.answer or "处理完成"))
        return XHSFoodResponse(
            status="error",
            error_message=result.stopped_reason or "agent loop failed",
        )

    async def run(
        self,
        user_input: str,
        *,
        session_id: str = "local",
        turn_id: int | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        event_sink: Any = None,
    ) -> AgentRunResult:
        self._last_run = None
        current_turn = turn_id or max(1, self._context.turn_count + 1)
        runtime_context = AgentRunContext(
            run_id=str(uuid.uuid4()),
            session_id=session_id,
            turn_id=current_turn,
            user_input=user_input,
            conversation=conversation_history or list(self._context.conversation_history),
            metadata={
                "has_recommendations": bool(self._context.last_recommendations),
                "auth_scopes": [],
            },
        )
        executor = PlanExecutor(
            self._gateway.invoke,
            max_concurrency=settings.agent_capability_concurrency,
            capability_concurrency={
                manifest.name: manifest.max_concurrency for manifest in self._gateway.manifests()
            },
            event_sink=event_sink,
            idempotency_store=self._idempotency_store,
            capability_idempotency={
                manifest.name: manifest.idempotent for manifest in self._gateway.manifests()
            },
        )
        loop = AgentLoop(
            planner=self._planner,
            executor=executor,
            reviewer=self._reviewer,
            config=self._loop_config,
            memory=self._memory,
            capabilities=self._gateway.manifests(),
            event_sink=event_sink,
        )
        self._last_run = await loop.run(runtime_context)
        return self._last_run

    async def stream(
        self,
        user_input: str,
        emitter: Any,
        *,
        session_id: str = "local",
        turn_id: int | None = None,
    ) -> AgentRunResult:
        """Run a turn and translate internal lifecycle events to stable SSE."""

        self._last_run = None
        emitter.init_steps(user_input)
        await emitter.step_start("step1", "Agent Loop：观察与规划")

        async def on_event(event: str, data: Mapping[str, Any]) -> None:
            if event == "step_finished":
                capability = str(data.get("capability", ""))
                step_id = {
                    "food.parse_intent": "step1",
                    "food.collect_notes": "step2",
                    "food.analyze_notes": "step3",
                    "food.rank_candidates": "step4",
                    "food.enrich_poi": "step5",
                    "food.compose_response": "step6",
                    "food.follow_up": "step1",
                }.get(capability, "step6")
                if data.get("success"):
                    await emitter.step_done(step_id, f"{capability} 完成")
                else:
                    await emitter.step_error(step_id, str(data.get("error") or "执行失败"))
            elif event in {"observe", "plan", "execute", "review", "replan"}:
                await emitter.emit_progress(
                    f"agent loop {event}",
                    {"phase": event, **dict(data)},
                )

        result = await self.run(
            user_input,
            session_id=session_id,
            turn_id=turn_id,
            event_sink=on_event,
        )
        response = result.answer if isinstance(result.answer, XHSFoodResponse) else None
        if result.status != "completed" or response is None:
            await emitter.emit_error(result.stopped_reason or "agent loop failed")
            return result
        for recommendation in response.recommendations:
            await emitter.emit_restaurant(recommendation.to_dict())
        await emitter.emit_result(
            response.summary,
            len(response.recommendations),
            response.filtered_count,
        )
        await emitter.emit_done()
        return result

    def _register_capabilities(self) -> None:
        self._catalog.register(
            FixedWorkflowSkill(
                SkillDefinition(
                    SkillManifest(
                        name="food.search.fixed",
                        version="1.0.0",
                        skill_pack="food-search-core",
                        description="Stable parse, collect, analyze, rank, POI and response workflow",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"},
                        max_concurrency=1,
                    ),
                    self._fixed_search,
                )
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.parse_intent",
                    description="Parse a user request into a typed FoodSearchIntent",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    max_concurrency=4,
                ),
                self._parse_intent,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.collect_notes",
                    description="Collect typed XHS notes using the search workflow",
                    input_schema={"type": "object", "required": ["parsed"]},
                    output_schema={"type": "object"},
                    max_concurrency=2,
                ),
                self._collect_notes,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.analyze_notes",
                    description="Analyze comments concurrently and extract restaurants",
                    input_schema={"type": "object", "required": ["collected"]},
                    output_schema={"type": "object"},
                    max_concurrency=2,
                ),
                self._analyze_notes,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.rank_candidates",
                    description="Merge, score and filter recommendations deterministically",
                    input_schema={"type": "object", "required": ["analyzed"]},
                    output_schema={"type": "object"},
                    max_concurrency=1,
                ),
                self._rank_candidates,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.enrich_poi",
                    description="Enrich recommendations with POI data",
                    input_schema={"type": "object", "required": ["ranked"]},
                    output_schema={"type": "object"},
                    max_concurrency=1,
                    side_effect=SideEffectLevel.EXTERNAL,
                ),
                self._enrich_poi,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.compose_response",
                    description="Compose a response from traceable recommendations",
                    input_schema={"type": "object", "required": ["ranked", "enriched"]},
                    output_schema={"type": "object"},
                    max_concurrency=1,
                ),
                self._compose_response,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="food.follow_up",
                    description="Handle a follow-up using memory and existing recommendations",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    max_concurrency=1,
                ),
                self._follow_up,
            )
        )

        # Lower-level tools remain available to a model planner for exploratory
        # queries; the fixed skill above is the fast path for routine turns.
        legacy_tools = {
            "xhs_search": (
                "xhs.search_notes",
                "Search XHS notes by keyword",
                {
                    "type": "object",
                    "required": ["keyword"],
                    "properties": {
                        "keyword": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                },
            ),
            "xhs_note": (
                "xhs.fetch_note",
                "Fetch one XHS note and comments",
                {
                    "type": "object",
                    "required": ["note_id"],
                    "properties": {"note_id": {"type": "string"}},
                },
            ),
            "xhs_batch": (
                "xhs.batch_research",
                "Research multiple XHS topics",
                {
                    "type": "object",
                    "required": ["topics"],
                    "properties": {"topics": {"type": "array"}},
                },
            ),
        }
        for provider_name, (name, description, schema) in legacy_tools.items():
            provider = self._xhs_registry.get(provider_name)
            if provider is not None:
                self._catalog.register(
                    mcp_provider_capability(
                        provider,
                        name=name,
                        description=description,
                        input_schema=schema,
                        output_schema={"type": "object"},
                    )
                )

        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="search.expand_query",
                    description="Expand one user query into focused search variants",
                    input_schema={
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                    output_schema={"type": "array"},
                ),
                self._expand_query,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="search.dedupe_notes",
                    description="Deduplicate notes by stable source id",
                    input_schema={
                        "type": "object",
                        "required": ["notes"],
                        "properties": {"notes": {"type": "array"}},
                    },
                    output_schema={"type": "array"},
                ),
                self._dedupe_notes,
            )
        )
        self._catalog.register(
            LocalCapability(
                CapabilityManifest(
                    name="evidence.rank",
                    description="Rank note evidence deterministically by interactions",
                    input_schema={
                        "type": "object",
                        "required": ["notes"],
                        "properties": {"notes": {"type": "array"}},
                    },
                    output_schema={"type": "array"},
                ),
                self._rank_evidence,
            )
        )

    async def _fixed_search(
        self, _args: Mapping[str, Any], context: AgentRunContext
    ) -> XHSFoodResponse:
        parsed = await self._parse_intent({}, context)
        context.working_memory["intent_result"] = parsed
        collected = await self._collect_notes({"parsed": parsed}, context)
        context.working_memory["collected"] = collected
        analyzed = await self._analyze_notes({"collected": collected}, context)
        context.working_memory["analyzed"] = analyzed
        ranked = await self._rank_candidates({"analyzed": analyzed}, context)
        context.working_memory["ranked"] = ranked
        enriched = await self._enrich_poi({"ranked": ranked}, context)
        context.working_memory["enriched"] = enriched
        return await self._compose_response({"ranked": ranked, "enriched": enriched}, context)

    async def _expand_query(self, args: Mapping[str, Any], _context: AgentRunContext) -> list[str]:
        query = str(args["query"]).strip()
        variants = [query, f"{query} 本地人", f"{query} 老店", f"{query} 避雷"]
        return list(dict.fromkeys(item for item in variants if item.strip()))

    async def _dedupe_notes(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for index, note in enumerate(args.get("notes", [])):
            if not isinstance(note, dict):
                continue
            source_id = str(note.get("id") or note.get("note_id") or f"anonymous-{index}")
            unique.setdefault(source_id, note)
        return list(unique.values())

    async def _rank_evidence(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> list[dict[str, Any]]:
        notes = [note for note in args.get("notes", []) if isinstance(note, dict)]
        return sorted(
            notes,
            key=lambda note: (
                int(note.get("comments_count") or note.get("comment_count") or 0),
                int(note.get("likes") or note.get("like_count") or 0),
            ),
            reverse=True,
        )

    async def _parse_intent(
        self, _args: Mapping[str, Any], context: AgentRunContext
    ) -> IntentParseResult:
        return await self._intent_parser.parse(context.user_input, self._context)

    async def _collect_notes(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> dict[str, Any]:
        parsed = args.get("parsed")
        if not isinstance(parsed, IntentParseResult) or not parsed.success or parsed.intent is None:
            return {"short_circuit": parsed}
        self._search_executor.reset_cache()
        notes = await self._search_executor.execute_4_stage_search(parsed.intent)
        return {"intent": parsed.intent, "notes": notes}

    async def _analyze_notes(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> dict[str, Any]:
        collected = args.get("collected") or {}
        if "short_circuit" in collected:
            return collected
        intent = collected["intent"]
        restaurants = await self._search_executor.analyze_notes_concurrent(
            collected.get("notes", []), intent
        )
        return {
            "intent": intent,
            "notes": collected.get("notes", []),
            "restaurants": restaurants,
        }

    async def _rank_candidates(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> dict[str, Any]:
        analyzed = args.get("analyzed") or {}
        if "short_circuit" in analyzed:
            return analyzed
        intent = analyzed["intent"]
        merged = self._search_executor.merge_and_validate(analyzed.get("restaurants", []))
        recommendations = [
            rec
            for rec in merged
            if rec.is_recommended
            and not any(ex in rec.name or rec.name in ex for ex in self._context.excluded_shops)
        ]
        filtered_count = len(merged) - len(recommendations)
        recommendations.sort(
            key=lambda item: (item.confidence, len(item.source_notes)), reverse=True
        )
        recommendations = recommendations[: self._max_restaurants]
        self._context.target_city = intent.location
        self._context.last_intent = intent.to_dict()
        self._context.last_notes = list(analyzed.get("notes", [])) or self._context.last_notes
        self._context.add_recommendations(recommendations)
        return {
            "intent": intent,
            "recommendations": recommendations,
            "filtered_count": filtered_count,
        }

    async def _enrich_poi(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> dict[str, Any]:
        ranked = args.get("ranked") or {}
        if "short_circuit" in ranked:
            return ranked
        recommendations = ranked.get("recommendations", [])
        if not recommendations:
            return {**ranked, "enriched": []}
        from xhs_food.agents import get_poi_enricher

        enricher = get_poi_enricher()
        enriched: list[dict[str, Any]] = []
        async for item in enricher.enrich_stream(recommendations, self._context.target_city):
            if hasattr(item, "to_dict"):
                payload = cast(dict[str, Any], item.to_dict())
            elif isinstance(item, Mapping):
                payload = dict(item)
            else:
                raise TypeError("POI enricher must return a mapping or to_dict object")
            enriched.append(payload)
            for rec in recommendations:
                if rec.name == payload.get("name"):
                    rec.poi_details = payload
                    break
        return {**ranked, "enriched": enriched}

    async def _compose_response(
        self, args: Mapping[str, Any], _context: AgentRunContext
    ) -> XHSFoodResponse:
        ranked = args.get("ranked") or {}
        if "short_circuit" in ranked:
            parsed = ranked.get("short_circuit")
            if isinstance(parsed, IntentParseResult) and parsed.need_clarify:
                return XHSFoodResponse(
                    status="clarify",
                    clarify_questions=parsed.questions,
                    summary="需要更多信息以完成搜索",
                )
            error = getattr(parsed, "error", None) or "意图解析失败"
            return XHSFoodResponse(status="error", error_message=error)
        intent = ranked.get("intent")
        if not isinstance(intent, FoodSearchIntent):
            return XHSFoodResponse(status="error", error_message="搜索意图缺失")
        recommendations = ranked.get("recommendations", [])
        summary = f"在 {intent.location} 找到 {len(recommendations)} 家推荐店铺"
        response = XHSFoodResponse(
            status="ok",
            recommendations=recommendations,
            filtered_count=ranked.get("filtered_count", 0),
            summary=summary,
        )
        self._context.last_summary = response.summary
        self._context.turn_count += 1
        return response

    async def _follow_up(
        self, _args: Mapping[str, Any], context: AgentRunContext
    ) -> XHSFoodResponse:
        follow_type, target = self._intent_parser.detect_follow_up_type(
            context.user_input, self._context
        )
        if follow_type == FollowUpType.FILTER:
            return await self._follow_up_handler.handle_filter(
                IntentParseResult(True, follow_up_type=follow_type, filter_target=target)
            )
        if follow_type == FollowUpType.CATEGORY_FILTER:
            return await self._follow_up_handler.handle_category_filter(
                IntentParseResult(True, follow_up_type=follow_type, category_target=target)
            )
        if follow_type == FollowUpType.DETAIL:
            return await self._follow_up_handler.handle_detail(
                IntentParseResult(True, follow_up_type=follow_type, detail_target=target)
            )
        if follow_type == FollowUpType.CONFIRM:
            return await self._follow_up_handler.handle_confirm()
        # For ambiguous follow-ups retain the existing LLM behavior; if the
        # model says this is a new search, run the normal typed pipeline.
        response = await self._follow_up_handler.process_follow_up_with_llm(context.user_input)
        if response is not None:
            return response
        parsed = await self._intent_parser.parse(context.user_input, self._context)
        if not parsed.success or parsed.intent is None:
            return XHSFoodResponse(
                status="clarify" if parsed.need_clarify else "error",
                clarify_questions=parsed.questions,
                error_message=parsed.error,
                summary="需要更多信息以完成搜索" if parsed.need_clarify else "意图解析失败",
            )
        return await self._search_executor.handle_new_search(parsed)
