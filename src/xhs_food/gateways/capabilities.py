"""Explicit versioned capability registry for platform source bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    """One immutable source capability advertisement."""

    capability: str
    version: str
    source_id: str
    connector_version: str
    enabled: bool = True
    provenance_ref: str = ""
    dependency_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("capability", "version", "source_id", "connector_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.enabled and not self.provenance_ref.strip():
            raise ValueError("enabled capability requires a provenance reference")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.capability, self.version, self.source_id)


class CapabilityCollisionError(ValueError):
    """Raised when a registration would silently replace another source."""


class CapabilityNotRegisteredError(LookupError):
    pass


class PlatformCapabilityRegistry:
    """Resolve platform capabilities without replacing legacy providers."""

    def __init__(self, registrations: tuple[CapabilityRegistration, ...] = ()) -> None:
        self._registrations: dict[tuple[str, str, str], CapabilityRegistration] = {}
        for registration in registrations:
            self.register(registration)

    @property
    def registrations(self) -> tuple[CapabilityRegistration, ...]:
        return tuple(self._registrations.values())

    @property
    def snapshot(self) -> Mapping[tuple[str, str, str], CapabilityRegistration]:
        return MappingProxyType(dict(self._registrations))

    def register(self, registration: CapabilityRegistration) -> None:
        key = registration.key
        if key in self._registrations:
            raise CapabilityCollisionError(
                "duplicate capability snapshot: "
                f"{registration.capability}@{registration.version}/{registration.source_id}"
            )
        # Two enabled implementations for one capability/source pair are
        # ambiguous even when connector versions differ.  Operators must
        # choose explicitly by source ID or disable one registration.
        siblings = [
            item
            for item in self._registrations.values()
            if item.capability == registration.capability
            and item.source_id == registration.source_id
            and item.enabled
            and registration.enabled
        ]
        if siblings:
            raise CapabilityCollisionError(
                "enabled capability collision: "
                f"{registration.capability}/{registration.source_id}"
            )
        self._registrations[key] = registration

    def resolve(
        self,
        capability: str,
        *,
        source_id: str | None = None,
        version: str | None = None,
    ) -> CapabilityRegistration:
        candidates = [
            item
            for item in self._registrations.values()
            if item.enabled
            and item.capability == capability
            and (source_id is None or item.source_id == source_id)
            and (version is None or item.version == version)
        ]
        if not candidates:
            raise CapabilityNotRegisteredError(capability)
        if len(candidates) > 1:
            raise CapabilityCollisionError(
                f"capability {capability!r} has multiple enabled registrations; "
                "select source_id and version explicitly"
            )
        return candidates[0]

    def disable(self, *, source_id: str, capability: str | None = None) -> None:
        for key, item in tuple(self._registrations.items()):
            if item.source_id != source_id or (
                capability is not None and item.capability != capability
            ):
                continue
            self._registrations[key] = CapabilityRegistration(
                capability=item.capability,
                version=item.version,
                source_id=item.source_id,
                connector_version=item.connector_version,
                enabled=False,
                provenance_ref=item.provenance_ref,
                dependency_digest=item.dependency_digest,
            )


# Alias used by composition code and architecture documents.
CapabilityMultiplexer = PlatformCapabilityRegistry


__all__ = [
    "CapabilityCollisionError",
    "CapabilityMultiplexer",
    "CapabilityNotRegisteredError",
    "CapabilityRegistration",
    "PlatformCapabilityRegistry",
]
