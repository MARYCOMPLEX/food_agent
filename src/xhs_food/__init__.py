"""
XHS Food Agent Module - 小红书美食智能检索代理 (独立版).

该模块提供:
- XHSFoodOrchestrator: 主编排器
- IntentParserAgent: 用户意图解析
- AnalyzerAgent: 内容分析（网红店判断）

使用示例:
    from xhs_food import XHSFoodOrchestrator
    from xhs_food.di import get_xhs_tool_registry
    
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=get_xhs_tool_registry()
    )
    result = await orchestrator.process(
        "搜索自贡本地人经常吃的地道老店，不要网红店"
    )
    print(result.to_markdown_table())
"""

from xhs_food.orchestrator import XHSFoodOrchestrator
from xhs_food.state import XHSFoodState
from xhs_food.schemas import (
    FoodSearchIntent,
    XHSFoodResponse,
    RestaurantRecommendation,
    SearchPhase,
    CommentWeight,
    CrossValidationResult,
    RecommendationLevel,
    WanghongScore,
    FollowUpType,
    ConversationContext,
)

__all__ = [
    "XHSFoodOrchestrator",
    "XHSFoodState",
    "FoodSearchIntent",
    "XHSFoodResponse",
    "RestaurantRecommendation",
    "SearchPhase",
    "CommentWeight",
    "CrossValidationResult",
    "RecommendationLevel",
    "WanghongScore",
    "FollowUpType",
    "ConversationContext",
]
