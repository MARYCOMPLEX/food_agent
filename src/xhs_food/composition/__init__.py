"""Composition Root and adapter registry lifecycle."""

from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    RegistryState,
    build_legacy_composition_root,
)

__all__ = [
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "RegistryState",
    "build_legacy_composition_root",
]
