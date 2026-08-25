"""Travel output adapter that never projects itineraries as Restaurants."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from xhs_food.contracts.base import JsonValue
from xhs_food.domain_packs.travel import load_travel_manifest


class TravelOutputAdapter:
    """Validate and return the domain-neutral Travel result shape."""

    def __init__(self, validator: Any | None = None) -> None:
        self._validator = validator or load_travel_manifest().validate_final_output

    def from_domain_output(self, value: JsonValue) -> dict[str, Any]:
        self._validator(value)
        if not isinstance(value, Mapping):
            raise ValueError("Travel final output must be an object")
        itineraries = value.get("itineraries")
        if not isinstance(itineraries, list):
            raise ValueError("Travel final output itineraries must be an array")
        return cast(dict[str, Any], dict(value))


__all__ = ["TravelOutputAdapter"]
