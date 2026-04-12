"""XHSFoodOrchestrator - 主编排器, 4阶段搜索 + 多轮对话."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from xhs_food.agents.intent_parser import IntentParserAgent
from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.schemas import (
    RestaurantRecommendation,
    XHSFoodResponse,
    ConversationContext,
)
from xhs_food.protocols.mcp import MCPToolRegistry
from xhs_food.orchestrator.follow_up import FollowUpHandler
from xhs_food.orchestrator.search_executor import SearchExecutor

logger = logging.getLogger(__name__)


class XHSFoodOrchestrator:
    """XHS 美食智能搜索主编排器 (支持多轮对话)."""

    def __init__(
        self,
        *,
        xhs_registry: Optional[MCPToolRegistry] = None,
        intent_parser: Optional[IntentParserAgent] = None,
        analyzer: Optional[AnalyzerAgent] = None,
        llm_service=None,
        deep_search: Optional[bool] = None,
        fast_mode_limit: Optional[int] = None,
    ):
        import os

        self._xhs_registry = xhs_registry
        self._intent_parser = intent_parser
        self._analyzer = analyzer
        self._llm_service = llm_service
        if deep_search is None:
            env_deep = os.getenv("SEARCH_DEEP_MODE", "false").lower()
            self._deep_search = env_deep in ("true", "1", "yes")
        else:
            self._deep_search = deep_search
        if fast_mode_limit is None:
            self._fast_mode_limit = int(os.getenv("SEARCH_NOTE_LIMIT", "15"))
        else:
            self._fast_mode_limit = fast_mode_limit
        self._notes_per_keyword = int(os.getenv("SEARCH_NOTES_PER_KEYWORD", "4"))
        self._max_restaurants = int(os.getenv("SEARCH_MAX_RESTAURANTS", "10"))
        self._context = ConversationContext()
        self._follow_up_handler: Optional[FollowUpHandler] = None
        self._search_executor: Optional[SearchExecutor] = None

    async def _ensure_initialized(self) -> None:
        """确保所有组件初始化."""
        if self._intent_parser is None:
            self._intent_parser = IntentParserAgent(llm_service=self._llm_service)
        if self._analyzer is None:
            self._analyzer = AnalyzerAgent(llm_service=self._llm_service, use_legacy_mode=True)
        if self._xhs_registry is None:
            from xhs_food.di.factories import get_xhs_tool_registry
            self._xhs_registry = get_xhs_tool_registry()
        if self._follow_up_handler is None:
            self._follow_up_handler = FollowUpHandler(
                context=self._context,
                llm_service=self._llm_service,
            )
        if self._search_executor is None:
            self._search_executor = SearchExecutor(
                xhs_registry=self._xhs_registry,
                analyzer=self._analyzer,
                context=self._context,
                deep_search=self._deep_search,
                fast_mode_limit=self._fast_mode_limit,
                notes_per_keyword=self._notes_per_keyword,
                max_restaurants=self._max_restaurants,
            )

    def reset_context(self) -> None:
        """重置对话上下文（开始新会话）."""
        self._context.reset()
        if self._search_executor:
            self._search_executor.reset_cache()

    @property
    def context(self) -> ConversationContext:
        """获取当前对话上下文."""
        return self._context

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
        return response

    async def search(self, user_input: str) -> XHSFoodResponse:
        """执行搜索（推荐使用的多轮对话入口），自动管理对话上下文。"""
        response = await self.process(user_input)
        return self._record_response(response)

    async def search_stream(self, user_input: str, emitter: "SearchEventEmitter"):
        """流式搜索（支持 SSE 推送），通过 emitter 发射中间步骤和结果。"""
        await self._ensure_initialized()
        self._context.add_user_message(user_input)
        emitter.init_steps(user_input)

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
                    return
            parse_result = await self._intent_parser.parse(user_input, self._context)
            if not parse_result.success:
                await emitter.step_error("step1", parse_result.error or "意图解析失败")
                await emitter.emit_error(parse_result.error or "意图解析失败")
                return
            self._context.target_city = parse_result.intent.location
            await emitter.step_done("step1", f"意图: {parse_result.intent.location} {parse_result.intent.food_type or ''}", {
                "intent": parse_result.intent.to_dict() if parse_result.intent else None,
            })
            await emitter.step_start("step2", "搜索小红书笔记...")
            intent = parse_result.intent
            self._search_executor.reset_cache()

            all_notes = await self._search_executor.execute_4_stage_search(intent)

            if not all_notes:
                await emitter.step_error("step2", "未找到相关笔记")
                await emitter.emit_error("未找到相关笔记")
                return

            await emitter.step_done("step2", f"找到 {len(all_notes)} 篇笔记")

            await emitter.step_start("step3", "分析评论内容...")

            all_restaurants: List[RestaurantRecommendation] = []
            for note in all_notes:
                try:
                    analyze_result = await self._search_executor.analyze_note(note, intent)
                    if analyze_result.success:
                        all_restaurants.extend(analyze_result.restaurants)
                except Exception as e:
                    logger.warning(f"分析笔记失败: {e}")

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
                logger.info(f"  店铺数量 {len(recommendations)} 超过上限 {self._max_restaurants}，截取")
                recommendations = recommendations[:self._max_restaurants]

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
            await emitter.emit_result(response.summary, len(recommendations), response.filtered_count)
            await emitter.emit_done()

            self._record_response(response)

        except Exception as e:
            logger.exception("流式搜索失败")
            await emitter.emit_error(str(e))

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
        emitter: "SearchEventEmitter",
    ):
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
        """从位置提取城市."""
        if not location:
            return ""
        cities = ["成都", "重庆", "达州", "自贡", "泸州", "绵阳", "德阳", "南充"]
        for city in cities:
            if city in location:
                return city
        return ""

    async def process(
        self,
        user_input: str,
        *,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> XHSFoodResponse:
        """处理用户请求，返回美食推荐（主入口方法）."""
        await self._ensure_initialized()

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

        except Exception as e:
            logger.exception("处理请求时发生错误")
            return XHSFoodResponse(
                status="error",
                error_message=str(e),
            )
