"""POI enrichment consumes only the async Place lookup port."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_food import services as services_module
from xhs_food.agents import poi_enricher as poi_module
from xhs_food.agents.poi_enricher import POIEnricherAgent
from xhs_food.composition import adapters as composition_adapters
from xhs_food.composition import build_legacy_composition_root
from xhs_food.composition import legacy_poi as legacy_poi_module
from xhs_food.contracts import PlaceCacheRepositoryPort, PlaceLookupPort
from xhs_food.gateways import PlaceLookupToolAdapter
from xhs_food.schemas import RestaurantRecommendation

pytestmark = pytest.mark.unit


class _AsyncPlaceLookup:
    def __init__(
        self,
        result: dict[str, Any] | None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def lookup(
        self, *, keywords: str, city: str = "", types: str = "050000"
    ) -> dict[str, Any] | None:
        self.calls.append({"keywords": keywords, "city": city, "types": types})
        if self.error is not None:
            raise self.error
        return self.result


class _LegacyAmapFixture:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {"pois": []}
        self.calls: list[dict[str, str]] = []

    def search_poi(self, keywords: str, city: str = "", types: str = "050000") -> dict[str, Any]:
        self.calls.append({"keywords": keywords, "city": city, "types": types})
        return self.result


class _CachePort:
    def __init__(self, storage: Any | None = None) -> None:
        self.storage = storage

    async def get_cached_place_by_name(self, name: str) -> dict[str, Any] | None:
        if self.storage is None:
            return None
        value = await self.storage.get_cached_restaurant_by_name(name)
        return value if isinstance(value, dict) else None


def _recommendation() -> RestaurantRecommendation:
    return RestaurantRecommendation(
        name="盐帮馆子",
        location="自流井区同兴路",
        features=["本地口味"],
        source_notes=["note-1"],
        confidence=0.8,
    )


async def _cache_miss(_name: str) -> None:
    return None


@pytest.mark.asyncio
async def test_legacy_amap_constructor_injection_preserves_arguments_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _LegacyAmapFixture(
        {
            "pois": [
                {
                    "name": "盐帮馆子",
                    "address": "同兴路 1 号",
                    "location": "104.1,29.3",
                    "tel": "0813-1234567",
                }
            ]
        }
    )
    agent = POIEnricherAgent(amap_api=client)
    monkeypatch.setattr(agent, "_get_cached_poi", _cache_miss)

    enriched = (await agent.enrich([_recommendation()], city="自贡"))[0]

    assert client.calls == [{"keywords": "盐帮馆子", "city": "自贡", "types": "050000"}]
    assert enriched.address == "同兴路 1 号"
    assert enriched.location == "104.1,29.3"
    assert enriched.tel == "0813-1234567"


@pytest.mark.asyncio
async def test_place_tool_adapter_implements_lookup_port_without_leaking_failure_envelope() -> None:
    payload = {"pois": [{"name": "盐帮馆子"}]}
    client = _LegacyAmapFixture(payload)
    adapter = PlaceLookupToolAdapter(client)

    assert isinstance(adapter, PlaceLookupPort)
    assert await adapter.lookup(keywords="盐帮馆子", city="自贡", types="050000") == payload
    assert client.calls == [{"keywords": "盐帮馆子", "city": "自贡", "types": "050000"}]
    failed = PlaceLookupToolAdapter(_LegacyAmapFixture({"error": "AMAP_UNAVAILABLE"}))
    assert await failed.lookup(keywords="盐帮馆子", city="自贡") is None


@pytest.mark.asyncio
async def test_zero_argument_compatibility_resolves_owner_ports_without_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _AsyncPlaceLookup({"pois": [{"name": "盐帮馆子", "address": "同兴路 1 号"}]})
    monkeypatch.setattr(poi_module, "_place_lookup_factory", None)
    monkeypatch.setattr(poi_module, "_place_cache_factory", None)
    monkeypatch.setattr(
        legacy_poi_module,
        "build_legacy_poi_ports",
        lambda: (port, _CachePort()),
    )

    enriched = (await POIEnricherAgent().enrich([_recommendation()], city="自贡"))[0]

    assert enriched.address == "同兴路 1 号"
    assert port.calls == [{"keywords": "盐帮馆子", "city": "自贡", "types": "050000"}]


@pytest.mark.asyncio
async def test_composition_root_rebinds_existing_default_singleton_to_place_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _AsyncPlaceLookup({"pois": []})
    monkeypatch.setattr(poi_module, "_place_lookup_factory", None)
    monkeypatch.setattr(poi_module, "_place_cache_factory", None)
    monkeypatch.setattr(poi_module, "_poi_enricher", None)
    monkeypatch.setattr(composition_adapters, "build_place_tool", lambda: port)

    class Storage:
        async def get_cached_restaurant_by_name(self, name: str) -> dict[str, Any]:
            assert name == "盐帮馆子"
            return {"name": name, "address": "缓存地址"}

    storage = Storage()

    async def get_storage() -> Storage:
        return storage

    monkeypatch.setattr(services_module, "get_user_storage_service", get_storage)
    monkeypatch.setattr(
        legacy_poi_module,
        "build_legacy_poi_ports",
        lambda: (port, _CachePort(storage)),
    )
    existing = poi_module.get_poi_enricher()

    root = build_legacy_composition_root()
    try:
        assert poi_module.get_poi_enricher() is existing
        assert await existing._do_poi_search("盐帮馆子", "自贡") is None
        assert await existing._get_cached_poi("盐帮馆子") == {
            "name": "盐帮馆子",
            "address": "缓存地址",
        }
        cache = await root.resolve("repositories", "place_cache_legacy")
        assert isinstance(cache, PlaceCacheRepositoryPort)
    finally:
        await root.close()

    assert port.calls == [{"keywords": "盐帮馆子", "city": "自贡", "types": "050000"}]


@pytest.mark.asyncio
async def test_place_failure_keeps_basic_projection_and_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommendation = _recommendation()
    failed = POIEnricherAgent(
        amap_api=_AsyncPlaceLookup(None, error=ConnectionError("amap unavailable"))
    )
    monkeypatch.setattr(failed, "_get_cached_poi", _cache_miss)

    enriched = (await failed.enrich([recommendation]))[0]

    assert enriched.name == recommendation.name
    assert enriched.address == recommendation.location
    assert enriched.location is None
    cancelled = POIEnricherAgent(amap_api=_AsyncPlaceLookup(None, error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await cancelled._do_poi_search(recommendation.name, "")
