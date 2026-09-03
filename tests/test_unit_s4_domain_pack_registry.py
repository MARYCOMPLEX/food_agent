"""S4 registry, tool-boundary, and output-publication contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

import pytest

import xhs_food.composition.domain_packs as domain_pack_composition
from xhs_food.composition import build_composition_root
from xhs_food.composition.adapters.food_output import LegacyFoodOutputAdapter
from xhs_food.composition.domain_packs import (
    DomainPackActivationError,
    DomainPackRegistry,
    discover_allowlisted_domain_packs,
)
from xhs_food.contracts import DomainRegistrationFailureCode
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
        tool_capabilities={},
        source_capabilities={
            "xhs.notes.search": "1.0.0",
            "xhs.notes.detail": "1.0.0",
            "xhs.comments.search": "1.0.0",
            "dianping.places.search": "1.0.0",
            "dianping.places.detail": "1.0.0",
            "dianping.reviews.search": "1.0.0",
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
        build_composition_root()


def test_food_pack_delegates_source_tools_to_the_managed_mcp_catalog() -> None:
    manifest, _ = load_food_contract_resources()
    assert manifest.allowed_tools == ()
    assert {source.capability for source in manifest.domain_sources} == {
        "notes.search",
        "notes.detail",
        "comments.search",
        "places.search",
        "places.detail",
        "reviews.search",
    }
