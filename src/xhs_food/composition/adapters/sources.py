"""Concrete place-source factories owned by the Composition Root."""

from __future__ import annotations

from xhs_food.gateways import (
    AmapPlaceSourceConnector,
    PlaceLookupToolAdapter,
)
from xhs_food.services.amap_api import AmapAPI, get_amap_api


def build_place_source_connector(
    client: AmapAPI | None = None,
) -> AmapPlaceSourceConnector:
    return AmapPlaceSourceConnector(client or get_amap_api())


def build_place_tool(client: AmapAPI | None = None) -> PlaceLookupToolAdapter:
    return PlaceLookupToolAdapter(client or get_amap_api())


__all__ = [
    "build_place_source_connector",
    "build_place_tool",
]
