"""Adapters for local Python functions and legacy MCP providers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .base import CapabilityExecutionContext
from .models import CapabilityKind, CapabilityManifest

Handler = Callable[
    [Mapping[str, Any], CapabilityExecutionContext], Any | Awaitable[Any]
]


class LocalCapability:
    """Wrap a function without leaking it into model-visible state."""

    def __init__(self, manifest: CapabilityManifest, handler: Handler) -> None:
        self._manifest = manifest.model_copy(update={"kind": CapabilityKind.LOCAL})
        self._handler = handler

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    async def invoke(
        self,
        args: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> Any:
        value = self._handler(args, context)
        return await value if inspect.isawaitable(value) else value


def mcp_provider_capability(
    provider: Any,
    *,
    name: str | None = None,
    description: str = "Legacy MCP provider",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> LocalCapability:
    """Expose an existing ``MCPToolProvider`` through the new gateway."""

    capability_name = name or provider.name

    async def invoke(args: Mapping[str, Any], _context: CapabilityExecutionContext) -> Any:
        result = await provider.execute(**dict(args))
        if getattr(result, "success", True) is False:
            raise RuntimeError(getattr(result, "error_message", None) or "tool failed")
        return getattr(result, "data", result)

    return LocalCapability(
        CapabilityManifest(
            name=capability_name,
            description=description,
            input_schema=input_schema or {"type": "object"},
            output_schema=output_schema or {"type": "object"},
            tags=["legacy-mcp-adapter"],
        ),
        invoke,
    )
