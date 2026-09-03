"""Managed Agent tool catalog backed by remote account-service MCP discovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from xhs_food.contracts import (
    HIDDEN_AGENT_TOOL_ARGUMENTS,
    AgentToolCatalogSnapshot,
    AgentToolDefinition,
    AgentToolExecutionContext,
    AgentToolPolicy,
    AgentToolProjection,
    AgentToolRejection,
    ContractError,
    ErrorCategory,
    ErrorScope,
    JsonValue,
    PlatformChannel,
    RemoteErrorCategory,
    RemoteSideEffect,
    ToolCall,
    ToolResult,
    normalize_agent_tool_input_schema,
    normalize_agent_tool_output_schema,
    validate_agent_tool_schema_value,
)
from xhs_food.contracts.account_service import (
    McpToolDescriptor,
    validate_remote_payload,
)
from xhs_food.gateways.account_service import RemoteAccountServiceError

from .account_services import AccountServiceRegistry

_PUBLIC_NAME_PART = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class _ManagedRoute:
    public_name: str
    service_id: str
    platform: PlatformChannel
    descriptor: McpToolDescriptor
    public_input_schema: dict[str, Any]
    remote_input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    hidden_arguments: frozenset[str]


@dataclass(frozen=True, slots=True)
class _SnapshotState:
    snapshot: AgentToolCatalogSnapshot
    routes: Mapping[str, _ManagedRoute]


class AccountServiceAgentToolCatalog:
    """Policy-owned catalog and pinned executor over AccountServiceRegistry."""

    def __init__(
        self,
        registry: AccountServiceRegistry,
        policy: AgentToolPolicy,
    ) -> None:
        self._registry = registry
        self.policy = policy
        self._lock = asyncio.Lock()
        self._states: OrderedDict[str, _SnapshotState] = OrderedDict()
        self._active_refs: dict[str, int] = {}
        self._generation = 0
        self._current_ref: str | None = None

    async def snapshot(self, context: AgentToolExecutionContext) -> AgentToolCatalogSnapshot:
        state = await self._build(tuple(context.platforms))
        async with self._lock:
            self._active_refs[state.snapshot.snapshot_ref] = (
                self._active_refs.get(state.snapshot.snapshot_ref, 0) + 1
            )
        return state.snapshot

    async def release(self, snapshot_ref: str) -> None:
        async with self._lock:
            active = self._active_refs.get(snapshot_ref, 0)
            if active <= 1:
                self._active_refs.pop(snapshot_ref, None)
            else:
                self._active_refs[snapshot_ref] = active - 1
            self._prune_locked()

    async def current_projection(self) -> AgentToolCatalogSnapshot:
        return (await self._build(self.policy.allowed_platforms)).snapshot

    async def execute(
        self,
        *,
        snapshot_ref: str,
        call: ToolCall,
        context: AgentToolExecutionContext,
    ) -> ToolResult:
        async with self._lock:
            state = self._states.get(snapshot_ref)
        if state is None:
            return _failure(call, "TOOL_SNAPSHOT_UNAVAILABLE", ErrorCategory.DEPENDENCY_UNAVAILABLE)
        route = state.routes.get(call.tool_name)
        if route is None:
            return _failure(call, "TOOL_POLICY_DENIED", ErrorCategory.POLICY_DENIED)
        if route.platform not in context.platforms:
            return _failure(call, "TOOL_POLICY_DENIED", ErrorCategory.POLICY_DENIED)
        if any(key in HIDDEN_AGENT_TOOL_ARGUMENTS for key in call.arguments):
            return _failure(call, "TOOL_CONTEXT_OVERRIDE_DENIED", ErrorCategory.POLICY_DENIED)
        try:
            validate_remote_payload(call.arguments, "arguments")
            validate_agent_tool_schema_value(route.public_input_schema, call.arguments)
        except Exception as exc:
            return _failure(
                call,
                "TOOL_INPUT_INVALID",
                ErrorCategory.VALIDATION,
                message=_safe_error(exc),
            )

        arguments = dict(call.arguments)
        required = set(route.remote_input_schema.get("required", ()))
        values: dict[str, JsonValue] = {
            "tenant_ref": context.tenant_ref,
            "account_ref": context.account_refs.get(route.platform.value),
            "expected_session_version": context.expected_session_versions.get(route.platform.value),
            "correlation_id": call.call_id,
        }
        for name in route.hidden_arguments:
            value = values[name]
            if value is None:
                if name in required:
                    return _failure(
                        call,
                        "TOOL_CONTEXT_MISSING",
                        ErrorCategory.POLICY_DENIED,
                    )
                continue
            arguments[name] = value
        try:
            validate_agent_tool_schema_value(route.remote_input_schema, arguments)
        except Exception as exc:
            return _failure(
                call,
                "TOOL_CONTEXT_INVALID",
                ErrorCategory.VALIDATION,
                message=_safe_error(exc),
            )

        try:
            remote = await self._registry.call_pinned_tool(
                platform=route.platform,
                descriptor=route.descriptor,
                arguments=arguments,
            )
        except RemoteAccountServiceError as exc:
            return _remote_failure(call, exc)
        except Exception:
            return _failure(
                call,
                "TOOL_DEPENDENCY_UNAVAILABLE",
                ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=True,
            )
        if remote.is_error:
            return _failure(
                call,
                "MCP_TOOL_ERROR",
                ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=False,
            )
        try:
            output = _normalize_mcp_content(remote.content)
            output = validate_agent_tool_schema_value(route.output_schema, output)
        except Exception as exc:
            return _failure(
                call,
                "TOOL_OUTPUT_INVALID",
                ErrorCategory.MALFORMED_RESPONSE,
                message=_safe_error(exc),
            )
        return ToolResult(
            call_id=call.call_id,
            success=True,
            output=output,
            metadata={
                "service_id": route.service_id,
                "platform": route.platform.value,
                "capability": route.descriptor.capability,
                "capability_version": route.descriptor.capability_version,
                "snapshot_ref": snapshot_ref,
            },
        )

    async def health(self, *, snapshot_ref: str, tool_name: str) -> bool:
        async with self._lock:
            state = self._states.get(snapshot_ref)
        if state is None:
            return False
        route = state.routes.get(tool_name)
        if route is None:
            return False
        try:
            return any(
                item.name == route.descriptor.name
                for item in self._registry.tools_for(route.platform)
            )
        except Exception:
            return False

    async def _build(self, platforms: tuple[PlatformChannel, ...]) -> _SnapshotState:
        routes: dict[str, _ManagedRoute] = {}
        projections: dict[str, AgentToolProjection] = {}
        rejections: list[AgentToolRejection] = []
        collisions: set[str] = set()
        for platform in sorted(set(platforms), key=lambda item: item.value):
            try:
                service_id = self._registry.service_id_for(platform)
                descriptors = self._registry.tools_for(platform)
            except Exception:
                continue
            for descriptor in sorted(descriptors, key=lambda item: item.name):
                public_name = _public_name(platform, descriptor.name)
                rejection = _policy_rejection(
                    self.policy,
                    service_id=service_id,
                    platform=platform,
                    descriptor=descriptor,
                    public_name=public_name,
                )
                if rejection is not None:
                    rejections.append(rejection)
                    continue
                try:
                    public_schema, remote_schema, hidden = normalize_agent_tool_input_schema(
                        descriptor.input_schema
                    )
                    output_schema = normalize_agent_tool_output_schema(descriptor.output_schema)
                except Exception:
                    rejections.append(
                        _rejection(
                            service_id,
                            platform,
                            descriptor,
                            "schema-invalid",
                        )
                    )
                    continue
                if public_name in collisions:
                    rejections.append(
                        _rejection(
                            service_id,
                            platform,
                            descriptor,
                            "name-collision",
                        )
                    )
                    continue
                previous = routes.pop(public_name, None)
                if previous is not None:
                    projections.pop(public_name, None)
                    collisions.add(public_name)
                    rejections.extend(
                        (
                            _rejection(
                                previous.service_id,
                                previous.platform,
                                previous.descriptor,
                                "name-collision",
                            ),
                            _rejection(
                                service_id,
                                platform,
                                descriptor,
                                "name-collision",
                            ),
                        )
                    )
                    continue
                routes[public_name] = _ManagedRoute(
                    public_name=public_name,
                    service_id=service_id,
                    platform=platform,
                    descriptor=descriptor,
                    public_input_schema=public_schema,
                    remote_input_schema=remote_schema,
                    output_schema=output_schema,
                    hidden_arguments=hidden,
                )
                projections[public_name] = AgentToolProjection(
                    public_name=public_name,
                    service_id=service_id,
                    platform=platform,
                    capability=descriptor.capability,
                    capability_version=descriptor.capability_version,
                )

        payload = {
            "routes": [_route_digest(routes[name]) for name in sorted(routes)],
            "rejections": sorted(
                (item.model_dump(mode="json") for item in rejections),
                key=lambda item: (
                    item["service_id"],
                    item["platform"],
                    item["remote_name"],
                    item["code"],
                ),
            ),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot_ref = f"agent-tools-v1:{digest[:24]}"
        async with self._lock:
            existing = self._states.get(snapshot_ref)
            if existing is not None:
                self._states.move_to_end(snapshot_ref)
                self._current_ref = snapshot_ref
                return existing
            self._generation += 1
            ordered_routes = {name: routes[name] for name in sorted(routes)}
            snapshot = AgentToolCatalogSnapshot(
                snapshot_ref=snapshot_ref,
                generation=self._generation,
                created_at=datetime.now(UTC),
                tools=tuple(
                    AgentToolDefinition(
                        name=name,
                        description=route.descriptor.description,
                        input_schema=route.public_input_schema,
                        output_schema=route.output_schema,
                        timeout_ms=_timeout_ms(self._registry, route.service_id),
                    )
                    for name, route in ordered_routes.items()
                ),
                projection=tuple(projections[name] for name in sorted(projections)),
                rejections=tuple(rejections),
            )
            state = _SnapshotState(snapshot=snapshot, routes=ordered_routes)
            self._states[snapshot_ref] = state
            self._current_ref = snapshot_ref
            self._prune_locked()
            return state

    def _prune_locked(self) -> None:
        limit = self.policy.max_retained_snapshots
        for snapshot_ref in tuple(self._states):
            if len(self._states) <= limit:
                break
            if snapshot_ref != self._current_ref and self._active_refs.get(snapshot_ref, 0) == 0:
                self._states.pop(snapshot_ref, None)


def build_agent_tool_policy(settings: object) -> AgentToolPolicy:
    raw = getattr(settings, "agent_mcp_tool_policy_json", None)
    if not raw:
        return AgentToolPolicy()
    try:
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise ValueError("policy must be a JSON object")
        validate_remote_payload(value, "agent_tool_policy")
        return AgentToolPolicy.model_validate(value)
    except Exception as exc:
        raise ValueError("MODULAR_AGENT_MCP_TOOL_POLICY_JSON is invalid") from exc


def _public_name(platform: PlatformChannel, remote_name: str) -> str:
    normalized = _PUBLIC_NAME_PART.sub("_", remote_name).strip("_")
    if not normalized:
        raise ValueError("remote tool name cannot be normalized")
    return f"{platform.value}__{normalized}"[:128]


def _route_digest(route: _ManagedRoute) -> dict[str, Any]:
    return {
        "public_name": route.public_name,
        "service_id": route.service_id,
        "platform": route.platform.value,
        "remote_name": route.descriptor.name,
        "capability": route.descriptor.capability,
        "capability_version": route.descriptor.capability_version,
        "input_schema": route.remote_input_schema,
        "output_schema": route.output_schema,
    }


def _policy_rejection(
    policy: AgentToolPolicy,
    *,
    service_id: str,
    platform: PlatformChannel,
    descriptor: McpToolDescriptor,
    public_name: str,
) -> AgentToolRejection | None:
    if descriptor.side_effect != RemoteSideEffect.READ_ONLY:
        return _rejection(service_id, platform, descriptor, "side-effect-denied")
    if not policy.allows(
        platform=platform,
        capability=descriptor.capability,
        public_name=public_name,
    ):
        return _rejection(service_id, platform, descriptor, "policy-denied")
    return None


def _rejection(
    service_id: str,
    platform: PlatformChannel,
    descriptor: McpToolDescriptor,
    code: str,
) -> AgentToolRejection:
    return AgentToolRejection(
        service_id=service_id,
        platform=platform,
        remote_name=descriptor.name,
        capability=descriptor.capability,
        code=code,  # type: ignore[arg-type]
    )


def _normalize_mcp_content(value: object) -> JsonValue:
    candidate = value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], Mapping):
        item = value[0]
        if item.get("type") == "json" and "json" in item:
            candidate = item["json"]
        elif item.get("type") == "text" and "text" in item:
            candidate = item["text"]
    if isinstance(candidate, str):
        with suppress(json.JSONDecodeError):
            candidate = json.loads(candidate)
    return validate_agent_tool_schema_value({}, candidate)


def _timeout_ms(registry: AccountServiceRegistry, service_id: str) -> int:
    config = next(item for item in registry.configs if item.service_id == service_id)
    return max(1, int(config.timeout_seconds * 1000))


def _safe_error(exc: BaseException) -> str:
    return type(exc).__name__


def _remote_failure(call: ToolCall, exc: RemoteAccountServiceError) -> ToolResult:
    categories = {
        RemoteErrorCategory.TIMEOUT: ErrorCategory.TIMEOUT,
        RemoteErrorCategory.RATE_LIMITED: ErrorCategory.RATE_LIMITED,
        RemoteErrorCategory.AUTHENTICATION: ErrorCategory.POLICY_DENIED,
        RemoteErrorCategory.AUTHORIZATION: ErrorCategory.POLICY_DENIED,
        RemoteErrorCategory.INVALID: ErrorCategory.VALIDATION,
    }
    return _failure(
        call,
        f"MCP_{exc.category.value.replace('-', '_').upper()}",
        categories.get(exc.category, ErrorCategory.DEPENDENCY_UNAVAILABLE),
        retryable=exc.retryable,
    )


def _failure(
    call: ToolCall,
    code: str,
    category: ErrorCategory,
    *,
    message: str | None = None,
    retryable: bool = False,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        success=False,
        error=ContractError(
            code=code,
            category=category,
            scope=ErrorScope.TOOL,
            retryable=retryable,
            boundary_ref=call.tool_name,
            message=message,
        ),
    )


__all__ = ["AccountServiceAgentToolCatalog", "build_agent_tool_policy"]
