"""
IntentParserAgent - 用户意图解析代理 (支持多轮对话).

将用户自然语言需求解析为结构化的 FoodSearchIntent，
支持追问识别和上下文感知。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from xhs_food.prompts.prompts import (
    INTENT_PARSER_SYSTEM_PROMPT_ZH,
    INTENT_PARSER_INSTRUCTION_ZH,
)
from xhs_food.schemas import (
    FoodSearchIntent,
    FollowUpType,
    ConversationContext,
)


# 追问识别关键词模式
FOLLOW_UP_PATTERNS = {
    FollowUpType.FILTER: [
        r"排除(.+)",
        r"不要(.+)了",
        r"去掉(.+)",
        r"只要(.+)",
        r"只看(.+)",
        r"换成(.+)",
    ],
    FollowUpType.EXPAND: [
        r"还有(吗|其他|更多)",
        r"多找(几家|一些)",
        r"继续(找|搜)",
        r"再来(几个|一些)",
        r"不够",
    ],
    FollowUpType.DETAIL: [
        r"(.+)(怎么样|好不好|推荐吗)",
        r"(.+)(在哪|地址|位置)",
        r"(.+)(什么菜|推荐菜)",
        r"介绍一下(.+)",
        r"详细说说(.+)",
    ],
    FollowUpType.CONFIRM: [
        r"就(这个|这家|它)了",
        r"帮我选",
        r"推荐(一家|哪家)",
        r"去哪家",
    ],
    FollowUpType.REFINE: [
        r"换个(地方|区域|城市)",
        r"(火锅|川菜|烧烤)的",
        r"便宜(一点|点)的",
        r"(老店|新店)的",
    ],
}


class IntentParseResult:
    """意图解析结果."""
    def __init__(
        self,
        success: bool,
        intent: Optional[FoodSearchIntent] = None,
        follow_up_type: FollowUpType = FollowUpType.NEW_SEARCH,
        need_clarify: bool = False,
        questions: Optional[List[str]] = None,
        raw_output: str = "",
        error: Optional[str] = None,
        # 追问相关
        filter_target: Optional[str] = None,  # 过滤目标（如"排除XX店"中的XX店）
        detail_target: Optional[str] = None,  # 详情目标（如"XX店怎么样"中的XX店）
    ):
        self.success = success
        self.intent = intent
        self.follow_up_type = follow_up_type
        self.need_clarify = need_clarify
        self.questions = questions or []
        self.raw_output = raw_output
        self.error = error
        self.filter_target = filter_target
        self.detail_target = detail_target


class IntentParserAgent:
    """
    用户意图解析代理 - 支持多轮对话.
    
    在有上下文的情况下，能够识别追问类型并正确处理。
    """
    
    def __init__(self, llm_service=None):
        self._llm_service = llm_service
    
    async def _get_llm_service(self):
        """懒加载 LLM 服务."""
        if self._llm_service is None:
            from xhs_food.services.llm_service import LLMService
            self._llm_service = LLMService()
        return self._llm_service
    
    def detect_follow_up_type(
        self,
        user_input: str,
        context: Optional[ConversationContext] = None,
    ) -> tuple[FollowUpType, Optional[str]]:
        """
        检测追问类型（不使用LLM，纯规则匹配）.
        
        Returns:
            (追问类型, 提取的目标)
        """
        # 如果没有上下文，一定是新搜索
        if context is None or context.turn_count == 0:
            return FollowUpType.NEW_SEARCH, None
        
        user_input_lower = user_input.lower()
        
        # 检查各种追问模式
        for follow_type, patterns in FOLLOW_UP_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, user_input)
                if match:
                    # 提取匹配的目标
                    target = match.group(1) if match.lastindex else None
                    return follow_type, target
        
        # 如果输入很短且有上下文，可能是追问
        if len(user_input) < 20 and context.turn_count > 0:
            # 检查是否提到了上一轮的店名
            for shop_name in context.last_recommendations.keys():
                if shop_name in user_input:
                    return FollowUpType.DETAIL, shop_name
        
        # 默认为新搜索
        return FollowUpType.NEW_SEARCH, None
    
    async def parse(
        self,
        user_input: str,
        context: Optional[ConversationContext] = None,
    ) -> IntentParseResult:
        """
        解析用户输入为搜索意图.
        
        Args:
            user_input: 用户自然语言输入
            context: 对话上下文（可选）
            
        Returns:
            IntentParseResult: 解析结果
        """
        # 先检测追问类型
        follow_up_type, target = self.detect_follow_up_type(user_input, context)
        
        # 如果是过滤类追问
        if follow_up_type == FollowUpType.FILTER and context and context.last_intent:
            # 复用上一轮意图，添加过滤条件
            intent = FoodSearchIntent.from_dict(context.last_intent)
            if target:
                intent.exclude_keywords.append(target)
            return IntentParseResult(
                success=True,
                intent=intent,
                follow_up_type=follow_up_type,
                filter_target=target,
            )
        
        # 如果是详情类追问
        if follow_up_type == FollowUpType.DETAIL and target:
            return IntentParseResult(
                success=True,
                intent=None,  # 不需要新搜索
                follow_up_type=follow_up_type,
                detail_target=target,
            )
        
        # 如果是扩展类追问
        if follow_up_type == FollowUpType.EXPAND and context and context.last_intent:
            # 复用上一轮意图
            intent = FoodSearchIntent.from_dict(context.last_intent)
            return IntentParseResult(
                success=True,
                intent=intent,
                follow_up_type=follow_up_type,
            )
        
        # 如果是确认类追问
        if follow_up_type == FollowUpType.CONFIRM:
            return IntentParseResult(
                success=True,
                intent=None,
                follow_up_type=follow_up_type,
            )
        
        # 新搜索或细化搜索：使用LLM解析
        try:
            llm = await self._get_llm_service()
            
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content=INTENT_PARSER_SYSTEM_PROMPT_ZH),
                HumanMessage(content=INTENT_PARSER_INSTRUCTION_ZH.format(user_input=user_input)),
            ]
            
            response = await llm.call(messages)
            raw_output = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON
            parsed = self._extract_json(raw_output)
            if parsed is None:
                return IntentParseResult(
                    success=False,
                    raw_output=raw_output,
                    error="Failed to parse JSON from LLM output"
                )
            
            # Check if needs clarification
            if parsed.get("need_clarify", False):
                return IntentParseResult(
                    success=False,
                    need_clarify=True,
                    questions=parsed.get("questions", []),
                    raw_output=raw_output,
                )
            
            # Build intent
            intent = FoodSearchIntent.from_dict(parsed)
            
            # 如果是细化搜索，合并上一轮的排除条件
            if follow_up_type == FollowUpType.REFINE and context and context.excluded_shops:
                for shop in context.excluded_shops:
                    if shop not in intent.exclude_keywords:
                        intent.exclude_keywords.append(shop)
            
            return IntentParseResult(
                success=True,
                intent=intent,
                follow_up_type=follow_up_type,
                raw_output=raw_output,
            )
            
        except Exception as e:
            return IntentParseResult(
                success=False,
                error=str(e),
            )
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从 LLM 输出中提取 JSON."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try markdown code block
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
