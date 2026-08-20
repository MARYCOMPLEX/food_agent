"""Pure Food public decision policies with structural compatibility inputs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .scoring import ShopScore


class _WanghongLike(Protocol):
    score: object
    reasons: list[str]
    has_local_mentions: bool


class RecommendationLike(Protocol):
    name: str
    features: list[str]
    source_notes: list[str]
    confidence: float
    wanghong_analysis: _WanghongLike | None
    is_recommended: bool
    filter_reason: str | None


@dataclass(frozen=True, slots=True)
class WanghongDecision:
    score: str
    confidence: float
    reasons: tuple[str, ...]
    has_local_mentions: bool
    is_recommended: bool
    filter_reason: str | None


class FoodDecisionPolicy:
    """Own deterministic Food scoring projection, merge, filtering, and rank."""

    version = "food.public-score@1.0.0"

    def assess_shop(
        self,
        shop: ShopScore,
        exclude_keywords: Sequence[str],
    ) -> WanghongDecision:
        should_exclude = any(keyword.lower() in shop.name.lower() for keyword in exclude_keywords)
        if shop.local_signal_count >= 2 and shop.total_score > 10:
            score, confidence = "definitely_local", 0.9
        elif shop.local_signal_count >= 1 and shop.total_score > 5:
            score, confidence = "likely_local", 0.75
        elif shop.negative_count > shop.positive_count:
            score, confidence = "likely_wanghong", 0.6
        else:
            score, confidence = "unknown", 0.5

        is_recommended = not should_exclude and score not in {
            "definitely_wanghong",
            "likely_wanghong",
        }
        filter_reason = None
        if should_exclude:
            filter_reason = "匹配用户排除关键词"
        elif not is_recommended:
            filter_reason = f"判定为网红店: {', '.join(shop.reasons[:2])}"
        return WanghongDecision(
            score=score,
            confidence=confidence,
            reasons=tuple(shop.reasons),
            has_local_mentions=shop.local_signal_count > 0,
            is_recommended=is_recommended,
            filter_reason=filter_reason,
        )

    def merge_and_validate(self, restaurants: Sequence[Any]) -> list[Any]:
        merged: dict[str, Any] = {}
        for restaurant in restaurants:
            name = restaurant.name.strip()
            if not name or name == "未知":
                continue
            normalized_name = name.replace(" ", "").replace("\u3000", "")
            if normalized_name in merged:
                existing = merged[normalized_name]
                existing.source_notes.extend(restaurant.source_notes)
                existing.features.extend(
                    feature for feature in restaurant.features if feature not in existing.features
                )
                if restaurant.confidence > existing.confidence:
                    existing.confidence = restaurant.confidence
                    existing.wanghong_analysis = restaurant.wanghong_analysis
            else:
                merged[normalized_name] = restaurant

        for restaurant in merged.values():
            source_count = len(set(restaurant.source_notes))
            analysis = restaurant.wanghong_analysis
            if analysis is None:
                continue
            score = getattr(analysis.score, "value", analysis.score)
            if score in {"definitely_wanghong", "likely_wanghong"}:
                restaurant.is_recommended = False
                restaurant.filter_reason = f"判定为网红店: {', '.join(analysis.reasons[:2])}"
            elif source_count < 2:
                restaurant.confidence *= 0.7
            elif source_count >= 3 and analysis.has_local_mentions:
                restaurant.confidence = min(restaurant.confidence * 1.2, 1.0)
        return list(merged.values())

    def rank_and_filter(
        self,
        restaurants: Sequence[Any],
        excluded_shops: Sequence[str],
    ) -> tuple[list[Any], int]:
        recommended: list[Any] = []
        filtered_count = 0
        for restaurant in restaurants:
            is_excluded = any(
                excluded in restaurant.name or restaurant.name in excluded
                for excluded in excluded_shops
            )
            if restaurant.is_recommended and not is_excluded:
                recommended.append(restaurant)
            else:
                filtered_count += 1
        recommended.sort(
            key=lambda item: (item.confidence, len(item.source_notes)),
            reverse=True,
        )
        return recommended, filtered_count


__all__ = [
    "FoodDecisionPolicy",
    "RecommendationLike",
    "WanghongDecision",
]
