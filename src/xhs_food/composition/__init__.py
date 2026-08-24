"""Composition Root and adapter registry lifecycle."""

from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    DisabledBindingError,
    LogicalBinding,
    RegistryState,
    build_legacy_composition_root,
    build_reliable_research_worker,
)

__all__ = [
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "DisabledBindingError",
    "LogicalBinding",
    "RegistryState",
    "build_legacy_composition_root",
    "build_reliable_research_worker",
]
