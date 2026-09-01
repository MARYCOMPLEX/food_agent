"""Platform account and login control-plane HTTP adapters.

The router is intentionally thin: all authorization, idempotency, and durable
state transitions belong to :class:`PlatformLoginService`.  Missing platform
wiring is reported as a stable dependency-unavailable response; no legacy XHS
cookie or process-local fallback is created here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from api.deps import get_current_user_id
from xhs_food.contracts.account import PlatformChannel
from xhs_food.contracts.account_service import validate_remote_payload
from xhs_food.experience.platform_login import (
    LoginMode,
    PlatformLoginService,
    PlatformLoginServiceError,
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
    account_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
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


def install_platform_runtime(application: Any, bundle: Any | None) -> None:
    """Install an explicitly composed platform bundle on ``app.state``.

    The helper is intentionally a plain setter so the application lifespan can
    supply either a production bundle (PostgreSQL/Alembic + Temporal) or a
    synthetic qualification fixture.  Passing ``None`` clears all bindings;
    the router then reports a stable disabled response rather than constructing
    an in-memory authority behind the operator's back.
    """

    if bundle is None:
        application.state.platform_login_service = None
        application.state.platform_account_authority = None
        application.state.platform_session_codec = None
        application.state.platform_source_gateway = None
        application.state.platform_readiness = None
        return
    assembly = getattr(bundle, "assembly", bundle)
    application.state.platform_login_service = getattr(assembly, "login_service", None)
    application.state.platform_account_authority = getattr(assembly, "account_authority", None)
    application.state.platform_session_codec = getattr(assembly, "session_codec", None)
    application.state.platform_source_gateway = getattr(assembly, "gateway", None)
    application.state.platform_readiness = getattr(assembly, "readiness", None)


def _service(request: Request) -> PlatformLoginService:
    service = getattr(request.app.state, "platform_login_service", None)
    if service is None:
        raise PlatformLoginServiceError(
            "PLATFORM_DISABLED",
            "platform account control plane is disabled",
            status_code=503,
        )
    if not isinstance(service, PlatformLoginService) and not all(
        callable(getattr(service, name, None))
        for name in ("start_login", "status", "cancel")
    ):
        raise PlatformLoginServiceError(
            "PLATFORM_UNAVAILABLE",
            "platform account control plane is unavailable",
            status_code=503,
        )
    readiness = getattr(request.app.state, "platform_readiness", None)
    if readiness is None:
        root = getattr(request.app.state, "composition_root", None)
        readiness = getattr(root, "platform_readiness", None)
    if readiness is not None:
        login_requested = bool(getattr(readiness, "login_requested", False))
        source_requested = any(
            bool(getattr(item, "requested", False))
            for item in getattr(readiness, "statuses", ())
        )
        disabled = not login_requested and not source_requested
        disabled = disabled or (login_requested and not bool(getattr(readiness, "login_enabled", False)))
    else:
        disabled = False
    if disabled:
        raise PlatformLoginServiceError(
            "PLATFORM_DISABLED",
            "platform account control plane is disabled",
            status_code=503,
        )
    return service  # type: ignore[return-value]


def _failure(error: PlatformLoginServiceError) -> JSONResponse:
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
    category = getattr(getattr(error, "category", None), "value", getattr(error, "category", "dependency-unavailable"))
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
        "status": getattr(getattr(account, "status", None), "value", getattr(account, "status", None)),
        "health": getattr(getattr(account, "health", None), "value", getattr(account, "health", None)),
        "session_version": getattr(account, "session_version", None),
        "provider_subject_id": getattr(account, "provider_subject_id", None) or getattr(account, "provider_subject_ref", None),
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
        "provider_subject_id": getattr(flow, "provider_subject_id", None) or getattr(flow, "provider_subject_ref", None),
        "error_code": getattr(getattr(flow, "error_code", None), "value", getattr(flow, "error_code", None)),
        "error_message": getattr(flow, "error_message", None),
    }


async def _run(call: Any) -> Any:
    try:
        return await call()
    except PlatformLoginServiceError as exc:
        return _failure(exc)
    except Exception:
        return _unexpected()


@router.get("/readiness")
async def platform_readiness(request: Request) -> Any:
    service = getattr(request.app.state, "platform_login_service", None)
    root = getattr(request.app.state, "composition_root", None)
    readiness = getattr(root, "platform_readiness", None)
    if readiness is None:
        readiness = getattr(request.app.state, "platform_readiness", None)
    if readiness is not None and hasattr(readiness, "as_dict"):
        value = readiness.as_dict()
    elif isinstance(readiness, Mapping):
        value = dict(readiness)
    else:
        value = {"state": "disabled", "ready": False, "login": {"enabled": False}}
    if service is not None and callable(getattr(service, "readiness", None)):
        try:
            value["login_runtime"] = await service.readiness()
        except Exception:
            value["login_runtime"] = {"enabled": False, "execution": "unavailable"}
    registry = getattr(request.app.state, "account_service_registry", None)
    if registry is not None and callable(getattr(registry, "readiness", None)):
        try:
            value["account_services"] = registry.readiness()
        except Exception:
            value["account_services"] = {"enabled": False, "ready": False, "state": "dependency-unavailable"}
    return _success(value)


@router.get("/account-services/{platform}/tools")
async def list_account_service_tools(
    request: Request,
    platform: str,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    """Expose the refreshed, redacted MCP tool catalog to an agent."""

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
        result = await registry.call_tool(
            platform=channel,
            tool_name=tool_name,
            arguments={**(body.arguments if body is not None else {}), "tenant_ref": principal_id},
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
        result = await registry.invoke_for_platform(
            tenant_ref=principal_id,
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
        account = await service.register_account(
            tenant_id=principal_id,
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
        account = await service.get_account(
            tenant_id=principal_id,
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
        submission = await service.start_login(
            tenant_id=principal_id,
            principal_id=principal_id,
            platform=platform,
            account_ref=account_ref,
            mode=body.mode,
            idempotency_key=key,
            credential_ref=body.credential_ref,
        )
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
    payload = body or PlatformLoginStartRequest(mode=LoginMode.QR.value)
    payload = payload.model_copy(update={"mode": LoginMode.QR.value})
    return await _start_login(request, platform, account_ref, payload, principal_id, idempotency_header)


@router.post("/accounts/{platform}/{account_ref}/login")
async def start_platform_login(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformLoginStartRequest,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _start_login(request, platform, account_ref, body, principal_id, idempotency_header)


@router.post("/accounts/{platform}/{account_ref}/login/re-auth")
async def reauthenticate_platform_account(
    request: Request,
    platform: str,
    account_ref: str,
    body: PlatformReauthRequest,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _start_login(request, platform, account_ref, body, principal_id, idempotency_header)


@router.post("/login/{flow_id}/poll")
async def poll_platform_login(
    request: Request,
    flow_id: str,
    principal_id: str = Depends(get_current_user_id),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        submission = await service.poll(
            tenant_id=principal_id,
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
        presentation = await service.get_qr(
            tenant_id=principal_id,
            principal_id=principal_id,
            flow_id=flow_id,
        )
        return _success(presentation.as_dict())

    return await _run(operation)


@router.post("/login/{flow_id}/cancel")
async def cancel_platform_login(
    request: Request,
    flow_id: str,
    body: PlatformCancelRequest | None = None,
    principal_id: str = Depends(get_current_user_id),
) -> Any:
    async def operation() -> Any:
        service = _service(request)
        submission = await service.cancel(
            tenant_id=principal_id,
            principal_id=principal_id,
            flow_id=flow_id,
            reason=body.reason if body is not None else None,
        )
        return _success(submission.as_dict())

    return await _run(operation)


async def _login_status(request: Request, flow_id: str, principal_id: str) -> Any:
    async def operation() -> Any:
        service = _service(request)
        flow = await service.status(tenant_id=principal_id, principal_id=principal_id, flow_id=flow_id)
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


__all__ = [
    "PlatformAccountCreateRequest",
    "PlatformCancelRequest",
    "PlatformLoginStartRequest",
    "PlatformReauthRequest",
    "install_platform_runtime",
    "router",
]
