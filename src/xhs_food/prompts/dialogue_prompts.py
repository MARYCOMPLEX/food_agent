"""Backwards-compat shim.

Contents moved to :mod:`xhs_food.prompts.analyzer` (COMMENT_ANALYSIS_*) and
:mod:`xhs_food.prompts.follow_up` (FOLLOW_UP_PROCESSING_PROMPT) during the
per-agent prompt split. Re-exported here to keep `from
xhs_food.prompts.dialogue_prompts import ...` working.
"""
from __future__ import annotations

from .analyzer import COMMENT_ANALYSIS_SYSTEM_PROMPT, COMMENT_ANALYSIS_USER_PROMPT
from .follow_up import FOLLOW_UP_PROCESSING_PROMPT

__all__ = [
    "COMMENT_ANALYSIS_SYSTEM_PROMPT",
    "COMMENT_ANALYSIS_USER_PROMPT",
    "FOLLOW_UP_PROCESSING_PROMPT",
]
