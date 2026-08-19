"""S1 Composition Root lifecycle and legacy-only binding tests."""

from __future__ import annotations

import pytest

from xhs_food.composition import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    RegistryState,
    build_legacy_composition_root,
)


class _Closable:
    def __init__(self, calls: list[str], name: str) -> None:
        self._calls = calls
        self._name = name

    async def aclose(self) -> None:
        self._calls.append(self._name)


async def test_registry_freezes_after_activation_and_caches_instances() -> None:
    calls: list[str] = []
    registry = BindingRegistry("fixture")
    registry.register(
        AdapterBinding(
            name="adapter",
            contract_version="fixture/v1",
            factory=lambda: _Closable(calls, "adapter"),
            legacy=True,
        )
    )
    registry.activate()

    first = await registry.resolve("adapter")
    second = await registry.resolve("adapter")
    assert first is second
    assert registry.state is RegistryState.ACTIVE

    with pytest.raises(RuntimeError, match="not configurable"):
        registry.register(
            AdapterBinding("late", "fixture/v1", lambda: object(), legacy=True)
        )

    await registry.close()
    await registry.close()
    assert calls == ["adapter"]
    assert registry.state is RegistryState.CLOSED


def test_duplicate_bindings_and_non_legacy_s1_bindings_are_rejected() -> None:
    root = CompositionRoot()
    registry = root.registry("fixture")
    legacy = AdapterBinding("same", "legacy/v1", lambda: object(), legacy=True)
    registry.register(legacy)
    with pytest.raises(ValueError, match="duplicate binding"):
        registry.register(legacy)

    root.registry("target").register(
        AdapterBinding("disabled", "target/v1", lambda: object(), legacy=False)
    )
    with pytest.raises(RuntimeError, match="non-legacy bindings"):
        root.assert_legacy_only()


async def test_legacy_composition_root_registers_only_current_factories() -> None:
    root = build_legacy_composition_root()
    try:
        assert root.state is RegistryState.ACTIVE
        assert {
            name: list(registry.bindings)
            for name, registry in root.registries.items()
        } == {
            "foundation": ["xhs_service"],
            "tools": ["xhs_tool_registry"],
            "orchestrators": ["xhs_food_orchestrator"],
        }
        assert all(
            binding.legacy
            for registry in root.registries.values()
            for binding in registry.bindings.values()
        )

        tool_registry = await root.resolve("tools", "xhs_tool_registry")
        assert tool_registry.list_tools() == ["xhs_search", "xhs_note", "xhs_batch"]
    finally:
        await root.close()


async def test_root_closes_registry_instances_in_reverse_registry_order() -> None:
    calls: list[str] = []
    root = CompositionRoot()
    root.registry("first").register(
        AdapterBinding("one", "legacy/v1", lambda: _Closable(calls, "one"), legacy=True)
    )
    root.registry("second").register(
        AdapterBinding("two", "legacy/v1", lambda: _Closable(calls, "two"), legacy=True)
    )
    root.activate()
    await root.resolve("first", "one")
    await root.resolve("second", "two")

    await root.close()
    assert calls == ["two", "one"]
    assert root.state is RegistryState.CLOSED
