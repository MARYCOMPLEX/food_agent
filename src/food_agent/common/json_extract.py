# -*- coding: utf-8 -*-
"""Robust JSON extraction from LLM text output.

LLMs frequently wrap JSON in markdown code fences or prose. This helper
centralizes the parsing strategies previously duplicated across
``intent_parser`` and ``analyzer``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_PATTERNS = (
    re.compile(r"```json\s*(.*?)\s*```", re.DOTALL),
    re.compile(r"```\s*(.*?)\s*```", re.DOTALL),
)
_BRACE_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Optional[Any]:
    """Try increasingly permissive strategies to parse JSON from ``text``.

    Returns ``None`` if no valid JSON object can be extracted.
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for pattern in _FENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    match = _BRACE_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
