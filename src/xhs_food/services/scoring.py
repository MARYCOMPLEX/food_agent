"""Compatibility facade for the Food Pack's deterministic scoring policy."""

from xhs_food.domain_packs.food.scoring import (
    IDENTITY_COEFFICIENTS,
    CommentAnalysis,
    CommentScore,
    ShopScore,
    calculate_comment_score,
    calculate_scores,
    calculate_shop_scores,
    get_content_coefficient,
    get_identity_coefficient,
    get_top_shops,
)

__all__ = [
    "IDENTITY_COEFFICIENTS",
    "CommentAnalysis",
    "CommentScore",
    "ShopScore",
    "calculate_comment_score",
    "calculate_scores",
    "calculate_shop_scores",
    "get_content_coefficient",
    "get_identity_coefficient",
    "get_top_shops",
]
