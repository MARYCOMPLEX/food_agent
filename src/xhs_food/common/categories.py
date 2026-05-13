# -*- coding: utf-8 -*-
"""Food category mapping (single source of truth).

Replaces duplicated CATEGORY_MAPPING definitions previously found in
``agents/intent_parser.py`` and ``orchestrator/follow_up.py``.
"""
from __future__ import annotations

from typing import Dict, List

CATEGORY_MAPPING: Dict[str, List[str]] = {
    "炒菜": ["炒菜", "川菜", "家常菜", "江湖菜", "小炒", "中餐", "粤菜", "湘菜"],
    "川菜": ["川菜", "炒菜", "家常菜", "江湖菜"],
    "火锅": ["火锅", "串串", "冒菜", "麻辣烫"],
    "烧烤": ["烧烤", "烤肉", "撸串", "烤鱼"],
    "面食": ["面", "抄手", "馄饨", "饺子", "面条", "粉"],
    "小吃": ["小吃", "小吃店", "路边摊", "点心"],
    "甜品": ["甜品", "甜点", "蛋糕", "奶茶"],
    "鱼": ["鱼", "鱼庄", "烤鱼", "冷锅鱼", "花椒鱼"],
}

_CLEAN_SUFFIXES = ("类", "的", "点")
_FILLER_WORDS = ("我想吃", "想吃点", "来点", "换成", "只要", "只看", "有没有")


def normalize_category(raw: str) -> str:
    """Strip filler words and trailing classifiers from a user-supplied category."""
    if not raw:
        return ""
    cleaned = raw.strip()
    for word in _FILLER_WORDS:
        cleaned = cleaned.replace(word, "")
    while cleaned and cleaned.endswith(_CLEAN_SUFFIXES):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def expand_category_keywords(category: str) -> List[str]:
    """Expand a category into the synonyms used for matching."""
    if not category:
        return []
    expanded: List[str] = [category]
    for key, synonyms in CATEGORY_MAPPING.items():
        if category in key or key in category:
            expanded.extend(synonyms)
    return list(dict.fromkeys(expanded))
