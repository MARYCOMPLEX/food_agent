"""Compatibility facade for Food search and scoring prompts."""

from xhs_food.domain_packs.food.prompts.strategy import (
    COMMENT_FIRST_SEARCH_STRATEGY,
    COMMENT_WEIGHT_SYSTEM,
    CROSS_VALIDATION_STANDARDS,
)

__all__ = [
    "COMMENT_WEIGHT_SYSTEM",
    "CROSS_VALIDATION_STANDARDS",
    "COMMENT_FIRST_SEARCH_STRATEGY",
]
