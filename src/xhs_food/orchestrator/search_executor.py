"""搜索执行器 - 封装 4 阶段搜索策略和笔记分析."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from xhs_food.agents.analyzer import AnalyzerAgent, AnalyzeResult
from xhs_food.composition.adapters.food_output import LegacyFoodOutputAdapter
from xhs_food.domain_packs.food.pack import FoodBehavior, create_food_pack
from xhs_food.observability.metrics import xhs_notes_fetched_total
from xhs_food.protocols.mcp import MCPToolRegistry
from xhs_food.schemas import (
    ConversationContext,
    FoodSearchIntent,
    RestaurantRecommendation,
    XHSFoodResponse,
)

logger = logging.getLogger(__name__)


class SearchExecutor:
    """封装搜索策略和笔记分析."""

    def __init__(
        self,
        *,
        xhs_registry: MCPToolRegistry,
        analyzer: AnalyzerAgent,
        context: ConversationContext,
        deep_search: bool = False,
        fast_mode_limit: int = 15,
        notes_per_keyword: int = 4,
        max_restaurants: int = 10,
        analyze_concurrency: int = 5,
        food_pack: FoodBehavior | None = None,
    ):
        self._xhs_registry = xhs_registry
        self._analyzer = analyzer
        self._context = context
        self._deep_search = deep_search
        self._fast_mode_limit = fast_mode_limit
        self._notes_per_keyword = notes_per_keyword
        self._max_restaurants = max_restaurants
        self._analyze_concurrency = max(1, analyze_concurrency)
        self._food_pack = food_pack if food_pack is not None else create_food_pack()
        self._food_output = LegacyFoodOutputAdapter(validator=self._food_pack.validate_final_output)

        # 搜索过程中的临时缓存
        self._shop_mentions: dict[str, list[str]] = {}
        self._analyzed_shops: dict[str, RestaurantRecommendation] = {}

    @property
    def context(self) -> ConversationContext:
        """Return the context shared with the owning orchestrator."""

        return self._context

    def reset_cache(self) -> None:
        """重置搜索缓存."""
        self._shop_mentions = {}
        self._analyzed_shops = {}

    async def handle_new_search(self, parse_result) -> XHSFoodResponse:
        """处理新搜索或细化搜索."""
        intent = parse_result.intent
        if not intent:
            return self._food_output.response(status="error", error_message="无法解析搜索意图")
        self.reset_cache()
        logger.info(f"  解析结果: {intent.location} / {intent.food_type}")
        all_notes = await self.execute_4_stage_search(intent)
        if not all_notes:
            return self._food_output.response(
                status="ok",
                recommendations=[],
                summary=f"未找到关于 {intent.location} 的相关笔记",
            )
        logger.info(f"  共获取 {len(all_notes)} 篇笔记")
        all_restaurants = await self.analyze_notes_concurrent(all_notes, intent)
        logger.info(f"  识别出 {len(all_restaurants)} 家店铺")
        merged_restaurants = self.merge_and_validate(all_restaurants)
        recommended, filtered_count = self._food_pack.decision.rank_and_filter(
            merged_restaurants,
            self._context.excluded_shops,
        )
        logger.info(f"  推荐 {len(recommended)} 家，过滤 {filtered_count} 家")
        self._context.last_intent = intent.to_dict()
        self._context.add_recommendations(recommended)
        self._context.last_notes = all_notes
        self._context.turn_count += 1
        return self._food_output.response(
            status="ok",
            recommendations=recommended,
            filtered_count=filtered_count,
            summary=f"在 {intent.location} 找到 {len(recommended)} 家推荐店铺，过滤了 {filtered_count} 家网红店",
        )

    async def execute_4_stage_search(self, intent: FoodSearchIntent) -> list[dict[str, Any]]:
        """执行4阶段搜索策略，快速模式下达到 fast_mode_limit 后提前返回."""
        all_notes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        search_tool = self._xhs_registry.get_required("xhs_search")

        def _should_stop() -> bool:
            if self._food_pack.workflow.should_stop(
                len(all_notes),
                deep_search=self._deep_search,
                fast_limit=self._fast_mode_limit,
            ):
                logger.info(f"  [快速模式] 已达到 {len(all_notes)} 篇笔记，跳过后续阶段")
                return True
            return False

        logger.info("  [Phase 1] 广撒网 - 建立候选池")
        phase1_keywords = self.generate_phase1_keywords(intent)
        for kw in phase1_keywords[:3]:
            if _should_stop():
                break
            notes = await self.search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)
        if _should_stop():
            return all_notes
        logger.info("  [Phase 2] 挖隐藏 - 发现宝藏店铺")
        phase2_keywords = self.generate_phase2_keywords(intent)
        for kw in phase2_keywords[:3]:
            if _should_stop():
                break
            notes = await self.search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)
        if _should_stop():
            return all_notes
        shop_names = self.extract_shop_names(all_notes)
        if shop_names:
            logger.info(f"  [Phase 3] 定向验证 - 验证 {len(shop_names)} 家店铺")
            for i in range(0, min(len(shop_names), 4), 2):
                if _should_stop():
                    break
                names = shop_names[i : i + 2]
                kw = f"{intent.location} {' '.join(names)}"
                notes = await self.search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)
        if _should_stop():
            return all_notes
        if intent.food_type and intent.food_type != "美食":
            logger.info(f"  [Phase 4] 细分搜索 - {intent.food_type}")
            phase4_keywords = self._food_pack.workflow.phase4_keywords(intent)
            for kw in phase4_keywords:
                if _should_stop():
                    break
                notes = await self.search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)

        return all_notes

    async def execute_expand_search(self, intent: FoodSearchIntent) -> list[dict[str, Any]]:
        """执行扩展搜索（使用不同关键词）."""
        all_notes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for note in self._context.last_notes:
            note_id = note.get("id") or note.get("note_id", "")
            if note_id:
                seen_ids.add(note_id)
        search_tool = self._xhs_registry.get_required("xhs_search")
        expand_keywords = self._food_pack.workflow.expand_keywords(intent)
        for kw in expand_keywords:
            notes = await self.search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)

        return all_notes

    async def search_with_keyword(
        self, search_tool, keyword: str, seen_ids: set[str]
    ) -> list[dict[str, Any]]:
        """执行单次搜索."""
        try:
            result = await search_tool.execute(
                keyword=keyword,
                count=self._notes_per_keyword,
                sort_type="most_comments",
                include_details=True,
                include_comments=True,
            )
            if not result.success:
                logger.warning(f"搜索失败: {keyword} - {result.error_message}")
                return []
            notes = result.data.get("notes", [])
            new_notes = []
            for note in notes:
                note_id = note.get("id") or note.get("note_id", "")
                if note_id and note_id not in seen_ids:
                    seen_ids.add(note_id)
                    new_notes.append(note)

            logger.info(f"    搜索 '{keyword}': 新增 {len(new_notes)} 篇")
            if new_notes:
                xhs_notes_fetched_total.labels(keyword_phase="search").inc(len(new_notes))
            return new_notes
        except Exception as e:
            logger.warning(f"搜索异常: {keyword} - {e}")
            return []

    def generate_phase1_keywords(self, intent: FoodSearchIntent) -> list[str]:
        """生成阶段1关键词（广撒网）."""
        return self._food_pack.workflow.phase1_keywords(intent)

    def generate_phase2_keywords(self, intent: FoodSearchIntent) -> list[str]:
        """生成阶段2关键词（挖隐藏）."""
        return self._food_pack.workflow.phase2_keywords(intent)

    def extract_shop_names(self, notes: list[dict[str, Any]]) -> list[str]:
        """从笔记中提取店铺名."""
        return self._food_pack.workflow.extract_shop_names(notes)

    async def analyze_notes_concurrent(
        self,
        notes: list[dict[str, Any]],
        intent: FoodSearchIntent,
    ) -> list[RestaurantRecommendation]:
        """Concurrently analyze ``notes`` under a semaphore.

        Errors in individual notes are logged and skipped — partial results
        are preferable to failing the whole pipeline.
        """
        if not notes:
            return []
        xhs_notes_fetched_total.labels(keyword_phase="analyzed").inc(len(notes))
        semaphore = asyncio.Semaphore(self._analyze_concurrency)

        async def _one(note: dict[str, Any]) -> list[RestaurantRecommendation]:
            async with semaphore:
                try:
                    result = await self.analyze_note(note, intent)
                except Exception as exc:
                    logger.warning(f"分析笔记失败: {exc}")
                    return []
                if not result.success:
                    return []
                return list(result.restaurants)

        gathered = await asyncio.gather(*(_one(note) for note in notes))
        restaurants: list[RestaurantRecommendation] = []
        for batch in gathered:
            restaurants.extend(batch)
        return restaurants

    async def analyze_note(self, note: dict[str, Any], intent: FoodSearchIntent) -> AnalyzeResult:
        """分析单篇笔记."""
        title = note.get("title") or ""
        content = note.get("desc", "") or note.get("full_desc", "")
        note_id = note.get("id") or note.get("note_id", "")
        comments = []
        raw_comments = note.get("top_comments", [])
        for c in raw_comments:
            if isinstance(c, dict):
                text = c.get("content", "") or c.get("text", "")
                likes = c.get("like_count", 0) or c.get("likes", 0)
                comments.append(f"{text} [{likes}赞]")
            elif isinstance(c, str):
                comments.append(c)

        return await self._analyzer.analyze(
            title=title,
            content=content,
            comments=comments,
            exclude_keywords=intent.exclude_keywords,
            note_id=note_id,
        )

    def merge_and_validate(
        self, restaurants: list[RestaurantRecommendation]
    ) -> list[RestaurantRecommendation]:
        """合并相同店铺并进行交叉验证."""
        return self._food_pack.decision.merge_and_validate(restaurants)
