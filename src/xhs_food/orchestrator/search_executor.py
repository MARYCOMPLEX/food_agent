"""搜索执行器 - 封装 4 阶段搜索策略和笔记分析."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Set

from xhs_food.agents.analyzer import AnalyzerAgent, AnalyzeResult
from xhs_food.observability.metrics import xhs_notes_fetched_total
from xhs_food.schemas import (
    FoodSearchIntent,
    RestaurantRecommendation,
    WanghongScore,
    XHSFoodResponse,
    ConversationContext,
)
from xhs_food.protocols.mcp import MCPToolRegistry

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
    ):
        self._xhs_registry = xhs_registry
        self._analyzer = analyzer
        self._context = context
        self._deep_search = deep_search
        self._fast_mode_limit = fast_mode_limit
        self._notes_per_keyword = notes_per_keyword
        self._max_restaurants = max_restaurants
        self._analyze_concurrency = max(1, analyze_concurrency)

        # 搜索过程中的临时缓存
        self._shop_mentions: Dict[str, List[str]] = {}
        self._analyzed_shops: Dict[str, RestaurantRecommendation] = {}

    def reset_cache(self) -> None:
        """重置搜索缓存."""
        self._shop_mentions = {}
        self._analyzed_shops = {}

    async def handle_new_search(self, parse_result) -> XHSFoodResponse:
        """处理新搜索或细化搜索."""
        intent = parse_result.intent
        if not intent:
            return XHSFoodResponse(status="error", error_message="无法解析搜索意图")
        self.reset_cache()
        logger.info(f"  解析结果: {intent.location} / {intent.food_type}")
        all_notes = await self.execute_4_stage_search(intent)
        if not all_notes:
            return XHSFoodResponse(
                status="ok", recommendations=[],
                summary=f"未找到关于 {intent.location} 的相关笔记",
            )
        logger.info(f"  共获取 {len(all_notes)} 篇笔记")
        all_restaurants = await self.analyze_notes_concurrent(all_notes, intent)
        logger.info(f"  识别出 {len(all_restaurants)} 家店铺")
        merged_restaurants = self.merge_and_validate(all_restaurants)
        recommended = []
        filtered_count = 0
        for r in merged_restaurants:
            is_excluded = any(
                ex in r.name or r.name in ex for ex in self._context.excluded_shops
            )
            if r.is_recommended and not is_excluded:
                recommended.append(r)
            else:
                filtered_count += 1
        recommended.sort(
            key=lambda x: (x.confidence, len(x.source_notes)), reverse=True
        )
        logger.info(f"  推荐 {len(recommended)} 家，过滤 {filtered_count} 家")
        self._context.last_intent = intent.to_dict()
        self._context.add_recommendations(recommended)
        self._context.last_notes = all_notes
        self._context.turn_count += 1
        return XHSFoodResponse(
            status="ok",
            recommendations=recommended,
            filtered_count=filtered_count,
            summary=f"在 {intent.location} 找到 {len(recommended)} 家推荐店铺，过滤了 {filtered_count} 家网红店",
        )

    async def execute_4_stage_search(self, intent: FoodSearchIntent) -> List[Dict[str, Any]]:
        """执行4阶段搜索策略，快速模式下达到 fast_mode_limit 后提前返回."""
        all_notes: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        search_tool = self._xhs_registry.get_required("xhs_search")

        def _should_stop() -> bool:
            if not self._deep_search and len(all_notes) >= self._fast_mode_limit:
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
                names = shop_names[i:i+2]
                kw = f"{intent.location} {' '.join(names)}"
                notes = await self.search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)
        if _should_stop():
            return all_notes
        if intent.food_type and intent.food_type != "美食":
            logger.info(f"  [Phase 4] 细分搜索 - {intent.food_type}")
            phase4_keywords = [
                f"{intent.location} {intent.food_type} 老店",
                f"{intent.location} {intent.food_type} 本地人",
            ]
            for kw in phase4_keywords:
                if _should_stop():
                    break
                notes = await self.search_with_keyword(search_tool, kw, seen_ids)
                all_notes.extend(notes)

        return all_notes

    async def execute_expand_search(self, intent: FoodSearchIntent) -> List[Dict[str, Any]]:
        """执行扩展搜索（使用不同关键词）."""
        all_notes: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for note in self._context.last_notes:
            note_id = note.get("id") or note.get("note_id", "")
            if note_id:
                seen_ids.add(note_id)
        search_tool = self._xhs_registry.get_required("xhs_search")
        expand_keywords = [
            f"{intent.location} 隐藏美食",
            f"{intent.location} 老字号",
            f"{intent.location} 街边小店",
        ]
        for kw in expand_keywords:
            notes = await self.search_with_keyword(search_tool, kw, seen_ids)
            all_notes.extend(notes)

        return all_notes

    async def search_with_keyword(self, search_tool, keyword: str, seen_ids: Set[str]) -> List[Dict[str, Any]]:
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

    def generate_phase1_keywords(self, intent: FoodSearchIntent) -> List[str]:
        """生成阶段1关键词（广撒网）."""
        base = intent.location
        food = intent.food_type or "美食"
        keywords = [
            f"{base} 本地人 老店",
            f"{base} {food} 地道",
            f"{base} 本地人 推荐",
        ]
        for req in intent.requirements[:2]:
            keywords.append(f"{base} {req}")
        return keywords

    def generate_phase2_keywords(self, intent: FoodSearchIntent) -> List[str]:
        """生成阶段2关键词（挖隐藏）."""
        base = intent.location
        return [
            f"{base} 苍蝇馆子 好吃",
            f"{base} 小馆子 本地人",
            f"{base} 巷子里 老店",
            f"{base} 不起眼 好吃",
        ]

    def extract_shop_names(self, notes: List[Dict[str, Any]]) -> List[str]:
        """从笔记中提取店铺名."""
        names: List[str] = []
        for note in notes:
            title = note.get("title") or ""
            if not title:
                continue
            if "店" in title or "馆" in title:
                words = title.replace("｜", " ").replace("|", " ").split()
                for w in words:
                    if ("店" in w or "馆" in w) and 2 <= len(w) <= 10:
                        if w not in names:
                            names.append(w)
        return names[:6]

    async def analyze_notes_concurrent(
        self,
        notes: List[Dict[str, Any]],
        intent: FoodSearchIntent,
    ) -> List[RestaurantRecommendation]:
        """Concurrently analyze ``notes`` under a semaphore.

        Errors in individual notes are logged and skipped — partial results
        are preferable to failing the whole pipeline.
        """
        if not notes:
            return []
        xhs_notes_fetched_total.labels(keyword_phase="analyzed").inc(len(notes))
        semaphore = asyncio.Semaphore(self._analyze_concurrency)

        async def _one(note: Dict[str, Any]) -> List[RestaurantRecommendation]:
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
        restaurants: List[RestaurantRecommendation] = []
        for batch in gathered:
            restaurants.extend(batch)
        return restaurants

    async def analyze_note(self, note: Dict[str, Any], intent: FoodSearchIntent) -> AnalyzeResult:
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

    def merge_and_validate(self, restaurants: List[RestaurantRecommendation]) -> List[RestaurantRecommendation]:
        """合并相同店铺并进行交叉验证."""
        merged: Dict[str, RestaurantRecommendation] = {}
        for r in restaurants:
            name = r.name.strip()
            if not name or name == "未知":
                continue
            norm_name = name.replace(" ", "").replace("\u3000", "")
            if norm_name in merged:
                existing = merged[norm_name]
                existing.source_notes.extend(r.source_notes)
                existing.features.extend([f for f in r.features if f not in existing.features])
                if r.confidence > existing.confidence:
                    existing.confidence = r.confidence
                    existing.wanghong_analysis = r.wanghong_analysis
            else:
                merged[norm_name] = r
        for name, r in merged.items():
            source_count = len(set(r.source_notes))
            if r.wanghong_analysis:
                score = r.wanghong_analysis.score
                if score in (WanghongScore.DEFINITELY_WANGHONG, WanghongScore.LIKELY_WANGHONG):
                    r.is_recommended = False
                    r.filter_reason = f"判定为网红店: {', '.join(r.wanghong_analysis.reasons[:2])}"
                elif source_count < 2:
                    r.confidence *= 0.7
                elif source_count >= 3 and r.wanghong_analysis.has_local_mentions:
                    r.confidence = min(r.confidence * 1.2, 1.0)
        return list(merged.values())
