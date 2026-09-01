"""Composition Root and adapter registry lifecycle."""

from .account_services import (
    AccountServiceRegistry,
    AccountServiceRegistryError,
    build_account_service_registry,
)
from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    DisabledBindingError,
    LogicalBinding,
    PlatformBindingAssembly,
    PlatformBindingStatus,
    PlatformReadiness,
    RegistryState,
    ReliableRuntimeBindings,
    build_account_auth_worker,
    build_legacy_composition_root,
    build_media_worker,
    build_platform_bindings,
    build_refresh_worker,
    build_reliable_research_worker,
    build_reliable_runtime_bindings,
)

__all__ = [
    "AccountServiceRegistry",
    "AccountServiceRegistryError",
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "DisabledBindingError",
    "LogicalBinding",
    "PlatformBindingAssembly",
    "PlatformBindingStatus",
    "PlatformReadiness",
    "RegistryState",
    "ReliableRuntimeBindings",
    "build_account_auth_worker",
    "build_account_service_registry",
    "build_media_worker",
    "build_platform_bindings",
    "build_legacy_composition_root",
    "build_refresh_worker",
    "build_reliable_runtime_bindings",
    "build_reliable_research_worker",
]
