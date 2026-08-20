"""S1 Composition Root lifecycle and legacy-only binding tests."""

from __future__ import annotations

import asyncio

import pytest

from xhs_food.composition import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    RegistryState,
    build_legacy_composition_root,
)
from xhs_food.protocols.mcp import MCPToolRegistry


class _Closable:
    def __init__(self, calls: list[str], name: str) -> None:
        self._calls = calls
        self._name = name

    async def aclose(self) -> None:
        self._calls.append(self._name)


class _FlakyClosable(_Closable):
    def __init__(self, calls: list[str], name: str) -> None:
        super().__init__(calls, name)
        self._failures_remaining = 1

    async def aclose(self) -> None:
        await super().aclose()
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise RuntimeError(f"{self._name} close failed")


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
        registry.register(AdapterBinding("late", "fixture/v1", lambda: object(), legacy=True))

    await registry.close()
    await registry.close()
    assert calls == ["adapter"]
    assert registry.state is RegistryState.CLOSED


async def test_registry_single_flights_concurrent_first_resolution_and_closes_once() -> None:
    created: list[_Closable] = []
    closed: list[str] = []
    factory_entered = asyncio.Event()
    release_factory = asyncio.Event()

    async def factory() -> _Closable:
        instance = _Closable(closed, "adapter")
        created.append(instance)
        factory_entered.set()
        await release_factory.wait()
        return instance

    registry = BindingRegistry("fixture")
    registry.register(AdapterBinding("adapter", "fixture/v1", factory, legacy=True))
    registry.activate()

    first_task = asyncio.create_task(registry.resolve("adapter"))
    await factory_entered.wait()
    second_task = asyncio.create_task(registry.resolve("adapter"))
    release_factory.set()

    first, second = await asyncio.gather(first_task, second_task)
    assert first is second
    assert created == [first]

    await asyncio.gather(registry.close(), registry.close())
    assert closed == ["adapter"]


async def test_registry_factory_failure_is_retryable() -> None:
    attempts = 0
    instance = object()

    async def factory() -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("factory failed")
        return instance

    registry = BindingRegistry("fixture")
    registry.register(AdapterBinding("adapter", "fixture/v1", factory, legacy=True))
    registry.activate()

    with pytest.raises(RuntimeError, match="factory failed"):
        await registry.resolve("adapter")

    assert await registry.resolve("adapter") is instance
    assert await registry.resolve("adapter") is instance
    assert attempts == 2
    await registry.close()


async def test_registry_close_waits_for_inflight_resolution_and_closes_instance() -> None:
    closed: list[str] = []
    factory_entered = asyncio.Event()
    release_factory = asyncio.Event()

    async def factory() -> _Closable:
        factory_entered.set()
        await release_factory.wait()
        return _Closable(closed, "adapter")

    registry = BindingRegistry("fixture")
    registry.register(AdapterBinding("adapter", "fixture/v1", factory, legacy=True))
    registry.activate()

    resolve_task = asyncio.create_task(registry.resolve("adapter"))
    await factory_entered.wait()
    close_task = asyncio.create_task(registry.close())
    await asyncio.sleep(0)
    assert not close_task.done()

    release_factory.set()
    instance = await resolve_task
    await close_task

    assert isinstance(instance, _Closable)
    assert closed == ["adapter"]
    assert registry.state is RegistryState.CLOSED


async def test_registry_close_continues_after_failure_and_retries_only_failed_instance() -> None:
    calls: list[str] = []
    registry = BindingRegistry("fixture")
    registry.register(
        AdapterBinding("one", "fixture/v1", lambda: _Closable(calls, "one"), legacy=True)
    )
    registry.register(
        AdapterBinding(
            "flaky-one",
            "fixture/v1",
            lambda: _FlakyClosable(calls, "flaky-one"),
            legacy=True,
        )
    )
    registry.register(
        AdapterBinding(
            "flaky-two",
            "fixture/v1",
            lambda: _FlakyClosable(calls, "flaky-two"),
            legacy=True,
        )
    )
    registry.register(
        AdapterBinding("three", "fixture/v1", lambda: _Closable(calls, "three"), legacy=True)
    )
    registry.activate()
    await registry.resolve("one")
    await registry.resolve("flaky-one")
    await registry.resolve("flaky-two")
    await registry.resolve("three")

    with pytest.raises(ExceptionGroup, match="fixture.flaky-two, fixture.flaky-one") as exc_info:
        await registry.close()

    assert len(exc_info.value.exceptions) == 2
    assert calls == ["three", "flaky-two", "flaky-one", "one"]
    assert registry.state is RegistryState.CLOSED
    with pytest.raises(RuntimeError, match="not active"):
        await registry.resolve("flaky-one")

    await registry.close()
    assert calls == [
        "three",
        "flaky-two",
        "flaky-one",
        "one",
        "flaky-two",
        "flaky-one",
    ]
    await registry.close()
    assert calls == [
        "three",
        "flaky-two",
        "flaky-one",
        "one",
        "flaky-two",
        "flaky-one",
    ]


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


async def test_s4_composition_root_registers_validated_food_pack_and_legacy_fallback() -> None:
    from xhs_food.composition.domain_packs import RegisteredDomainPack
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
    from xhs_food.domain_packs.food import FoodPack

    root = build_legacy_composition_root()
    try:
        assert root.state is RegistryState.ACTIVE
        assert {name: list(registry.bindings) for name, registry in root.registries.items()} == {
            "foundation": ["xhs_service"],
            "tools": ["xhs_tool_registry", "food_tool_gateway", "schema_tool_gateway"],
            "sources": [
                "xhs_compat",
                "food_place_capability",
                "food_reviews_capability",
                "place_compat",
                "place_tool_compat",
            ],
            "models": ["legacy_llm_provider"],
            "repositories": [
                "session_legacy",
                "user_legacy",
                "history_legacy",
                "favorites_legacy",
                "search_result_legacy",
                "place_cache_legacy",
                "public_evidence_disabled",
            ],
            "state": [
                "task_state_legacy",
                "event_bus_legacy",
                "session_window_legacy",
            ],
            "target_foundation": [
                "sqlalchemy",
                "temporal",
                "temporal_activities",
                "object_store",
                "redis_contract",
                "observability",
            ],
            "orchestrators": ["xhs_food_orchestrator"],
            "domain_packs": ["registry", "food_1_0_0", "food_legacy"],
            "use_cases": ["research_task"],
        }
        assert {
            f"{registry.name}.{binding.name}"
            for registry in root.registries.values()
            for binding in registry.bindings.values()
            if binding.enabled and not binding.legacy
        } == {
            "domain_packs.food_1_0_0",
            "domain_packs.registry",
            "sources.food_place_capability",
            "sources.food_reviews_capability",
            "tools.food_tool_gateway",
        }
        logical = root.logical_bindings["modular_core"]
        assert (
            logical.registry_name,
            logical.binding_name,
        ) == ("use_cases", "research_task")
        assert isinstance(
            await root.resolve_logical("modular_core"),
            LegacyResearchTaskFacade,
        )
        food_binding = root.logical_bindings["food_pack"]
        assert (food_binding.registry_name, food_binding.binding_name) == (
            "domain_packs",
            "food_1_0_0",
        )
        registered_food = await root.resolve_logical("food_pack")
        assert isinstance(registered_food, RegisteredDomainPack)
        assert isinstance(registered_food.implementation, FoodPack)

        tool_registry = await root.resolve("tools", "xhs_tool_registry")
        assert isinstance(tool_registry, MCPToolRegistry)
        assert tool_registry.list_tools() == ["xhs_search", "xhs_note", "xhs_batch"]
    finally:
        await root.close()


async def test_food_pack_selection_is_isolated_between_coexisting_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.composition.adapters.legacy_food import LegacyFoodPackAdapter
    from xhs_food.composition.domain_packs import RegisteredDomainPack

    monkeypatch.setenv("MODULAR_FOOD_PACK_VERSION", "1.0.0")
    registered_root = build_legacy_composition_root()
    monkeypatch.setenv("MODULAR_FOOD_PACK_VERSION", "legacy/v1")
    legacy_root = build_legacy_composition_root()

    try:
        registered_pack = await registered_root.resolve_logical("food_pack")
        legacy_pack = await legacy_root.resolve_logical("food_pack")
        registered_orchestrator = await registered_root.resolve(
            "orchestrators", "xhs_food_orchestrator"
        )
        legacy_orchestrator = await legacy_root.resolve("orchestrators", "xhs_food_orchestrator")

        registered_executor = getattr(registered_orchestrator, "_search_executor")
        legacy_executor = getattr(legacy_orchestrator, "_search_executor")
        assert isinstance(registered_pack, RegisteredDomainPack)
        assert isinstance(legacy_pack, LegacyFoodPackAdapter)
        assert getattr(registered_executor, "_food_pack") is registered_pack
        assert getattr(legacy_executor, "_food_pack") is legacy_pack
    finally:
        await asyncio.gather(registered_root.close(), legacy_root.close())


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


async def test_root_close_continues_after_registry_failure_and_retries_cleanup() -> None:
    calls: list[str] = []
    root = CompositionRoot()
    root.registry("first").register(
        AdapterBinding("one", "legacy/v1", lambda: _Closable(calls, "one"), legacy=True)
    )
    root.registry("second").register(
        AdapterBinding(
            "two",
            "legacy/v1",
            lambda: _FlakyClosable(calls, "two"),
            legacy=True,
        )
    )
    root.activate()
    await root.resolve("first", "one")
    await root.resolve("second", "two")

    with pytest.raises(ExceptionGroup, match="second") as exc_info:
        await root.close()

    assert len(exc_info.value.exceptions) == 1
    assert calls == ["two", "one"]
    assert root.state is RegistryState.CLOSED

    await root.close()
    assert calls == ["two", "one", "two"]
    await root.close()
    assert calls == ["two", "one", "two"]
