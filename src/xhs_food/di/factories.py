"""
XHS Food Agent DI Factories - 依赖注入工厂函数.

提供:
- get_xhs_service: 获取 XHSService 实例
- get_xhs_tool_registry: 获取 XHS 工具注册表
- get_xhs_food_orchestrator: 获取主编排器
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from xhs_food.protocols.mcp import MCPToolRegistry
from xhs_food.providers.xhs_providers import (
    XHSSearchProvider,
    XHSNoteProvider,
    XHSBatchProvider,
)

if TYPE_CHECKING:
    from xhs_food.spider.services.xhs_service import XHSService


@lru_cache()
def get_xhs_service() -> "XHSService":
    """
    获取 XHSService 单例.
    
    Returns:
        XHSService 实例
        
    Note:
        结果会被缓存，首次调用后返回同一实例。
    """
    from xhs_food.spider.services.xhs_service import XHSService
    return XHSService()


def get_xhs_tool_registry() -> MCPToolRegistry:
    """
    获取预注册所有 XHS 工具的注册表.
    
    Returns:
        MCPToolRegistry 实例
        
    使用示例:
        registry = get_xhs_tool_registry()
        
        search = registry.get_required("xhs_search")
        result = await search.execute(keyword="自贡美食")
    """
    registry = MCPToolRegistry()
    
    registry.register(XHSSearchProvider())
    registry.register(XHSNoteProvider())
    registry.register(XHSBatchProvider())
    
    return registry


async def get_xhs_food_orchestrator():
    """
    获取 XHS Food Orchestrator 实例.
    
    Returns:
        XHSFoodOrchestrator 实例
        
    使用示例:
        orchestrator = await get_xhs_food_orchestrator()
        response = await orchestrator.process(
            "搜索自贡本地人经常吃的地道老店"
        )
    """
    from xhs_food.orchestrator import XHSFoodOrchestrator
    return XHSFoodOrchestrator(
        xhs_registry=get_xhs_tool_registry(),
    )
