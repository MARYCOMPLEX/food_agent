"""
XHS Food Agent Schemas - 数据模型定义.

包含:
- FoodSearchIntent: 用户搜索意图
- RestaurantInfo: 餐厅信息
- RestaurantRecommendation: 最终推荐结果
- AnalysisResult: 分析结果
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


@dataclass
class CommentWeight:
    """评论权重计算结果.
    
    权重公式: 基础分 × 身份系数 × 互动系数 × 内容系数
    """
    text: str  # 评论内容
    base_score: float = 1.0  # 基础分
    identity_factor: float = 1.0  # 身份系数 (本地人强信号×3.0/中等×2.0/无×1.0/营销×0.1)
    interaction_factor: float = 1.0  # 互动系数 (>50赞×2.0/20-50×1.5/5-20×1.2/<5×1.0)
    content_factor: float = 1.0  # 内容系数 (纠正性×3.0/详细×2.0/对比×1.5/赞美×0.5)
    
    @property
    def total_weight(self) -> float:
        """计算总权重."""
        return self.base_score * self.identity_factor * self.interaction_factor * self.content_factor
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:100],  # 截断
            "weight": round(self.total_weight, 2),
            "breakdown": f"{self.identity_factor}×{self.interaction_factor}×{self.content_factor}",
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
class ConversationContext:
    """多轮对话上下文.
    
    用于缓存对话历史和搜索结果，支持追问处理。
    """
    # 对话历史 [{"role": "user"/"assistant", "content": "..."}]
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    
    # 上一轮的搜索意图
    last_intent: Optional[Dict[str, Any]] = None
    
    # 上一轮的推荐结果（店名 -> 推荐详情）
    last_recommendations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # 累积的排除店铺
    excluded_shops: List[str] = field(default_factory=list)
    
    # 累积的偏好
    accumulated_preferences: List[str] = field(default_factory=list)
    
    # 对话轮次
    turn_count: int = 0
    
    # 上一轮的原始笔记（用于扩展搜索）
    last_notes: List[Dict[str, Any]] = field(default_factory=list)
    
    # 目标搜索城市（从意图解析获取，传递给 POI enricher）
    target_city: str = ""
    
    def add_user_message(self, content: str) -> None:
        """添加用户消息到对话历史."""
        self.conversation_history.append({"role": "user", "content": content})
    
    def add_assistant_message(self, content: str) -> None:
        """添加助手消息到对话历史."""
        self.conversation_history.append({"role": "assistant", "content": content})
    
    def get_history_for_llm(self, max_turns: int = 10) -> str:
        """获取格式化的对话历史（用于 LLM）."""
        recent = self.conversation_history[-(max_turns * 2):]
        lines = []
        for msg in recent:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    
    def add_recommendations(self, recommendations: List[Any]) -> None:
        """添加推荐结果到缓存."""
        for r in recommendations:
            if hasattr(r, 'name') and hasattr(r, 'to_dict'):
                self.last_recommendations[r.name] = r.to_dict()
            elif isinstance(r, dict):
                name = r.get("name", "")
                if name:
                    self.last_recommendations[name] = r
    
    def exclude_shop(self, shop_name: str) -> None:
        """添加排除店铺."""
        if shop_name not in self.excluded_shops:
            self.excluded_shops.append(shop_name)
    
    def get_shop_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """根据名称获取店铺信息."""
        # 精确匹配
        if name in self.last_recommendations:
            return self.last_recommendations[name]
        # 模糊匹配
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
        """重置上下文（开始新搜索）."""
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
    location: str  # 地点：自贡
    food_type: Optional[str] = None  # 美食类型：川菜、火锅等
    requirements: List[str] = field(default_factory=list)  # 正向要求：["本地人常去", "老店"]
    exclude_keywords: List[str] = field(default_factory=list)  # 排除关键词：["网红", "打卡"]
    time_filter: Optional[str] = None  # 时间筛选：老店/新开等
    price_range: Optional[str] = None  # 价位范围
    
    def to_search_queries(self) -> List[str]:
        """生成搜索关键词列表."""
        queries = []
        base = self.location
        if self.food_type:
            base = f"{self.location} {self.food_type}"
        
        # 基础查询
        queries.append(base)
        
        # 添加正向要求
        for req in self.requirements[:2]:  # 最多2个
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


@dataclass
class XHSNote:
    """小红书笔记信息."""
    id: str
    title: str
    desc: str = ""
    full_desc: str = ""
    link: str = ""
    likes: int = 0
    comments_count: int = 0
    tags: List[str] = field(default_factory=list)
    top_comments: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "desc": self.desc,
            "full_desc": self.full_desc,
            "link": self.link,
            "likes": self.likes,
            "comments_count": self.comments_count,
            "tags": self.tags,
            "top_comments": self.top_comments,
        }


@dataclass
class RestaurantInfo:
    """从笔记中提取的餐厅信息."""
    name: str
    location: Optional[str] = None  # 位置描述（可能从评论提取）
    features: List[str] = field(default_factory=list)  # 特点
    recommended_dishes: List[str] = field(default_factory=list)  # 推荐菜品
    price_info: Optional[str] = None  # 价格信息
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "location": self.location,
            "features": self.features,
            "recommended_dishes": self.recommended_dishes,
            "price_info": self.price_info,
        }


@dataclass
class WanghongAnalysis:
    """网红店分析结果."""
    score: WanghongScore
    confidence: float  # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)  # 判断理由
    
    # 具体指标
    has_queue_mentions: bool = False  # 提到排队
    has_photo_focus: bool = False  # 强调拍照打卡
    has_negative_service: bool = False  # 服务差评
    has_local_mentions: bool = False  # 本地人提及
    has_years_mentioned: bool = False  # 提到开了多少年
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score.value,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "indicators": {
                "has_queue_mentions": self.has_queue_mentions,
                "has_photo_focus": self.has_photo_focus,
                "has_negative_service": self.has_negative_service,
                "has_local_mentions": self.has_local_mentions,
                "has_years_mentioned": self.has_years_mentioned,
            }
        }


@dataclass
class MustTryItem:
    """必点推荐项."""
    name: str
    reason: str = ""
    img: str = ""  # 图片URL（可选，通常为空）
    
    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "reason": self.reason, "img": self.img}


@dataclass
class BlackListItem:
    """避雷菜品项."""
    name: str
    reason: str = ""
    
    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "reason": self.reason}


@dataclass
class ShopStats:
    """店铺综合评级."""
    flavor: str = ""  # 口味评级: A/B/C 或空
    cost: str = ""    # 人均: $/$$/$$$  
    wait: str = ""    # 等位时间: 5min/15min/30min+
    env: str = ""     # 环境: Quiet/Casual/Noisy
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "flavor": self.flavor,
            "cost": self.cost,
            "wait": self.wait,
            "env": self.env,
        }



@dataclass
class RestaurantRecommendation:
    """最终餐厅推荐."""
    name: str
    location: Optional[str] = None
    features: List[str] = field(default_factory=list)
    source_notes: List[str] = field(default_factory=list)  # 来源笔记ID
    confidence: float = 0.5  # 推荐置信度
    wanghong_analysis: Optional[WanghongAnalysis] = None
    
    # 是否通过筛选
    is_recommended: bool = True
    filter_reason: Optional[str] = None  # 如果被过滤，原因
    
    # POI 详情（高德地图补充）
    poi_details: Optional[Dict[str, Any]] = None
    
    # 新增: 详细评价字段
    pros: List[str] = field(default_factory=list)  # 正向评价
    cons: List[str] = field(default_factory=list)  # 负向评价
    must_try: List[MustTryItem] = field(default_factory=list)  # 必点推荐
    black_list: List[BlackListItem] = field(default_factory=list)  # 避雷菜品
    stats: Optional[ShopStats] = None  # 综合评级
    tags: List[str] = field(default_factory=list)  # 标签汇总
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "location": self.location,
            "features": self.features,
            "source_notes": self.source_notes,
            "confidence": self.confidence,
            "is_recommended": self.is_recommended,
            "filter_reason": self.filter_reason,
            "wanghong_analysis": self.wanghong_analysis.to_dict() if self.wanghong_analysis else None,
            "poi_details": self.poi_details,
            # 新增字段
            "pros": self.pros,
            "cons": self.cons,
            "mustTry": [item.to_dict() for item in self.must_try] if self.must_try else [],
            "blackList": [item.to_dict() for item in self.black_list] if self.black_list else [],
            "stats": self.stats.to_dict() if self.stats else {"flavor": "", "cost": "", "wait": "", "env": ""},
            "tags": self.tags,
        }
    
    def to_table_row(self) -> Dict[str, str]:
        """转换为表格行."""
        wanghong_status = "未知"
        if self.wanghong_analysis:
            score = self.wanghong_analysis.score
            if score in (WanghongScore.DEFINITELY_LOCAL, WanghongScore.LIKELY_LOCAL):
                wanghong_status = "✅ 本地老店"
            elif score in (WanghongScore.DEFINITELY_WANGHONG, WanghongScore.LIKELY_WANGHONG):
                wanghong_status = "❌ 网红店"
            else:
                wanghong_status = "❓ 待验证"
        
        return {
            "店名": self.name,
            "位置": self.location or "见评论区",
            "特点": "、".join(self.features[:3]) if self.features else "-",
            "类型判断": wanghong_status,
            "来源数": str(len(self.source_notes)),
        }



@dataclass  
class XHSFoodResponse:
    """XHS Food Agent 最终响应."""
    status: str = "ok"  # ok, clarify, error
    recommendations: List[RestaurantRecommendation] = field(default_factory=list)
    filtered_count: int = 0  # 被过滤的数量
    clarify_questions: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "filtered_count": self.filtered_count,
            "clarify_questions": self.clarify_questions,
            "error_message": self.error_message,
            "summary": self.summary,
        }
    
    def to_markdown_table(self) -> str:
        """生成 Markdown 表格."""
        if not self.recommendations:
            return "暂无推荐结果"
        
        rows = [r.to_table_row() for r in self.recommendations if r.is_recommended]
        if not rows:
            return "所有店铺都被过滤（可能都是网红店）"
        
        headers = list(rows[0].keys())
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(row.values()) + " |")
        
        return "\n".join(lines)
