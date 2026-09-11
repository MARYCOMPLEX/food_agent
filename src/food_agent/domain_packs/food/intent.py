"""Food intent schema owned by the Food Domain Pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FoodSearchIntent:
    """Parsed Food search intent kept wire-compatible with the legacy DTO."""

    location: str
    food_type: str | None = None
    requirements: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    time_filter: str | None = None
    price_range: str | None = None

    def to_search_queries(self) -> list[str]:
        queries = []
        base = self.location
        if self.food_type:
            base = f"{self.location} {self.food_type}"
        queries.append(base)
        for requirement in self.requirements[:2]:
            queries.append(f"{base} {requirement}")
        return queries

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "food_type": self.food_type,
            "requirements": self.requirements,
            "exclude_keywords": self.exclude_keywords,
            "time_filter": self.time_filter,
            "price_range": self.price_range,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FoodSearchIntent:
        return cls(
            location=data.get("location", ""),
            food_type=data.get("food_type"),
            requirements=data.get("requirements", []),
            exclude_keywords=data.get("exclude_keywords", []),
            time_filter=data.get("time_filter"),
            price_range=data.get("price_range"),
        )


__all__ = ["FoodSearchIntent"]
