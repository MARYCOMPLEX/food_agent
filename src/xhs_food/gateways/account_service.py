"""HTTP and MCP clients for provider-owned account microservices.

The clients are deliberately provider-neutral.  They carry opaque account and
flow references only; provider credentials remain inside the upstream service.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Any, Protocol, cast

import httpx

from xhs_food.contracts.account import PlatformChannel
from xhs_food.contracts.account_service import (
    ACCOUNT_SERVICE_CONTRACT_VERSION,
    MCP_PROTOCOL_VERSION,
    AccountServiceConfig,
    AccountServiceDescriptor,
    McpToolCallResult,
    McpToolDescriptor,
    RemoteAccountProjection,
    RemoteErrorCategory,
    RemoteErrorEnvelope,
    RemoteLoginFlowProjection,
    RemotePayloadRejected,
    RemoteQrPresentation,
    RemoteSideEffect,
    RemoteSourceInvocation,
    sanitize_remote_payload,
    validate_remote_payload,
)

AuthHeaderProvider = Callable[[], Mapping[str, str] | Awaitable[Mapping[str, str] | None] | None]


class AccountServiceClientPort(Protocol):
    config: AccountServiceConfig

    async def capabilities(self) -> AccountServiceDescriptor: ...

    async def register_account(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        alias: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteAccountProjection: ...

    async def start_qr_login(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection: ...

    async def account(
        self, *, platform: PlatformChannel, account_ref: str, tenant_ref: str
    ) -> RemoteAccountProjection: ...

    async def start_login(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        tenant_ref: str,
        mode: str,
        credential_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection: ...

    async def flow_status(self, *, flow_id: str, tenant_ref: str) -> RemoteLoginFlowProjection: ...

    async def qr_presentation(self, *, flow_id: str, tenant_ref: str) -> RemoteQrPresentation: ...

    async def poll_login(
        self, *, flow_id: str, tenant_ref: str, idempotency_key: str | None = None
    ) -> RemoteLoginFlowProjection: ...

    async def cancel_login(
        self, *, flow_id: str, tenant_ref: str, reason: str | None = None
    ) -> RemoteLoginFlowProjection: ...

    async def invoke(self, request: RemoteSourceInvocation) -> object: ...

    async def aclose(self) -> None: ...


class RemoteAccountServiceError(RuntimeError):
    """Stable error that is safe to expose to the main application's boundary."""

    def __init__(
        self,
        category: RemoteErrorCategory,
        message: str,
        *,
        service_id: str,
        status_code: int | None = None,
        capability: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.category = category
        self.service_id = service_id
        self.status_code = status_code
        self.capability = capability
        self.retryable = retryable
        self.envelope = RemoteErrorEnvelope(
            code=category,
            message=message,
            service_id=service_id,
            capability=capability,
            retryable=retryable,
        )
        super().__init__(message)


def _category_for_status(status_code: int) -> RemoteErrorCategory:
    return {
        401: RemoteErrorCategory.AUTHENTICATION,
        403: RemoteErrorCategory.AUTHORIZATION,
        409: RemoteErrorCategory.CONFLICT,
        408: RemoteErrorCategory.TIMEOUT,
        429: RemoteErrorCategory.RATE_LIMITED,
    }.get(
        status_code,
        RemoteErrorCategory.DEPENDENCY_UNAVAILABLE
        if status_code >= 500
        else RemoteErrorCategory.INVALID,
    )


def _data(body: object) -> object:
    if isinstance(body, Mapping) and body.get("success") is True and "data" in body:
        return body["data"]
    return body


def _ensure_mapping(value: object, *, service_id: str, capability: str | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RemoteAccountServiceError(
            RemoteErrorCategory.INVALID,
            "remote service returned an invalid envelope",
            service_id=service_id,
            capability=capability,
        )
    return cast(Mapping[str, Any], value)


class HttpAccountServiceClient:
    """Bounded async HTTP client for one account-service microservice."""

    def __init__(
        self,
        config: AccountServiceConfig,
        *,
        client: httpx.AsyncClient | None = None,
        auth_headers: AuthHeaderProvider | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(
            base_url=str(config.base_url).rstrip("/"),
            timeout=httpx.Timeout(config.timeout_seconds),
            headers={"Accept": "application/json", "X-Account-Service-Contract": ACCOUNT_SERVICE_CONTRACT_VERSION},
        )
        self._owns_client = client is None
        self._auth_headers = auth_headers
        self._descriptor: AccountServiceDescriptor | None = None
        self._closed = False

    @property
    def descriptor(self) -> AccountServiceDescriptor | None:
        return self._descriptor

    async def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._auth_headers is not None:
            values = self._auth_headers()
            if asyncio.iscoroutine(values) or isinstance(values, Awaitable):
                values = await values
            if values:
                headers.update({str(key): str(value) for key, value in values.items()})
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        capability: str | None = None,
    ) -> object:
        if self._closed:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "remote service client is closed",
                service_id=self.config.service_id,
                capability=capability,
            )
        if json is not None:
            validate_remote_payload(json)
        headers = await self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._client.request(
                method,
                path,
                params=dict(params or {}),
                json=json,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.TIMEOUT,
                "remote account service timed out",
                service_id=self.config.service_id,
                capability=capability,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "remote account service is unavailable",
                service_id=self.config.service_id,
                capability=capability,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            category = _category_for_status(response.status_code)
            raise RemoteAccountServiceError(
                category,
                "remote account service request failed",
                service_id=self.config.service_id,
                status_code=response.status_code,
                capability=capability,
                retryable=category in {RemoteErrorCategory.TIMEOUT, RemoteErrorCategory.RATE_LIMITED},
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote account service returned non-JSON data",
                service_id=self.config.service_id,
                capability=capability,
            ) from exc
        sanitized = sanitize_remote_payload(body)
        if isinstance(sanitized, Mapping) and sanitized.get("success") is False:
            error = sanitized.get("error")
            code = RemoteErrorCategory.INVALID
            if isinstance(error, str):
                with suppress(ValueError):
                    code = RemoteErrorCategory(error)
            raise RemoteAccountServiceError(
                code,
                "remote account service rejected the request",
                service_id=self.config.service_id,
                capability=capability,
            )
        return sanitized

    async def capabilities(self) -> AccountServiceDescriptor:
        body = _ensure_mapping(await self._request("GET", "/v1/capabilities"), service_id=self.config.service_id)
        payload = _ensure_mapping(_data(body), service_id=self.config.service_id)
        try:
            descriptor = AccountServiceDescriptor.model_validate(payload)
        except Exception as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote capability descriptor is invalid",
                service_id=self.config.service_id,
            ) from exc
        configured_channels = set(self.config.channels)
        configured_capabilities = set(self.config.capabilities)
        if descriptor.service_id != self.config.service_id:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote service identity does not match configuration",
                service_id=self.config.service_id,
            )
        if descriptor.contract_version != self.config.descriptor_version:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote contract version is not approved",
                service_id=self.config.service_id,
            )
        if not configured_channels.issubset(set(descriptor.platform_channels)):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote service does not advertise configured channels",
                service_id=self.config.service_id,
            )
        if not configured_capabilities.issubset(set(descriptor.capabilities)):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "remote service does not advertise configured capabilities",
                service_id=self.config.service_id,
            )
        self._descriptor = descriptor
        return descriptor

    def _check_channel(self, platform: PlatformChannel) -> None:
        if platform not in self.config.channels:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "platform channel is not assigned to this service",
                service_id=self.config.service_id,
            )

    async def register_account(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        alias: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteAccountProjection:
        self._check_channel(platform)
        body = await self._request(
            "POST",
            "/v1/accounts",
            json={"tenant_ref": tenant_ref, "platform": platform.value, "account_ref": account_ref, "alias": alias},
            idempotency_key=idempotency_key,
            capability="account.register",
        )
        return RemoteAccountProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def account(self, *, platform: PlatformChannel, account_ref: str, tenant_ref: str) -> RemoteAccountProjection:
        self._check_channel(platform)
        body = await self._request(
            "GET",
            f"/v1/accounts/{platform.value}/{account_ref}",
            params={"tenant_ref": tenant_ref},
            capability="account.read",
        )
        return RemoteAccountProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def start_qr_login(
        self,
        *,
        platform: PlatformChannel,
        account_ref: str,
        tenant_ref: str,
        idempotency_key: str | None = None,
    ) -> RemoteLoginFlowProjection:
        self._check_channel(platform)
        body = await self._request(
            "POST",
            f"/v1/accounts/{platform.value}/{account_ref}/login/qr",
            json={"tenant_ref": tenant_ref, "mode": "qr"},
            idempotency_key=idempotency_key,
            capability="account.login",
        )
        return RemoteLoginFlowProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

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
        self._check_channel(platform)
        payload: dict[str, object] = {"tenant_ref": tenant_ref, "mode": mode}
        if credential_ref is not None:
            payload["credential_ref"] = credential_ref
        body = await self._request(
            "POST",
            f"/v1/accounts/{platform.value}/{account_ref}/login",
            json=payload,
            idempotency_key=idempotency_key,
            capability="account.login",
        )
        return RemoteLoginFlowProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def flow_status(self, *, flow_id: str, tenant_ref: str) -> RemoteLoginFlowProjection:
        body = await self._request(
            "GET",
            f"/v1/login/{flow_id}/status",
            params={"tenant_ref": tenant_ref},
            capability="account.login",
        )
        return RemoteLoginFlowProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def qr_presentation(self, *, flow_id: str, tenant_ref: str) -> RemoteQrPresentation:
        body = await self._request(
            "GET",
            f"/v1/login/{flow_id}/qr",
            params={"tenant_ref": tenant_ref},
            capability="account.login",
        )
        return RemoteQrPresentation.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def poll_login(self, *, flow_id: str, tenant_ref: str, idempotency_key: str | None = None) -> RemoteLoginFlowProjection:
        body = await self._request(
            "POST",
            f"/v1/login/{flow_id}/poll",
            json={"tenant_ref": tenant_ref},
            idempotency_key=idempotency_key,
            capability="account.login",
        )
        return RemoteLoginFlowProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def cancel_login(self, *, flow_id: str, tenant_ref: str, reason: str | None = None) -> RemoteLoginFlowProjection:
        payload: dict[str, object] = {"tenant_ref": tenant_ref}
        if reason:
            payload["reason"] = reason
        body = await self._request("POST", f"/v1/login/{flow_id}/cancel", json=payload, capability="account.login")
        return RemoteLoginFlowProjection.model_validate(_ensure_mapping(_data(body), service_id=self.config.service_id))

    async def invoke(self, request: RemoteSourceInvocation) -> object:
        if request.service_id != self.config.service_id:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "source invocation service mismatch",
                service_id=self.config.service_id,
                capability=request.capability,
            )
        self._check_channel(request.platform)
        body = await self._request(
            "POST",
            "/v1/source/invoke",
            json=request.model_dump(mode="json"),
            capability=request.capability,
        )
        return sanitize_remote_payload(_data(body))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()


class McpAccountServiceClient:
    """Minimal MCP JSON-RPC client used for capability discovery and tools."""

    def __init__(
        self,
        config: AccountServiceConfig,
        *,
        client: httpx.AsyncClient | None = None,
        auth_headers: AuthHeaderProvider | None = None,
    ) -> None:
        self.config = config
        endpoint = str(config.mcp_url or (str(config.base_url).rstrip("/") + "/mcp"))
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds))
        self._owns_client = client is None
        self._endpoint = endpoint
        self._auth_headers = auth_headers
        self._session_id: str | None = None
        self._next_id = itertools.count(1)
        self._initialized = False
        self._tools: dict[str, McpToolDescriptor] = {}
        self._closed = False

    @property
    def tools(self) -> Mapping[str, McpToolDescriptor]:
        return dict(self._tools)

    async def _rpc(self, method: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if self._closed:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "MCP client is closed",
                service_id=self.config.service_id,
            )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._auth_headers:
            values = self._auth_headers()
            if asyncio.iscoroutine(values) or isinstance(values, Awaitable):
                values = await values
            if values:
                headers.update({str(key): str(value) for key, value in values.items()})
        request_id = next(self._next_id)
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params or {})}
        validate_remote_payload(body)
        try:
            response = await self._client.post(self._endpoint, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.TIMEOUT,
                "MCP service timed out",
                service_id=self.config.service_id,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "MCP service is unavailable",
                service_id=self.config.service_id,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise RemoteAccountServiceError(
                _category_for_status(response.status_code),
                "MCP service request failed",
                service_id=self.config.service_id,
                status_code=response.status_code,
            )
        try:
            raw = response.json()
        except ValueError as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP service returned non-JSON data",
                service_id=self.config.service_id,
            ) from exc
        value = _ensure_mapping(sanitize_remote_payload(raw), service_id=self.config.service_id)
        if value.get("jsonrpc") != "2.0" or value.get("id") != request_id:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP service returned an invalid JSON-RPC envelope",
                service_id=self.config.service_id,
            )
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if "error" in value:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP service returned a protocol error",
                service_id=self.config.service_id,
            )
        return _ensure_mapping(value.get("result", value), service_id=self.config.service_id)

    async def initialize(self) -> Mapping[str, Any]:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "xhs-food-agent", "version": "1"},
            },
        )
        protocol_version = result.get("protocolVersion")
        if protocol_version != MCP_PROTOCOL_VERSION:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP protocol version is not supported",
                service_id=self.config.service_id,
            )
        self._initialized = True
        return result

    async def list_tools(self) -> tuple[McpToolDescriptor, ...]:
        if not self._initialized:
            await self.initialize()
        result = await self._rpc("tools/list", {})
        raw_tools = result.get("tools", ())
        if not isinstance(raw_tools, (list, tuple)):
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP tools/list returned an invalid tool list",
                service_id=self.config.service_id,
            )
        accepted: dict[str, McpToolDescriptor] = {}
        allowed = set(self.config.capabilities)
        for raw in raw_tools:
            if not isinstance(raw, Mapping):
                continue
            value = dict(raw)
            if "input_schema" not in value and "inputSchema" in value:
                value["input_schema"] = value["inputSchema"]
            value.pop("inputSchema", None)
            if "output_schema" not in value and "outputSchema" in value:
                value["output_schema"] = value["outputSchema"]
            value.pop("outputSchema", None)
            value.setdefault("capability", value.get("name", "unknown"))
            value.setdefault("capability_version", self.config.descriptor_version)
            value.setdefault("side_effect", RemoteSideEffect.READ_ONLY.value)
            value.setdefault("input_schema", {})
            try:
                descriptor = McpToolDescriptor.model_validate(value)
            except Exception:
                continue
            if allowed and not any(
                descriptor.capability == item or descriptor.capability.startswith(item + ".")
                for item in allowed
            ):
                continue
            if descriptor.side_effect not in {RemoteSideEffect.READ_ONLY, RemoteSideEffect.ACCOUNT_LOGIN}:
                continue
            accepted[descriptor.name] = descriptor
        self._tools = accepted
        return tuple(accepted.values())

    async def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> McpToolCallResult:
        descriptor = self._tools.get(name)
        if descriptor is None:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.AUTHORIZATION,
                "MCP tool is not allow-listed",
                service_id=self.config.service_id,
            )
        args = dict(arguments or {})
        try:
            validate_remote_payload(args, "arguments")
        except RemotePayloadRejected as exc:
            raise RemoteAccountServiceError(
                RemoteErrorCategory.INVALID,
                "MCP arguments contain forbidden material",
                service_id=self.config.service_id,
                capability=descriptor.capability,
            ) from exc
        result = await self._rpc("tools/call", {"name": name, "arguments": args})
        content = sanitize_remote_payload(result.get("content", result))
        return McpToolCallResult(tool_name=name, is_error=bool(result.get("isError", False)), content=content)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()


__all__ = [
    "AccountServiceClientPort",
    "AuthHeaderProvider",
    "HttpAccountServiceClient",
    "McpAccountServiceClient",
    "RemoteAccountServiceError",
]
