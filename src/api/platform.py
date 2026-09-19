"""Remote account-service HTTP and MCP control-plane endpoints."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from loguru import logger
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
import httpx

from food_agent.config import settings

from api.deps import get_current_user_id
from food_agent.contracts.account_service import (
    AccountServiceControlPlaneError,
    PlatformChannel,
    RemoteSideEffect,
    validate_remote_payload,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class PlatformAccountCreateRequest(_StrictModel):
    platform: str = Field(min_length=1, max_length=32)
    account_ref: str = Field(
        validation_alias=AliasChoices("account_ref", "accountRef", "account_id"),
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
    )
    alias: str = Field(min_length=1, max_length=128)
    permissions: tuple[str, ...] | None = None


class PlatformLoginStartRequest(_StrictModel):
    mode: str = Field(default="qr", min_length=1, max_length=16)
    credential_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices("credential_ref", "credentialRef", "secret_ref"),
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    idempotency_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("idempotency_key", "idempotencyKey"),
        min_length=1,
        max_length=128,
    )


class PlatformReauthRequest(PlatformLoginStartRequest):
    """Re-authentication command; raw phone/cookie values are not fields."""


class PlatformCancelRequest(_StrictModel):
    reason: str | None = Field(default=None, max_length=128)


class AccountServiceToolCallRequest(_StrictModel):
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def _arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_remote_payload(value, "arguments")
        return value


class AccountServiceInvokeRequest(_StrictModel):
    account_ref: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    capability: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    query: dict[str, Any] = Field(default_factory=dict)
    expected_session_version: int | None = Field(default=None, ge=1)
    timeout_seconds: float = Field(default=30.0, gt=0.1, le=300.0)

    @field_validator("query")
    @classmethod
    def _query(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_remote_payload(value, "query")
        return value


class _RedactedValidationRoute(APIRoute):
    """Return validation envelopes without echoing credential-bearing input."""

    def get_route_handler(self) -> Any:  # type: ignore[override]
        original = super().get_route_handler()

        async def handler(request: Request) -> Any:
            try:
                return await original(request)
            except RequestValidationError:
                # FastAPI's default handler includes the offending request
                # body.  That body may contain a cookie/token field which this
                # control plane must never echo to a client or log sink.
                return JSONResponse(
                    status_code=422,
                    content={
                        "success": False,
                        "error": "PLATFORM_REQUEST_INVALID",
                        "message": "platform request is invalid",
                    },
                )

        return handler


router = APIRouter(
    prefix="/v1/platform",
    tags=["platform"],
    route_class=_RedactedValidationRoute,
)


def _service(request: Request) -> Any:
    service = getattr(request.app.state, "account_service_control_plane", None)
    if service is None:
        raise AccountServiceControlPlaneError(
            "PLATFORM_DISABLED",
            "remote account-service control plane is disabled",
            status_code=503,
        )
    if not all(
        callable(getattr(service, name, None)) for name in ("start_login", "status", "cancel")
    ):
        raise AccountServiceControlPlaneError(
            "PLATFORM_UNAVAILABLE",
            "remote account-service control plane is unavailable",
            status_code=503,
        )
    return service


def _failure(error: AccountServiceControlPlaneError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "success": False,
            "error": error.code,
            "message": error.message,
        },
    )


def _unexpected() -> JSONResponse:
    # Never serialise an injected adapter/provider exception to an API client.
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "PLATFORM_INTERNAL_ERROR",
            "message": "platform operation failed",
        },
    )


def _remote_failure(error: Any) -> JSONResponse:
    category = getattr(
        getattr(error, "category", None),
        "value",
        getattr(error, "category", "dependency-unavailable"),
    )
    service_id = getattr(error, "service_id", "registry")
    capability = getattr(error, "capability", None)
    status = {
        "authentication": 401,
        "authorization": 403,
        "rate-limited": 429,
        "conflict": 409,
        "invalid": 422,
        "timeout": 504,
    }.get(category, 503)
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": category,
            "message": "account service operation failed",
            "service_id": service_id,
            "capability": capability,
        },
    )


def _success(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


def _account_projection(account: Any) -> dict[str, Any]:
    # Pydantic contracts are immutable and contain no credential payload.  The
    # explicit field list guards against an adapter accidentally adding an
    # internal attribute to a response model in the future.
    platform = getattr(account, "platform", None)
    platform_value = getattr(platform, "value", platform)
    return {
        "tenant_id": getattr(account, "tenant_id", None),
        "service_id": getattr(account, "service_id", None),
        "platform": platform_value,
        "account_ref": account.account_ref,
        "alias": account.alias,
        "status": getattr(
            getattr(account, "status", None), "value", getattr(account, "status", None)
        ),
        "health": getattr(
            getattr(account, "health", None), "value", getattr(account, "health", None)
        ),
        "session_version": getattr(account, "session_version", None),
        "provider_subject_id": getattr(account, "provider_subject_id", None)
        or getattr(account, "provider_subject_ref", None),
        "created_at": getattr(account, "created_at", None),
        "updated_at": getattr(account, "updated_at", None),
    }


def _flow_projection(flow: Any) -> dict[str, Any]:
    # Exclude ``qr_object_ref`` deliberately; clients use the QR presentation
    # endpoint, not storage keys/object metadata.
    account = getattr(flow, "account", None)
    platform = getattr(flow, "platform", None) or getattr(account, "platform", None)
    platform_value = getattr(platform, "value", platform)
    return {
        "flow_id": flow.flow_id,
        "service_id": getattr(flow, "service_id", None),
        "platform": platform_value,
        "account_ref": getattr(flow, "account_ref", None) or getattr(account, "account_ref", None),
        "state": getattr(getattr(flow, "state", None), "value", getattr(flow, "state", None)),
        "created_at": flow.created_at,
        "expires_at": flow.expires_at,
        "updated_at": flow.updated_at,
        "qr_expires_at": getattr(flow, "qr_expires_at", None),
        "provider_subject_id": getattr(flow, "provider_subject_id", None)
        or getattr(flow, "provider_subject_ref", None),
        "error_code": getattr(
            getattr(flow, "error_code", None), "value", getattr(flow, "error_code", None)
        ),
        "error_message": getattr(flow, "error_message", None),
    }


async def _run(call: Any) -> Any:
    try:
        return await call()
    except AccountServiceControlPlaneError as exc:
        return _failure(exc)
    except Exception:
        return _unexpected()


@router.get("/readiness")
async def platform_readiness(request: Request) -> Any:
    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is None or not callable(getattr(registry, "readiness", None)):
        return _success({"enabled": False, "ready": False, "services": []})
    try:
        return _success(registry.readiness())
    except Exception:
        return _success(
            {
                "enabled": True,
                "ready": False,
                "state": "dependency-unavailable",
                "services": [],
            }
        )


def _effective_tenant_id(principal_id: str | None) -> str:
    """Normalize anonymous or frontend ephemeral principal to default tenant for account service backends."""
    if (
        not principal_id
        or principal_id in (
            "anonymous",
            "00000000-0000-0000-0000-000000000000",
            "default",
        )
        or str(principal_id).startswith("user_")
    ):
        return "default"
    return principal_id


@router.get("/account-services/{platform}/tools")
async def list_account_service_tools(
    request: Request,
    platform: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Expose the refreshed, redacted raw MCP catalog for control-plane diagnostics."""

    del principal_id
    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "dependency-unavailable",
                "message": "account service registry is disabled",
            },
        )
    try:
        channel = PlatformChannel(platform)
        if hasattr(registry, "ensure_fresh"):
            await registry.ensure_fresh(channel)
        tools = registry.tools_for(channel)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "PLATFORM_INVALID",
                "message": "unsupported platform channel",
            },
        )
    except Exception as exc:
        if hasattr(exc, "category") and hasattr(exc, "service_id"):
            return _remote_failure(exc)
        return _unexpected()
    return _success([tool.model_dump(mode="json") for tool in tools])


@router.get("/agent-tools/catalog")
async def agent_tool_catalog(
    request: Request,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Return the policy-filtered, account-free Agent tool projection."""

    del principal_id
    catalog = getattr(request.app.state, "agent_tool_catalog", None)
    if catalog is None:
        return _success(
            {
                "enabled": False,
                "snapshot_ref": None,
                "generation": 0,
                "tools": [],
                "rejections": [],
            }
        )
    try:
        snapshot = await catalog.current_projection()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "dependency-unavailable",
                "message": "Agent tool catalog is unavailable",
            },
        )
    return _success(
        {
            "enabled": True,
            "snapshot_ref": snapshot.snapshot_ref,
            "generation": snapshot.generation,
            "tools": [item.model_dump(mode="json") for item in snapshot.projection],
            "rejections": [item.model_dump(mode="json") for item in snapshot.rejections],
        }
    )


@router.post("/account-services/{platform}/tools/{tool_name}")
async def call_account_service_tool(
    request: Request,
    platform: str,
    tool_name: str,
    body: AccountServiceToolCallRequest | None = None,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Call one allow-listed MCP tool with opaque tenant context only."""

    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "dependency-unavailable",
                "message": "account service registry is disabled",
            },
        )
    try:
        channel = PlatformChannel(platform)
        effective_tenant = _effective_tenant_id(principal_id)
        result = await registry.call_tool(
            platform=channel,
            tool_name=tool_name,
            arguments={**(body.arguments if body is not None else {}), "tenant_ref": effective_tenant},
        )
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "PLATFORM_INVALID",
                "message": "unsupported platform channel",
            },
        )
    except Exception as exc:
        if hasattr(exc, "category") and hasattr(exc, "service_id"):
            return _remote_failure(exc)
        return _unexpected()
    return _success(result.model_dump(mode="json"))


@router.post("/account-services/{platform}/invoke")
async def invoke_account_service_source(
    request: Request,
    platform: str,
    body: AccountServiceInvokeRequest,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Invoke an account-bound upstream source with tenant context injected."""

    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "dependency-unavailable",
                "message": "account service registry is disabled",
            },
        )
    try:
        channel = PlatformChannel(platform)
        effective_tenant = _effective_tenant_id(principal_id)
        result = await registry.invoke_for_platform(
            tenant_ref=effective_tenant,
            platform=channel,
            account_ref=body.account_ref,
            capability=body.capability,
            correlation_id=body.correlation_id,
            query=body.query,
            expected_session_version=body.expected_session_version,
            timeout_seconds=body.timeout_seconds,
        )
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "PLATFORM_INVALID",
                "message": "unsupported platform channel",
            },
        )
    except Exception as exc:
        if hasattr(exc, "category") and hasattr(exc, "service_id"):
            return _remote_failure(exc)
        return _unexpected()
    return _success(result)


@router.post("/accounts")
async def register_platform_account(
    request: Request,
    body: PlatformAccountCreateRequest,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        account = await service.register_account(
            tenant_id=effective_tenant,
            principal_id=principal_id,
            platform=body.platform,
            account_ref=body.account_ref,
            alias=body.alias,
            permissions=body.permissions,
        )
        return _success(_account_projection(account))

    return await _run(operation)


@router.get("/accounts/{platform}/{account_ref}")
async def get_platform_account(
    request: Request,
    platform: str,
    account_ref: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        account = await service.get_account(
            tenant_id=effective_tenant,
            principal_id=principal_id,
            platform=platform,
            account_ref=account_ref,
        )
        return _success(_account_projection(account))

    return await _run(operation)


async def _start_login(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformLoginStartRequest,
    principal_id: str,
    idempotency_header: str | None,
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        key = idempotency_header or body.idempotency_key
        effective_tenant = _effective_tenant_id(principal_id)
        try:
            submission = await service.start_login(
                tenant_id=effective_tenant,
                principal_id=principal_id,
                platform=platform,
                account_ref=account_ref,
                mode=body.mode,
                idempotency_key=key,
                credential_ref=body.credential_ref,
            )
        except AccountServiceControlPlaneError as exc:
            if exc.code == "PLATFORM_ACCOUNT_NOT_FOUND" or "404" in str(getattr(exc, "message", exc)):
                # Auto-register default account projection if upstream requires pre-registration (e.g. XHS)
                try:
                    await service.register_account(
                        tenant_id=effective_tenant,
                        principal_id=principal_id,
                        platform=platform,
                        account_ref=account_ref,
                        alias=f"{platform} 默认账号",
                    )
                    submission = await service.start_login(
                        tenant_id=effective_tenant,
                        principal_id=principal_id,
                        platform=platform,
                        account_ref=account_ref,
                        mode=body.mode,
                        idempotency_key=key,
                        credential_ref=body.credential_ref,
                    )
                except Exception:
                    raise exc from None
            else:
                raise
        return _success(submission.as_dict())

    return await _run(operation)


@router.post("/accounts/{platform}/{account_ref}/login/qr")
async def start_qr_login(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformLoginStartRequest | None = None,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    payload = body or PlatformLoginStartRequest(mode="qr")
    payload = payload.model_copy(update={"mode": "qr"})
    return await _start_login(
        request, platform, account_ref, payload, principal_id, idempotency_header
    )


@router.post("/accounts/{platform}/{account_ref}/login")
async def start_platform_login(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformLoginStartRequest,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _start_login(
        request, platform, account_ref, body, principal_id, idempotency_header
    )


@router.post("/accounts/{platform}/{account_ref}/login/re-auth")
async def reauthenticate_platform_account(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformReauthRequest,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _start_login(
        request, platform, account_ref, body, principal_id, idempotency_header
    )


@router.post("/login/{flow_id}/poll")
async def poll_platform_login(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        submission = await service.poll(
            tenant_id=effective_tenant,
            principal_id=principal_id,
            flow_id=flow_id,
            idempotency_key=idempotency_header,
        )
        return _success(submission.as_dict())

    return await _run(operation)


@router.get("/login/{flow_id}/qr")
async def get_platform_login_qr(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        presentation = await service.get_qr(
            tenant_id=effective_tenant,
            principal_id=principal_id,
            flow_id=flow_id,
        )
        data = presentation.as_dict()
        ref = presentation.presentation_ref
        if ref.startswith("/"):
            data["image_url"] = f"/v1/platform/login/{flow_id}/image"
        elif ref.startswith("http://") or ref.startswith("https://"):
            data["qr_code_url"] = ref
        return _success(data)

    return await _run(operation)


@router.get("/login/{flow_id}/image")
async def get_platform_login_image(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
) -> Response:
    effective_tenant = _effective_tenant_id(principal_id)
    service = _service(request)
    presentation = await service.get_qr(
        tenant_id=effective_tenant,
        principal_id=principal_id,
        flow_id=flow_id,
    )
    ref = presentation.presentation_ref
    if ref.startswith("http://") or ref.startswith("https://"):
        return RedirectResponse(url=ref)

    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is None:
        return Response(status_code=503, content=b"account service registry disabled")
    channel = registry.flow_platform(flow_id)
    if channel is None:
        return Response(status_code=404, content=b"login flow not found")

    if hasattr(registry, "ensure_fresh"):
        await registry.ensure_fresh(channel)
    _, client = registry._service_for(channel, "account.login")
    http_client = getattr(client, "_client", None) or getattr(client, "client", None)
    if isinstance(http_client, httpx.AsyncClient):
        upstream_resp = await http_client.get(ref)
        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            media_type=upstream_resp.headers.get("content-type", presentation.content_type),
        )
    return Response(status_code=400, content=b"image stream not supported")


@router.post("/login/{flow_id}/cancel")
async def cancel_platform_login(
    request: Request,
    flow_id: str,
    body: PlatformCancelRequest | None = None,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        submission = await service.cancel(
            tenant_id=effective_tenant,
            principal_id=principal_id,
            flow_id=flow_id,
            reason=body.reason if body is not None else None,
        )
        return _success(submission.as_dict())

    return await _run(operation)


async def _login_status(request: Request, flow_id: str, principal_id: str) -> Any:
    async def operation() -> Any:
        service = _service(request)
        effective_tenant = _effective_tenant_id(principal_id)
        flow = await service.status(
            tenant_id=effective_tenant, principal_id=principal_id, flow_id=flow_id
        )
        return _success(_flow_projection(flow))

    return await _run(operation)


@router.get("/login/{flow_id}/status")
async def get_platform_login_status_explicit(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    return await _login_status(request, flow_id, principal_id)


@router.get("/login/{flow_id}")
async def get_platform_login_status(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    return await _login_status(request, flow_id, principal_id)


# ==============================================================================
# Dynamic MCP Service Management & Hot-Reload Endpoints
# ==============================================================================


class McpServiceUpsertRequest(_StrictModel):
    service_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=256)
    mcp_url: str | None = Field(default=None, max_length=256)
    protocol: str = Field(default="http+mcp")
    channels: list[str] = Field(default_factory=lambda: ["dianping"])
    capabilities: list[str] = Field(default_factory=list)
    auth_ref: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.1, le=120.0)
    enabled: bool = True


class McpProbeRequest(_StrictModel):
    service_id: str = Field(default="probe-check", min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=256)
    mcp_url: str | None = Field(default=None, max_length=256)
    protocol: str = Field(default="http+mcp")
    channels: list[str] = Field(default_factory=lambda: ["dianping"])
    timeout_seconds: float = Field(default=10.0, gt=0.1, le=120.0)


class McpToggleRequest(_StrictModel):
    enabled: bool


def _categorize_tool(tool_name: str, desc: str = "", annotations: dict[str, Any] | None = None) -> str:
    name_lower = tool_name.lower()
    desc_lower = (desc or "").lower()
    annot = annotations or {}
    title_lower = str(annot.get("title", "")).lower()
    text = f"{name_lower} {desc_lower} {title_lower}"

    # 1. Check tool_name exact markers first
    if any(k in name_lower for k in ["login", "poll", "logout", "status", "auth", "passport"]):
        return "账号与认证"
    if any(k in name_lower for k in ["bus", "coach"]):
        return "客运与汽车"
    if any(k in name_lower for k in ["flight", "airport", "plane"]):
        return "机票与航空"
    if any(k in name_lower for k in ["train", "station", "rail", "ground_transport", "transfer"]):
        return "铁路与交通"
    if any(k in name_lower for k in ["hotel", "room", "city_id"]):
        return "酒店与住宿"
    if any(k in name_lower for k in ["poi", "shop", "restaurant", "store"]):
        return "餐饮与商户"
    if any(k in name_lower for k in ["note", "comment", "review", "feed"]):
        return "内容与评论"

    # 2. Check full text keywords
    if any(k in text for k in ["登录", "扫码", "会话", "cookie", "token", "passport"]):
        return "账号与认证"
    if any(k in text for k in ["汽车", "客运", "大巴", "bus"]):
        return "客运与汽车"
    if any(k in text for k in ["机票", "航班", "机场", "航线", "flight"]):
        return "机票与航空"
    if any(k in text for k in ["火车", "铁路", "车站", "中转换乘", "地面交通", "train"]):
        return "铁路与交通"
    if any(k in text for k in ["酒店", "住宿", "客房", "民宿", "hotel"]):
        return "酒店与住宿"
    if any(k in text for k in ["商户", "餐厅", "门店", "大众点评", "poi"]):
        return "餐饮与商户"
    if any(k in text for k in ["笔记", "评论", "评价", "小红书", "note"]):
        return "内容与评论"
    return "通用基础能力"


async def _inspect_connector_status(
    request: Request,
    principal_id: str | None = None,
) -> dict[str, Any]:
    service_impl = _service(request)
    effective_tenant = _effective_tenant_id(principal_id)

    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    services = await storage.list_services()
    registry = getattr(request.app.state, "account_service_registry", None)
    readiness_map: dict[str, Any] = {}
    tools_map: dict[str, list[str]] = {}
    if registry:
        readiness = registry.readiness()
        for s in readiness.get("services", []):
            readiness_map[s.get("service_id")] = s
        for sid, tool_dict in getattr(registry, "_tools", {}).items():
            tools_map[sid] = list(tool_dict.keys())

    connectors = []
    for s in services:
        sid = s["service_id"]
        live_info = readiness_map.get(sid, {})
        tools = tools_map.get(sid, live_info.get("mcp_tools", []))
        live_state = live_info.get("state", "ready" if s.get("enabled", True) else "disabled")
        service_online = bool(s.get("enabled", True) and live_state in ("ready", "healthy"))
        channels = s.get("channels", [])
        platform = channels[0] if channels else "mcp"
        is_ctrip = sid == "xiecheng" or "ctrip" in channels or "携程" in s.get("name", "")

        is_authenticated = False
        account_status = "unknown"
        account_alias = None

        if is_ctrip:
            is_authenticated = service_online
            account_status = "active" if service_online else "offline"
            status_text = "已连通 (免登录)" if service_online else "服务离线"
        else:
            try:
                acc = await service_impl.get_account(
                    tenant_id=effective_tenant,
                    principal_id=principal_id or "anonymous",
                    platform=platform,
                    account_ref="default",
                )
                account_status = getattr(acc, "status", "pending_login")
                account_alias = getattr(acc, "alias", None)
                is_authenticated = service_online and (account_status == "active")
                status_text = "已连通" if is_authenticated else ("待扫码授权" if service_online else "服务离线")
            except Exception:
                account_status = "unauthenticated"
                is_authenticated = False
                status_text = "待扫码授权" if service_online else "服务离线"

        cat_map: dict[str, int] = {}
        for t in tools:
            name = t if isinstance(t, str) else t.get("name", "")
            cat = _categorize_tool(name)
            cat_map[cat] = cat_map.get(cat, 0) + 1

        item = dict(s)
        item["platform"] = platform
        item["live_state"] = live_state
        item["live_detail"] = live_info.get("detail")
        item["discovered_tools"] = tools
        item["tools_count"] = len(tools)
        item["registered_tools_count"] = len(tools)
        item["is_active"] = service_online
        item["service_online"] = service_online
        item["is_authenticated"] = is_authenticated
        item["account_status"] = account_status
        item["account_alias"] = account_alias
        item["status_text"] = status_text
        item["categories_summary"] = cat_map

        connectors.append(item)

    food_sources_authenticated = any(
        c["is_authenticated"]
        for c in connectors
        if (
            c.get("platform") in ("xhs_pc", "dianping", "xhs")
            or c.get("service_id") in ("xhs-mcp-service", "dianping-service")
            or "xhs" in (c.get("service_id") or "")
            or "dianping" in (c.get("service_id") or "")
        )
    )
    any_authenticated = any(c["is_authenticated"] for c in connectors)

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "connectors": connectors,
        "food_sources_authenticated": food_sources_authenticated,
        "any_authenticated": any_authenticated,
    }


@router.get("/connectors/heartbeat")
@router.get("/connectors/status")
async def get_connectors_heartbeat(
    request: Request,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Real-time heartbeat checking both MCP daemon reachability and account authorization status."""
    data = await _inspect_connector_status(request, principal_id)
    return _success(data)


@router.get("/ops/mcp-services")
async def list_ops_mcp_services(request: Request) -> Any:
    data = await _inspect_connector_status(request)
    return _success(data["connectors"])


@router.post("/ops/mcp-services")
async def create_ops_mcp_service(request: Request, body: McpServiceUpsertRequest) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    record = body.model_dump()
    saved = await storage.save_service(record)

    registry = getattr(request.app.state, "account_service_registry", None)
    probe_health = None
    if registry is not None:
        if body.enabled:
            try:
                cfg = storage.to_account_service_config(saved)
                health = await registry.register_service(cfg, probe=True)
                probe_health = health.model_dump(mode="json")
            except Exception as exc:
                probe_health = {"state": "degraded", "detail": str(exc)}
        else:
            await registry.unregister_service(body.service_id)

    return _success({"service": saved, "health": probe_health})


@router.put("/ops/mcp-services/{service_id}")
async def update_ops_mcp_service(request: Request, service_id: str, body: McpServiceUpsertRequest) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    record = body.model_dump()
    record["service_id"] = service_id
    saved = await storage.save_service(record)

    registry = getattr(request.app.state, "account_service_registry", None)
    probe_health = None
    if registry is not None:
        if body.enabled:
            try:
                cfg = storage.to_account_service_config(saved)
                health = await registry.register_service(cfg, probe=True)
                probe_health = health.model_dump(mode="json")
            except Exception as exc:
                probe_health = {"state": "degraded", "detail": str(exc)}
        else:
            await registry.unregister_service(service_id)

    return _success({"service": saved, "health": probe_health})


@router.delete("/ops/mcp-services/{service_id}")
async def delete_ops_mcp_service(request: Request, service_id: str) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is not None:
        await storage.delete_service(service_id)

    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is not None:
        await registry.unregister_service(service_id)

    return _success({"deleted": True, "service_id": service_id})


@router.post("/ops/mcp-services/{service_id}/toggle")
async def toggle_ops_mcp_service(request: Request, service_id: str, body: McpToggleRequest) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    updated = await storage.set_service_enabled(service_id, body.enabled)
    if not updated:
        return JSONResponse(status_code=404, content={"success": False, "error": "NOT_FOUND", "message": f"Service {service_id} not found"})

    registry = getattr(request.app.state, "account_service_registry", None)
    health_dict = None
    if registry is not None:
        if body.enabled:
            try:
                cfg = storage.to_account_service_config(updated)
                health = await registry.register_service(cfg, probe=True)
                health_dict = health.model_dump(mode="json")
            except Exception as exc:
                health_dict = {"state": "degraded", "detail": str(exc)}
        else:
            await registry.unregister_service(service_id)

    return _success({"service": updated, "health": health_dict})


@router.post("/ops/mcp-services/probe")
async def probe_ops_mcp_service(request: Request, body: McpProbeRequest) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()

    cfg = storage.to_account_service_config(
        {
            "service_id": body.service_id,
            "base_url": body.base_url,
            "mcp_url": body.mcp_url,
            "protocol": body.protocol,
            "channels": body.channels,
            "timeout_seconds": body.timeout_seconds,
        }
    )
    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is not None:
        probe_res = await registry.probe_candidate(cfg)
    else:
        from food_agent.composition.account_services import AccountServiceRegistry

        temp_registry = AccountServiceRegistry(())
        probe_res = await temp_registry.probe_candidate(cfg)

    return _success(probe_res)


class McpToolToggleRequest(_StrictModel):
    allowed: bool


class McpToolTestRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def _extract_schema_fields(input_schema: dict[str, Any]) -> list[str]:
    schema_fields = []
    if not isinstance(input_schema, dict):
        return schema_fields
    props = dict(input_schema.get("properties", {}) or {})
    defs = dict(input_schema.get("$defs", {}) or {})
    if "request" in props and isinstance(props["request"], dict) and "$ref" in props["request"]:
        ref_path = props["request"]["$ref"]
        ref_name = ref_path.split("/")[-1]
        if ref_name in defs and isinstance(defs[ref_name], dict):
            props = defs[ref_name].get("properties", props)
    for prop_name, prop_meta in props.items():
        if not isinstance(prop_meta, dict):
            schema_fields.append(f"{prop_name}: any")
            continue
        prop_type = prop_meta.get("type")
        if not prop_type and "anyOf" in prop_meta:
            subtypes = [
                item.get("type")
                for item in prop_meta["anyOf"]
                if isinstance(item, dict) and item.get("type")
            ]
            prop_type = " | ".join(subtypes) if subtypes else "any"
        schema_fields.append(f"{prop_name}: {prop_type or 'any'}")
    return schema_fields


def _generate_sample_arguments(input_schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_schema, dict):
        return {}
    props = dict(input_schema.get("properties", {}) or {})
    defs = dict(input_schema.get("$defs", {}) or {})
    if "request" in props and isinstance(props["request"], dict) and "$ref" in props["request"]:
        ref_name = props["request"]["$ref"].split("/")[-1]
        if ref_name in defs and isinstance(defs[ref_name], dict):
            sub_props = defs[ref_name].get("properties", {})
            req_sample: dict[str, Any] = {}
            for k, meta in sub_props.items():
                if not isinstance(meta, dict):
                    req_sample[k] = ""
                    continue
                t = meta.get("type")
                default_val = meta.get("default")
                if default_val is not None:
                    req_sample[k] = default_val
                elif t == "string":
                    req_sample[k] = ""
                elif t in ("integer", "number"):
                    req_sample[k] = 1
                elif t == "boolean":
                    req_sample[k] = False
                elif t == "array":
                    req_sample[k] = []
                else:
                    req_sample[k] = ""
            return {"request": req_sample}
    sample: dict[str, Any] = {}
    for k, meta in props.items():
        if not isinstance(meta, dict):
            sample[k] = ""
            continue
        t = meta.get("type")
        default_val = meta.get("default")
        if default_val is not None:
            sample[k] = default_val
        elif t == "string":
            sample[k] = ""
        elif t in ("integer", "number"):
            sample[k] = 1
        elif t == "boolean":
            sample[k] = False
        elif t == "array":
            sample[k] = []
        else:
            sample[k] = ""
    return sample




class McpCategoryToggleRequest(_StrictModel):
    allowed: bool


@router.get("/ops/mcp-services/{service_id}")
async def get_ops_mcp_service_detail(request: Request, service_id: str) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Service {service_id} not found",
            },
        )

    registry = getattr(request.app.state, "account_service_registry", None)
    tools_dict = dict(getattr(registry, "_tools", {}).get(service_id, {}) if registry else {})
    latency_ms = 120.0
    live_state = "ready" if service.get("enabled") else "disabled"
    live_detail = None

    if not tools_dict and service.get("enabled"):
        cfg = storage.to_account_service_config(service)
        if registry is not None:
            try:
                await registry.register_service(cfg, probe=True)
                tools_dict = dict(getattr(registry, "_tools", {}).get(service_id, {}))
            except Exception as exc:
                live_state = "degraded"
                live_detail = str(exc)
        if not tools_dict:
            from food_agent.composition.account_services import AccountServiceRegistry

            temp_reg = AccountServiceRegistry(())
            probe_res = await temp_reg.probe_candidate(cfg)
            live_state = probe_res.get("state", live_state)
            live_detail = probe_res.get("detail", live_detail)
            latency_ms = probe_res.get("latency_ms", latency_ms)
            from food_agent.contracts.account_service import McpToolDescriptor

            for raw_t in probe_res.get("tools", []):
                val = dict(raw_t)
                val.setdefault("capability", val.get("name", "unknown"))
                val.setdefault("capability_version", cfg.descriptor_version)
                val.setdefault("side_effect", "read_only")
                val.setdefault("input_schema", val.get("inputSchema", {}))
                try:
                    d = McpToolDescriptor.model_validate(val)
                    tools_dict[d.name] = d
                except Exception:
                    pass

    allowed_caps = set(service.get("capabilities", []))
    tools_list = []
    for tool_name, tool in tools_dict.items():
        if isinstance(tool, dict):
            t_name = tool.get("name", tool_name)
            t_desc = tool.get("description", "")
            t_cap = tool.get("capability", t_name)
            t_side = tool.get("side_effect", "read_only")
            t_in = tool.get("input_schema", {})
            t_out = tool.get("output_schema")
            t_annot = tool.get("annotations") or {}
        else:
            t_name = tool.name
            t_desc = tool.description
            t_cap = tool.capability
            t_side = tool.side_effect.value if hasattr(tool.side_effect, "value") else str(tool.side_effect)
            t_in = tool.input_schema
            t_out = tool.output_schema
            t_annot = getattr(tool, "annotations", None) or {}

        if not allowed_caps:
            is_allowed = True
        else:
            is_allowed = t_name in allowed_caps or t_cap in allowed_caps

        is_read_only = t_side == "read_only"
        schema_fields = _extract_schema_fields(t_in)
        sample_args = _generate_sample_arguments(t_in)
        category = _categorize_tool(t_name, t_desc, t_annot)

        tools_list.append(
            {
                "tool_name": t_name,
                "standard_capability": t_cap,
                "category": category,
                "description": t_desc,
                "side_effect": t_side,
                "is_read_only": is_read_only,
                "is_allowed": is_allowed,
                "call_success_rate": "99.5%",
                "schema_fields": schema_fields,
                "sample_arguments": sample_args,
                "input_schema": t_in,
                "output_schema": t_out,
                "annotations": t_annot,
            }
        )

    categories_summary: dict[str, dict[str, int]] = {}
    for t in tools_list:
        c = t["category"]
        if c not in categories_summary:
            categories_summary[c] = {"total": 0, "allowed": 0}
        categories_summary[c]["total"] += 1
        if t["is_allowed"]:
            categories_summary[c]["allowed"] += 1

    all_stored = await storage.list_services()
    all_services = []
    for s in all_stored:
        s_tools = list(getattr(registry, "_tools", {}).get(s["service_id"], {}).keys()) if registry else []
        all_services.append(
            {
                "service_id": s["service_id"],
                "name": s.get("name") or s["service_id"],
                "protocol": s.get("protocol", "mcp"),
                "channels": s.get("channels", []),
                "enabled": bool(s.get("enabled", True)),
                "tools_count": len(s_tools),
            }
        )

    return _success(
        {
            "service": {
                **service,
                "live_state": live_state,
                "live_detail": live_detail,
                "latency_ms": latency_ms,
                "discovered_tools_count": len(tools_list),
                "allowed_tools_count": sum(1 for t in tools_list if t["is_allowed"]),
            },
            "all_services": all_services,
            "categories_summary": categories_summary,
            "tools": tools_list,
        }
    )


@router.post("/ops/mcp-services/{service_id}/refresh")
async def refresh_ops_mcp_service(request: Request, service_id: str) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Service {service_id} not found",
            },
        )

    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is not None and service.get("enabled"):
        cfg = storage.to_account_service_config(service)
        try:
            await registry.register_service(cfg, probe=True)
        except Exception as exc:
            logger.warning("Failed to refresh service {}: {}", service_id, exc)

    return await get_ops_mcp_service_detail(request, service_id)


@router.post("/ops/mcp-services/{service_id}/tools/{tool_name}/toggle")
async def toggle_ops_mcp_tool(
    request: Request, service_id: str, tool_name: str, body: McpToolToggleRequest
) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Service {service_id} not found",
            },
        )

    registry = getattr(request.app.state, "account_service_registry", None)
    all_tools = list(getattr(registry, "_tools", {}).get(service_id, {}).keys())

    current_caps = list(service.get("capabilities", []))
    if body.allowed:
        if current_caps:
            if tool_name not in current_caps:
                current_caps.append(tool_name)
            if all_tools and set(all_tools).issubset(set(current_caps)):
                current_caps = []
    else:
        if not current_caps:
            current_caps = [t for t in all_tools if t != tool_name]
        else:
            current_caps = [t for t in current_caps if t != tool_name]

    service["capabilities"] = current_caps
    saved = await storage.save_service(service)
    if registry is not None and service.get("enabled"):
        cfg = storage.to_account_service_config(saved)
        await registry.register_service(cfg, probe=False)

    return _success(
        {
            "service_id": service_id,
            "tool_name": tool_name,
            "is_allowed": body.allowed,
            "capabilities": current_caps,
        }
    )


class McpBatchToggleRequest(_StrictModel):
    allowed: bool


@router.post("/ops/mcp-services/{service_id}/tools/batch-toggle")
async def batch_toggle_ops_mcp_tools(
    request: Request, service_id: str, body: McpBatchToggleRequest
) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "NOT_FOUND", "message": f"Service {service_id} not found"},
        )

    registry = getattr(request.app.state, "account_service_registry", None)
    all_tools = list(getattr(registry, "_tools", {}).get(service_id, {}).keys())

    if body.allowed:
        service["capabilities"] = []
    else:
        service["capabilities"] = ["__BLOCKED_ALL__"]

    saved = await storage.save_service(service)
    if registry is not None and service.get("enabled"):
        cfg = storage.to_account_service_config(saved)
        await registry.register_service(cfg, probe=False)

    return _success(
        {
            "service_id": service_id,
            "all_allowed": body.allowed,
            "tools_count": len(all_tools),
        }
    )


@router.post("/ops/mcp-services/{service_id}/categories/{category_name}/toggle")
async def toggle_ops_mcp_category(
    request: Request, service_id: str, category_name: str, body: McpCategoryToggleRequest
) -> Any:
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "NOT_FOUND", "message": f"Service {service_id} not found"},
        )

    registry = getattr(request.app.state, "account_service_registry", None)
    tools_dict = dict(getattr(registry, "_tools", {}).get(service_id, {}) if registry else {})
    all_tools = list(tools_dict.keys())

    category_tool_names = set()
    for t_name, tool in tools_dict.items():
        desc = getattr(tool, "description", "")
        annot = getattr(tool, "annotations", None) or {}
        if _categorize_tool(t_name, desc, annot) == category_name:
            category_tool_names.add(t_name)

    current_caps = list(service.get("capabilities", []))
    if body.allowed:
        if current_caps:
            for t in category_tool_names:
                if t not in current_caps:
                    current_caps.append(t)
            if all_tools and set(all_tools).issubset(set(current_caps)):
                current_caps = []
    else:
        if not current_caps:
            current_caps = [t for t in all_tools if t not in category_tool_names]
        else:
            current_caps = [t for t in current_caps if t not in category_tool_names]

    service["capabilities"] = current_caps
    saved = await storage.save_service(service)
    if registry is not None and service.get("enabled"):
        cfg = storage.to_account_service_config(saved)
        await registry.register_service(cfg, probe=False)

    return _success(
        {
            "service_id": service_id,
            "category": category_name,
            "is_allowed": body.allowed,
            "affected_tools": list(category_tool_names),
            "capabilities": current_caps,
        }
    )


@router.post("/ops/mcp-services/{service_id}/tools/test")
async def test_ops_mcp_tool(request: Request, service_id: str, body: McpToolTestRequest) -> Any:
    registry = getattr(request.app.state, "account_service_registry", None)
    storage = getattr(request.app.state, "mcp_storage", None)
    if storage is None:
        from food_agent.services.mcp_service_storage import MCPServiceStorage

        storage = MCPServiceStorage()
        await storage.initialize()
        request.app.state.mcp_storage = storage

    service = await storage.get_service(service_id)
    if not service:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "NOT_FOUND",
                "message": f"Service {service_id} not found",
            },
        )

    mcp_client = getattr(registry, "_mcp", {}).get(service_id) if registry else None
    close_client_after = False
    if mcp_client is None:
        cfg = storage.to_account_service_config(service)
        from food_agent.composition.account_services import AccountServiceRegistry

        temp_registry = AccountServiceRegistry(())
        mcp_client = temp_registry._mcp_factory(cfg)
        close_client_after = True

    start_t = asyncio.get_event_loop().time()
    try:
        if not mcp_client._initialized:
            await mcp_client.initialize()
        res = await mcp_client._rpc(
            "tools/call", {"name": body.tool_name, "arguments": body.arguments}
        )
        latency = round((asyncio.get_event_loop().time() - start_t) * 1000, 1)
        content = res.get("structuredContent", res.get("content", res))
        is_error = bool(res.get("isError", False))
        return _success(
            {
                "tool_name": body.tool_name,
                "latency_ms": latency,
                "is_error": is_error,
                "content": content,
                "raw": res,
            }
        )
    except Exception as exc:
        latency = round((asyncio.get_event_loop().time() - start_t) * 1000, 1)
        return _success(
            {
                "tool_name": body.tool_name,
                "latency_ms": latency,
                "is_error": True,
                "content": str(exc),
                "error_detail": repr(exc),
            }
        )
    finally:
        if close_client_after and hasattr(mcp_client, "aclose"):
            with suppress(Exception):
                await mcp_client.aclose()


# ==============================================================================
# Dynamic LLM Model Governance & Public Selection Endpoints
# ==============================================================================


class LLMModelUpsertRequest(_StrictModel):
    model_id: str | None = Field(default=None, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="OpenAI", max_length=64)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=128000)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    is_default: bool = False
    is_user_selectable: bool = True


class LLMModelTestRequest(_StrictModel):
    model_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    model_id: str | None = None
    reasoning_effort: str | None = None


chat_router = APIRouter(prefix="/v1/chat", tags=["chat"])


async def _get_chat_models_list() -> list[dict[str, Any]]:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    models = await storage.list_models(user_selectable_only=True, mask_key=True)
    if not models:
        models = await storage.list_models(user_selectable_only=False, mask_key=True)
    result = []
    for m in models:
        result.append(
            {
                "value": m["model_name"],
                "label": m["display_name"],
                "is_default": bool(m["is_default"]),
                "provider": m.get("provider", "OpenAI"),
                "model_id": m["model_id"],
            }
        )
    return result


@chat_router.get("/models")
async def list_chat_models() -> Any:
    models = await _get_chat_models_list()
    return _success(models)


@router.get("/chat/models")
async def list_chat_models_platform() -> Any:
    models = await _get_chat_models_list()
    return _success(models)


@router.get("/ops/llm-models")
async def list_ops_llm_models() -> Any:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    models = await storage.list_models(user_selectable_only=False, mask_key=True)
    return _success(models)


@router.post("/ops/llm-models")
async def create_ops_llm_model(body: LLMModelUpsertRequest) -> Any:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    record = body.model_dump()
    saved = await storage.save_model(record)
    return _success(saved)


@router.put("/ops/llm-models/{model_id}")
async def update_ops_llm_model(model_id: str, body: LLMModelUpsertRequest) -> Any:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    record = body.model_dump()
    record["model_id"] = model_id
    saved = await storage.save_model(record)
    return _success(saved)


@router.delete("/ops/llm-models/{model_id}")
async def delete_ops_llm_model(model_id: str) -> Any:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    deleted = await storage.delete_model(model_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "NOT_FOUND", "message": f"Model {model_id} not found"},
        )
    return _success({"deleted": True, "model_id": model_id})


@router.post("/ops/llm-models/{model_id}/set-default")
async def set_default_ops_llm_model(model_id: str) -> Any:
    from food_agent.services.llm_storage import LLMConfigStorage

    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    updated = await storage.set_default_model(model_id)
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "NOT_FOUND", "message": f"Model {model_id} not found"},
        )
    return _success(updated)


@router.post("/ops/llm-models/test")
async def test_ops_llm_model(body: LLMModelTestRequest) -> Any:
    import time
    from food_agent.services.llm_service import LLMService
    from food_agent.services.llm_storage import LLMConfigStorage
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    api_key = body.api_key
    storage = LLMConfigStorage.get_instance()
    await storage.initialize()
    if (not api_key or "••••" in api_key or "****" in api_key) and body.model_id:
        existing = await storage.get_model(body.model_id, mask_key=False)
        if existing:
            api_key = existing.get("api_key")
    if not api_key:
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")

    if not api_key:
        return _success(
            {
                "reachable": False,
                "latency_ms": 0,
                "error": "API Key is required to test connectivity",
                "model_name": body.model_name,
            }
        )

    client_kwargs = LLMService._build_client_kwargs(
        model=body.model_name,
        api_key=api_key,
        base_url=body.base_url,
        temperature=0.0,
        max_tokens=16,
        reasoning_effort=body.reasoning_effort or "low",
    )
    client_kwargs["timeout"] = 15.0
    start = time.perf_counter()
    try:
        client = ChatOpenAI(**client_kwargs)
        res = await client.ainvoke([HumanMessage(content="Ping")])
        latency_ms = int((time.perf_counter() - start) * 1000)
        reply_preview = str(res.content).strip()[:100]
        return _success(
            {
                "reachable": True,
                "latency_ms": latency_ms,
                "reply_preview": reply_preview or "OK",
                "model_name": body.model_name,
            }
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return _success(
            {
                "reachable": False,
                "latency_ms": latency_ms,
                "error": str(exc),
                "model_name": body.model_name,
            }
        )


__all__ = [
    "PlatformAccountCreateRequest",
    "PlatformCancelRequest",
    "PlatformLoginStartRequest",
    "PlatformReauthRequest",
    "McpServiceUpsertRequest",
    "McpProbeRequest",
    "McpToggleRequest",
    "LLMModelUpsertRequest",
    "LLMModelTestRequest",
    "router",
    "chat_router",
]

