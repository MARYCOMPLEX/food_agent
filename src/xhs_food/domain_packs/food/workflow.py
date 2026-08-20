"""Deterministic Food research workflow policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .intent import FoodSearchIntent


class FoodWorkflowPolicy:
    """Own Food keyword generation and legacy-compatible stopping rules."""

    version = "research-standard/v1"
    stopping_profile = "food-stopping/v1"

    def phase1_keywords(self, intent: FoodSearchIntent) -> list[str]:
        base = intent.location
        food = intent.food_type or "美食"
        keywords = [
            f"{base} 本地人 老店",
            f"{base} {food} 地道",
            f"{base} 本地人 推荐",
        ]
        for requirement in intent.requirements[:2]:
            keywords.append(f"{base} {requirement}")
        return keywords

    def phase2_keywords(self, intent: FoodSearchIntent) -> list[str]:
        base = intent.location
        return [
            f"{base} 苍蝇馆子 好吃",
            f"{base} 小馆子 本地人",
            f"{base} 巷子里 老店",
            f"{base} 不起眼 好吃",
        ]

    def phase4_keywords(self, intent: FoodSearchIntent) -> list[str]:
        if not intent.food_type or intent.food_type == "美食":
            return []
        return [
            f"{intent.location} {intent.food_type} 老店",
            f"{intent.location} {intent.food_type} 本地人",
        ]

    def expand_keywords(self, intent: FoodSearchIntent) -> list[str]:
        return [
            f"{intent.location} 隐藏美食",
            f"{intent.location} 老字号",
            f"{intent.location} 街边小店",
        ]

    def should_stop(self, note_count: int, *, deep_search: bool, fast_limit: int) -> bool:
        return not deep_search and note_count >= fast_limit

    def extract_shop_names(self, notes: Sequence[Mapping[str, object]]) -> list[str]:
        names: list[str] = []
        for note in notes:
            title = note.get("title") or ""
            if not isinstance(title, str) or not title:
                continue
            if "店" not in title and "馆" not in title:
                continue
            words = title.replace("｜", " ").replace("|", " ").split()
            for word in words:
                if ("店" in word or "馆" in word) and 2 <= len(word) <= 10 and word not in names:
                    names.append(word)
        return names[:6]


__all__ = ["FoodWorkflowPolicy"]
