"""Backwards-compat shim.

Contents moved to per-agent files during the prompt split:
- :mod:`xhs_food.prompts.intent` (INTENT_PARSER_*)
- :mod:`xhs_food.prompts.analyzer` (ANALYZER_*)
- :mod:`xhs_food.prompts.orchestrator` (ORCHESTRATOR_SYSTEM_PROMPT,
  REPORT_GENERATION_PROMPT)

Re-exported here so any `from xhs_food.prompts.agent_prompts import ...` still
resolves.
"""
from __future__ import annotations

from .analyzer import (
    ANALYZER_INSTRUCTION_ZH,
    ANALYZER_SYSTEM_PROMPT_ZH,
    ANALYZER_USER_PROMPT_TEMPLATE,
)
from .intent import INTENT_PARSER_INSTRUCTION_ZH, INTENT_PARSER_SYSTEM_PROMPT_ZH
from .orchestrator import ORCHESTRATOR_SYSTEM_PROMPT, REPORT_GENERATION_PROMPT

__all__ = [
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "INTENT_PARSER_SYSTEM_PROMPT_ZH",
    "INTENT_PARSER_INSTRUCTION_ZH",
    "ANALYZER_SYSTEM_PROMPT_ZH",
    "ANALYZER_INSTRUCTION_ZH",
    "ANALYZER_USER_PROMPT_TEMPLATE",
    "REPORT_GENERATION_PROMPT",
]
