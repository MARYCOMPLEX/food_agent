"""Deterministic Food research workflow policy."""

from __future__ import annotations

from .intent import FoodSearchIntent


class FoodWorkflowPolicy:
    """Own bounded, information-seeking query planning for comment discovery."""

    version = "research-standard/v1"
    stopping_profile = "food-stopping/v1"

    def plan_queries(self, intent: FoodSearchIntent, *, max_queries: int = 3) -> tuple[str, ...]:
        base = self._base(intent)
        candidates = [base]
        if intent.requirements:
            candidates.append(f"{base} {' '.join(intent.requirements[:2])}")
        candidates.append(f"{base} 争议 避雷")
        return tuple(dict.fromkeys(item for item in candidates if item))[: max(1, max_queries)]

    @staticmethod
    def _base(intent: FoodSearchIntent) -> str:
        return " ".join(
            item for item in (intent.location.strip(), (intent.food_type or "美食").strip()) if item
        )


__all__ = ["FoodWorkflowPolicy"]
