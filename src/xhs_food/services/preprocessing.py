"""Compatibility facade for Food comment preprocessing."""

from xhs_food.domain_packs.food.preprocessing import (
    ProcessedComment,
    calculate_interaction_score,
    extract_likes_from_text,
    format_comments_for_llm,
    preprocess_comments,
)

__all__ = [
    "ProcessedComment",
    "calculate_interaction_score",
    "extract_likes_from_text",
    "format_comments_for_llm",
    "preprocess_comments",
]
