"""Food Domain output to frozen legacy DTO compatibility mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import cast

from xhs_food.contracts import DomainPackManifest
from xhs_food.contracts.base import JsonValue
from xhs_food.domain_packs.food.resources import load_food_manifest
from xhs_food.schemas import RestaurantRecommendation, XHSFoodResponse


class LegacyFoodOutputAdapter:
    """Validate Pack output before projecting the existing client DTO."""

    def __init__(
        self,
        manifest: DomainPackManifest | None = None,
        *,
        validator: Callable[[JsonValue], None] | None = None,
    ) -> None:
        self._manifest = manifest if manifest is not None else load_food_manifest()
        self._validator = validator or self._manifest.validate_final_output

    def response(
        self,
        *,
        status: str = "ok",
        recommendations: Sequence[RestaurantRecommendation] = (),
        filtered_count: int = 0,
        clarify_questions: Sequence[str] = (),
        error_message: str | None = None,
        summary: str = "",
    ) -> XHSFoodResponse:
        self._validator(self._domain_projection(recommendations, summary=summary))
        return self._response(
            status=status,
            recommendations=recommendations,
            filtered_count=filtered_count,
            clarify_questions=clarify_questions,
            error_message=error_message,
            summary=summary,
        )

    @staticmethod
    def _response(
        *,
        status: str,
        recommendations: Sequence[RestaurantRecommendation],
        filtered_count: int,
        clarify_questions: Sequence[str],
        error_message: str | None,
        summary: str,
    ) -> XHSFoodResponse:
        return XHSFoodResponse(
            status=status,
            recommendations=list(recommendations),
            filtered_count=filtered_count,
            clarify_questions=list(clarify_questions),
            error_message=error_message,
            summary=summary,
        )

    def from_domain_output(self, value: JsonValue) -> XHSFoodResponse:
        self._validator(value)
        if not isinstance(value, Mapping):
            raise ValueError("Food final output must be an object")
        raw_recommendations = value["recommendations"]
        if not isinstance(raw_recommendations, (list, tuple)):
            raise ValueError("Food final output recommendations must be an array")
        recommendations = [self._recommendation(item) for item in raw_recommendations]
        return self._response(
            status="ok",
            recommendations=recommendations,
            filtered_count=0,
            clarify_questions=(),
            error_message=None,
            summary=cast(str, value["summary"]),
        )

    def to_frontend(self, response: XHSFoodResponse) -> dict[str, object]:
        """Preserve the frozen renderer casing and null/default behavior."""

        return cast(dict[str, object], response.to_dict())

    @staticmethod
    def _recommendation(value: object) -> RestaurantRecommendation:
        if not isinstance(value, Mapping):
            raise ValueError("Food final output recommendation must be an object")
        return RestaurantRecommendation(
            name=cast(str, value["entityId"]),
            confidence=float(cast(float, value["publicScore"])),
            source_notes=list(cast(Sequence[str], value["explanationRefs"])),
        )

    @staticmethod
    def _domain_projection(
        recommendations: Sequence[RestaurantRecommendation],
        *,
        summary: str,
    ) -> JsonValue:
        return {
            "schemaVersion": "food-agent-final-output/v1",
            "summary": summary,
            "recommendations": [
                {
                    "entityId": recommendation.name,
                    "publicScore": recommendation.confidence,
                    "explanationRefs": list(recommendation.source_notes),
                }
                for recommendation in recommendations
            ],
        }


__all__ = ["LegacyFoodOutputAdapter"]
