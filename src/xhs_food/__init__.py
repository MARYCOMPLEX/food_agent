"""XHS Food Agent Module - 小红书美食智能检索代理 (独立版).

该模块提供:
- XHSFoodOrchestrator: 主编排器
- IntentParserAgent: 用户意图解析
- AnalyzerAgent: 内容分析（网红店判断）

Food search receives its only source tool from the managed account-service MCP
catalog at the application Composition Root.
"""

# pyright: reportUnsupportedDunderAll=false

from __future__ import annotations

from importlib import import_module
from typing import Any

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

_EXPORT_MODULES = {
    "XHSFoodOrchestrator": "xhs_food.orchestrator",
    "XHSFoodState": "xhs_food.state",
    "FoodSearchIntent": "xhs_food.schemas",
    "XHSFoodResponse": "xhs_food.schemas",
    "RestaurantRecommendation": "xhs_food.schemas",
    "SearchPhase": "xhs_food.schemas",
    "CommentWeight": "xhs_food.schemas",
    "CrossValidationResult": "xhs_food.schemas",
    "RecommendationLevel": "xhs_food.schemas",
    "WanghongScore": "xhs_food.schemas",
    "FollowUpType": "xhs_food.schemas",
    "ConversationContext": "xhs_food.schemas",
}


def __getattr__(name: str) -> Any:
    """Load legacy public exports only when a caller requests one."""

    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
