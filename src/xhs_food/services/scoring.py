"""
评论计分服务 - Comment Scoring Service.

负责：
1. 接收 LLM 语义分析结果
2. 结合预处理的 interaction_score
3. 计算最终权重和店铺得分
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from xhs_food.services.preprocessing import ProcessedComment


@dataclass
class CommentAnalysis:
    """LLM 返回的评论语义分析结果."""
    
    id: str
    identity: str = "none"  # strong / medium / none
    sentiment: str = "neutral"  # positive / negative / neutral
    is_correction: bool = False
    mentioned_shops: List[str] = field(default_factory=list)


@dataclass
class CommentScore:
    """单条评论的最终得分."""
    
    comment_id: str
    text: str
    final_score: float
    interaction_score: float
    identity_coefficient: float
    content_coefficient: float
    mentioned_shops: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "final_score": round(self.final_score, 2),
            "breakdown": f"{self.interaction_score}×{self.identity_coefficient}×{self.content_coefficient}",
            "mentioned_shops": self.mentioned_shops,
        }


@dataclass
class ShopScore:
    """店铺最终得分."""
    
    name: str
    total_score: float
    mention_count: int
    positive_count: int
    negative_count: int
    local_signal_count: int
    correction_count: int
    key_comments: List[CommentScore] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total_score": round(self.total_score, 2),
            "mention_count": self.mention_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "local_signal_count": self.local_signal_count,
            "correction_count": self.correction_count,
            "key_comments": [c.to_dict() for c in self.key_comments[:5]],
            "reasons": self.reasons,
        }


# =============================================================================
# 系数映射常量
# =============================================================================

IDENTITY_COEFFICIENTS = {
    "strong": 3.0,
    "medium": 2.0,
    "none": 1.0,
}

# content_coefficient: is_correction 优先，否则按 sentiment
def get_content_coefficient(is_correction: bool, sentiment: str) -> float:
    """
    计算内容系数.
    
    规则:
    - is_correction = True: 3.0
    - sentiment = negative: 1.5 (负面评价往往更有价值)
    - sentiment = positive: 1.0
    - sentiment = neutral: 1.0
    """
    if is_correction:
        return 3.0
    
    if sentiment == "negative":
        return 1.5
    
    return 1.0


def get_identity_coefficient(identity: str) -> float:
    """获取身份系数."""
    return IDENTITY_COEFFICIENTS.get(identity, 1.0)


# =============================================================================
# 核心计分逻辑
# =============================================================================

def calculate_comment_score(
    processed: ProcessedComment,
    analysis: CommentAnalysis,
) -> CommentScore:
    """
    计算单条评论的最终得分.
    
    公式: Score = interaction_score * identity_coefficient * content_coefficient
    
    Args:
        processed: 预处理后的评论数据 (含 interaction_score)
        analysis: LLM 分析结果 (含 identity, sentiment, is_correction)
        
    Returns:
        CommentScore: 得分详情
    """
    interaction_score = processed.interaction_score
    identity_coefficient = get_identity_coefficient(analysis.identity)
    content_coefficient = get_content_coefficient(analysis.is_correction, analysis.sentiment)
    
    final_score = interaction_score * identity_coefficient * content_coefficient
    
    return CommentScore(
        comment_id=processed.id,
        text=processed.text,
        final_score=final_score,
        interaction_score=interaction_score,
        identity_coefficient=identity_coefficient,
        content_coefficient=content_coefficient,
        mentioned_shops=analysis.mentioned_shops,
    )


def calculate_shop_scores(
    comment_scores: List[CommentScore],
) -> Dict[str, ShopScore]:
    """
    汇总店铺得分.
    
    Args:
        comment_scores: 所有评论的得分列表
        
    Returns:
        Dict[str, ShopScore]: 店铺名 -> 得分详情
    """
    shop_data: Dict[str, ShopScore] = {}
    
    for cs in comment_scores:
        for shop_name in cs.mentioned_shops:
            if not shop_name:
                continue
                
            if shop_name not in shop_data:
                shop_data[shop_name] = ShopScore(
                    name=shop_name,
                    total_score=0.0,
                    mention_count=0,
                    positive_count=0,
                    negative_count=0,
                    local_signal_count=0,
                    correction_count=0,
                    key_comments=[],
                    reasons=[],
                )
            
            shop = shop_data[shop_name]
            shop.total_score += cs.final_score
            shop.mention_count += 1
            shop.key_comments.append(cs)
            
            # 统计信号
            if cs.identity_coefficient >= 2.0:
                shop.local_signal_count += 1
            if cs.content_coefficient >= 3.0:
                shop.correction_count += 1
    
    # 按总分排序 key_comments
    for shop in shop_data.values():
        shop.key_comments.sort(key=lambda c: c.final_score, reverse=True)
        
        # 生成推荐理由
        if shop.local_signal_count > 0:
            shop.reasons.append(f"{shop.local_signal_count}条本地人评论")
        if shop.correction_count > 0:
            shop.reasons.append(f"{shop.correction_count}条纠正性评论")
        if shop.mention_count >= 2:
            shop.reasons.append(f"在{shop.mention_count}条评论中被提及")
    
    return shop_data


def calculate_scores(
    llm_results: List[Dict[str, Any]],
    preprocessed_data: List[ProcessedComment],
) -> Dict[str, ShopScore]:
    """
    主入口：结合 LLM 结果和预处理数据计算最终得分.
    
    Args:
        llm_results: LLM 返回的分析结果列表，每项包含:
            - id: 评论 ID
            - identity: strong/medium/none
            - sentiment: positive/negative/neutral
            - is_correction: bool
            - mentioned_shops: List[str]
        preprocessed_data: 预处理后的评论列表
        
    Returns:
        Dict[str, ShopScore]: 店铺得分映射
    """
    # 构建 ID -> ProcessedComment 映射
    processed_map = {pc.id: pc for pc in preprocessed_data}
    
    # 转换 LLM 结果为 CommentAnalysis
    analyses = []
    for r in llm_results:
        analyses.append(CommentAnalysis(
            id=r.get("id", ""),
            identity=r.get("identity", "none"),
            sentiment=r.get("sentiment", "neutral"),
            is_correction=r.get("is_correction", False),
            mentioned_shops=r.get("mentioned_shops", []),
        ))
    
    # 计算每条评论的得分
    comment_scores = []
    for analysis in analyses:
        processed = processed_map.get(analysis.id)
        if processed:
            score = calculate_comment_score(processed, analysis)
            comment_scores.append(score)
    
    # 汇总店铺得分
    return calculate_shop_scores(comment_scores)


def get_top_shops(
    shop_scores: Dict[str, ShopScore],
    min_mentions: int = 1,
    top_n: int = 10,
) -> List[ShopScore]:
    """
    获取排名靠前的店铺.
    
    Args:
        shop_scores: 店铺得分映射
        min_mentions: 最少提及次数
        top_n: 返回数量
        
    Returns:
        List[ShopScore]: 排序后的店铺列表
    """
    filtered = [
        shop for shop in shop_scores.values()
        if shop.mention_count >= min_mentions
    ]
    
    # 按总分排序
    filtered.sort(key=lambda s: s.total_score, reverse=True)
    
    return filtered[:top_n]
