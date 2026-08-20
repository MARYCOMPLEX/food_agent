"""S4 registry, tool-boundary, and output-publication contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

import pytest

import xhs_food.composition.domain_packs as domain_pack_composition
from xhs_food.composition import build_legacy_composition_root
from xhs_food.composition.adapters.food_output import LegacyFoodOutputAdapter
from xhs_food.composition.domain_packs import (
    DomainPackActivationError,
    DomainPackRegistry,
    discover_allowlisted_domain_packs,
)
from xhs_food.contracts import (
    DomainRegistrationFailureCode,
    ToolCall,
)
from xhs_food.domain_packs.food import (
    FoodPack,
    create_food_pack,
    load_food_contract_resources,
)
from xhs_food.gateways import (
    ProviderResult,
    SchemaToolGateway,
    ToolRegistration,
)

pytestmark = pytest.mark.unit


def _registry() -> DomainPackRegistry:
    return DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={
            "place.lookup": "1.0.0",
            "evidence.search_reviews": "1.0.0",
        },
        source_capabilities={
            "place.lookup": "1.0.0",
            "reviews.search": "1.0.0",
        },
    )


def test_mapping_manifest_registers_and_returns_the_pinned_pack() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    registry = _registry()

    registered = registry.register_or_raise(
        manifest.model_dump(mode="json", by_alias=True),
        create_food_pack(),
        schema_bundle.model_dump(mode="json", by_alias=True),
    )

    assert registered.manifest.pack_key == ("food", "1.0.0")
    assert registered.contract_pin.domain_id == "food"
    assert registry.get("food", "1.0.0") is registered


def test_rejected_candidate_does_not_publish_or_modify_a_snapshot() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    registry = _registry()
    accepted = registry.register_candidate(manifest, create_food_pack(), schema_bundle)
    assert accepted.activation_allowed is True
    before = registry.publish_snapshot()

    malformed = deepcopy(manifest.model_dump(mode="json", by_alias=True))
    malformed["finalOutputExample"]["recommendations"][0]["publicScore"] = 2
    rejected = registry.register_candidate(malformed, create_food_pack(), schema_bundle)

    assert rejected.activation_allowed is False
    # Duplicate identity is checked before any candidate can replace the
    # already-published version; the malformed candidate remains invisible.
    assert rejected.failure_code is DomainRegistrationFailureCode.DUPLICATE_PACK_VERSION
    assert registry.publish_snapshot() == before
    assert registry.get("food", "1.0.0") is before[("food", "1.0.0")]


def test_pin_unregister_and_restore_keep_task_pin_and_snapshot_isolation() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    registry = _registry()
    registered = registry.register_or_raise(manifest, create_food_pack(), schema_bundle)
    pin = registry.pin("food", "1.0.0")
    published_before_remove = registry.publish_snapshot()

    removed = registry.unregister("food", "1.0.0")
    assert removed is registered
    assert pin == registered.contract_pin
    assert published_before_remove[("food", "1.0.0")] is registered
    with pytest.raises(KeyError, match="unknown Domain Pack"):
        registry.get("food", "1.0.0")

    registry.restore(removed)
    assert registry.get("food", "1.0.0") is registered
    with pytest.raises(ValueError, match="duplicate Domain Pack"):
        registry.restore(removed)


class _BrokenDescribeFoodPack(FoodPack):
    def describe(self) -> Any:
        raise RuntimeError("broken fixture")


def test_restore_revalidates_before_republishing_a_removed_pack() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    registry = _registry()
    registered = registry.register_or_raise(manifest, create_food_pack(), schema_bundle)
    removed = registry.unregister("food", "1.0.0")
    before = registry.publish_snapshot()

    invalid_restore = replace(
        registered,
        implementation=_BrokenDescribeFoodPack(manifest),
    )
    with pytest.raises(DomainPackActivationError):
        registry.restore(invalid_restore)

    assert registry.publish_snapshot() == before
    registry.restore(removed)
    assert registry.get("food", "1.0.0") is registered


class _MalformedFinalOutputFoodPack(FoodPack):
    def build_final_output(self, value: dict[str, Any]) -> Any:
        del value
        return {
            "schemaVersion": "food-agent-final-output/v1",
            "summary": "bad",
            "recommendations": [
                {
                    "entityId": "restaurant-1",
                    "publicScore": 2,
                    "explanationRefs": [],
                }
            ],
        }


def test_registered_pack_validates_final_output_before_publication() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    registered = _registry().register_or_raise(
        manifest,
        _MalformedFinalOutputFoodPack(manifest),
        schema_bundle,
    )

    with pytest.raises(ValueError):
        registered.build_final_output({})


@dataclass
class _EntryPointFixture:
    name: str
    group: str
    value: object
    loads: int = 0

    def load(self) -> object:
        self.loads += 1
        return self.value


def test_entry_point_discovery_loads_only_allowlisted_domain_group_once() -> None:
    allowed = _EntryPointFixture("food", "food_agent.domain_packs", "food-factory")
    duplicate = _EntryPointFixture("food", "food_agent.domain_packs", "duplicate")
    wrong_group = _EntryPointFixture("food", "other.group", "wrong")
    not_allowed = _EntryPointFixture("travel", "food_agent.domain_packs", "travel-factory")

    loaded = discover_allowlisted_domain_packs(
        ("food",),
        entry_points=(wrong_group, not_allowed, allowed, duplicate),
    )

    assert loaded == ("food-factory",)
    assert allowed.loads == 1
    assert duplicate.loads == 0
    assert wrong_group.loads == 0
    assert not_allowed.loads == 0


def test_installed_food_entry_point_resolves_the_pack_factory() -> None:
    loaded = discover_allowlisted_domain_packs(("food",))

    assert loaded == (create_food_pack,)


@pytest.mark.parametrize(
    ("loaded", "message"),
    [
        ((), "exactly one allow-listed factory; found 0"),
        (
            (create_food_pack, create_food_pack),
            "exactly one allow-listed factory; found 2",
        ),
        ((object(),), "entry point must load a callable factory"),
    ],
)
def test_composition_root_rejects_missing_duplicate_or_non_callable_food_entry_point(
    monkeypatch: pytest.MonkeyPatch,
    loaded: tuple[object, ...],
    message: str,
) -> None:
    monkeypatch.setattr(
        domain_pack_composition,
        "discover_allowlisted_domain_packs",
        lambda allow_list: loaded,
    )

    with pytest.raises(RuntimeError, match=message):
        build_legacy_composition_root()


class _ToolProvider:
    def __init__(self, name: str, result: ProviderResult) -> None:
        self.name = name
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self.result

    async def health_check(self) -> bool:
        return True


def _food_gateway(
    *, allowed: frozenset[str] | None = None, result: ProviderResult
) -> tuple[SchemaToolGateway, _ToolProvider]:
    manifest, _ = load_food_contract_resources()
    contract = next(item for item in manifest.allowed_tools if item.tool_id == "place.lookup")
    provider = _ToolProvider(contract.tool_id, result)
    return (
        SchemaToolGateway(
            (ToolRegistration(contract=contract, provider=provider),),
            allowed_tools=allowed,
        ),
        provider,
    )


def _place_call(arguments: dict[str, Any], *, tool_name: str = "place.lookup") -> ToolCall:
    return ToolCall(
        call_id="s4-call",
        task_id="s4-task",
        tool_name=tool_name,
        arguments=arguments,
    )


async def test_food_tool_gateway_rejects_malformed_input_before_provider_call() -> None:
    gateway, provider = _food_gateway(
        result=ProviderResult(
            success=True,
            data={"schemaVersion": "place.lookup/output/v1", "places": []},
        )
    )

    result = await gateway.execute(
        _place_call({"schemaVersion": "place.lookup/input/v1", "query": "火锅"})
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_INPUT_INVALID"
    assert provider.calls == []


async def test_food_tool_gateway_rejects_undeclared_and_malformed_output() -> None:
    valid_input = {
        "schemaVersion": "place.lookup/input/v1",
        "query": "火锅",
        "geo": "CN-SC-Zigong",
    }
    gateway, provider = _food_gateway(
        allowed=frozenset(),
        result=ProviderResult(
            success=True,
            data={"schemaVersion": "place.lookup/output/v1", "places": [{"sourceId": "p1"}]},
        ),
    )

    denied = await gateway.execute(_place_call(valid_input))
    assert denied.success is False
    assert denied.error is not None
    assert denied.error.code == "TOOL_POLICY_DENIED"
    assert provider.calls == []

    gateway, provider = _food_gateway(
        result=ProviderResult(
            success=True,
            data={"schemaVersion": "place.lookup/output/v1", "places": [{"sourceId": "p1"}]},
        )
    )
    malformed = await gateway.execute(_place_call(valid_input))
    assert malformed.success is False
    assert malformed.error is not None
    assert malformed.error.code == "TOOL_OUTPUT_INVALID"
    assert len(provider.calls) == 1


def test_legacy_output_adapter_validates_domain_schema_before_dto_mapping() -> None:
    manifest, _ = load_food_contract_resources()
    adapter = LegacyFoodOutputAdapter()
    valid = adapter.from_domain_output(manifest.final_output_example)
    assert isinstance(manifest.final_output_example, Mapping)
    assert valid.summary == manifest.final_output_example["summary"]

    malformed = {
        "schemaVersion": "food-agent-final-output/v1",
        "summary": "bad",
        "recommendations": [
            {
                "entityId": "restaurant-1",
                "publicScore": 2,
                "explanationRefs": [],
            }
        ],
    }
    with pytest.raises(ValueError):
        adapter.from_domain_output(malformed)
