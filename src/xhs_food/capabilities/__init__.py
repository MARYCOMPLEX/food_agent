"""Capability Gateway: one contract for local tools, Skills and MCP tools."""

from .base import Capability, CapabilityExecutionContext
from .catalog import CapabilityCatalog
from .gateway import CapabilityGateway, CapabilityPolicy, CapabilityPolicyError
from .local import LocalCapability, mcp_provider_capability
from .mcp import MCPClient, MCPDiscoveryClient, MCPRemoteCapability, MCPToolSource
from .models import CapabilityKind, CapabilityManifest, SideEffectLevel

__all__ = [
    "Capability",
    "CapabilityCatalog",
    "CapabilityExecutionContext",
    "CapabilityGateway",
    "CapabilityKind",
    "CapabilityManifest",
    "CapabilityPolicy",
    "CapabilityPolicyError",
    "LocalCapability",
    "MCPClient",
    "MCPDiscoveryClient",
    "MCPRemoteCapability",
    "MCPToolSource",
    "SideEffectLevel",
    "mcp_provider_capability",
]
