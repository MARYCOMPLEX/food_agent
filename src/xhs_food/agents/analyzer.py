"""
AnalyzerAgent - 内容分析代理 (重构版).

采用三阶段流水线架构：
1. Python 预处理: 提取点赞、计算 interaction_score
2. LLM 语义分析: 仅判断 identity/sentiment/is_correction/mentioned_shops
3. Python 后处理: 精确计算最终权重得分

此架构解决 LLM 算术错误问题，并大幅降低 Prompt 成本。
"""

from __future__ import annotations

import logging
from typing import Any

from xhs_food.common import extract_json
from xhs_food.domain_packs.food.decision import FoodDecisionPolicy
from xhs_food.domain_packs.food.preprocessing import (
    format_comments_for_llm,
    preprocess_comments,
)
from xhs_food.domain_packs.food.scoring import (
    ShopScore,
    calculate_scores,
    get_top_shops,
)
from xhs_food.prompts import (
    COMMENT_ANALYSIS_SYSTEM_PROMPT,
    COMMENT_ANALYSIS_USER_PROMPT,
)
from xhs_food.schemas import (
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)

logger = logging.getLogger(__name__)
_FOOD_DECISION = FoodDecisionPolicy()


class AnalyzeResult:
    """分析结果."""

    def __init__(
        self,
        success: bool,
        restaurants: list[RestaurantRecommendation] | None = None,
        shop_scores: dict[str, ShopScore] | None = None,
        raw_output: str = "",
        error: str | None = None,
    ):
        self.success = success
        self.restaurants = restaurants or []
        self.shop_scores = shop_scores or {}
        self.raw_output = raw_output
        self.error = error


class AnalyzerAgent:
    """
    内容分析代理 - 三阶段流水线.

    Pipeline:
    1. preprocess_comments() -> ProcessedComment[] (含 interaction_score)
    2. LLM analyze          -> CommentAnalysis[] (语义标签)
    3. calculate_scores()   -> ShopScore[] (精确计算)
    """

    def __init__(self, llm_service: Any | None = None) -> None:
        self._llm_service = llm_service

    async def _get_llm_service(self) -> Any:
        """懒加载 LLM 服务."""
        if self._llm_service is None:
            from xhs_food.services.llm_service import LLMService

            self._llm_service = LLMService()
        return self._llm_service

    async def analyze(
        self,
        title: str,
        content: str,
        comments: list[Any],
        exclude_keywords: list[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        """分析笔记内容和评论 (入口方法)."""
        return await self._analyze_pipeline(title, content, comments, exclude_keywords, note_id)

    async def _analyze_pipeline(
        self,
        title: str,
        content: str,
        comments: list[Any],
        exclude_keywords: list[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        """
        三阶段流水线分析.

        Stage 1: Python 预处理
        Stage 2: LLM 语义分析 (简化 Prompt)
        Stage 3: Python 后处理计分
        """
        try:
            # ============================================================
            # Stage 1: 预处理 - Python 端计算 interaction_score
            # ============================================================
            normalized_comments = self._normalize_comments(comments)
            processed = preprocess_comments(normalized_comments, max_comments=30)

            if not processed:
                return AnalyzeResult(
                    success=True,
                    restaurants=[],
                    shop_scores={},
                )

            logger.debug(f"Stage 1: 预处理完成, {len(processed)} 条评论")

            # ============================================================
            # Stage 2: LLM 语义分析 - 仅判断语义标签
            # ============================================================
            llm = await self._get_llm_service()

            # 格式化评论供 LLM 分析
            comments_text = format_comments_for_llm(processed)

            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=COMMENT_ANALYSIS_SYSTEM_PROMPT),
                HumanMessage(content=COMMENT_ANALYSIS_USER_PROMPT.format(comments=comments_text)),
            ]

            response = await llm.call(messages)
            raw_output = response.content if hasattr(response, "content") else str(response)

            parsed = extract_json(raw_output)
            if parsed is None:
                logger.warning("LLM 输出 JSON 解析失败")
                return AnalyzeResult(
                    success=False,
                    raw_output=raw_output,
                    error="Failed to parse JSON from LLM output",
                )

            llm_results = parsed.get("results", [])
            logger.debug(f"Stage 2: LLM 分析完成, {len(llm_results)} 条结果")

            # ============================================================
            # Stage 3: 后处理计分 - Python 端精确计算
            # ============================================================
            shop_scores = calculate_scores(llm_results, processed)

            # 不限制数量，返回所有满足条件的店铺
            top_shops = get_top_shops(shop_scores, min_mentions=1, top_n=999)

            logger.info(
                f"Stage 3: 计分完成, 识别 {len(shop_scores)} 家店铺, 返回 {len(top_shops)} 家"
            )

            # 转换为 RestaurantRecommendation 格式
            restaurants = self._convert_to_recommendations(top_shops, note_id, exclude_keywords)

            return AnalyzeResult(
                success=True,
                restaurants=restaurants,
                shop_scores=shop_scores,
                raw_output=raw_output,
            )

        except Exception as e:
            logger.exception("Pipeline 分析失败")
            return AnalyzeResult(
                success=False,
                error=str(e),
            )

    def _normalize_comments(self, comments: list[Any]) -> list[dict[str, Any]]:
        """将评论统一转换为字典格式."""
        normalized = []
        for c in comments:
            if isinstance(c, str):
                normalized.append({"text": c})
            elif isinstance(c, dict):
                normalized.append(c)
            else:
                normalized.append({"text": str(c)})
        return normalized

    def _convert_to_recommendations(
        self,
        shops: list[ShopScore],
        note_id: str,
        exclude_keywords: list[str],
    ) -> list[RestaurantRecommendation]:
        """将 ShopScore 转换为 RestaurantRecommendation."""
        recommendations = []

        for shop in shops:
            decision = _FOOD_DECISION.assess_shop(shop, exclude_keywords)
            wh_score = WanghongScore(decision.score)

            wanghong = WanghongAnalysis(
                score=wh_score,
                confidence=decision.confidence,
                reasons=list(decision.reasons),
                has_local_mentions=decision.has_local_mentions,
                has_years_mentioned=False,  # 暂不支持
            )

            rec = RestaurantRecommendation(
                name=shop.name,
                location=None,
                features=[f"评论权重得分: {shop.total_score:.1f}"] + shop.reasons,
                source_notes=[note_id] if note_id else [],
                confidence=decision.confidence,
                wanghong_analysis=wanghong,
                is_recommended=decision.is_recommended,
                filter_reason=decision.filter_reason,
            )
            recommendations.append(rec)

        return recommendations
