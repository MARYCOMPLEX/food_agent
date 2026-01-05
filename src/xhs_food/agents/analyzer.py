"""
AnalyzerAgent - 内容分析代理 (简化版).

分析小红书笔记内容和评论，判断店铺是否为网红店，提取店铺信息。
直接使用 LLM 而不依赖 LangGraph。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from xhs_food.prompts.prompts import (
    ANALYZER_SYSTEM_PROMPT_ZH,
    ANALYZER_INSTRUCTION_ZH,
)
from xhs_food.schemas import (
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)


class AnalyzeResult:
    """分析结果."""
    def __init__(
        self,
        success: bool,
        restaurants: Optional[List[RestaurantRecommendation]] = None,
        raw_output: str = "",
        error: Optional[str] = None,
    ):
        self.success = success
        self.restaurants = restaurants or []
        self.raw_output = raw_output
        self.error = error


class AnalyzerAgent:
    """
    内容分析代理 - 简化版.
    
    直接使用 LLM 服务进行内容分析，不依赖 LangGraph。
    """
    
    def __init__(self, llm_service=None):
        self._llm_service = llm_service
    
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
        comments: List[str],
        exclude_keywords: List[str],
        note_id: str = "",
    ) -> AnalyzeResult:
        """
        分析笔记内容和评论.
        
        Args:
            title: 笔记标题
            content: 笔记内容
            comments: 评论列表
            exclude_keywords: 用户排除关键词
            note_id: 笔记ID
            
        Returns:
            AnalyzeResult: 分析结果
        """
        try:
            llm = await self._get_llm_service()
            
            # Format comments
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
                
                # 提取关键评论权重（如果LLM返回了）
                key_comments = wa_data.get("key_comments", [])
                if key_comments:
                    # 检查是否有高权重本地人评论
                    high_weight_count = sum(1 for c in key_comments if c.get("weight", 0) > 3.0)
                    if high_weight_count > 0:
                        wanghong.has_local_mentions = True

                
                # Determine if should be filtered
                is_recommended = wanghong.score not in (
                    WanghongScore.DEFINITELY_WANGHONG,
                    WanghongScore.LIKELY_WANGHONG,
                )
                filter_reason = None
                if not is_recommended:
                    filter_reason = f"判定为网红店: {', '.join(wanghong.reasons[:2])}"
                
                rec = RestaurantRecommendation(
                    name=r_data.get("name", "未知"),
                    location=r_data.get("location"),
                    features=r_data.get("features", []),
                    source_notes=[note_id] if note_id else [],
                    confidence=wanghong.confidence,
                    wanghong_analysis=wanghong,
                    is_recommended=is_recommended,
                    filter_reason=filter_reason,
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
