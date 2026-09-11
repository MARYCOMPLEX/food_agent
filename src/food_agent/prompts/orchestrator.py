"""Compatibility facade for Food orchestration prompts."""

from food_agent.domain_packs.food.prompts.orchestrator import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    REPORT_GENERATION_PROMPT,
)

__all__ = ["ORCHESTRATOR_SYSTEM_PROMPT", "REPORT_GENERATION_PROMPT"]
