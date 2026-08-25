"""B5 Travel Pack registration, tool, output, and rollback contracts."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.composition.adapters import TravelOutputAdapter, build_travel_tool_gateway
from xhs_food.composition.domain_packs import DomainPackRegistry
from xhs_food.contracts import ToolCall
from xhs_food.domain_packs.food import create_food_pack, load_food_contract_resources
from xhs_food.domain_packs.travel import (
    create_travel_pack,
    load_travel_contract_resources,
)


class _Lookup:
    async def lookup(self, **_: Any) -> dict[str, Any]:
        return {"pois": [{"id": "poi-1", "name": "博物馆", "address": "市中心"}]}


def _registry() -> DomainPackRegistry:
    return DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={"travel.poi.lookup": "1.0.0"},
        source_capabilities={"place.lookup": "1.0.0"},
    )


@pytest.mark.unit
def test_travel_manifest_registers_with_shared_core_and_explicit_semantics() -> None:
    manifest, schemas = load_travel_contract_resources()
    assert manifest.domain_id == "travel"
    assert {"entities", "relations", "evidence_types", "feature_set", "personalization_slots"} == set(
        type(manifest.domain_schemas).model_fields
    )
    registered = _registry().register_or_raise(manifest, create_travel_pack(), schemas)
    assert registered.contract_pin.domain_id == "travel"
    assert registered.contract_pin.final_output_schema_id == "urn:food-agent:travel:final-output:v1"
    assert manifest.domain_sources[0].capability == "place.lookup"


@pytest.mark.unit
def test_travel_output_is_not_a_restaurant_projection() -> None:
    pack = create_travel_pack()
    output = pack.build_final_output(
        {
            "public_scores": {
                "scores": [
                    {
                        "entity_id": "itinerary-1",
                        "score": 0.8,
                        "stops": ["博物馆", "老街"],
                        "season": "春秋",
                        "ticket": "免费",
                        "crowding": "低",
                        "duration_minutes": 180,
                        "suitable_for": ["family"],
                    }
                ]
            }
        }
    )
    assert "itineraries" in output
    assert "recommendations" not in output
    assert TravelOutputAdapter().from_domain_output(output)["itineraries"][0]["stops"] == ["博物馆", "老街"]


@pytest.mark.unit
async def test_travel_allowed_tool_uses_shared_place_port_and_schema_boundary() -> None:
    gateway, provider = build_travel_tool_gateway(_Lookup())
    result = await gateway.execute(
        ToolCall(
            call_id="travel-tool-1",
            task_id="travel-task-1",
            tool_name="travel.poi.lookup",
            arguments={"schemaVersion": "travel.poi.lookup/input/v1", "query": "景点", "geo": "CN-SC"},
        )
    )
    assert result.success is True
    assert isinstance(result.output, dict)
    assert result.output["places"][0]["name"] == "博物馆"
    assert provider.source_capability == "place.lookup"


@pytest.mark.unit
def test_travel_unregister_does_not_remove_food_or_shared_core() -> None:
    registry = DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={"travel.poi.lookup": "1.0.0"},
        source_capabilities={"place.lookup": "1.0.0"},
    )
    travel_manifest, travel_schemas = load_travel_contract_resources()
    registered = registry.register_or_raise(travel_manifest, create_travel_pack(), travel_schemas)
    removed = registry.unregister("travel", "1.0.0")
    assert removed is registered
    food_manifest, food_schemas = load_food_contract_resources()
    food_registry = DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={"place.lookup": "1.0.0", "evidence.search_reviews": "1.0.0"},
        source_capabilities={"place.lookup": "1.0.0", "reviews.search": "1.0.0"},
    )
    assert food_registry.register_candidate(food_manifest, create_food_pack(), food_schemas).accepted


@pytest.mark.unit
async def test_travel_tool_provider_failure_isolated_from_pack_contract() -> None:
    class Broken:
        async def lookup(self, **_: Any) -> None:
            return None

    gateway, _ = build_travel_tool_gateway(Broken())
    result = await gateway.execute(
        ToolCall(
            call_id="travel-tool-2",
            task_id="travel-task-2",
            tool_name="travel.poi.lookup",
            arguments={"schemaVersion": "travel.poi.lookup/input/v1", "query": "景点", "geo": "CN-SC"},
        )
    )
    assert result.success is False
    assert result.error is not None


@pytest.mark.unit
async def test_travel_tool_boundary_rejects_malformed_and_unauthorized_calls() -> None:
    gateway, provider = build_travel_tool_gateway(_Lookup())
    malformed = await gateway.execute(
        ToolCall(
            call_id="travel-tool-3",
            task_id="travel-task-3",
            tool_name="travel.poi.lookup",
            arguments={"schemaVersion": "wrong/v1", "query": "景点", "geo": "CN-SC"},
        )
    )
    assert malformed.success is False
    assert malformed.error is not None
    assert provider.name == "travel.poi.lookup"

    unauthorized = await gateway.execute(
        ToolCall(
            call_id="travel-tool-4",
            task_id="travel-task-4",
            tool_name="place.lookup",
            arguments={"schemaVersion": "travel.poi.lookup/input/v1", "query": "景点", "geo": "CN-SC"},
        )
    )
    assert unauthorized.success is False
    assert unauthorized.error is not None


@pytest.mark.unit
def test_travel_registry_rejects_incomplete_or_throwing_pack_without_publication() -> None:
    manifest, schemas = load_travel_contract_resources()
    registry = _registry()
    incomplete = manifest.model_copy(update={"allowed_tools": ()})
    rejected = registry.register_candidate(incomplete, create_travel_pack(), schemas)
    assert rejected.activation_allowed is False
    assert registry.publish_snapshot() == {}

    class BrokenTravelPack(type(create_travel_pack())):
        def describe(self) -> Any:
            raise RuntimeError("travel fixture initialization failed")

    broken = registry.register_candidate(manifest, BrokenTravelPack(), schemas)
    assert broken.activation_allowed is False
    assert registry.publish_snapshot() == {}


@pytest.mark.unit
def test_travel_recovery_output_schema_version_is_pinned() -> None:
    output = create_travel_pack().build_final_output({"public_scores": {"scores": []}})
    assert output["schemaVersion"] == "travel-agent-final-output/v1"
