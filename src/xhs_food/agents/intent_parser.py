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
    ],
    FollowUpType.CATEGORY_FILTER: [
        r"(只要|只看|想吃|换成|来点|想要)(.+)(类|的)",
        r"有没有(.+)(类|的)?",
        r"(.+)(类|的)有吗",
        r"我想吃(.+)",
        r"想吃点(.+)",
        r"换(.+)的",
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
        r"便宜(一点|点)的",
        r"(老店|新店)的",
    ],
}

# 品类关键词映射表
CATEGORY_MAPPING = {
    "炒菜": ["炒菜", "川菜", "家常菜", "江湖菜", "小炒", "中餐"],
    "川菜": ["川菜", "炒菜", "家常菜", "江湖菜"],
    "火锅": ["火锅", "串串", "冒菜", "麻辣烫"],
    "烧烤": ["烧烤", "烤肉", "撸串"],
    "面食": ["面", "抄手", "馄饨", "饺子", "面条"],
    "小吃": ["小吃", "小吃店", "路边摊"],
    "甜品": ["甜品", "甜点", "蛋糕", "奶茶"],
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
        category_target: Optional[str] = None,  # 品类过滤目标（如"炒菜类"）
        location_target: Optional[str] = None,  # 位置过滤目标（如"渝中区"）
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
        self.category_target = category_target
        self.location_target = location_target


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
        
        # 返回 None 表示需要 LLM 理解
        return None, None
    
    async def parse(
        self,
        user_input: str,
        context: Optional[ConversationContext] = None,
    ) -> IntentParseResult:
        """
        解析用户输入为搜索意图.
        
        注意：追问处理现在由 orchestrator._process_follow_up_with_llm 直接处理。
        这个方法只负责解析新的搜索意图。
        
        Args:
            user_input: 用户自然语言输入
            context: 对话上下文（可选）
            
        Returns:
            IntentParseResult: 解析结果
        """
        # 使用 LLM 解析搜索意图
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
            
            # Validate location - it's required for search
            if not intent.location or intent.location.strip() in ["", "未指定", "不明确", "未知"]:
                return IntentParseResult(
                    success=False,
                    need_clarify=True,
                    questions=["请问您想在哪个城市或区域搜索美食？（如：成都、重庆渝中区、北京三里屯等）"],
                    raw_output=raw_output,
                )
            
            return IntentParseResult(
                success=True,
                intent=intent,
                follow_up_type=FollowUpType.NEW_SEARCH,
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
    
    def _extract_category(self, user_input: str, regex_target: Optional[str]) -> str:
        """
        从用户输入中提取品类关键词.
        
        Args:
            user_input: 用户输入
            regex_target: 正则匹配的目标
            
        Returns:
            标准化的品类关键词
        """
        # 先尝试使用正则匹配的目标
        if regex_target:
            # 清理多余的字符
            category = regex_target.strip()
            category = re.sub(r"[类的点]$", "", category)  # 去除尾部的"类"、"的"、"点"
            return category
        
        # 否则从用户输入中提取
        for known_category in CATEGORY_MAPPING.keys():
            if known_category in user_input:
                return known_category
        
        # 兜底：使用完整输入（去除常见词汇）
        cleaned = user_input
        for word in ["我想吃", "想吃点", "来点", "换成", "只要", "只看", "有没有", "类", "的"]:
            cleaned = cleaned.replace(word, "")
        return cleaned.strip() or user_input
