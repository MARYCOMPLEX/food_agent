"""Policy and execution boundary for every capability."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from xhs_food.runtime.models import AgentRunContext

from .catalog import CapabilityCatalog
from .models import CapabilityManifest, SideEffectLevel


class CapabilityPolicyError(PermissionError):
    """Raised when a plan violates the capability policy."""


@dataclass(frozen=True)
class CapabilityPolicy:
    allowed_trust: frozenset[str] = frozenset({"builtin", "verified", "local"})
    max_side_effect: SideEffectLevel = SideEffectLevel.EXTERNAL
    max_estimated_cost: float = 100.0
    required_auth_scopes: frozenset[str] = frozenset()


class CapabilityGateway:
    """Single invocation boundary for local, Skill and MCP capabilities."""

    def __init__(
        self,
        catalog: CapabilityCatalog,
        *,
        policy: CapabilityPolicy | None = None,
    ) -> None:
        self.catalog = catalog
        self.policy = policy or CapabilityPolicy()
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def manifests(self) -> list[CapabilityManifest]:
        return self.catalog.list()

    async def invoke(
        self,
        name: str,
        args: Mapping[str, Any],
        context: AgentRunContext,
    ) -> Any:
        capability = self.catalog.require(name)
        manifest = capability.manifest
        self._authorize(manifest, args, context)
        semaphore = self._semaphores.setdefault(
            name, asyncio.Semaphore(manifest.max_concurrency)
        )
        async with semaphore:
            value = capability.invoke(args, context)
            if inspect.isawaitable(value):
                return await asyncio.wait_for(value, timeout=manifest.timeout_seconds)
            return value

    def _authorize(
        self,
        manifest: CapabilityManifest,
        args: Mapping[str, Any],
        context: AgentRunContext,
    ) -> None:
        if manifest.trust not in self.policy.allowed_trust:
            raise CapabilityPolicyError(f"capability {manifest.name!r} is not trusted")
        if manifest.side_effect > self.policy.max_side_effect:
            raise CapabilityPolicyError(
                f"capability {manifest.name!r} exceeds side-effect policy"
            )
        if manifest.estimated_cost > self.policy.max_estimated_cost:
            raise CapabilityPolicyError(
                f"capability {manifest.name!r} exceeds cost policy"
            )
        granted = set(context.metadata.get("auth_scopes", []))
        missing_scopes = set(manifest.auth_scopes) - granted
        missing_scopes |= set(self.policy.required_auth_scopes) - granted
        if missing_scopes:
            raise CapabilityPolicyError(
                f"capability {manifest.name!r} requires scopes: {sorted(missing_scopes)}"
            )
        self._validate_args(manifest, args)

    @staticmethod
    def _validate_args(manifest: CapabilityManifest, args: Mapping[str, Any]) -> None:
        schema = manifest.input_schema or {}
        required = schema.get("required", [])
        missing = [name for name in required if name not in args]
        if missing:
            raise ValueError(f"capability {manifest.name!r} missing arguments: {missing}")
        properties = schema.get("properties", {})
        for key, value in args.items():
            expected = properties.get(key, {}).get("type")
            if expected == "string" and not isinstance(value, str):
                raise ValueError(f"argument {key!r} must be a string")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"argument {key!r} must be an integer")
            if expected == "number" and not isinstance(value, (int, float)):
                raise ValueError(f"argument {key!r} must be a number")
            if expected == "array" and not isinstance(value, list):
                raise ValueError(f"argument {key!r} must be an array")
