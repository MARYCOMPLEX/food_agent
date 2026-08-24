"""Composition Root and adapter registry lifecycle."""

from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    DisabledBindingError,
    LogicalBinding,
    RegistryState,
    ReliableRuntimeBindings,
    build_legacy_composition_root,
    build_reliable_research_worker,
    build_reliable_runtime_bindings,
)

__all__ = [
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "DisabledBindingError",
    "LogicalBinding",
    "RegistryState",
    "ReliableRuntimeBindings",
    "build_legacy_composition_root",
    "build_reliable_runtime_bindings",
    "build_reliable_research_worker",
]
