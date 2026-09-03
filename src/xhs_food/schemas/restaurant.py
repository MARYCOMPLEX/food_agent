"""
XHS Food Agent Schemas - 餐厅相关数据模型.

包含:
- XHSNote: 小红书笔记
- RestaurantInfo: 餐厅基础信息
- WanghongAnalysis: 网红分析
- MustTryItem/BlackListItem/ShopStats: 评价细节
- RestaurantRecommendation: 最终推荐
- XHSFoodResponse: API 响应
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .enums_and_models import WanghongScore


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
    location: Optional[str] = None
    features: List[str] = field(default_factory=list)
    recommended_dishes: List[str] = field(default_factory=list)
    price_info: Optional[str] = None

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
    reasons: List[str] = field(default_factory=list)
    has_queue_mentions: bool = False
    has_photo_focus: bool = False
    has_negative_service: bool = False
    has_local_mentions: bool = False
    has_years_mentioned: bool = False

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
    img: str = ""

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
    flavor: str = ""
    cost: str = ""
    wait: str = ""
    env: str = ""

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
    source_notes: List[str] = field(default_factory=list)
    confidence: float = 0.5
    wanghong_analysis: Optional[WanghongAnalysis] = None
    is_recommended: bool = True
    filter_reason: Optional[str] = None
    # Canonical structured profile projection produced by the Dianping
    # enrichment boundary. Store/profile data has one explicit wire shape.
    shop_profile: Optional[Dict[str, Any]] = None
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    must_try: List[MustTryItem] = field(default_factory=list)
    black_list: List[BlackListItem] = field(default_factory=list)
    stats: Optional[ShopStats] = None
    tags: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    source_gaps: List[Dict[str, Any]] = field(default_factory=list)

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
            "shopProfile": self.shop_profile,
            "pros": self.pros,
            "cons": self.cons,
            "mustTry": [item.to_dict() for item in self.must_try] if self.must_try else [],
            "blackList": [item.to_dict() for item in self.black_list] if self.black_list else [],
            "stats": self.stats.to_dict() if self.stats else {"flavor": "", "cost": "", "wait": "", "env": ""},
            "tags": self.tags,
            "evidenceRefs": self.evidence_refs,
            "evidenceSummary": self.evidence_summary,
            "sourceGaps": self.source_gaps,
        }

    def to_table_row(self) -> Dict[str, str]:
        wanghong_status = "未知"
        if self.wanghong_analysis:
            score = self.wanghong_analysis.score
            if score in (WanghongScore.DEFINITELY_LOCAL, WanghongScore.LIKELY_LOCAL):
                wanghong_status = "本地老店"
            elif score in (WanghongScore.DEFINITELY_WANGHONG, WanghongScore.LIKELY_WANGHONG):
                wanghong_status = "网红店"
            else:
                wanghong_status = "待验证"
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
    status: str = "ok"
    recommendations: List[RestaurantRecommendation] = field(default_factory=list)
    filtered_count: int = 0
    clarify_questions: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    summary: str = ""
    research_metadata: Dict[str, Any] = field(default_factory=dict)
    gaps: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "filtered_count": self.filtered_count,
            "clarify_questions": self.clarify_questions,
            "error_message": self.error_message,
            "summary": self.summary,
            "researchMetadata": self.research_metadata,
            "gaps": self.gaps,
        }

    def to_markdown_table(self) -> str:
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
