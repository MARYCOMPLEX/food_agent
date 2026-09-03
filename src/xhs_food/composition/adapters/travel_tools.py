"""Composition-owned Travel allowed-tool adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from xhs_food.contracts import PlaceLookupPort
from xhs_food.domain_packs.travel import load_travel_manifest
from xhs_food.gateways import ProviderResult, SchemaToolGateway, ToolRegistration


class TravelPlaceLookupProvider:
    name = "travel.poi.lookup"
    tool_version = "1.0.0"
    source_capability = "place.lookup"
    source_version = "1.0.0"

    def __init__(self, lookup: PlaceLookupPort) -> None:
        self._lookup = lookup

    async def execute(self, **arguments: Any) -> ProviderResult:
        raw = await self._lookup.lookup(
            keywords=cast(str, arguments["query"]), city=cast(str, arguments["geo"]), types="110000"
        )
        if raw is None or not isinstance(raw.get("pois"), list):
            return ProviderResult(False, error_code="DEPENDENCY_UNAVAILABLE")
        places: list[dict[str, str]] = []
        for place in raw["pois"]:
            if not isinstance(place, Mapping):
                return ProviderResult(False, error_code="MALFORMED_RESPONSE")
            source_id = place.get("poi_id") or place.get("id")
            name = place.get("name")
            if not isinstance(source_id, (str, int)) or not isinstance(name, str) or not name:
                return ProviderResult(False, error_code="MALFORMED_RESPONSE")
            places.append(
                {
                    "sourceId": str(source_id),
                    "name": name,
                    "address": str(place.get("address") or ""),
                }
            )
        return ProviderResult(
            True, data={"schemaVersion": "travel.poi.lookup/output/v1", "places": places}
        )

    async def health_check(self) -> bool:
        check = getattr(self._lookup, "health_check", None)
        return bool(await check()) if callable(check) else True


def build_travel_tool_gateway(
    lookup: PlaceLookupPort,
) -> tuple[SchemaToolGateway, TravelPlaceLookupProvider]:
    manifest = load_travel_manifest()
    contract = next(
        tool for tool in manifest.allowed_tools if tool.tool_id == TravelPlaceLookupProvider.name
    )
    provider = TravelPlaceLookupProvider(lookup)
    return SchemaToolGateway(
        (ToolRegistration(contract=contract, provider=provider),),
        allowed_tools=frozenset({contract.tool_id}),
    ), provider


__all__ = ["TravelPlaceLookupProvider", "build_travel_tool_gateway"]
