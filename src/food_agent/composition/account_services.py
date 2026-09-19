"""Configuration-driven registry for provider account microservices."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
import uuid

from loguru import logger

from food_agent.contracts.account_service import (
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
from food_agent.gateways.account_service import (
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


class McpAccountLoginAdapter:
    """Bridges pure MCP services (e.g. Ctrip/Xiecheng) into AccountServiceClientPort."""

    def __init__(self, config: AccountServiceConfig, mcp_client: McpAccountServiceClient) -> None:
        self.config = config
        self._mcp = mcp_client
        self._flows: dict[str, dict[str, Any]] = {}
        self._accounts: dict[str, RemoteAccountProjection] = {}
        self._closed = False

    @property
    def descriptor(self) -> AccountServiceDescriptor | None:
        now = datetime.now(UTC)
        return AccountServiceDescriptor(
            service_id=self.config.service_id,
            service_version="mcp",
            contract_version=self.config.descriptor_version,
            protocol=self.config.protocol,
            platform_channels=self.config.channels,
            capabilities=self.config.capabilities or (
                "account.register",
                "account.read",
                "account.login",
                "source.invoke",
            ),
            login_modes=("qr",),
            expires_at=now + timedelta(seconds=self.config.descriptor_ttl_seconds),
        )

    async def capabilities(self) -> AccountServiceDescriptor:
        return self.descriptor  # type: ignore[return-value]

    async def register_account(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        alias: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteAccountProjection:
        now = datetime.now(UTC)
        account = RemoteAccountProjection(
            service_id=self.config.service_id,
            platform=platform,
            account_ref=account_ref,
            alias=alias,
            status="active",
            health="healthy",
            session_version=1,
        )
        self._accounts[account_ref] = account
        return account

    async def _find_tool(self, *patterns: str) -> str | None:
        if not getattr(self._mcp, "_initialized", False):
            await self._mcp.initialize()
        raw_list = await self._mcp._rpc("tools/list", {})
        raw_tools = raw_list.get("tools", [])
        names = [t.get("name", "") for t in raw_tools if isinstance(t, dict)]
        for pat in patterns:
            for name in names:
                if pat in name or name.endswith(pat):
                    return name
        return None

    async def account(
        self, *, platform: PlatformChannel, account_ref: str, tenant_ref: str
    ) -> RemoteAccountProjection:
        existing = self._accounts.get(account_ref)
        status = existing.status if existing else "active"
        try:
            status_tool = await self._find_tool("_login_status", "login_status")
            if status_tool:
                raw = await self._mcp._rpc("tools/call", {"name": status_tool, "arguments": {}})
                text = ""
                content_items = raw.get("content", [])
                if isinstance(content_items, list) and content_items:
                    text = content_items[0].get("text", "")
                parsed: dict[str, Any] = {}
                if text:
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        pass
                if not parsed and isinstance(raw.get("structuredContent"), dict):
                    parsed = raw["structuredContent"]
                sub = parsed.get("result") if isinstance(parsed.get("result"), dict) else parsed
                if sub:
                    if (
                        sub.get("logged_in") is True
                        or sub.get("ok") is True
                        or sub.get("return_code") == 0
                        or sub.get("state") == "logged_in"
                    ):
                        status = "active"
                    elif sub.get("logged_in") is False or sub.get("state") in ("unauthenticated", "logged_out"):
                        status = "unauthenticated"
        except Exception:
            pass

        if existing:
            updated = existing.model_copy(update={"status": status, "health": "healthy" if status == "active" else "degraded"})
            self._accounts[account_ref] = updated
            return updated

        account = RemoteAccountProjection(
            service_id=self.config.service_id,
            platform=platform,
            account_ref=account_ref,
            alias=f"{platform.value} 默认账号",
            status=status,
            health="healthy" if status == "active" else "degraded",
            session_version=1,
        )
        self._accounts[account_ref] = account
        return account

    async def start_qr_login(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection:
        return await self.start_login(
            platform=platform,
            account_ref=account_ref,
            tenant_ref=tenant_ref,
            mode="qr",
            idempotency_key=idempotency_key,
        )

    async def start_login(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        tenant_ref: str,
        mode: str,
        credential_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection:
        start_tool = await self._find_tool("_login_start", "login_start")
        if not start_tool:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                f"MCP service '{self.config.service_id}' does not provide a login_start tool",
                service_id=self.config.service_id,
                capability="account.login",
            )

        raw = await self._mcp._rpc("tools/call", {"name": start_tool, "arguments": {}})
        text = ""
        content_items = raw.get("content", [])
        if isinstance(content_items, list) and content_items:
            text = content_items[0].get("text", "")
        parsed: dict[str, Any] = {}
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                pass
        if not parsed and isinstance(raw.get("structuredContent"), dict):
            parsed = raw["structuredContent"]

        qr_url = (
            parsed.get("qr_code_url")
            or parsed.get("qr_url")
            or parsed.get("url")
            or parsed.get("qr_image_path")
        )
        if not qr_url:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "login_start tool did not return a valid QR code URL",
                service_id=self.config.service_id,
                capability="account.login",
            )

        now = datetime.now(UTC)
        ttl = int(parsed.get("ttl_seconds") or 180)
        expires_at = now + timedelta(seconds=ttl)
        flow_id = f"{self.config.service_id}-flow-{uuid.uuid4().hex[:12]}"

        qr_code = parsed.get("qr_code") or (parsed.get("result", {}).get("qr_code") if isinstance(parsed.get("result"), dict) else None)
        flow_info = {
            "flow_id": flow_id,
            "platform": platform,
            "account_ref": account_ref,
            "tenant_ref": tenant_ref,
            "qr_code": qr_code,
            "qr_code_url": qr_url,
            "created_at": now,
            "expires_at": expires_at,
            "state": "qr_ready",
        }
        self._flows[flow_id] = flow_info

        return RemoteLoginFlowProjection(
            service_id=self.config.service_id,
            platform=platform,
            account_ref=account_ref,
            flow_id=flow_id,
            state="qr_ready",
            created_at=now,
            expires_at=expires_at,
            updated_at=now,
            qr_expires_at=expires_at,
        )

    async def flow_status(self, *, flow_id: str, tenant_ref: str) -> RemoteLoginFlowProjection:
        flow = self._flows.get(flow_id)
        now = datetime.now(UTC)
        if not flow:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "login flow not found",
                service_id=self.config.service_id,
                capability="account.login",
            )
        return RemoteLoginFlowProjection(
            service_id=self.config.service_id,
            platform=flow["platform"],
            account_ref=flow["account_ref"],
            flow_id=flow_id,
            state=flow["state"],
            created_at=flow["created_at"],
            expires_at=flow["expires_at"],
            updated_at=now,
            qr_expires_at=flow["expires_at"],
        )

    async def qr_presentation(self, *, flow_id: str, tenant_ref: str) -> RemoteQrPresentation:
        flow = self._flows.get(flow_id)
        if not flow:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "login flow not found",
                service_id=self.config.service_id,
                capability="account.login",
            )
        return RemoteQrPresentation(
            service_id=self.config.service_id,
            flow_id=flow_id,
            object_ref=flow["qr_code_url"],
            expires_at=flow["expires_at"],
            content_type="image/png",
        )

    async def poll_login(
        self, *, flow_id: str, tenant_ref: str, idempotency_key: str | None = None
    ) -> RemoteLoginFlowProjection:
        flow = self._flows.get(flow_id)
        if not flow:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "login flow not found",
                service_id=self.config.service_id,
                capability="account.login",
            )
        now = datetime.now(UTC)
        poll_tool = await self._find_tool("_login_poll", "login_poll")
        if poll_tool:
            args: dict[str, Any] = {"request": {}}
            if flow.get("qr_code"):
                args["request"]["qr_code"] = flow["qr_code"]

            raw: Mapping[str, Any] = {}
            try:
                raw = await self._mcp._rpc("tools/call", {"name": poll_tool, "arguments": args})
            except Exception:
                pass

            if not raw or raw.get("isError"):
                try:
                    raw = await self._mcp._rpc("tools/call", {"name": poll_tool, "arguments": {}})
                except Exception:
                    raw = {}

            text = ""
            content_items = raw.get("content", [])
            if isinstance(content_items, list) and content_items:
                text = content_items[0].get("text", "")
            parsed: dict[str, Any] = {}
            if text:
                try:
                    parsed = json.loads(text)
                except Exception:
                    pass
            if not parsed and isinstance(raw.get("structuredContent"), dict):
                parsed = raw["structuredContent"]

            sub = (
                parsed.get("result")
                if isinstance(parsed.get("result"), dict)
                else (parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed)
            )
            st = str(
                sub.get("state")
                or sub.get("status")
                or parsed.get("state")
                or parsed.get("status")
                or ""
            ).lower()
            is_logged_in = bool(
                sub.get("logged_in")
                or parsed.get("logged_in")
                or sub.get("authenticated")
                or parsed.get("authenticated")
            )
            ok = bool(parsed.get("ok", False) or sub.get("ok", False))

            if is_logged_in or st in ("logged_in", "authenticated", "success", "succeeded") or (ok and st not in ("waiting", "scanned", "expired", "cancelled", "")):
                flow["state"] = "authenticated"
            elif st in ("expired", "timeout", "timed_out"):
                flow["state"] = "expired"
            elif st in ("scanned", "scan", "waiting_for_confirmation"):
                flow["state"] = "scanned"
            elif st in ("cancelled", "canceled"):
                flow["state"] = "cancelled"
            elif st in ("failed", "error"):
                flow["state"] = "failed"
            else:
                flow["state"] = "waiting"

        if flow["state"] != "authenticated":
            status_tool = await self._find_tool("_login_status", "login_status")
            if status_tool:
                try:
                    s_raw = await self._mcp._rpc("tools/call", {"name": status_tool, "arguments": {}})
                    s_text = ""
                    s_items = s_raw.get("content", [])
                    if isinstance(s_items, list) and s_items:
                        s_text = s_items[0].get("text", "")
                    s_parsed: dict[str, Any] = {}
                    if s_text:
                        try:
                            s_parsed = json.loads(s_text)
                        except Exception:
                            pass
                    if not s_parsed and isinstance(s_raw.get("structuredContent"), dict):
                        s_parsed = s_raw["structuredContent"]
                    s_sub = (
                        s_parsed.get("result")
                        if isinstance(s_parsed.get("result"), dict)
                        else (s_parsed.get("data") if isinstance(s_parsed.get("data"), dict) else s_parsed)
                    )
                    s_status = str(s_sub.get("status") or s_sub.get("state") or "").lower()
                    if s_sub.get("logged_in") is True or s_sub.get("return_code") == 0 or s_status in ("authenticated", "logged_in"):
                        flow["state"] = "authenticated"
                except Exception:
                    pass

        if flow["state"] == "authenticated":
            self._accounts[flow["account_ref"]] = RemoteAccountProjection(
                service_id=self.config.service_id,
                platform=flow["platform"],
                account_ref=flow["account_ref"],
                alias=f"{flow['platform'].value} 默认账号",
                status="active",
                health="healthy",
                session_version=1,
            )

        return RemoteLoginFlowProjection(
            service_id=self.config.service_id,
            platform=flow["platform"],
            account_ref=flow["account_ref"],
            flow_id=flow_id,
            state=flow["state"],
            created_at=flow["created_at"],
            expires_at=flow["expires_at"],
            updated_at=now,
            qr_expires_at=flow["expires_at"],
        )

    async def cancel_login(
        self, *, flow_id: str, tenant_ref: str, reason: str | None = None
    ) -> RemoteLoginFlowProjection:
        flow = self._flows.pop(flow_id, None)
        now = datetime.now(UTC)
        if flow is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "login flow not found",
                service_id=self.config.service_id,
                capability="account.login",
            )
        try:
            logout_tool = await self._find_tool("_login_logout", "login_logout")
            if logout_tool:
                await self._mcp._rpc("tools/call", {"name": logout_tool, "arguments": {}})
        except Exception:
            pass

        return RemoteLoginFlowProjection(
            service_id=self.config.service_id,
            platform=flow["platform"],
            account_ref=flow["account_ref"],
            flow_id=flow_id,
            state="canceled",
            created_at=flow["created_at"],
            expires_at=flow["expires_at"],
            updated_at=now,
            qr_expires_at=flow["expires_at"],
        )

    async def invoke(self, request: RemoteSourceInvocation) -> object:
        return await self._mcp.call_tool(request.capability, request.query)

    async def aclose(self) -> None:
        self._closed = True
        await self._mcp.aclose()


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

    @staticmethod
    def _normalize_channel(platform: PlatformChannel | str) -> PlatformChannel:
        val_str = str(getattr(platform, "value", platform))
        if val_str in ("xhs", "xiaohongshu"):
            return PlatformChannel("xhs_pc")
        if val_str in ("xiecheng", "ctrip_flight", "ctrip_hotel"):
            return PlatformChannel("ctrip")
        return PlatformChannel(val_str)

    def tools_for(self, platform: PlatformChannel) -> tuple[McpToolDescriptor, ...]:
        """Return the current allow-listed MCP tools for one channel."""

        norm_platform = self._normalize_channel(platform)
        configs = [config for config in self.configs if norm_platform in config.channels or platform in config.channels]
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
            logger.warning(
                f"Descriptor for {config.service_id} expired at {descriptor.expires_at}; serving tools in degraded mode"
            )
        return tuple(self._tools.get(config.service_id, {}).values())

    async def _ensure_clients(self, config: AccountServiceConfig) -> None:
        if config.protocol in {AccountServiceProtocol.HTTP, AccountServiceProtocol.HTTP_MCP}:
            if config.service_id not in self._http:
                self._http[config.service_id] = self._http_factory(config)
        if config.protocol in {AccountServiceProtocol.MCP, AccountServiceProtocol.HTTP_MCP}:
            if config.service_id not in self._mcp:
                self._mcp[config.service_id] = self._mcp_factory(config)
        if config.protocol is AccountServiceProtocol.MCP:
            if config.service_id not in self._http:
                self._http[config.service_id] = McpAccountLoginAdapter(
                    config, self._mcp[config.service_id]
                )

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
                    if previous is not None:
                        self._health[config.service_id] = AccountServiceHealth(
                            service_id=config.service_id,
                            state="degraded",
                            detail=f"refresh failed; previous descriptor retained: {exc.envelope.code.value}",
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

    async def register_service(
        self, config: AccountServiceConfig, probe: bool = True
    ) -> AccountServiceHealth:
        """Dynamically add or update an account service config at runtime."""
        async with self._refresh_lock:
            if self._closed:
                raise AccountServiceRegistryError("account service registry is closed")

            other_configs = [c for c in self.configs if c.service_id != config.service_id]
            test_configs = tuple([*other_configs, config])
            self._validate_configs(test_configs)
            self.configs = test_configs

            old_http = self._http.pop(config.service_id, None)
            if old_http and hasattr(old_http, "aclose"):
                try:
                    await old_http.aclose()
                except Exception:
                    pass
            old_mcp = self._mcp.pop(config.service_id, None)
            if old_mcp and hasattr(old_mcp, "aclose"):
                try:
                    await old_mcp.aclose()
                except Exception:
                    pass

            await self._ensure_clients(config)
            if probe:
                try:
                    descriptor = await self._refresh_one(config)
                    self._descriptors[config.service_id] = descriptor
                    health = AccountServiceHealth(
                        service_id=config.service_id,
                        state="ready",
                        descriptor_version=descriptor.contract_version,
                    )
                except RemoteAccountServiceError as exc:
                    self._descriptors.pop(config.service_id, None)
                    self._tools.pop(config.service_id, None)
                    health = AccountServiceHealth(
                        service_id=config.service_id,
                        state="dependency-unavailable",
                        detail=exc.envelope.code.value,
                        descriptor_version=config.descriptor_version,
                    )
            else:
                health = AccountServiceHealth(
                    service_id=config.service_id,
                    state="disabled",
                    detail="unprobed",
                    descriptor_version=config.descriptor_version,
                )
            self._health[config.service_id] = health
            return health

    async def unregister_service(self, service_id: str) -> None:
        """Dynamically remove an account service at runtime."""
        async with self._refresh_lock:
            self.configs = tuple(c for c in self.configs if c.service_id != service_id)
            old_http = self._http.pop(service_id, None)
            if old_http and hasattr(old_http, "aclose"):
                try:
                    await old_http.aclose()
                except Exception:
                    pass
            old_mcp = self._mcp.pop(service_id, None)
            if old_mcp and hasattr(old_mcp, "aclose"):
                try:
                    await old_mcp.aclose()
                except Exception:
                    pass
            self._descriptors.pop(service_id, None)
            self._tools.pop(service_id, None)
            self._health.pop(service_id, None)
            self._mcp_health.pop(service_id, None)

    async def probe_candidate(
        self, config: AccountServiceConfig
    ) -> dict[str, Any]:
        """Probe an endpoint without modifying registry state."""
        http_client = self._http_factory(config)
        mcp_client = self._mcp_factory(config)
        discovered_tools = []
        capabilities = []
        state = "ready"
        detail = None
        http_error: Exception | None = None
        mcp_error: Exception | None = None
        start_t = asyncio.get_event_loop().time()

        try:
            if config.protocol in {AccountServiceProtocol.HTTP, AccountServiceProtocol.HTTP_MCP}:
                try:
                    desc = await http_client.capabilities()
                    capabilities = list(desc.capabilities)
                except Exception as exc:
                    http_error = exc

            if config.protocol in {AccountServiceProtocol.MCP, AccountServiceProtocol.HTTP_MCP}:
                try:
                    tools = await mcp_client.list_tools()
                    discovered_tools = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "side_effect": getattr(t, "side_effect", "read_only"),
                            "inputSchema": getattr(t, "input_schema", {}),
                        }
                        for t in tools
                    ]
                except Exception as exc:
                    mcp_error = exc

            if config.protocol is AccountServiceProtocol.HTTP:
                if http_error:
                    state = "dependency-unavailable"
                    detail = str(http_error)
            elif config.protocol is AccountServiceProtocol.MCP:
                if mcp_error:
                    state = "dependency-unavailable"
                    detail = str(mcp_error)
            else:  # HTTP_MCP
                if mcp_error and http_error:
                    state = "dependency-unavailable"
                    detail = f"MCP: {mcp_error}; HTTP: {http_error}"
                elif mcp_error:
                    state = "degraded"
                    detail = f"MCP 工具探测失败: {mcp_error}"
                elif http_error:
                    # Discovered MCP tools successfully, HTTP control-plane is not implemented
                    state = "ready"
                    detail = f"成功探测到 {len(discovered_tools)} 个 MCP 工具 (注: HTTP 控制面端点未实现或返回错误: {http_error})"
        finally:
            if hasattr(http_client, "aclose"):
                try:
                    await http_client.aclose()
                except Exception:
                    pass
            if hasattr(mcp_client, "aclose"):
                try:
                    await mcp_client.aclose()
                except Exception:
                    pass
        latency_ms = round((asyncio.get_event_loop().time() - start_t) * 1000, 1)
        return {
            "service_id": config.service_id,
            "state": state,
            "detail": detail,
            "latency_ms": latency_ms,
            "capabilities": capabilities,
            "tools": discovered_tools,
        }


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

    async def ensure_fresh(self, platform: PlatformChannel | None = None) -> None:
        """Proactively refresh expired descriptors for platform (or all platforms)."""
        norm_platform = self._normalize_channel(platform) if platform is not None else None
        targets = (
            [cfg for cfg in self.configs if norm_platform in cfg.channels or platform in cfg.channels]
            if norm_platform is not None
            else list(self.configs)
        )
        now = datetime.now(UTC)
        for cfg in targets:
            desc = self._descriptors.get(cfg.service_id)
            if desc is None or desc.expires_at <= now:
                await self._refresh_service(cfg)

    async def _refresh_service(self, config: AccountServiceConfig) -> AccountServiceDescriptor | None:
        """Refresh a single service descriptor with degraded fallback."""
        async with self._refresh_lock:
            if self._closed:
                return None
            await self._ensure_clients(config)
            try:
                descriptor = await self._refresh_one(config)
                self._descriptors[config.service_id] = descriptor
                self._health[config.service_id] = AccountServiceHealth(
                    service_id=config.service_id,
                    state="ready",
                    descriptor_version=descriptor.contract_version,
                )
                return descriptor
            except Exception as exc:
                logger.warning(
                    f"Service refresh failed for {config.service_id}: {exc}"
                )
                previous = self._descriptors.get(config.service_id)
                if previous is not None:
                    self._health[config.service_id] = AccountServiceHealth(
                        service_id=config.service_id,
                        state="degraded",
                        detail=f"refresh failed; using cached descriptor: {exc}",
                        descriptor_version=previous.contract_version,
                    )
                    return previous
                self._health[config.service_id] = AccountServiceHealth(
                    service_id=config.service_id,
                    state="dependency-unavailable",
                    detail=str(exc),
                    descriptor_version=config.descriptor_version,
                )
                return None

    def _service_for(
        self, platform: PlatformChannel, capability: str | None = None
    ) -> tuple[AccountServiceConfig, AccountServiceClientPort]:
        norm_platform = self._normalize_channel(platform)
        matches = [config for config in self.configs if norm_platform in config.channels or platform in config.channels]
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
            logger.warning(
                f"Descriptor for {config.service_id} expired at {descriptor.expires_at}; serving request in degraded state"
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
        await self.ensure_fresh(kwargs.get("platform"))
        _, client = self._service_for(kwargs["platform"], "account.register")
        return await client.register_account(**kwargs)

    async def account(self, **kwargs: Any) -> RemoteAccountProjection:
        await self.ensure_fresh(kwargs.get("platform"))
        _, client = self._service_for(kwargs["platform"], "account.read")
        return await client.account(**kwargs)

    async def start_login(self, **kwargs: Any) -> RemoteLoginFlowProjection:
        await self.ensure_fresh(kwargs.get("platform"))
        _, client = self._service_for(kwargs["platform"], "account.login")
        flow = await client.start_login(**kwargs)
        self._flow_platform[flow.flow_id] = kwargs["platform"]
        return flow

    async def start_qr_login(self, **kwargs: Any) -> RemoteLoginFlowProjection:
        await self.ensure_fresh(kwargs.get("platform"))
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

        norm_platform = self._normalize_channel(platform)
        configs = [config for config in self.configs if norm_platform in config.channels or platform in config.channels]
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
        await self.ensure_fresh(platform)
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
        await self.ensure_fresh(platform)
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
        await self.ensure_fresh(platform)
        _, client = self._service_for(platform, "account.login")
        flow = await client.poll_login(
            flow_id=flow_id, tenant_ref=tenant_ref, idempotency_key=idempotency_key
        )
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    async def cancel_login(
        self, *, platform: PlatformChannel, flow_id: str, tenant_ref: str, reason: str | None = None
    ) -> RemoteLoginFlowProjection:
        await self.ensure_fresh(platform)
        _, client = self._service_for(platform, "account.login")
        flow = await client.cancel_login(flow_id=flow_id, tenant_ref=tenant_ref, reason=reason)
        self._flow_platform[flow.flow_id] = flow.platform
        return flow

    async def invoke(self, request: RemoteSourceInvocation) -> object:
        await self.ensure_fresh(request.platform)
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
        await self.ensure_fresh(platform)
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

        await self.ensure_fresh(platform)
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
        val_str = str(getattr(value, "value", value))
        if val_str in ("xiecheng", "ctrip_flight", "ctrip_hotel"):
            val_str = "ctrip"
        elif val_str in ("xhs", "xiaohongshu"):
            val_str = "xhs_pc"
        try:
            return PlatformChannel(val_str)
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
                from loguru import logger
                logger.warning(f"_translate caught RemoteAccountServiceError: {exc}, category={exc.category}, envelope={getattr(exc, 'envelope', None)}")
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
                    f"remote account service operation failed: {exc}",
                    status_code=status,
                ) from exc

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
