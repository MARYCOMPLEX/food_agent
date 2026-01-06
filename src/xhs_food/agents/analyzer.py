"""
AnalyzerAgent - 内容分析代理 (重构版).

采用三阶段流水线架构：
1. Python 预处理: 提取点赞、计算 interaction_score
2. LLM 语义分析: 仅判断 identity/sentiment/is_correction/mentioned_shops
3. Python 后处理: 精确计算最终权重得分

此架构解决 LLM 算术错误问题，并大幅降低 Prompt 成本。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from xhs_food.prompts.prompts import (
    COMMENT_ANALYSIS_SYSTEM_PROMPT,
    COMMENT_ANALYSIS_USER_PROMPT,
    # 保留旧版 prompt 用于向后兼容
    ANALYZER_SYSTEM_PROMPT_ZH,
    ANALYZER_INSTRUCTION_ZH,
)
from xhs_food.schemas import (
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
    MustTryItem,
    BlackListItem,
    ShopStats,
)
from xhs_food.services.preprocessing import (
    ProcessedComment,
    preprocess_comments,
    format_comments_for_llm,
)
from xhs_food.services.scoring import (
    CommentAnalysis,
    ShopScore,
    calculate_scores,
    get_top_shops,
)

logger = logging.getLogger(__name__)


class AnalyzeResult:
    """分析结果."""
    def __init__(
        self,
        success: bool,
        restaurants: Optional[List[RestaurantRecommendation]] = None,
        shop_scores: Optional[Dict[str, ShopScore]] = None,
        raw_output: str = "",
        error: Optional[str] = None,
    ):
        self.success = success
        self.restaurants = restaurants or []
        self.shop_scores = shop_scores or {}
        self.raw_output = raw_output
        self.error = error


class AnalyzerAgent:
    """
    内容分析代理 - 重构版 (三阶段流水线).
    
    Pipeline:
    1. preprocess_comments() -> ProcessedComment[] (含 interaction_score)
    2. LLM analyze          -> CommentAnalysis[] (语义标签)
    3. calculate_scores()   -> ShopScore[] (精确计算)
    """
    
    def __init__(self, llm_service=None, use_legacy_mode: bool = False):
        """
        初始化分析器.
        
        Args:
            llm_service: LLM 服务实例
            use_legacy_mode: 是否使用旧版模式（向后兼容）
        """
        self._llm_service = llm_service
        self._use_legacy_mode = use_legacy_mode
    
    async def _get_llm_service(self):
        """懒加载 LLM 服务."""
        if self._llm_service is None:
            from xhs_food.services.llm_service import LLMService
            self._llm_service = LLMService()
        return self._llm_service
    
    async def analyze(
        self,
        title: str,
        content: str,
        comments: List[Any],
        exclude_keywords: List[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        """
        分析笔记内容和评论 (入口方法).
        
        Args:
            title: 笔记标题
            content: 笔记内容
            comments: 评论列表 (支持 str 或 Dict 格式)
            exclude_keywords: 用户排除关键词
            note_id: 笔记ID
            
        Returns:
            AnalyzeResult: 分析结果
        """
        if self._use_legacy_mode:
            return await self._analyze_legacy(
                title, content, comments, exclude_keywords, note_id
            )
        
        return await self._analyze_pipeline(
            title, content, comments, exclude_keywords, note_id
        )
    
    async def _analyze_pipeline(
        self,
        title: str,
        content: str,
        comments: List[Any],
        exclude_keywords: List[str],
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
            
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content=COMMENT_ANALYSIS_SYSTEM_PROMPT),
                HumanMessage(content=COMMENT_ANALYSIS_USER_PROMPT.format(
                    comments=comments_text
                )),
            ]
            
            response = await llm.call(messages)
            raw_output = response.content if hasattr(response, 'content') else str(response)
            
            # 解析 LLM 输出
            parsed = self._extract_json(raw_output)
            if parsed is None:
                logger.warning("LLM 输出 JSON 解析失败，降级到旧模式")
                return await self._analyze_legacy(
                    title, content, comments, exclude_keywords, note_id
                )
            
            llm_results = parsed.get("results", [])
            logger.debug(f"Stage 2: LLM 分析完成, {len(llm_results)} 条结果")
            
            # ============================================================
            # Stage 3: 后处理计分 - Python 端精确计算
            # ============================================================
            shop_scores = calculate_scores(llm_results, processed)
            
            # 不限制数量，返回所有满足条件的店铺
            top_shops = get_top_shops(shop_scores, min_mentions=1, top_n=999)
            
            logger.info(f"Stage 3: 计分完成, 识别 {len(shop_scores)} 家店铺, 返回 {len(top_shops)} 家")
            
            # 转换为 RestaurantRecommendation 格式
            restaurants = self._convert_to_recommendations(
                top_shops, note_id, exclude_keywords
            )
            
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
    
    def _normalize_comments(self, comments: List[Any]) -> List[Dict[str, Any]]:
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
        shops: List[ShopScore],
        note_id: str,
        exclude_keywords: List[str],
    ) -> List[RestaurantRecommendation]:
        """将 ShopScore 转换为 RestaurantRecommendation."""
        recommendations = []
        
        for shop in shops:
            # 检查是否应被排除
            should_exclude = any(
                kw.lower() in shop.name.lower() 
                for kw in exclude_keywords
            )
            
            # 基于得分判断网红程度
            if shop.local_signal_count >= 2 and shop.total_score > 10:
                wh_score = WanghongScore.DEFINITELY_LOCAL
                confidence = 0.9
            elif shop.local_signal_count >= 1 and shop.total_score > 5:
                wh_score = WanghongScore.LIKELY_LOCAL
                confidence = 0.75
            elif shop.negative_count > shop.positive_count:
                wh_score = WanghongScore.LIKELY_WANGHONG
                confidence = 0.6
            else:
                wh_score = WanghongScore.UNKNOWN
                confidence = 0.5
            
            wanghong = WanghongAnalysis(
                score=wh_score,
                confidence=confidence,
                reasons=shop.reasons,
                has_local_mentions=shop.local_signal_count > 0,
                has_years_mentioned=False,  # 暂不支持
            )
            
            is_recommended = (
                not should_exclude and
                wh_score not in (
                    WanghongScore.DEFINITELY_WANGHONG,
                    WanghongScore.LIKELY_WANGHONG,
                )
            )
            
            filter_reason = None
            if should_exclude:
                filter_reason = "匹配用户排除关键词"
            elif not is_recommended:
                filter_reason = f"判定为网红店: {', '.join(shop.reasons[:2])}"
            
            rec = RestaurantRecommendation(
                name=shop.name,
                location=None,
                features=[f"评论权重得分: {shop.total_score:.1f}"] + shop.reasons,
                source_notes=[note_id] if note_id else [],
                confidence=confidence,
                wanghong_analysis=wanghong,
                is_recommended=is_recommended,
                filter_reason=filter_reason,
            )
            recommendations.append(rec)
        
        return recommendations
    
    # =========================================================================
    # Legacy Mode (向后兼容)
    # =========================================================================
    
    async def _analyze_legacy(
        self,
        title: str,
        content: str,
        comments: List[Any],
        exclude_keywords: List[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        """旧版分析方法 (向后兼容)."""
        try:
            llm = await self._get_llm_service()
            
            # Format comments
            if comments and isinstance(comments[0], dict):
                comments_text = "\n".join([
                    f"- {c.get('text', c.get('content', str(c)))}" 
                    for c in comments[:20]
                ])
            else:
                comments_text = "\n".join([f"- {c}" for c in comments[:20]])
            
            # Build instruction
            instruction = ANALYZER_INSTRUCTION_ZH.format(
                title=title,
                content=content[:2000],
                comments=comments_text,
                exclude_keywords=", ".join(exclude_keywords),
            )
            
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content=ANALYZER_SYSTEM_PROMPT_ZH),
                HumanMessage(content=instruction),
            ]
            
            response = await llm.call(messages)
            raw_output = response.content if hasattr(response, 'content') else str(response)
            
            # Parse result
            parsed = self._extract_json(raw_output)
            if parsed is None:
                return AnalyzeResult(
                    success=False,
                    raw_output=raw_output,
                    error="Failed to parse JSON"
                )
            
            # Build recommendations
            restaurants = []
            for r_data in parsed.get("restaurants", []):
                # Parse wanghong analysis
                wa_data = r_data.get("wanghong_analysis", {})
                try:
                    score = WanghongScore(wa_data.get("score", "unknown"))
                except ValueError:
                    score = WanghongScore.UNKNOWN
                    
                wanghong = WanghongAnalysis(
                    score=score,
                    confidence=wa_data.get("confidence", 0.5),
                    reasons=wa_data.get("reasons", []),
                    has_queue_mentions=wa_data.get("indicators", {}).get("has_queue_mentions", False),
                    has_photo_focus=wa_data.get("indicators", {}).get("has_photo_focus", False),
                    has_negative_service=wa_data.get("indicators", {}).get("has_negative_service", False),
                    has_local_mentions=wa_data.get("indicators", {}).get("has_local_mentions", False),
                    has_years_mentioned=wa_data.get("indicators", {}).get("has_years_mentioned", False),
                )
                
                # Determine if should be filtered
                is_recommended = wanghong.score not in (
                    WanghongScore.DEFINITELY_WANGHONG,
                    WanghongScore.LIKELY_WANGHONG,
                )
                filter_reason = None
                if not is_recommended:
                    filter_reason = f"判定为网红店: {', '.join(wanghong.reasons[:2])}"
                
                # 解析新字段: mustTry
                must_try = []
                for item in r_data.get("mustTry", []):
                    if isinstance(item, dict) and item.get("name"):
                        must_try.append(MustTryItem(
                            name=item.get("name", ""),
                            reason=item.get("reason", ""),
                            img=item.get("img", ""),
                        ))
                
                # 解析新字段: blackList
                black_list = []
                for item in r_data.get("blackList", []):
                    if isinstance(item, dict) and item.get("name"):
                        black_list.append(BlackListItem(
                            name=item.get("name", ""),
                            reason=item.get("reason", ""),
                        ))
                
                # 解析新字段: stats
                stats_data = r_data.get("stats", {})
                stats = None
                if stats_data and isinstance(stats_data, dict):
                    stats = ShopStats(
                        flavor=stats_data.get("flavor", ""),
                        cost=stats_data.get("cost", ""),
                        wait=stats_data.get("wait", ""),
                        env=stats_data.get("env", ""),
                    )
                
                rec = RestaurantRecommendation(
                    name=r_data.get("name", "未知"),
                    location=r_data.get("location"),
                    features=r_data.get("features", []),
                    source_notes=[note_id] if note_id else [],
                    confidence=wanghong.confidence,
                    wanghong_analysis=wanghong,
                    is_recommended=is_recommended,
                    filter_reason=filter_reason,
                    # 新字段
                    pros=r_data.get("pros", []),
                    cons=r_data.get("cons", []),
                    must_try=must_try,
                    black_list=black_list,
                    stats=stats,
                    tags=r_data.get("tags", []),
                )
                restaurants.append(rec)
            
            return AnalyzeResult(
                success=True,
                restaurants=restaurants,
                raw_output=raw_output,
            )

            
        except Exception as e:
            return AnalyzeResult(
                success=False,
                error=str(e),
            )
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从 LLM 输出中提取 JSON."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{.*\}',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if '```' in pattern else match.group(0)
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    continue
        
        return None
