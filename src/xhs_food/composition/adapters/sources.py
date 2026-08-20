"""Concrete legacy source factories owned by the Composition Root."""

from __future__ import annotations

from xhs_food.di.factories import get_xhs_tool_registry
from xhs_food.gateways import (
    AmapPlaceSourceConnector,
    PlaceLookupToolAdapter,
    XHSSourceConnector,
)
from xhs_food.spider.apis.amap_api import AmapAPI, get_amap_api


def build_xhs_source_connector() -> XHSSourceConnector:
    registry = get_xhs_tool_registry()
    return XHSSourceConnector(
        search_provider=registry.get_required("xhs_search"),
        note_provider=registry.get_required("xhs_note"),
        batch_provider=registry.get_required("xhs_batch"),
    )


def build_place_source_connector(
    client: AmapAPI | None = None,
) -> AmapPlaceSourceConnector:
    return AmapPlaceSourceConnector(client or get_amap_api())


def build_place_tool(client: AmapAPI | None = None) -> PlaceLookupToolAdapter:
    return PlaceLookupToolAdapter(client or get_amap_api())


__all__ = [
    "build_place_source_connector",
    "build_place_tool",
    "build_xhs_source_connector",
]
