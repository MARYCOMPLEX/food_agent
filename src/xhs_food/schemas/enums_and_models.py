"""
XHS Food Agent Schemas - 枚举类型与核心数据模型.

包含:
- 枚举: WanghongScore, SearchPhase, RecommendationLevel, FollowUpType
- 模型: CommentWeight, CrossValidationResult, ConversationContext, FoodSearchIntent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class WanghongScore(Enum):
    """网红店评分."""
    DEFINITELY_WANGHONG = "definitely_wanghong"  # 确定是网红店
    LIKELY_WANGHONG = "likely_wanghong"  # 可能是网红店
    UNKNOWN = "unknown"  # 无法判断
    LIKELY_LOCAL = "likely_local"  # 可能是本地店
    DEFINITELY_LOCAL = "definitely_local"  # 确定是本地老店


class SearchPhase(Enum):
    """4阶段搜索策略."""
    PHASE_1_BROAD = "phase1_broad"  # 广撒网
    PHASE_2_HIDDEN = "phase2_hidden"  # 挖隐藏
    PHASE_3_VERIFY = "phase3_verify"  # 定向验证
    PHASE_4_CATEGORY = "phase4_category"  # 细分搜索


class RecommendationLevel(Enum):
    """推荐级别."""
    STRONGLY_RECOMMEND = "strongly_recommend"  # ⭐ 强烈推荐
    RECOMMEND = "recommend"  # ⭐⭐ 推荐
    CAUTIOUS = "cautious"  # ⭐⭐⭐ 谨慎
    NOT_RECOMMEND = "not_recommend"  # ❌ 不推荐


class FollowUpType(Enum):
    """追问类型."""
    NEW_SEARCH = "new_search"  # 新搜索（无上下文）
    FILTER = "filter"  # 过滤类：排除某店
    CATEGORY_FILTER = "category_filter"  # 品类过滤：在现有结果中筛选某类型
    LOCATION_FILTER = "location_filter"  # 位置过滤：在现有结果中筛选某区域
    REFINE = "refine"  # 细化类：多找几家火锅、换个区域
    EXPAND = "expand"  # 扩展类：还有吗、多找几家
    DETAIL = "detail"  # 详情类：XX店怎么样、具体位置
    CONFIRM = "confirm"  # 确认类：就这个了、帮我选一家


@dataclass
class CommentWeight:
    """评论权重计算结果.

    权重公式: 基础分 x 身份系数 x 互动系数 x 内容系数
    """
    text: str  # 评论内容
    base_score: float = 1.0  # 基础分
    identity_factor: float = 1.0  # 身份系数 (本地人强信号x3.0/中等x2.0/无x1.0/营销x0.1)
    interaction_factor: float = 1.0  # 互动系数 (>50赞x2.0/20-50x1.5/5-20x1.2/<5x1.0)
    content_factor: float = 1.0  # 内容系数 (纠正性x3.0/详细x2.0/对比x1.5/赞美x0.5)

    @property
    def total_weight(self) -> float:
        """计算总权重."""
        return self.base_score * self.identity_factor * self.interaction_factor * self.content_factor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100],  # 截断
            "weight": round(self.total_weight, 2),
            "breakdown": f"{self.identity_factor}x{self.interaction_factor}x{self.content_factor}",
        }


@dataclass
class CrossValidationResult:
    """交叉验证结果.

    三角验证法:
    - 至少在2个不同帖子中被提到
    - 至少有1个本地人正面评价(权重>3.0)
    - 无红色预警级别的负面评价
    - 有基本的位置信息
    """
    shop_name: str
    appearance_count: int = 0  # 出现次数
    positive_ratio: float = 0.0  # 正面评价占比
    has_local_endorsement: bool = False  # 有本地人背书 (权重>3.0的评论)
    has_red_warning: bool = False  # 有红色预警
    has_location_info: bool = False  # 有位置信息
    high_weight_comments: List[CommentWeight] = field(default_factory=list)  # 高权重评论

    @property
    def meets_minimum_standard(self) -> bool:
        """是否满足最低验证标准."""
        return (
            self.appearance_count >= 2 and
            self.has_local_endorsement and
            not self.has_red_warning and
            self.has_location_info
        )

    @property
    def recommendation_level(self) -> RecommendationLevel:
        """计算推荐级别."""
        if self.has_red_warning:
            return RecommendationLevel.NOT_RECOMMEND
        if not self.meets_minimum_standard:
            return RecommendationLevel.CAUTIOUS
        if self.appearance_count >= 3 and len(self.high_weight_comments) >= 2:
            return RecommendationLevel.STRONGLY_RECOMMEND
        return RecommendationLevel.RECOMMEND

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shop_name": self.shop_name,
            "appearance_count": self.appearance_count,
            "positive_ratio": round(self.positive_ratio, 2),
            "has_local_endorsement": self.has_local_endorsement,
            "has_red_warning": self.has_red_warning,
            "meets_minimum_standard": self.meets_minimum_standard,
            "recommendation_level": self.recommendation_level.value,
        }


@dataclass
class ConversationContext:
    """多轮对话上下文.

    用于缓存对话历史和搜索结果，支持追问处理。
    """
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    last_intent: Optional[Dict[str, Any]] = None
    last_recommendations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    excluded_shops: List[str] = field(default_factory=list)
    accumulated_preferences: List[str] = field(default_factory=list)
    turn_count: int = 0
    last_notes: List[Dict[str, Any]] = field(default_factory=list)
    target_city: str = ""

    def add_user_message(self, content: str) -> None:
        self.conversation_history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.conversation_history.append({"role": "assistant", "content": content})

    def get_history_for_llm(self, max_turns: int = 10) -> str:
        recent = self.conversation_history[-(max_turns * 2):]
        lines = []
        for msg in recent:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def add_recommendations(self, recommendations: List[Any]) -> None:
        for r in recommendations:
            if hasattr(r, 'name') and hasattr(r, 'to_dict'):
                self.last_recommendations[r.name] = r.to_dict()
            elif isinstance(r, dict):
                name = r.get("name", "")
                if name:
                    self.last_recommendations[name] = r

    def exclude_shop(self, shop_name: str) -> None:
        if shop_name not in self.excluded_shops:
            self.excluded_shops.append(shop_name)

    def get_shop_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        if name in self.last_recommendations:
            return self.last_recommendations[name]
        for shop_name, shop_info in self.last_recommendations.items():
            if name in shop_name or shop_name in name:
                return shop_info
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_intent": self.last_intent,
            "last_recommendations_count": len(self.last_recommendations),
            "excluded_shops": self.excluded_shops,
            "accumulated_preferences": self.accumulated_preferences,
            "turn_count": self.turn_count,
            "history_length": len(self.conversation_history),
        }

    def reset(self) -> None:
        self.conversation_history = []
        self.last_intent = None
        self.last_recommendations = {}
        self.excluded_shops = []
        self.accumulated_preferences = []
        self.turn_count = 0
        self.last_notes = []
        self.target_city = ""


@dataclass
class FoodSearchIntent:
    """解析后的用户搜索意图."""
    location: str
    food_type: Optional[str] = None
    requirements: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    time_filter: Optional[str] = None
    price_range: Optional[str] = None

    def to_search_queries(self) -> List[str]:
        queries = []
        base = self.location
        if self.food_type:
            base = f"{self.location} {self.food_type}"
        queries.append(base)
        for req in self.requirements[:2]:
            queries.append(f"{base} {req}")
        return queries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location": self.location,
            "food_type": self.food_type,
            "requirements": self.requirements,
            "exclude_keywords": self.exclude_keywords,
            "time_filter": self.time_filter,
            "price_range": self.price_range,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FoodSearchIntent":
        return cls(
            location=data.get("location", ""),
            food_type=data.get("food_type"),
            requirements=data.get("requirements", []),
            exclude_keywords=data.get("exclude_keywords", []),
            time_filter=data.get("time_filter"),
            price_range=data.get("price_range"),
        )
