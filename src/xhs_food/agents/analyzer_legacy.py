"""
LegacyAnalyzerMixin - 旧版分析方法 (向后兼容).

从 analyzer.py 拆分，包含 _analyze_legacy 和 _extract_json 方法。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from xhs_food.prompts import (
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

logger = logging.getLogger(__name__)


class LegacyAnalyzerMixin:
    """旧版分析方法的 Mixin 类.

    依赖主类提供 self._llm_service 和 self._get_llm_service() 方法。
    """

    async def _analyze_legacy(
        self,
        title: str,
        content: str,
        comments: List[Any],
        exclude_keywords: List[str],
        note_id: str = "",
    ) -> "AnalyzeResult":
        """旧版分析方法 (向后兼容)."""
        from .analyzer import AnalyzeResult

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
