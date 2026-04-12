"""
追问处理器 - 处理多轮对话中的各类追问.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from xhs_food.agents.intent_parser import IntentParseResult
from xhs_food.schemas import (
    XHSFoodResponse,
    ConversationContext,
)
from xhs_food.orchestrator.converters import dict_to_recommendation

logger = logging.getLogger(__name__)


class FollowUpHandler:
    """处理多轮对话中的追问逻辑."""

    def __init__(self, context: ConversationContext, llm_service=None):
        self._context = context
        self._llm_service = llm_service

    async def process_follow_up_with_llm(self, user_input: str) -> Optional[XHSFoodResponse]:
        """用 LLM 直接处理追问，不做意图分类."""
        try:
            from xhs_food.prompts import FOLLOW_UP_PROCESSING_PROMPT
            from langchain_core.messages import HumanMessage
            conversation_history = self._context.get_history_for_llm(max_turns=5)
            if not conversation_history:
                conversation_history = "(无历史对话)"
            shop_list = []
            for i, (name, rec_dict) in enumerate(self._context.last_recommendations.items(), 1):
                features = rec_dict.get("features", [])[:3]
                location = rec_dict.get("location", "未知")
                features_str = ", ".join(features) if features else "无"
                shop_list.append(f"{i}. {name}\n   位置: {location}\n   特点: {features_str}")

            shop_list_str = "\n".join(shop_list[:20]) if shop_list else "(无店铺列表)"
            prompt = FOLLOW_UP_PROCESSING_PROMPT.format(
                conversation_history=conversation_history,
                shop_list=shop_list_str,
                user_input=user_input,
            )

            llm = self._llm_service
            if llm is None:
                from xhs_food.services.llm_service import LLMService
                llm = LLMService()
            response = await llm.call([HumanMessage(content=prompt)])
            raw_output = response.content if hasattr(response, 'content') else str(response)
            json_match = re.search(r'\{[\s\S]*\}', raw_output)
            if not json_match:
                logger.warning(f"LLM 输出无法解析为 JSON: {raw_output[:200]}")
                return XHSFoodResponse(
                    status="ok",
                    recommendations=[
                        dict_to_recommendation(r)
                        for r in self._context.last_recommendations.values()
                    ],
                    summary="无法理解您的请求，以下是当前推荐列表",
                )

            parsed = json.loads(json_match.group())
            if parsed.get("new_search", False):
                logger.info("  用户要求重新搜索，触发新搜索流程")
                return None
            shops = parsed.get("shops", [])
            response_text = parsed.get("response", "")
            logger.info(f"  LLM 回复: {response_text[:50]}...")
            matched_recommendations = []
            for shop_name in shops:
                for name, rec_dict in self._context.last_recommendations.items():
                    if shop_name in name or name in shop_name:
                        if rec_dict not in matched_recommendations:
                            matched_recommendations.append(rec_dict)
                        break
            original_count = len(self._context.last_recommendations)
            self._context.turn_count += 1
            return XHSFoodResponse(
                status="ok",
                recommendations=[
                    dict_to_recommendation(r) for r in matched_recommendations
                ] if matched_recommendations else [],
                filtered_count=original_count - len(matched_recommendations) if matched_recommendations else 0,
                summary=response_text,
            )

        except Exception as e:
            logger.warning(f"LLM 追问处理失败: {e}")
            return XHSFoodResponse(
                status="ok",
                recommendations=[
                    dict_to_recommendation(r)
                    for r in self._context.last_recommendations.values()
                ],
                summary=f"处理失败: {str(e)}，以下是当前推荐列表",
            )

    async def handle_filter(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理过滤类追问."""
        target = parse_result.filter_target

        if target:
            self._context.exclude_shop(target)
            logger.info(f"  过滤店铺: {target}")

        # 过滤上一轮结果
        filtered_recommendations = []
        for name, rec_dict in self._context.last_recommendations.items():
            is_excluded = any(
                ex in name or name in ex
                for ex in self._context.excluded_shops
            )
            if not is_excluded:
                filtered_recommendations.append(rec_dict)

        self._context.turn_count += 1

        return XHSFoodResponse(
            status="ok",
            recommendations=[
                dict_to_recommendation(r) for r in filtered_recommendations
            ],
            filtered_count=len(self._context.last_recommendations) - len(filtered_recommendations),
            summary=f"已排除 {target}，剩余 {len(filtered_recommendations)} 家推荐",
        )

    async def handle_category_filter(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理品类过滤类追问（在现有结果中筛选某类型）."""
        target_category = parse_result.category_target or ""
        logger.info(f"  品类过滤: {target_category}")
        category_mapping = {
            "炒菜": ["炒菜", "川菜", "家常菜", "江湖菜", "小炒", "中餐", "粤菜", "湘菜"],
            "川菜": ["川菜", "炒菜", "家常菜", "江湖菜"],
            "火锅": ["火锅", "串串", "冒菜", "麻辣烫"],
            "烧烤": ["烧烤", "烤肉", "撸串", "烤鱼"],
            "面食": ["面", "抄手", "馄饨", "饺子", "面条", "粉"],
            "小吃": ["小吃", "小吃店", "路边摊", "点心"],
            "甜品": ["甜品", "甜点", "蛋糕", "奶茶"],
            "鱼": ["鱼", "鱼庄", "烤鱼", "冷锅鱼", "花椒鱼"],
        }
        match_keywords = [target_category]
        for category, keywords in category_mapping.items():
            if target_category in category or category in target_category:
                match_keywords.extend(keywords)
        match_keywords = list(set(match_keywords))
        logger.debug(f"  匹配关键词: {match_keywords}")
        matched_recommendations = []
        for name, rec_dict in self._context.last_recommendations.items():
            features = rec_dict.get("features", [])
            shop_name = rec_dict.get("name", "")

            is_match = False
            for keyword in match_keywords:
                if keyword in shop_name:
                    is_match = True
                    break
                for feature in features:
                    if keyword in feature or feature in keyword:
                        is_match = True
                        break
                if is_match:
                    break

            if is_match:
                matched_recommendations.append(rec_dict)
        self._context.turn_count += 1
        if not matched_recommendations:
            return XHSFoodResponse(
                status="ok",
                recommendations=[],
                summary=f"在现有 {len(self._context.last_recommendations)} 家店铺中未找到{target_category}类，可以尝试重新搜索",
            )
        original_count = len(self._context.last_recommendations)
        self._context.last_recommendations = {
            rec_dict.get("name", ""): rec_dict for rec_dict in matched_recommendations
        }
        return XHSFoodResponse(
            status="ok",
            recommendations=[dict_to_recommendation(r) for r in matched_recommendations],
            filtered_count=original_count - len(matched_recommendations),
            summary=f"从现有结果中筛选出 {len(matched_recommendations)} 家{target_category}类店铺",
        )

    async def handle_location_filter(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理位置过滤类追问（在现有结果中筛选某区域）."""
        target_location = parse_result.location_target or ""
        logger.info(f"  位置过滤: {target_location}")

        matched_recommendations = []
        for name, rec_dict in self._context.last_recommendations.items():
            location = rec_dict.get("location", "")
            shop_name = rec_dict.get("name", "")

            is_match = False
            if location and target_location:
                if target_location in location or location in target_location:
                    is_match = True
            if target_location in shop_name:
                is_match = True

            if is_match:
                matched_recommendations.append(rec_dict)
        self._context.turn_count += 1
        if not matched_recommendations:
            return XHSFoodResponse(
                status="ok", recommendations=[],
                summary=f"在现有 {len(self._context.last_recommendations)} 家店铺中未找到{target_location}区域的店铺，可以尝试重新搜索",
            )
        original_count = len(self._context.last_recommendations)
        self._context.last_recommendations = {
            rec_dict.get("name", ""): rec_dict for rec_dict in matched_recommendations
        }
        return XHSFoodResponse(
            status="ok",
            recommendations=[dict_to_recommendation(r) for r in matched_recommendations],
            filtered_count=original_count - len(matched_recommendations),
            summary=f"从现有结果中筛选出 {len(matched_recommendations)} 家位于{target_location}的店铺",
        )

    async def handle_detail(self, parse_result: IntentParseResult) -> XHSFoodResponse:
        """处理详情类追问."""
        target = parse_result.detail_target
        if not target:
            return XHSFoodResponse(
                status="error",
                error_message="请指定要查询的店铺名称",
            )

        shop_info = self._context.get_shop_by_name(target)
        if shop_info:
            self._context.turn_count += 1
            features = shop_info.get("features", [])
            location = shop_info.get("location", "位置信息见评论区")
            detail_summary = f"**{shop_info.get('name', target)}**\n"
            detail_summary += f"- 位置: {location}\n"
            detail_summary += f"- 特点: {', '.join(features[:5])}\n"
            if shop_info.get("wanghong_analysis"):
                wa = shop_info["wanghong_analysis"]
                detail_summary += f"- 判定: {wa.get('score', 'unknown')}\n"
                detail_summary += f"- 理由: {', '.join(wa.get('reasons', [])[:3])}\n"

            return XHSFoodResponse(
                status="ok",
                recommendations=[dict_to_recommendation(shop_info)],
                summary=detail_summary,
            )
        else:
            return XHSFoodResponse(
                status="ok",
                recommendations=[],
                summary=f"未找到 {target} 的信息，可能需要重新搜索",
            )

    async def handle_confirm(self) -> XHSFoodResponse:
        """处理确认类追问（帮我选一家）."""
        if not self._context.last_recommendations:
            return XHSFoodResponse(
                status="error",
                error_message="没有可选的店铺，请先进行搜索",
            )
        best_shop = None
        best_score = -1
        for name, rec_dict in self._context.last_recommendations.items():
            wa = rec_dict.get("wanghong_analysis", {})
            score_str = wa.get("score", "unknown")

            score_map = {
                "definitely_local": 5,
                "likely_local": 4,
                "unknown": 2,
                "likely_wanghong": 1,
                "definitely_wanghong": 0,
            }
            score = score_map.get(score_str, 2)
            confidence = rec_dict.get("confidence", 0.5)
            total = score * confidence

            if total > best_score:
                best_score = total
                best_shop = rec_dict

        if best_shop:
            self._context.turn_count += 1
            return XHSFoodResponse(
                status="ok",
                recommendations=[dict_to_recommendation(best_shop)],
                summary=f"推荐你去 **{best_shop.get('name')}**！",
            )

        return XHSFoodResponse(
            status="error",
            error_message="无法选择店铺",
        )
