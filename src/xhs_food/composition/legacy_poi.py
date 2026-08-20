"""Narrow compatibility resolver for the legacy zero-argument POI facade."""

from __future__ import annotations

from xhs_food.contracts import PlaceCacheRepositoryPort, PlaceLookupPort


def build_legacy_poi_ports() -> tuple[PlaceLookupPort, PlaceCacheRepositoryPort]:
    """Return project-owned ports while preserving legacy lazy construction."""

    from xhs_food.composition.adapters import (
        LegacyPlaceCacheRepositoryAdapter,
        build_place_tool,
    )
    from xhs_food.services import get_user_storage_service

    return (
        build_place_tool(),
        LegacyPlaceCacheRepositoryAdapter(get_user_storage_service),
    )


__all__ = ["build_legacy_poi_ports"]
