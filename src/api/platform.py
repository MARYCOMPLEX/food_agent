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
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from api.deps import get_current_user_id
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


def _success(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


def _account_projection(account: Any) -> dict[str, Any]:
    # Pydantic contracts are immutable and contain no credential payload.  The
    # explicit field list guards against an adapter accidentally adding an
    # internal attribute to a response model in the future.
    return {
        "tenant_id": account.tenant_id,
        "platform": account.platform.value,
        "account_ref": account.account_ref,
        "alias": account.alias,
        "status": account.status.value,
        "health": account.health.value,
        "session_version": account.session_version,
        "provider_subject_id": account.provider_subject_id,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _flow_projection(flow: Any) -> dict[str, Any]:
    # Exclude ``qr_object_ref`` deliberately; clients use the QR presentation
    # endpoint, not storage keys/object metadata.
    return {
        "flow_id": flow.flow_id,
        "platform": flow.account.platform.value,
        "account_ref": flow.account.account_ref,
        "state": flow.state.value,
        "created_at": flow.created_at,
        "expires_at": flow.expires_at,
        "updated_at": flow.updated_at,
        "qr_expires_at": flow.qr_expires_at,
        "provider_subject_id": flow.provider_subject_id,
        "error_code": flow.error_code,
        "error_message": flow.error_message,
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
    return _success(value)


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
