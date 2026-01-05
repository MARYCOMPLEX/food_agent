"""
XHS Food Agent State - Agent 状态定义.

独立版本，不依赖 meet 框架的 AgentState。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from xhs_food.schemas import (
    FoodSearchIntent,
    XHSNote,
    RestaurantRecommendation,
)


@dataclass
class XHSFoodState:
    """XHS Food Agent 状态.
    
    Attributes:
        search_intent: 解析后的搜索意图
        search_queries: 生成的搜索关键词列表
        raw_notes: 从XHS搜索到的原始笔记
        analyzed_notes: 分析后的笔记（带网红分析）
        restaurants: 提取的餐厅信息
        recommendations: 最终推荐列表
        xhs_status: XHS 处理状态
        
        # 会话历史支持
        conversation_history: 会话历史
        search_phase: 当前搜索阶段
        validated_shops: 已验证的店铺 (店名 -> 出现次数)
    """
    # 搜索阶段
    search_intent: Optional[Dict[str, Any]] = None
    search_queries: List[str] = field(default_factory=list)
    
    # 数据获取阶段
    raw_notes: List[Dict[str, Any]] = field(default_factory=list)
    notes_with_comments: List[Dict[str, Any]] = field(default_factory=list)
    
    # 分析阶段
    analyzed_notes: List[Dict[str, Any]] = field(default_factory=list)
    restaurants: List[Dict[str, Any]] = field(default_factory=list)
    
    # 结果阶段
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    filtered_restaurants: List[Dict[str, Any]] = field(default_factory=list)
    
    # 状态追踪
    xhs_status: str = "pending"  # pending, searching, analyzing, completed, error
    xhs_error: Optional[str] = None
    
    # 会话历史支持
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    search_phase: str = "phase1"  # phase1_broad, phase2_hidden, phase3_verify, phase4_category
    validated_shops: Dict[str, int] = field(default_factory=dict)  # 店名 -> 出现次数
    high_weight_comments: List[Dict[str, Any]] = field(default_factory=list)  # 高权重评论缓存

    
    def get_intent(self) -> Optional[FoodSearchIntent]:
        """获取解析后的搜索意图."""
        if self.search_intent:
            return FoodSearchIntent.from_dict(self.search_intent)
        return None
    
    def set_intent(self, intent: FoodSearchIntent) -> None:
        """设置搜索意图."""
        self.search_intent = intent.to_dict()
        self.search_queries = intent.to_search_queries()
