"""Configuration-driven registry for provider account microservices."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from xhs_food.contracts.account_service import (
    AccountServiceConfig,
    AccountServiceControlPlaneError,
    AccountServiceDescriptor,
    AccountServiceHealth,
    AccountServiceProtocol,
    McpToolCallResult,
    McpToolDescriptor,
    PlatformChannel,
    RemoteAccountProjection,
    RemoteErrorCategory,
    RemoteLoginFlowProjection,
    RemoteQrPresentation,
    RemoteSourceInvocation,
    validate_remote_payload,
)
from xhs_food.gateways.account_service import (
    AccountServiceClientPort,
    HttpAccountServiceClient,
    McpAccountServiceClient,
    RemoteAccountServiceError,
)


@dataclass(frozen=True, slots=True)
class RemoteLoginSubmission:
    """Public login submission returned by a remote account service."""

    flow: RemoteLoginFlowProjection

    def as_dict(self) -> dict[str, object]:
        return {"flow": self.flow.model_dump(mode="json")}


@dataclass(frozen=True, slots=True)
class RemoteQrResult:
    flow_id: str
    presentation_ref: str
    expires_at: datetime
    content_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "flow_id": self.flow_id,
            "presentation_ref": self.presentation_ref,
            "expires_at": self.expires_at,
            "content_type": self.content_type,
        }


class AccountServiceRegistryError(ValueError):
    """Raised when remote service configuration is ambiguous or invalid."""


class AccountServiceRegistry:
    """Own one HTTP/MCP client pair per configured upstream service."""

    def __init__(
        self,
        configs: Sequence[AccountServiceConfig],
        *,
        http_client_factory: Callable[[AccountServiceConfig], AccountServiceClientPort]
        | None = None,
        mcp_client_factory: Callable[[AccountServiceConfig], McpAccountServiceClient] | None = None,
    ) -> None:
        self.configs = tuple(configs)
        self._validate_configs(self.configs)
        self._http_factory = http_client_factory or (
            lambda config: HttpAccountServiceClient(config)
        )
        self._mcp_factory = mcp_client_factory or (lambda config: McpAccountServiceClient(config))
        self._http: dict[str, AccountServiceClientPort] = {}
        self._mcp: dict[str, McpAccountServiceClient] = {}
        self._descriptors: dict[str, AccountServiceDescriptor] = {}
        self._tools: dict[str, Mapping[str, McpToolDescriptor]] = {}
        self._flow_platform: dict[str, PlatformChannel] = {}
        self._mcp_health: dict[str, tuple[str, str | None]] = {
            config.service_id: ("disabled", "not refreshed")
            for config in self.configs
            if config.protocol in {AccountServiceProtocol.MCP, AccountServiceProtocol.HTTP_MCP}
        }
        self._health: dict[str, AccountServiceHealth] = {
            config.service_id: AccountServiceHealth(
                service_id=config.service_id,
                state="disabled",
                detail="not refreshed",
                descriptor_version=config.descriptor_version,
            )
            for config in self.configs
        }
        self._refresh_lock = asyncio.Lock()
        self._closed = False

    @staticmethod
    def _validate_configs(configs: Sequence[AccountServiceConfig]) -> None:
        ids = [item.service_id for item in configs]
        if len(ids) != len(set(ids)):
            raise AccountServiceRegistryError("account service IDs must be unique")
        channel_owners: dict[PlatformChannel, str] = {}
        for config in configs:
            for channel in config.channels:
                previous = channel_owners.get(channel)
                if previous is not None:
                    raise AccountServiceRegistryError(
                        f"platform channel {channel.value!r} is claimed by both {previous!r} and {config.service_id!r}"
                    )
                channel_owners[channel] = config.service_id

    @classmethod
    def from_json(
        cls,
        value: str | None,
        *,
        file_path: str | None = None,
        http_client_factory: Callable[[AccountServiceConfig], AccountServiceClientPort]
        | None = None,
        mcp_client_factory: Callable[[AccountServiceConfig], McpAccountServiceClient] | None = None,
    ) -> AccountServiceRegistry:
        source = value
        if source is None and file_path:
            source = Path(file_path).read_text(encoding="utf-8")
        if not source:
            return cls(
                (), http_client_factory=http_client_factory, mcp_client_factory=mcp_client_factory
            )
        try:
            raw = json.loads(source)
        except json.JSONDecodeError as exc:
            raise AccountServiceRegistryError(
                "MODULAR_ACCOUNT_SERVICES_JSON is invalid JSON"
            ) from exc
        if not isinstance(raw, list):
            raise AccountServiceRegistryError("account service configuration must be a JSON list")
        validate_remote_payload(raw, "account_services")
        try:
            configs = tuple(AccountServiceConfig.model_validate(item) for item in raw)
        except Exception as exc:
            raise AccountServiceRegistryError("account service configuration is invalid") from exc
        return cls(
            configs, http_client_factory=http_client_factory, mcp_client_factory=mcp_client_factory
        )

    @property
    def enabled(self) -> bool:
        return bool(self.configs) and not self._closed

    @property
    def descriptors(self) -> Mapping[str, AccountServiceDescriptor]:
        return dict(self._descriptors)

    @property
    def tools(self) -> Mapping[str, Mapping[str, McpToolDescriptor]]:
        return {key: dict(value) for key, value in self._tools.items()}

    def tools_for(self, platform: PlatformChannel) -> tuple[McpToolDescriptor, ...]:
        """Return the current allow-listed MCP tools for one channel."""

        configs = [config for config in self.configs if platform in config.channels]
        if len(configs) != 1:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "no unique account service is configured for this platform",
                service_id="registry",
            )
        config = configs[0]
        health = self._health.get(config.service_id)
        descriptor = self._descriptors.get(config.service_id)
        if health is None or health.state not in {"ready", "degraded"} or descriptor is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "account service is not ready",
                service_id=config.service_id,
            )
        if descriptor.expires_at <= datetime.now(UTC):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "account service descriptor has expired",
                service_id=config.service_id,
            )
        return tuple(self._tools.get(config.service_id, {}).values())

    async def _ensure_clients(self, config: AccountServiceConfig) -> None:
        if config.protocol in {AccountServiceProtocol.HTTP, AccountServiceProtocol.HTTP_MCP}:
            self._http.setdefault(config.service_id, self._http_factory(config))
        if config.protocol in {AccountServiceProtocol.MCP, AccountServiceProtocol.HTTP_MCP}:
            self._mcp.setdefault(config.service_id, self._mcp_factory(config))

    async def refresh(self) -> Mapping[str, AccountServiceHealth]:
        """Refresh descriptors/tools with bounded work and isolated failures."""

        async with self._refresh_lock:
            if self._closed:
                raise AccountServiceRegistryError("account service registry is closed")
            for config in self.configs:
                await self._ensure_clients(config)
                try:
                    descriptor = await self._refresh_one(config)
                except RemoteAccountServiceError as exc:
                    previous = self._descriptors.get(config.service_id)
                    if previous is not None and previous.expires_at > datetime.now(UTC):
                        self._health[config.service_id] = AccountServiceHealth(
                            service_id=config.service_id,
                            state="degraded",
                            detail="refresh failed; previous descriptor retained",
                            descriptor_version=previous.contract_version,
                        )
                    else:
                        self._descriptors.pop(config.service_id, None)
                        self._tools.pop(config.service_id, None)
                        self._health[config.service_id] = AccountServiceHealth(
                            service_id=config.service_id,
                            state="dependency-unavailable",
                            detail=exc.envelope.code.value,
                            descriptor_version=config.descriptor_version,
                        )
                    continue
                self._descriptors[config.service_id] = descriptor
                self._health[config.service_id] = AccountServiceHealth(
                    service_id=config.service_id,
                    state="ready",
                    descriptor_version=descriptor.contract_version,
                )
            return dict(self._health)

    async def _refresh_one(self, config: AccountServiceConfig) -> AccountServiceDescriptor:
        descriptor: AccountServiceDescriptor
        if config.protocol is AccountServiceProtocol.MCP:
            now = datetime.now(UTC)
            descriptor = AccountServiceDescriptor(
                service_id=config.service_id,
                service_version="mcp",
                contract_version=config.descriptor_version,
                protocol=config.protocol,
                platform_channels=config.channels,
                capabilities=config.capabilities,
                login_modes=("qr", "credential"),
                expires_at=now + timedelta(seconds=config.descriptor_ttl_seconds),
            )
        else:
            descriptor = await self._http[config.service_id].capabilities()
        if config.protocol in {AccountServiceProtocol.MCP, AccountServiceProtocol.HTTP_MCP}:
            try:
                tools = await self._mcp[config.service_id].list_tools()
            except RemoteAccountServiceError as exc:
                self._tools.pop(config.service_id, None)
                self._mcp_health[config.service_id] = ("degraded", exc.envelope.code.value)
                if config.protocol is AccountServiceProtocol.MCP:
                    raise
            else:
                self._tools[config.service_id] = {tool.name: tool for tool in tools}
                self._mcp_health[config.service_id] = ("ready", None)
        return descriptor

    def _service_for(
        self, platform: PlatformChannel, capability: str | None = None
    ) -> tuple[AccountServiceConfig, AccountServiceClientPort]:
        matches = [config for config in self.configs if platform in config.channels]
        if len(matches) != 1:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "no unique account service is configured for this platform",
                service_id="registry",
                capability=capability,
            )
        config = matches[0]
        health = self._health.get(config.service_id)
        descriptor = self._descriptors.get(config.service_id)
        if health is None or health.state not in {"ready", "degraded"} or descriptor is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "account service is not ready",
                service_id=config.service_id,
                capability=capability,
            )
        if descriptor.expires_at <= datetime.now(UTC):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "account service descriptor has expired",
                service_id=config.service_id,
                capability=capability,
            )
        if (
            capability
            and config.capabilities
            and not any(
                capability == item or capability.startswith(item + ".")
                for item in config.capabilities
            )
        ):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "capability is not configured for this account service",
                service_id=config.service_id,
                capability=capability,
            )
        client = self._http.get(config.service_id)
        if client is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "HTTP account service client is not configured",
                service_id=config.service_id,
                capability=capability,
            )
        return config, client

    async def register_account(self, **kwargs: Any) -> RemoteAccountProjection:
        _, client = self._service_for(kwargs["platform"], "account.register")
        return await client.register_account(**kwargs)

    async def account(self, **kwargs: Any) -> RemoteAccountProjection:
        _, client = self._service_for(kwargs["platform"], "account.read")
        return await client.account(**kwargs)

    async def start_login(self, **kwargs: Any) -> RemoteLoginFlowProjection:
        _, client = self._service_for(kwargs["platform"], "account.login")
        flow = await client.start_login(**kwargs)
        self._flow_platform[flow.flow_id] = kwargs["platform"]
        return flow

    async def start_qr_login(self, **kwargs: Any) -> RemoteLoginFlowProjection:
        _, client = self._service_for(kwargs["platform"], "account.login")
        flow = await client.start_qr_login(**kwargs)
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    def remember_flow(self, flow: RemoteLoginFlowProjection) -> None:
        """Remember an opaque flow route without retaining provider state."""

        self._flow_platform[flow.flow_id] = flow.platform

    def flow_platform(self, flow_id: str) -> PlatformChannel | None:
        """Return the channel associated with a flow in this process."""

        return self._flow_platform.get(flow_id)

    def service_id_for(self, platform: PlatformChannel) -> str:
        """Resolve the configured service identity for a channel."""

        configs = [config for config in self.configs if platform in config.channels]
        if len(configs) != 1:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "no unique account service is configured for this platform",
                service_id="registry",
            )
        return configs[0].service_id

    async def flow_status(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str
    ) -> RemoteLoginFlowProjection:
        _, client = self._service_for(platform, "account.login")
        flow = await client.flow_status(flow_id=flow_id, tenant_ref=tenant_ref)
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    async def status(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str
    ) -> RemoteLoginFlowProjection:
        return await self.flow_status(platform=platform, flow_id=flow_id, tenant_ref=tenant_ref)

    async def qr_presentation(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str
    ) -> RemoteQrPresentation:
        _, client = self._service_for(platform, "account.login")
        return await client.qr_presentation(flow_id=flow_id, tenant_ref=tenant_ref)

    async def get_qr(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str
    ) -> RemoteQrPresentation:
        return await self.qr_presentation(platform=platform, flow_id=flow_id, tenant_ref=tenant_ref)

    async def poll_login(
        self,
        *,
        platform: PlatformChannel,
        flow_id: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection:
        _, client = self._service_for(platform, "account.login")
        flow = await client.poll_login(
            flow_id=flow_id, tenant_ref=tenant_ref, idempotency_key=idempotency_key
        )
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    async def cancel_login(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str, reason: str | None = None
    ) -> RemoteLoginFlowProjection:
        _, client = self._service_for(platform, "account.login")
        flow = await client.cancel_login(flow_id=flow_id, tenant_ref=tenant_ref, reason=reason)
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    async def invoke(self, request: RemoteSourceInvocation) -> object:
        _, client = self._service_for(request.platform, request.capability)
        return await client.invoke(request)

    async def invoke_for_platform(
        self,
        *,
        tenant_ref: str,
        platform: PlatformChannel,
        account_ref: str,
        capability: str,
        correlation_id: str,
        query: Mapping[str, Any] | None = None,
        expected_session_version: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> object:
        """Construct and invoke a tenant-bound source request for a channel."""

        request = RemoteSourceInvocation(
            service_id=self.service_id_for(platform),
            tenant_ref=tenant_ref,
            platform=platform,
            account_ref=account_ref,
            expected_session_version=expected_session_version,
            correlation_id=correlation_id,
            capability=capability,
            query=query or {},
            timeout_seconds=timeout_seconds,
        )
        return await self.invoke(request)

    async def call_tool(
        self,
        *,
        platform: PlatformChannel,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> McpToolCallResult:
        configs = [config for config in self.configs if platform in config.channels]
        if len(configs) != 1:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "no unique account service is configured for this platform",
                service_id="registry",
            )
        config = configs[0]
        available = {tool.name: tool for tool in self.tools_for(platform)}
        descriptor = available.get(tool_name)
        if descriptor is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "MCP tool is not available for this platform",
                service_id=config.service_id,
            )
        mcp = self._mcp.get(config.service_id)
        if mcp is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "MCP client is not configured for this service",
                service_id=config.service_id,
            )
        return await mcp.call_tool(tool_name, arguments)

    async def call_pinned_tool(
        self,
        *,
        platform: PlatformChannel,
        descriptor: McpToolDescriptor,
        arguments: Mapping[str, Any] | None = None,
    ) -> McpToolCallResult:
        """Execute a descriptor already approved in an immutable Agent snapshot."""

        configs = [config for config in self.configs if platform in config.channels]
        if len(configs) != 1:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "no unique account service is configured for this platform",
                service_id="registry",
                capability=descriptor.capability,
            )
        config = configs[0]
        if descriptor.side_effect.value != "read_only":
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "pinned Agent tools must be read-only",
                service_id=config.service_id,
                capability=descriptor.capability,
            )
        if config.capabilities and not any(
            descriptor.capability == item or descriptor.capability.startswith(item + ".")
            for item in config.capabilities
        ):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "MCP capability is not configured for this service",
                service_id=config.service_id,
                capability=descriptor.capability,
            )
        mcp = self._mcp.get(config.service_id)
        if mcp is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "MCP client is not configured for this service",
                service_id=config.service_id,
                capability=descriptor.capability,
            )
        return await mcp.call_tool(
            descriptor.name,
            arguments,
            approved_descriptor=descriptor,
        )

    def readiness(self) -> dict[str, object]:
        services: list[dict[str, object]] = []
        for config in self.configs:
            health = self._health[config.service_id]
            descriptor = self._descriptors.get(config.service_id)
            services.append(
                {
                    "service_id": config.service_id,
                    "protocol": config.protocol.value,
                    "channels": [channel.value for channel in config.channels],
                    "state": health.state,
                    "descriptor_version": descriptor.contract_version
                    if descriptor
                    else config.descriptor_version,
                    "capabilities": sorted(
                        descriptor.capabilities if descriptor else config.capabilities
                    ),
                    "mcp_tools": sorted(self._tools.get(config.service_id, {})),
                    "mcp_state": self._mcp_health.get(config.service_id, ("disabled", None))[0],
                    "mcp_detail": self._mcp_health.get(config.service_id, ("disabled", None))[1],
                    "detail": health.detail,
                }
            )
        ready = bool(services) and all(item["state"] in {"ready", "degraded"} for item in services)
        return {"enabled": self.enabled, "ready": ready, "services": services}

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[Exception] = []
        for client in [*self._mcp.values(), *self._http.values()]:
            try:
                await client.aclose()
            except Exception as exc:
                errors.append(exc)
        self._mcp.clear()
        self._http.clear()
        self._flow_platform.clear()
        if errors:
            raise ExceptionGroup("failed to close account service clients", errors)


def build_account_service_registry(target_settings: Any) -> AccountServiceRegistry | None:
    """Build the registry from target settings; return ``None`` when unset."""

    value = getattr(target_settings, "account_services_json", None)
    file_path = getattr(target_settings, "account_services_file", None)
    if not value and not file_path:
        return None
    return AccountServiceRegistry.from_json(value, file_path=file_path)


class RemoteAccountServiceFacade:
    """Expose account and login commands through remote services only."""

    def __init__(self, registry: AccountServiceRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _platform(value: str | PlatformChannel) -> PlatformChannel:
        try:
            return value if isinstance(value, PlatformChannel) else PlatformChannel(value)
        except ValueError as exc:
            raise AccountServiceControlPlaneError(
                "PLATFORM_INVALID", "unsupported platform channel", status_code=422
            ) from exc

    @staticmethod
    def _translate(call: Any) -> Any:
        async def run() -> Any:
            try:
                result = call() if callable(call) else call
                return await cast(Awaitable[Any], result)
            except RemoteAccountServiceError as exc:
                code = {
                    RemoteErrorCategory.AUTHORIZATION: "PLATFORM_ACCOUNT_NOT_FOUND",
                    RemoteErrorCategory.AUTHENTICATION: "LOGIN_AUTHENTICATION_FAILED",
                    RemoteErrorCategory.RATE_LIMITED: "LOGIN_RATE_LIMITED",
                    RemoteErrorCategory.TIMEOUT: "LOGIN_TIMEOUT",
                    RemoteErrorCategory.CONFLICT: "LOGIN_FLOW_CONFLICT",
                }.get(exc.category, "PLATFORM_SERVICE_UNAVAILABLE")
                status = (
                    404
                    if code == "PLATFORM_ACCOUNT_NOT_FOUND"
                    else (429 if code == "LOGIN_RATE_LIMITED" else 503)
                )
                raise AccountServiceControlPlaneError(
                    code,
                    "remote account service operation failed",
                    status_code=status,
                ) from None

        return run()

    async def register_account(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        platform: str,
        account_ref: str,
        alias: str,
        permissions: Sequence[str] | None = None,
    ) -> RemoteAccountProjection:
        channel = self._platform(platform)
        return await self._translate(
            self.registry.register_account(
                platform=channel, account_ref=account_ref, alias=alias, tenant_ref=tenant_id
            )
        )

    async def get_account(
        self, *, tenant_id: str, principal_id: str, platform: str, account_ref: str
    ) -> RemoteAccountProjection:
        channel = self._platform(platform)
        return await self._translate(
            self.registry.account(platform=channel, account_ref=account_ref, tenant_ref=tenant_id)
        )

    async def start_login(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        platform: str,
        account_ref: str,
        mode: Any,
        idempotency_key: str | None = None,
        credential_ref: str | None = None,
    ) -> RemoteLoginSubmission:
        channel = self._platform(platform)
        mode_value = getattr(mode, "value", mode)
        flow = await self._translate(
            self.registry.start_login(
                platform=channel,
                account_ref=account_ref,
                tenant_ref=tenant_id,
                mode=str(mode_value),
                credential_ref=credential_ref,
                idempotency_key=idempotency_key,
            )
        )
        return RemoteLoginSubmission(flow=flow)

    async def poll(
        self, *, tenant_id: str, principal_id: str, flow_id: str, idempotency_key: str | None = None
    ) -> RemoteLoginSubmission:
        channel = self.registry.flow_platform(flow_id)
        if channel is None:
            raise AccountServiceControlPlaneError(
                "LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404
            )
        flow = await self._translate(
            self.registry.poll_login(
                platform=channel,
                flow_id=flow_id,
                tenant_ref=tenant_id,
                idempotency_key=idempotency_key,
            )
        )
        return RemoteLoginSubmission(flow=flow)

    async def status(
        self, *, tenant_id: str, principal_id: str, flow_id: str
    ) -> RemoteLoginFlowProjection:
        channel = self.registry.flow_platform(flow_id)
        if channel is None:
            raise AccountServiceControlPlaneError(
                "LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404
            )
        return await self._translate(
            self.registry.status(platform=channel, flow_id=flow_id, tenant_ref=tenant_id)
        )

    async def cancel(
        self, *, tenant_id: str, principal_id: str, flow_id: str, reason: str | None = None
    ) -> RemoteLoginSubmission:
        channel = self.registry.flow_platform(flow_id)
        if channel is None:
            raise AccountServiceControlPlaneError(
                "LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404
            )
        flow = await self._translate(
            self.registry.cancel_login(
                platform=channel, flow_id=flow_id, tenant_ref=tenant_id, reason=reason
            )
        )
        return RemoteLoginSubmission(flow=flow)

    async def get_qr(self, *, tenant_id: str, principal_id: str, flow_id: str) -> RemoteQrResult:
        channel = self.registry.flow_platform(flow_id)
        if channel is None:
            raise AccountServiceControlPlaneError(
                "LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404
            )
        qr = await self._translate(
            self.registry.get_qr(platform=channel, flow_id=flow_id, tenant_ref=tenant_id)
        )
        return RemoteQrResult(
            flow_id=qr.flow_id,
            presentation_ref=qr.object_ref,
            expires_at=qr.expires_at,
            content_type=qr.content_type,
        )

    async def readiness(self) -> dict[str, object]:
        return {
            "enabled": self.registry.enabled,
            "execution": "remote",
            "services": self.registry.readiness().get("services", []),
        }


__all__ = [
    "AccountServiceRegistry",
    "AccountServiceRegistryError",
    "RemoteLoginSubmission",
    "RemoteAccountServiceFacade",
    "RemoteQrResult",
    "build_account_service_registry",
]
