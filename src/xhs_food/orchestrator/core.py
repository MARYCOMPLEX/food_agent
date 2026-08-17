"""XHSFoodOrchestrator - 主编排器, 4阶段搜索 + 多轮对话.

All collaborators are eagerly constructed in ``__init__`` (no lazy
``_ensure_initialized``); pass overrides for testing.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.agents.intent_parser import IntentParserAgent
from xhs_food.common.location import extract_city_from_location
from xhs_food.config import settings
from xhs_food.exceptions import IntentError, LLMError
from xhs_food.observability.metrics import (
    search_duration_seconds,
    search_finished_total,
    search_started_total,
)
from xhs_food.orchestrator.follow_up import FollowUpHandler
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.protocols.mcp import MCPToolRegistry
from xhs_food.schemas import (
    ConversationContext,
    RestaurantRecommendation,
    XHSFoodResponse,
)

if TYPE_CHECKING:
    from xhs_food.events import SearchEventEmitter

logger = logging.getLogger(__name__)


def _build_default_xhs_registry() -> MCPToolRegistry:
    """Lazy import to avoid pulling the di package into module-load order."""
    from xhs_food.di.factories import get_xhs_tool_registry

    return get_xhs_tool_registry()


class XHSFoodOrchestrator:
    """XHS 美食智能搜索主编排器 (支持多轮对话)."""

    def __init__(
        self,
        *,
        xhs_registry: MCPToolRegistry | None = None,
        llm_service: Any = None,
        intent_parser: IntentParserAgent | None = None,
        analyzer: AnalyzerAgent | None = None,
        follow_up_handler: FollowUpHandler | None = None,
        search_executor: SearchExecutor | None = None,
        deep_search: bool | None = None,
        fast_mode_limit: int | None = None,
        memory: Any = None,
        planner: Any = None,
        reviewer: Any = None,
        model_runtime: Any = None,
        use_agent_loop: bool = True,
    ) -> None:
        self._llm_service = llm_service
        self._deep_search = settings.search_deep_mode if deep_search is None else deep_search
        self._fast_mode_limit = (
            settings.search_note_limit if fast_mode_limit is None else fast_mode_limit
        )
        self._notes_per_keyword = settings.search_notes_per_keyword
        self._max_restaurants = settings.search_max_restaurants
        self._analyze_concurrency = settings.analyze_concurrency
        self._poi_concurrency = settings.poi_concurrency
        self._context = ConversationContext()
        self._use_agent_loop = use_agent_loop
        self._last_response: XHSFoodResponse | None = None

        # Eager dependency wiring with caller overrides.
        self._xhs_registry: MCPToolRegistry = (
            xhs_registry if xhs_registry is not None else _build_default_xhs_registry()
        )
        self._intent_parser: IntentParserAgent = (
            intent_parser
            if intent_parser is not None
            else IntentParserAgent(llm_service=self._llm_service)
        )
        self._analyzer: AnalyzerAgent = (
            analyzer if analyzer is not None else AnalyzerAgent(llm_service=self._llm_service)
        )
        self._follow_up_handler: FollowUpHandler = (
            follow_up_handler
            if follow_up_handler is not None
            else FollowUpHandler(context=self._context, llm_service=self._llm_service)
        )
        self._search_executor: SearchExecutor = (
            search_executor
            if search_executor is not None
            else SearchExecutor(
                xhs_registry=self._xhs_registry,
                analyzer=self._analyzer,
                context=self._context,
                deep_search=self._deep_search,
                fast_mode_limit=self._fast_mode_limit,
                notes_per_keyword=self._notes_per_keyword,
                max_restaurants=self._max_restaurants,
                analyze_concurrency=self._analyze_concurrency,
            )
        )

        # The public orchestrator remains a compatibility façade, while all
        # new turns go through the provider-neutral Agent Loop.  Legacy
        # collaborators stay injectable so existing deployments can roll back
        # by passing ``use_agent_loop=False``.
        from xhs_food.agentic.search import AgenticSearchOrchestrator

        if memory is None:
            from xhs_food.memory import LayeredMemoryProvider

            memory = LayeredMemoryProvider()

        self._agentic = AgenticSearchOrchestrator(
            xhs_registry=self._xhs_registry,
            llm_service=self._llm_service,
            intent_parser=self._intent_parser,
            analyzer=self._analyzer,
            follow_up_handler=self._follow_up_handler,
            search_executor=self._search_executor,
            context=self._context,
            deep_search=self._deep_search,
            max_restaurants=self._max_restaurants,
            memory=memory,
            planner=planner,
            reviewer=reviewer,
            model_runtime=model_runtime,
        )

    def reset_context(self) -> None:
        """重置对话上下文（开始新会话）."""
        self._context.reset()
        self._search_executor.reset_cache()
        self._agentic.reset_context()
        self._last_response = None

    @property
    def context(self) -> ConversationContext:
        """获取当前对话上下文."""
        return self._context

    @property
    def last_response(self) -> XHSFoodResponse | None:
        """Most recent response, exposed to task persistence adapters."""
        return self._last_response

    @property
    def last_run(self) -> Any:
        """Most recent Agent Loop result, if the loop adapter is enabled."""
        return self._agentic.last_run

    def _record_response(self, response: XHSFoodResponse) -> XHSFoodResponse:
        """记录响应到对话历史并返回."""
        if response.status == "ok":
            if response.recommendations:
                shop_names = [r.name for r in response.recommendations[:5]]
                summary = f"{response.summary}\n推荐店铺: {', '.join(shop_names)}"
                if len(response.recommendations) > 5:
                    summary += f" 等{len(response.recommendations)}家"
            else:
                summary = response.summary
        else:
            summary = response.summary or response.error_message or "处理完成"

        self._context.add_assistant_message(summary)
        self._context.last_summary = response.summary
        self._last_response = response
        return response

    async def search(self, user_input: str) -> XHSFoodResponse:
        """执行搜索（推荐使用的多轮对话入口），自动管理对话上下文。"""
        response = await self.process(user_input)
        return self._record_response(response)

    async def search_stream(self, user_input: str, emitter: SearchEventEmitter) -> None:
        """流式搜索（支持 SSE 推送），通过 emitter 发射中间步骤和结果。"""
        self._last_response = None
        if self._use_agent_loop:
            self._context.add_user_message(user_input)
            search_started_total.inc()
            _start_perf = time.perf_counter()
            _outcome = "error"
            try:
                run = await self._agentic.stream(
                    user_input,
                    emitter,
                    session_id=emitter.session_id,
                    turn_id=max(1, self._context.turn_count + 1),
                )
                if isinstance(run.answer, XHSFoodResponse):
                    self._record_response(run.answer)
                _outcome = "ok" if run.status == "completed" else "error"
            except Exception as exc:  # noqa: BLE001 - system boundary
                logger.exception("Agent Loop 流式搜索失败")
                await emitter.emit_error(str(exc))
            finally:
                search_finished_total.labels(status=_outcome).inc()
                search_duration_seconds.observe(time.perf_counter() - _start_perf)
            return

        self._context.add_user_message(user_input)
        emitter.init_steps(user_input)

        search_started_total.inc()
        _start_perf = time.perf_counter()
        _outcome = "error"  # default; flipped to "ok" on the success path

        try:
            await emitter.step_start("step1", f"解析: {user_input[:30]}...")

            if self._context.last_recommendations:
                result = await self._follow_up_handler.process_follow_up_with_llm(user_input)
                if result is not None:
                    await emitter.step_done("step1", "追问处理完成")
                    await self._stream_poi_enrich(result.recommendations, emitter)
                    await emitter.emit_result(result.summary, len(result.recommendations))
                    await emitter.emit_done()
                    self._record_response(result)
                    _outcome = "ok"
                    return
            parse_result = await self._intent_parser.parse(user_input, self._context)
            if not parse_result.success:
                await emitter.step_error("step1", parse_result.error or "意图解析失败")
                await emitter.emit_error(parse_result.error or "意图解析失败")
                return
            self._context.target_city = parse_result.intent.location
            await emitter.step_done(
                "step1",
                f"意图: {parse_result.intent.location} {parse_result.intent.food_type or ''}",
                {
                    "intent": parse_result.intent.to_dict() if parse_result.intent else None,
                },
            )
            await emitter.step_start("step2", "搜索小红书笔记...")
            intent = parse_result.intent
            self._search_executor.reset_cache()

            all_notes = await self._search_executor.execute_4_stage_search(intent)

            if not all_notes:
                await emitter.step_error("step2", "未找到相关笔记")
                await emitter.emit_error("未找到相关笔记")
                return

            await emitter.step_done("step2", f"找到 {len(all_notes)} 篇笔记")

            await emitter.step_start(
                "step3",
                f"分析评论内容（{len(all_notes)} 篇，并发 {self._analyze_concurrency}）...",
            )

            all_restaurants: list[
                RestaurantRecommendation
            ] = await self._search_executor.analyze_notes_concurrent(all_notes, intent)

            await emitter.step_done("step3", f"识别到 {len(all_restaurants)} 家店铺")

            await emitter.step_start("step4", "交叉验证筛选...")

            merged = self._search_executor.merge_and_validate(all_restaurants)

            recommendations = []
            filtered_count = 0
            for rec in merged:
                if rec.is_recommended:
                    recommendations.append(rec)
                else:
                    filtered_count += 1

            if len(recommendations) > self._max_restaurants:
                logger.info(
                    f"  店铺数量 {len(recommendations)} 超过上限 {self._max_restaurants}，截取"
                )
                recommendations = recommendations[: self._max_restaurants]

            await emitter.step_done("step4", f"筛选出 {len(recommendations)} 家推荐")

            for rec in recommendations:
                self._context.last_recommendations[rec.name] = rec.to_dict()

            await emitter.step_start("step5", f"补充 {len(recommendations)} 家店铺信息...")
            enriched_restaurants = await self._enrich_poi_batch(recommendations)
            await emitter.step_done("step5", f"完成 {len(enriched_restaurants)} 家店铺信息补充")

            await emitter.step_start("step6", "生成推荐结果...")

            for enriched in enriched_restaurants:
                await emitter.emit_restaurant(enriched)

            response = XHSFoodResponse(
                status="ok",
                recommendations=recommendations,
                filtered_count=filtered_count,
                summary=f"在{intent.location}找到 {len(recommendations)} 家推荐店铺",
            )

            await emitter.step_done("step6", response.summary)
            await emitter.emit_result(
                response.summary, len(recommendations), response.filtered_count
            )
            await emitter.emit_done()

            self._record_response(response)
            _outcome = "ok"

        except (IntentError, LLMError) as e:
            logger.warning("流式搜索领域错误: %s", e)
            await emitter.emit_error(str(e))
        except Exception as e:  # noqa: BLE001 - system boundary
            logger.exception("流式搜索失败")
            await emitter.emit_error(str(e))
        finally:
            search_finished_total.labels(status=_outcome).inc()
            search_duration_seconds.observe(time.perf_counter() - _start_perf)

    async def _enrich_poi_batch(self, recommendations: list) -> list:
        """批量 POI 补充（不流式输出）."""
        from xhs_food.agents import get_poi_enricher

        enricher = get_poi_enricher()
        city = self._context.target_city
        if not city and recommendations and recommendations[0].location:
            city = self._extract_city_from_location(recommendations[0].location)

        enriched_list = []
        async for enriched in enricher.enrich_stream(recommendations, city):
            enriched_list.append(enriched.to_dict())

        return enriched_list

    async def _stream_poi_enrich(
        self,
        recommendations: list,
        emitter: SearchEventEmitter,
    ) -> None:
        """流式 POI 补充（已弃用，保留兼容）."""
        from xhs_food.agents import get_poi_enricher

        await emitter.step_start("step5", f"补充 {len(recommendations)} 家店铺信息...")

        enricher = get_poi_enricher()
        city = self._context.target_city
        if not city and recommendations and recommendations[0].location:
            city = self._extract_city_from_location(recommendations[0].location)

        count = 0
        async for enriched in enricher.enrich_stream(recommendations, city):
            count += 1
            await emitter.emit_restaurant(enriched.to_dict())

        await emitter.step_done("step5", f"完成 {count} 家店铺信息补充")

    def _extract_city_from_location(self, location: str) -> str:
        """Delegate to common location helper (kept for backwards compat)."""
        return extract_city_from_location(location)

    async def process(
        self,
        user_input: str,
        *,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> XHSFoodResponse:
        """处理用户请求，返回美食推荐（主入口方法）."""
        if self._use_agent_loop:
            self._context.add_user_message(user_input)
            return await self._agentic.process(
                user_input,
                session_id="local",
                turn_id=max(1, self._context.turn_count + 1),
                conversation_history=conversation_history,
            )

        self._context.add_user_message(user_input)

        try:
            if self._context.last_recommendations:
                logger.info(f"[多轮对话] LLM 处理: {user_input[:50]}...")
                result = await self._follow_up_handler.process_follow_up_with_llm(user_input)
                if result is not None:
                    return result

            logger.info(f"[首次搜索] 解析用户意图: {user_input[:50]}...")
            parse_result = await self._intent_parser.parse(user_input, self._context)

            if not parse_result.success:
                if parse_result.need_clarify:
                    return XHSFoodResponse(
                        status="clarify",
                        clarify_questions=parse_result.questions,
                        summary="需要更多信息以完成搜索",
                    )
                return XHSFoodResponse(
                    status="error",
                    error_message=parse_result.error or "意图解析失败",
                )

            return await self._search_executor.handle_new_search(parse_result)

        except IntentError as e:
            logger.warning("意图解析失败: %s", e)
            return XHSFoodResponse(status="error", error_message=str(e))
        except LLMError as e:
            logger.warning("LLM 调用失败: %s", e)
            return XHSFoodResponse(status="error", error_message=str(e))
        except Exception as e:  # noqa: BLE001 - system boundary
            logger.exception("处理请求时发生错误")
            return XHSFoodResponse(
                status="error",
                error_message=str(e),
            )
