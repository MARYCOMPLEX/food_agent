"""Composition Root and adapter registry lifecycle."""

from .account_services import (
    AccountServiceControlPlaneError,
    AccountServiceRegistry,
    AccountServiceRegistryError,
    RemoteAccountServiceFacade,
    build_account_service_registry,
)
from .agent_tools import AccountServiceAgentToolCatalog, build_agent_tool_policy
from .modular_bindings import (
    CapabilityMode,
    ModularAdapterOverrides,
    ModularBindingPlan,
    build_modular_binding_plan,
)
from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    DisabledBindingError,
    LogicalBinding,
    RegistryState,
    ReliableRuntimeBindings,
    build_composition_root,
    build_media_worker,
    build_refresh_worker,
    build_reliable_research_worker,
    build_reliable_runtime_bindings,
)

__all__ = [
    "AccountServiceControlPlaneError",
    "AccountServiceRegistry",
    "AccountServiceRegistryError",
    "RemoteAccountServiceFacade",
    "AccountServiceAgentToolCatalog",
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "DisabledBindingError",
    "LogicalBinding",
    "RegistryState",
    "ReliableRuntimeBindings",
    "build_account_service_registry",
    "build_agent_tool_policy",
    "CapabilityMode",
    "ModularAdapterOverrides",
    "ModularBindingPlan",
    "build_modular_binding_plan",
    "build_media_worker",
    "build_composition_root",
    "build_refresh_worker",
    "build_reliable_runtime_bindings",
    "build_reliable_research_worker",
]
