"""Capability protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from xhs_food.runtime.models import AgentRunContext

from .models import CapabilityManifest

CapabilityExecutionContext = AgentRunContext


@runtime_checkable
class Capability(Protocol):
    @property
    def manifest(self) -> CapabilityManifest:
        ...

    async def invoke(
        self,
        args: Mapping[str, Any],
        context: CapabilityExecutionContext,
    ) -> Any:
        ...
