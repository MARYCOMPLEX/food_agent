"""Composition Root and adapter registry lifecycle."""

from .account_services import (
    AccountServiceControlPlaneError,
    AccountServiceRegistry,
    AccountServiceRegistryError,
    RemoteAccountServiceFacade,
    build_account_service_registry,
)
from .agent_tools import AccountServiceAgentToolCatalog, build_agent_tool_policy
from .managed_search import (
    ManagedMcpSearchTool,
    UnavailableManagedSearchTool,
    bind_managed_search_context,
)
from .root import (
    AdapterBinding,
    BindingRegistry,
    CompositionRoot,
    DisabledBindingError,
    LogicalBinding,
    RegistryState,
    ReliableRuntimeBindings,
    build_legacy_composition_root,
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
    "ManagedMcpSearchTool",
    "UnavailableManagedSearchTool",
    "bind_managed_search_context",
    "build_media_worker",
    "build_legacy_composition_root",
    "build_refresh_worker",
    "build_reliable_runtime_bindings",
    "build_reliable_research_worker",
]
