"""Optional MCP client adapter.

The core package does not require the MCP SDK.  Any MCP client implementing
this small protocol can be mounted, which keeps deployment and tests light.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from xhs_food.runtime.models import AgentRunContext

from .catalog import CapabilityCatalog
from .models import CapabilityKind, CapabilityManifest, SideEffectLevel


class MCPClient(Protocol):
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any: ...


class MCPDiscoveryClient(MCPClient, Protocol):
    async def list_tools(self, *, cursor: str | None = None) -> Any: ...


class MCPRemoteCapability:
    def __init__(
        self,
        client: MCPClient,
        manifest: CapabilityManifest,
        *,
        remote_name: str | None = None,
    ) -> None:
        self._client = client
        self._manifest = manifest.model_copy(update={"kind": CapabilityKind.MCP})
        self._remote_name = remote_name or manifest.name

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    async def invoke(self, args: Mapping[str, Any], context: AgentRunContext) -> Any:
        _ = context
        return await self._client.call_tool(self._remote_name, args)


class MCPToolSource:
    """Discover MCP tools and normalize them into gateway capabilities.

    ``namespace`` gives tools stable planner-visible names without changing the
    remote MCP tool name used by ``call_tool``. Mounting a source is an
    explicit trust decision; callers can lower ``trust`` and adjust gateway
    policy when tools originate outside the application boundary.
    """

    def __init__(
        self,
        client: MCPDiscoveryClient,
        *,
        namespace: str | None = None,
        version: str = "1.0.0",
        trust: str = "verified",
        timeout_seconds: float = 60.0,
        max_concurrency: int = 4,
        auth_scopes: Sequence[str] = (),
    ) -> None:
        self._client = client
        self._namespace = namespace.strip(".") if namespace else None
        self._version = version
        self._trust = trust
        self._timeout_seconds = timeout_seconds
        self._max_concurrency = max_concurrency
        self._auth_scopes = list(auth_scopes)

    async def discover(self) -> list[MCPRemoteCapability]:
        capabilities: list[MCPRemoteCapability] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            response = (
                await self._client.list_tools()
                if cursor is None
                else await self._client.list_tools(cursor=cursor)
            )
            tools = self._field(response, "tools", default=response)
            if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
                raise TypeError("MCP list_tools response must contain a tools sequence")
            capabilities.extend(self._to_capability(tool) for tool in tools)

            next_cursor = self._field(
                response,
                "nextCursor",
                "next_cursor",
                default=None,
            )
            if not next_cursor:
                return capabilities
            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise ValueError("MCP list_tools returned a repeated pagination cursor")
            seen_cursors.add(cursor)

    async def load_into(
        self,
        catalog: CapabilityCatalog,
        *,
        replace: bool = False,
    ) -> list[CapabilityManifest]:
        capabilities = await self.discover()
        for capability in capabilities:
            catalog.register(capability, replace=replace)
        return [capability.manifest for capability in capabilities]

    def _to_capability(self, tool: Any) -> MCPRemoteCapability:
        remote_name = str(self._field(tool, "name", default="")).strip()
        if not remote_name:
            raise ValueError("MCP tool name must not be blank")
        public_name = f"{self._namespace}.{remote_name}" if self._namespace else remote_name
        annotations = self._field(tool, "annotations", default={}) or {}
        read_only = bool(self._field(annotations, "readOnlyHint", "read_only_hint", default=False))
        destructive = bool(
            self._field(
                annotations,
                "destructiveHint",
                "destructive_hint",
                default=False,
            )
        )
        idempotent_hint = self._field(
            annotations,
            "idempotentHint",
            "idempotent_hint",
            default=None,
        )
        side_effect = (
            SideEffectLevel.DESTRUCTIVE
            if destructive
            else SideEffectLevel.READ_ONLY
            if read_only
            else SideEffectLevel.EXTERNAL
        )
        input_schema = self._schema(self._field(tool, "inputSchema", "input_schema", default=None))
        output_schema = self._schema(
            self._field(tool, "outputSchema", "output_schema", default=None)
        )
        tags = ["mcp"]
        if self._namespace:
            tags.append(f"mcp-source:{self._namespace}")
        manifest = CapabilityManifest(
            name=public_name,
            version=self._version,
            description=str(self._field(tool, "description", default="") or ""),
            kind=CapabilityKind.MCP,
            input_schema=input_schema,
            output_schema=output_schema,
            timeout_seconds=self._timeout_seconds,
            max_concurrency=self._max_concurrency,
            side_effect=side_effect,
            auth_scopes=self._auth_scopes,
            trust=self._trust,
            idempotent=(read_only if idempotent_hint is None else bool(idempotent_hint)),
            tags=tags,
        )
        return MCPRemoteCapability(
            self._client,
            manifest,
            remote_name=remote_name,
        )

    @staticmethod
    def _field(value: Any, *names: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            for name in names:
                if name in value:
                    return value[name]
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
        return default

    @staticmethod
    def _schema(value: Any) -> dict[str, Any]:
        if value is None:
            return {"type": "object"}
        if not isinstance(value, Mapping):
            raise TypeError("MCP tool schema must be a mapping")
        return dict(value)
