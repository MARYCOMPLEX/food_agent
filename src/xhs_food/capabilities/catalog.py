"""Version-aware capability registry."""

from __future__ import annotations

import builtins
from collections.abc import Iterable

from .base import Capability
from .models import CapabilityManifest


class CapabilityCatalog:
    """Registry shared by planners, gateway and health endpoints."""

    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        self._capabilities: dict[str, Capability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability, *, replace: bool = False) -> None:
        name = capability.manifest.name
        if name in self._capabilities and not replace:
            raise ValueError(f"capability {name!r} is already registered")
        self._capabilities[name] = capability

    def unregister(self, name: str) -> None:
        self._capabilities.pop(name, None)

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def require(self, name: str) -> Capability:
        capability = self.get(name)
        if capability is None:
            raise KeyError(f"capability {name!r} is not registered")
        return capability

    def list(self) -> builtins.list[CapabilityManifest]:
        return [capability.manifest for capability in self._capabilities.values()]

    def names(self) -> builtins.list[str]:
        return list(self._capabilities)
