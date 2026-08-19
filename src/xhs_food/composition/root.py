"""Central lifecycle for contract-to-adapter bindings.

S1 creates the root without routing production callers through it. The explicit
legacy builder is the only place in this package that imports concrete adapters.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

AdapterFactory = Callable[[], object | Awaitable[object]]


class RegistryState(StrEnum):
    CONFIGURING = "configuring"
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class AdapterBinding:
    """A versioned factory selected only by the Composition Root."""

    name: str
    contract_version: str
    factory: AdapterFactory
    legacy: bool

    def __post_init__(self) -> None:
        if not self.name or not self.contract_version:
            raise ValueError("binding name and contract_version must be non-empty")


@dataclass(frozen=True, slots=True)
class LogicalBinding:
    """A stable capability name resolved to one concrete registry binding."""

    name: str
    registry_name: str
    binding_name: str

    def __post_init__(self) -> None:
        if not self.name or not self.registry_name or not self.binding_name:
            raise ValueError("logical binding names must be non-empty")


class BindingRegistry:
    """Configure once, activate atomically, and close owned instances."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("registry name must be non-empty")
        self.name = name
        self._state = RegistryState.CONFIGURING
        self._bindings: dict[str, AdapterBinding] = {}
        self._instances: dict[str, object] = {}
        self._creation_order: list[str] = []

    @property
    def state(self) -> RegistryState:
        return self._state

    @property
    def bindings(self) -> Mapping[str, AdapterBinding]:
        return MappingProxyType(self._bindings)

    def register(self, binding: AdapterBinding) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"registry {self.name!r} is not configurable")
        if binding.name in self._bindings:
            raise ValueError(f"duplicate binding: {self.name}.{binding.name}")
        self._bindings[binding.name] = binding

    def activate(self) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"registry {self.name!r} cannot be activated from {self._state}")
        self._state = RegistryState.ACTIVE

    async def resolve(self, name: str) -> object:
        if self._state is not RegistryState.ACTIVE:
            raise RuntimeError(f"registry {self.name!r} is not active")
        if name in self._instances:
            return self._instances[name]
        try:
            binding = self._bindings[name]
        except KeyError as exc:
            raise KeyError(f"unknown binding: {self.name}.{name}") from exc

        instance = binding.factory()
        if inspect.isawaitable(instance):
            instance = await instance
        self._instances[name] = instance
        self._creation_order.append(name)
        return instance

    async def close(self) -> None:
        if self._state is RegistryState.CLOSED:
            return
        self._state = RegistryState.CLOSED
        for name in reversed(self._creation_order):
            instance = self._instances[name]
            close = getattr(instance, "aclose", None) or getattr(instance, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result
        self._instances.clear()
        self._creation_order.clear()


class CompositionRoot:
    """Own all registries without owning domain behavior."""

    def __init__(self) -> None:
        self._state = RegistryState.CONFIGURING
        self._registries: dict[str, BindingRegistry] = {}
        self._logical_bindings: dict[str, LogicalBinding] = {}

    @property
    def state(self) -> RegistryState:
        return self._state

    @property
    def registries(self) -> Mapping[str, BindingRegistry]:
        return MappingProxyType(self._registries)

    @property
    def logical_bindings(self) -> Mapping[str, LogicalBinding]:
        return MappingProxyType(self._logical_bindings)

    def registry(self, name: str) -> BindingRegistry:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError("composition root is no longer configurable")
        registry = self._registries.get(name)
        if registry is None:
            registry = BindingRegistry(name)
            self._registries[name] = registry
        return registry

    def bind_logical(self, name: str, *, registry_name: str, binding_name: str) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError("composition root is no longer configurable")
        if name in self._logical_bindings:
            raise ValueError(f"duplicate logical binding: {name}")
        try:
            registry = self._registries[registry_name]
        except KeyError as exc:
            raise KeyError(f"unknown registry: {registry_name}") from exc
        if binding_name not in registry.bindings:
            raise KeyError(f"unknown binding: {registry_name}.{binding_name}")
        self._logical_bindings[name] = LogicalBinding(
            name=name,
            registry_name=registry_name,
            binding_name=binding_name,
        )

    def activate(self) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"composition root cannot activate from {self._state}")
        for registry in self._registries.values():
            registry.activate()
        self._state = RegistryState.ACTIVE

    async def resolve(self, registry_name: str, binding_name: str) -> object:
        if self._state is not RegistryState.ACTIVE:
            raise RuntimeError("composition root is not active")
        try:
            registry = self._registries[registry_name]
        except KeyError as exc:
            raise KeyError(f"unknown registry: {registry_name}") from exc
        return await registry.resolve(binding_name)

    async def resolve_logical(self, name: str) -> object:
        if self._state is not RegistryState.ACTIVE:
            raise RuntimeError("composition root is not active")
        try:
            binding = self._logical_bindings[name]
        except KeyError as exc:
            raise KeyError(f"unknown logical binding: {name}") from exc
        return await self.resolve(binding.registry_name, binding.binding_name)

    def assert_legacy_only(self) -> None:
        non_legacy = [
            f"{registry.name}.{binding.name}"
            for registry in self._registries.values()
            for binding in registry.bindings.values()
            if not binding.legacy
        ]
        if non_legacy:
            raise RuntimeError(f"non-legacy bindings are disabled in S1: {non_legacy}")

    async def close(self) -> None:
        if self._state is RegistryState.CLOSED:
            return
        self._state = RegistryState.CLOSED
        for registry in reversed(tuple(self._registries.values())):
            await registry.close()


def build_legacy_composition_root() -> CompositionRoot:
    """Create the inactive-behavior S1 root using only current factories."""

    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
    from xhs_food.di import factories as legacy

    root = CompositionRoot()
    root.registry("foundation").register(
        AdapterBinding(
            name="xhs_service",
            contract_version="legacy/v1",
            factory=legacy.get_xhs_service,
            legacy=True,
        )
    )
    root.registry("tools").register(
        AdapterBinding(
            name="xhs_tool_registry",
            contract_version="legacy/v1",
            factory=legacy.get_xhs_tool_registry,
            legacy=True,
        )
    )
    root.registry("orchestrators").register(
        AdapterBinding(
            name="xhs_food_orchestrator",
            contract_version="legacy/v1",
            factory=legacy.get_xhs_food_orchestrator,
            legacy=True,
        )
    )
    root.registry("use_cases").register(
        AdapterBinding(
            name="research_task",
            contract_version="legacy/v1",
            factory=LegacyResearchTaskFacade,
            legacy=True,
        )
    )
    root.bind_logical(
        "modular_core",
        registry_name="use_cases",
        binding_name="research_task",
    )
    root.assert_legacy_only()
    root.activate()
    return root


__all__ = [
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "LogicalBinding",
    "RegistryState",
    "build_legacy_composition_root",
]
