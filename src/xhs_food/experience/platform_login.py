"""Application-facing account login use case.

This module deliberately depends only on the public contract SDK.  Concrete
PostgreSQL, ObjectStore, Temporal, and provider implementations are injected
by the Composition Root.  The HTTP adapter can therefore expose a stable
control plane without importing an infrastructure SDK or accidentally
serialising credentials.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from xhs_food.contracts import (
    AccountGrantPermission,
    LoginActivityOperation,
    LoginChallenge,
    LoginFlowState,
    PlatformAccount,
    PlatformAccountGrant,
    PlatformAccountGrantPort,
    PlatformAccountRef,
    PlatformAccountRepositoryPort,
    PlatformChannel,
    PlatformLoginActivityRequest,
    PlatformLoginFlow,
    PlatformLoginFlowPort,
    TemporalExecutionPolicy,
    WorkflowPort,
    WorkflowRun,
    transition_login_flow,
)


class PlatformLoginServiceError(RuntimeError):
    """Stable, secret-free error emitted by the login use case."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        # Codes/messages are authored by this module and never include provider
        # response bodies.  Keep the value bounded in case an injected adapter
        # passes an unexpectedly long diagnostic.
        self.code = "".join(c for c in str(code).upper() if c.isalnum() or c in "_.-")[:96] or "PLATFORM_ERROR"
        self.message = str(message)[:256]
        self.status_code = status_code
        super().__init__(self.message)


class LoginMode(StrEnum):
    QR = "qr"
    PHONE = "phone"
    COOKIE = "cookie"


@dataclass(frozen=True, slots=True)
class LoginSubmission:
    """Redacted acknowledgement returned by a login command."""

    flow: PlatformLoginFlow
    challenge: LoginChallenge | None = None
    workflow: WorkflowRun | None = None

    def as_dict(self) -> dict[str, Any]:
        flow = _redacted_flow(self.flow)
        value: dict[str, Any] = {
            "flow": flow,
            "flow_id": self.flow.flow_id,
            "state": self.flow.state.value,
        }
        if self.challenge is not None:
            # ``LoginChallenge`` only contains an opaque ObjectRef.  Do not
            # expose the underlying object key; clients receive a short-lived
            # presentation reference from ``get_qr`` instead.
            value["challenge"] = {
                "flow_id": self.challenge.flow_id,
                "expires_at": self.challenge.expires_at,
                "content_type": self.challenge.content_type,
            }
        if self.workflow is not None:
            value["workflow"] = self.workflow.model_dump(mode="json")
        return value


@dataclass(frozen=True, slots=True)
class QrPresentation:
    """Time-limited, opaque QR presentation metadata."""

    flow_id: str
    presentation_ref: str
    expires_at: datetime
    content_type: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "presentation_ref": self.presentation_ref,
            "expires_at": self.expires_at,
            "content_type": self.content_type,
        }


class _AccountAuthority(
    PlatformAccountRepositoryPort,
    PlatformAccountGrantPort,
    PlatformLoginFlowPort,
    Protocol,
):
    """Combined account authority used by the service (repository + grants)."""

    async def add_grant(self, grant: PlatformAccountGrant) -> PlatformAccountGrant: ...


WorkflowStartBuilder = Callable[..., Any]
_ACCOUNT_AUTH_CANCEL_SIGNAL = "platform-account-auth.cancel.requested"


class PlatformLoginService:
    """Account-scoped login control plane.

    ``workflow`` is the only execution boundary used in a qualified
    deployment.  ``coordinator`` is an explicitly injected local fixture seam
    for development and deterministic tests; no fallback provider is created
    by this class.
    """

    def __init__(
        self,
        *,
        accounts: _AccountAuthority,
        flows: PlatformLoginFlowPort | None = None,
        workflow: WorkflowPort | None = None,
        coordinator: Any | None = None,
        workflow_start_builder: WorkflowStartBuilder | None = None,
        object_store: Any | None = None,
        queue: str = "account-auth",
        flow_ttl_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
        execution_policy: TemporalExecutionPolicy | None = None,
    ) -> None:
        if not queue or any(character.isspace() for character in queue):
            raise ValueError("account-auth queue must be a non-empty whitespace-free name")
        if flow_ttl_seconds < 30:
            raise ValueError("login flow TTL must be at least 30 seconds")
        if workflow is not None and workflow_start_builder is None:
            raise ValueError("workflow_start_builder is required with a WorkflowPort")
        if workflow is None and coordinator is None:
            # A service without an execution boundary can still be used for
            # account registration/read-only status, but command methods fail
            # closed with a dependency error.
            pass
        self._accounts = accounts
        self._flows: PlatformLoginFlowPort = (
            flows if flows is not None else accounts
        )  # concrete authorities implement flow ports
        self._workflow = workflow
        self._coordinator = coordinator
        self._build_start = workflow_start_builder
        self._object_store = object_store
        self._queue = queue
        self._flow_ttl = flow_ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._execution_policy = execution_policy

    # ------------------------------------------------------------------
    # Account registration and redacted projections
    # ------------------------------------------------------------------

    async def register_account(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        platform: str | PlatformChannel,
        account_ref: str,
        alias: str,
        permissions: Sequence[str | AccountGrantPermission] | None = None,
    ) -> PlatformAccount:
        ref = _make_ref(tenant_id, platform, account_ref)
        _validate_alias(alias)
        _validate_principal(principal_id)
        try:
            existing = await self._accounts.get_account(ref)
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform account authority is unavailable",
                status_code=503,
            ) from None
        if existing is not None:
            raise PlatformLoginServiceError(
                "PLATFORM_ACCOUNT_CONFLICT",
                "account reference already exists",
                status_code=409,
            )

        now = self._now()
        register = getattr(self._accounts, "register_account", None)
        try:
            if callable(register):
                account = await _maybe_await(
                    register(
                        tenant_id=ref.tenant_id,
                        platform=ref.platform,
                        account_ref=ref.account_ref,
                        alias=alias,
                        now=now,
                    )
                )
            else:
                account = await self._accounts.save_account(
                    PlatformAccount(
                        tenant_id=ref.tenant_id,
                        platform=ref.platform,
                        account_ref=ref.account_ref,
                        alias=alias,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except PlatformLoginServiceError:
            raise
        except Exception as exc:
            # Repository adapters expose their own stable code; the API layer
            # maps this use-case error without serialising the exception text.
            code = getattr(exc, "code", "PLATFORM_ACCOUNT_CONFLICT")
            raise PlatformLoginServiceError(str(code), "account registration failed", status_code=409) from None

        grant_permissions = _normalise_permissions(permissions)
        add_grant = getattr(self._accounts, "add_grant", None)
        if callable(add_grant):
            grant = PlatformAccountGrant(
                grant_id=f"grant-{uuid4().hex}",
                account=ref,
                principal_id=principal_id,
                permissions=grant_permissions,
                issued_at=now,
            )
            try:
                await _maybe_await(add_grant(grant))
            except Exception:
                # Do not leave an account that the registering principal cannot
                # use.  A repository may expose a delete/disable seam; when it
                # does not, return a dependency error and require operator
                # reconciliation rather than granting an unscoped account.
                disable = getattr(self._accounts, "disable_account", None)
                if callable(disable):
                    await _maybe_await(disable(ref))
                raise PlatformLoginServiceError(
                    "PLATFORM_GRANT_UNAVAILABLE",
                    "account authorization is unavailable",
                    status_code=503,
                ) from None
        elif not callable(getattr(self._accounts, "authorize", None)):
            raise PlatformLoginServiceError(
                "PLATFORM_GRANT_UNAVAILABLE",
                "account authorization is unavailable",
                status_code=503,
            )
        return account

    async def get_account(self, *, tenant_id: str, principal_id: str, platform: str, account_ref: str) -> PlatformAccount:
        ref = _make_ref(tenant_id, platform, account_ref)
        await self._authorize(ref, principal_id, AccountGrantPermission.VIEW)
        try:
            account = await self._accounts.get_account(ref)
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform account authority is unavailable",
                status_code=503,
            ) from None
        if account is None:
            raise PlatformLoginServiceError("PLATFORM_ACCOUNT_NOT_FOUND", "account not found", status_code=404)
        return account

    # ------------------------------------------------------------------
    # Login command/query methods
    # ------------------------------------------------------------------

    async def start_login(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        platform: str | PlatformChannel,
        account_ref: str,
        mode: str | LoginMode = LoginMode.QR,
        idempotency_key: str | None = None,
        credential_ref: str | None = None,
    ) -> LoginSubmission:
        ref = _make_ref(tenant_id, platform, account_ref)
        login_mode = _parse_mode(mode)
        await self._authorize(ref, principal_id, AccountGrantPermission.LOGIN)
        try:
            account = await self._accounts.get_account(ref)
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform account authority is unavailable",
                status_code=503,
            ) from None
        if account is None:
            raise PlatformLoginServiceError("PLATFORM_ACCOUNT_NOT_FOUND", "account not found", status_code=404)
        key = _idempotency_key(idempotency_key)
        flow_id = _flow_id(ref, key)
        try:
            existing = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform login flow authority is unavailable",
                status_code=503,
            ) from None
        operation = {
            LoginMode.QR: LoginActivityOperation.CREATE_QR,
            LoginMode.PHONE: LoginActivityOperation.PHONE_LOGIN,
            LoginMode.COOKIE: LoginActivityOperation.COOKIE_IMPORT,
        }[login_mode]
        if operation in {LoginActivityOperation.PHONE_LOGIN, LoginActivityOperation.COOKIE_IMPORT}:
            _validate_credential_ref(credential_ref)
        if existing is not None:
            if existing.account.natural_key != ref.natural_key:
                raise PlatformLoginServiceError("LOGIN_FLOW_CONFLICT", "login flow conflict", status_code=409)
            if existing.state in {
                LoginFlowState.SUCCEEDED,
                LoginFlowState.EXPIRED,
                LoginFlowState.FAILED,
                LoginFlowState.CANCELLED,
            }:
                return LoginSubmission(flow=existing)
            # A local coordinator is an explicitly injected execution seam,
            # just like Temporal.  Active deterministic flows must be handed
            # back to it so a retry can resume a CREATED snapshot and mint the
            # QR challenge; returning the snapshot here would make local
            # idempotent retries appear successful while doing no work.
            flow = existing
        else:
            flow = await self._create_flow(ref, flow_id)
        request = PlatformLoginActivityRequest(
            flow_id=flow_id,
            account=ref,
            operation=operation,
            credential_ref=credential_ref,
        )

        if self._workflow is not None:
            command = _build_workflow_start(
                self._build_start,
                request,
                workflow_id=flow_id,
                idempotency_key=key,
                execution_policy=self._execution_policy,
                task_queue=self._queue,
            )
            try:
                run = await self._workflow.start(command)
            except Exception:
                # The initial flow remains queryable and can be retried with
                # the same idempotency key; no provider call occurs in API.
                raise PlatformLoginServiceError(
                    "LOGIN_WORKFLOW_UNAVAILABLE",
                    "login execution is unavailable",
                    status_code=503,
                ) from None
            return LoginSubmission(flow=flow, workflow=run)

        coordinator = self._coordinator
        if coordinator is None:
            raise PlatformLoginServiceError(
                "LOGIN_EXECUTION_UNAVAILABLE",
                "login execution is unavailable",
                status_code=503,
            )
        try:
            if operation is LoginActivityOperation.CREATE_QR:
                result = await _maybe_await(coordinator.start_qr(ref, flow_id=flow_id))
                actual_flow, challenge = result
                return LoginSubmission(flow=actual_flow, challenge=challenge)
            if operation is LoginActivityOperation.PHONE_LOGIN:
                actual_flow = await _maybe_await(
                    coordinator.phone_login(
                        flow_id, tenant_id=tenant_id, credential_ref=credential_ref or ""
                    )
                )
            else:
                actual_flow = await _maybe_await(
                    coordinator.cookie_import(
                        flow_id, tenant_id=tenant_id, credential_ref=credential_ref or ""
                    )
                )
            return LoginSubmission(flow=actual_flow)
        except TypeError:
            # Older local coordinators did not accept an explicit flow_id.  Do
            # not silently use them for deterministic API flows; surface a
            # dependency status instead of returning a mismatched ID.
            raise PlatformLoginServiceError(
                "LOGIN_COORDINATOR_VERSION_UNSUPPORTED",
                "login coordinator version is unavailable",
                status_code=503,
            ) from None
        except Exception:
            raise PlatformLoginServiceError(
                "LOGIN_PROVIDER_ERROR",
                "login provider operation failed",
                status_code=502,
            ) from None

    # Explicit aliases keep the use case discoverable for adapters that model
    # QR and re-auth commands as separate methods while retaining one
    # idempotency/authorization implementation.
    async def start_qr(self, **kwargs: Any) -> LoginSubmission:
        kwargs["mode"] = LoginMode.QR
        return await self.start_login(**kwargs)

    async def reauth(self, **kwargs: Any) -> LoginSubmission:
        return await self.start_login(**kwargs)

    async def poll(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        flow_id: str,
        idempotency_key: str | None = None,
    ) -> LoginSubmission:
        flow = await self._get_authorized_flow(flow_id, tenant_id, principal_id, AccountGrantPermission.LOGIN)
        if flow.state in {
            LoginFlowState.SUCCEEDED,
            LoginFlowState.EXPIRED,
            LoginFlowState.FAILED,
            LoginFlowState.CANCELLED,
        }:
            return LoginSubmission(flow=flow)
        key = _idempotency_key(idempotency_key or f"poll:{flow_id}")
        request = PlatformLoginActivityRequest(
            flow_id=flow.flow_id,
            account=flow.account,
            operation=LoginActivityOperation.POLL,
        )
        if self._workflow is not None:
            # Every operation for a login attempt addresses the same stable
            # Temporal Workflow ID.  The adapter's USE_EXISTING conflict
            # policy attaches a concurrent request to the active run, while
            # ALLOW_DUPLICATE permits the next poll/phone/cookie operation to
            # start a fresh run after the prior one has completed.  Keeping
            # the base ID here is essential: ``cancel()`` receives only the
            # public flow ID and must signal the currently active operation,
            # not an operation-specific derived ID that it cannot discover.
            workflow_id = flow.flow_id
            command = _build_workflow_start(
                self._build_start,
                request,
                workflow_id=workflow_id,
                idempotency_key=key,
                execution_policy=self._execution_policy,
                task_queue=self._queue,
            )
            try:
                run = await self._workflow.start(command)
            except Exception:
                raise PlatformLoginServiceError("LOGIN_WORKFLOW_UNAVAILABLE", "login execution is unavailable", status_code=503) from None
            return LoginSubmission(flow=flow, workflow=run)
        if self._coordinator is None:
            raise PlatformLoginServiceError("LOGIN_EXECUTION_UNAVAILABLE", "login execution is unavailable", status_code=503)
        try:
            updated = await _maybe_await(self._coordinator.poll(flow.flow_id, tenant_id=tenant_id))
        except Exception:
            raise PlatformLoginServiceError("LOGIN_PROVIDER_ERROR", "login provider operation failed", status_code=502) from None
        return LoginSubmission(flow=updated)

    async def status(self, *, tenant_id: str, principal_id: str, flow_id: str) -> PlatformLoginFlow:
        # ``VIEW`` is sufficient for status; it does not permit login commands.
        flow = await self._get_authorized_flow(flow_id, tenant_id, principal_id, AccountGrantPermission.VIEW)
        flow = await self._expire_flow_if_needed(flow)
        coordinator = self._coordinator
        if coordinator is not None and hasattr(coordinator, "status"):
            try:
                return await _maybe_await(coordinator.status(flow_id, tenant_id=tenant_id))
            except Exception:
                # The durable flow remains authoritative if the optional local
                # coordinator is unavailable.
                return flow
        return flow

    async def get_status(self, **kwargs: Any) -> PlatformLoginFlow:
        return await self.status(**kwargs)

    async def cancel(self, *, tenant_id: str, principal_id: str, flow_id: str, reason: str | None = None) -> LoginSubmission:
        flow = await self._get_authorized_flow(flow_id, tenant_id, principal_id, AccountGrantPermission.LOGIN)
        if flow.state in {
            LoginFlowState.SUCCEEDED,
            LoginFlowState.EXPIRED,
            LoginFlowState.FAILED,
            LoginFlowState.CANCELLED,
        }:
            return LoginSubmission(flow=flow)
        if self._workflow is not None:
            safe_reason = _safe_reason(reason)
            try:
                signal_with_start = getattr(self._workflow, "signal_with_start", None)
                if callable(signal_with_start):
                    # One atomic Temporal RPC handles both cancellation races:
                    # an active operation receives the signal, while a
                    # completed non-terminal poll causes a new CANCEL run to
                    # start under the same stable flow ID.  Older WorkflowPort
                    # implementations retain the plain-cancel compatibility
                    # path below.
                    key = f"cancel:{hashlib.sha256(flow.flow_id.encode()).hexdigest()[:48]}"
                    request = PlatformLoginActivityRequest(
                        flow_id=flow.flow_id,
                        account=flow.account,
                        operation=LoginActivityOperation.CANCEL,
                    )
                    command = _build_workflow_start(
                        self._build_start,
                        request,
                        workflow_id=flow.flow_id,
                        idempotency_key=key,
                        execution_policy=self._execution_policy,
                        task_queue=self._queue,
                    )
                    run = await _maybe_await(
                        signal_with_start(
                            command,
                            _ACCOUNT_AUTH_CANCEL_SIGNAL,
                            {"reason": safe_reason or ""},
                        )
                    )
                    return LoginSubmission(flow=flow, workflow=run)
                await self._workflow.cancel(flow.flow_id, reason=safe_reason)
            except Exception:
                raise PlatformLoginServiceError("LOGIN_WORKFLOW_UNAVAILABLE", "login cancellation is unavailable", status_code=503) from None
            return LoginSubmission(flow=flow)
        if self._coordinator is None:
            raise PlatformLoginServiceError("LOGIN_EXECUTION_UNAVAILABLE", "login execution is unavailable", status_code=503)
        try:
            updated = await _maybe_await(self._coordinator.cancel(flow.flow_id, tenant_id=tenant_id))
        except Exception:
            raise PlatformLoginServiceError("LOGIN_PROVIDER_ERROR", "login cancellation failed", status_code=502) from None
        return LoginSubmission(flow=updated)

    async def get_qr(self, *, tenant_id: str, principal_id: str, flow_id: str) -> QrPresentation:
        flow = await self._get_authorized_flow(flow_id, tenant_id, principal_id, AccountGrantPermission.VIEW)
        flow = await self._expire_flow_if_needed(flow)
        if flow.state in {
            LoginFlowState.SUCCEEDED,
            LoginFlowState.EXPIRED,
            LoginFlowState.FAILED,
            LoginFlowState.CANCELLED,
        }:
            raise PlatformLoginServiceError("LOGIN_QR_UNAVAILABLE", "QR challenge is no longer available", status_code=410)
        if flow.qr_object_ref is None or flow.qr_expires_at is None:
            raise PlatformLoginServiceError("LOGIN_QR_NOT_READY", "QR challenge is not ready", status_code=404)
        if self._now() >= flow.qr_expires_at:
            raise PlatformLoginServiceError("LOGIN_QR_EXPIRED", "QR challenge has expired", status_code=410)
        presentation_ref: str | None = None
        signer = getattr(self._object_store, "signed_url", None)
        if callable(signer):
            try:
                value = signer(flow.qr_object_ref, ttl_seconds=max(1, int((flow.qr_expires_at - self._now()).total_seconds())))
                presentation_ref = await _maybe_await(value)
            except Exception:
                presentation_ref = None
        if not isinstance(presentation_ref, str) or not presentation_ref:
            # Opaque in-app reference; it cannot be used as an object key or
            # reveal storage credentials.  A separate presentation adapter may
            # resolve it at the edge.
            digest = hashlib.sha256(f"{tenant_id}|{flow_id}".encode()).hexdigest()[:24]
            presentation_ref = f"qr-present:{digest}"
        return QrPresentation(
            flow_id=flow.flow_id,
            presentation_ref=presentation_ref,
            expires_at=flow.qr_expires_at,
            content_type=flow.qr_object_ref.content_type,
        )

    async def qr(self, **kwargs: Any) -> QrPresentation:
        return await self.get_qr(**kwargs)

    async def readiness(self) -> dict[str, Any]:
        return {
            "enabled": bool(self._workflow is not None or self._coordinator is not None),
            "execution": "temporal" if self._workflow is not None else ("local" if self._coordinator is not None else "disabled"),
            "queue": self._queue,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _authorize(self, ref: PlatformAccountRef, principal_id: str, permission: AccountGrantPermission) -> None:
        _validate_principal(principal_id)
        authorize = getattr(self._accounts, "authorize", None)
        if not callable(authorize):
            raise PlatformLoginServiceError("PLATFORM_GRANT_UNAVAILABLE", "account authorization is unavailable", status_code=503)
        try:
            grant = await _maybe_await(authorize(ref, principal_id, permission))
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform account authority is unavailable",
                status_code=503,
            ) from None
        if grant is None:
            # Deliberately indistinguishable from a missing account to avoid
            # cross-tenant account enumeration.
            raise PlatformLoginServiceError("PLATFORM_ACCOUNT_NOT_FOUND", "account not found", status_code=404)

    async def _get_authorized_flow(self, flow_id: str, tenant_id: str, principal_id: str, permission: AccountGrantPermission) -> PlatformLoginFlow:
        if not flow_id or len(flow_id) > 128 or any(character.isspace() for character in flow_id):
            raise PlatformLoginServiceError("LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404)
        try:
            flow = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
        except Exception:
            raise PlatformLoginServiceError(
                "PLATFORM_AUTHORITY_UNAVAILABLE",
                "platform login flow authority is unavailable",
                status_code=503,
            ) from None
        if flow is None:
            raise PlatformLoginServiceError("LOGIN_FLOW_NOT_FOUND", "login flow not found", status_code=404)
        await self._authorize(flow.account, principal_id, permission)
        return flow

    async def _create_flow(self, ref: PlatformAccountRef, flow_id: str) -> PlatformLoginFlow:
        now = self._now()
        flow = PlatformLoginFlow(
            flow_id=flow_id,
            account=ref,
            state=LoginFlowState.CREATED,
            created_at=now,
            expires_at=now + timedelta(seconds=self._flow_ttl),
            updated_at=now,
        )
        try:
            return await self._flows.save_flow(flow)
        except Exception:
            raise PlatformLoginServiceError("LOGIN_FLOW_CONFLICT", "login flow could not be created", status_code=409) from None

    async def _expire_flow_if_needed(self, flow: PlatformLoginFlow) -> PlatformLoginFlow:
        if flow.state in {
            LoginFlowState.SUCCEEDED,
            LoginFlowState.EXPIRED,
            LoginFlowState.FAILED,
            LoginFlowState.CANCELLED,
        }:
            return flow
        now = self._now()
        if now < flow.expires_at and (
            flow.qr_expires_at is None or now < flow.qr_expires_at
        ):
            return flow
        try:
            expired = transition_login_flow(
                flow,
                LoginFlowState.EXPIRED,
                updated_at=now,
                error_code="LOGIN_FLOW_EXPIRED",
            )
            return await self._flows.save_flow(expired)
        except Exception:
            # A concurrent worker may have performed the terminal transition;
            # re-read the durable record and keep the API fail-closed if the
            # authority is temporarily unavailable.
            try:
                current = await self._flows.get_flow(flow.flow_id, tenant_id=flow.account.tenant_id)
            except Exception:
                return flow
            return current or flow

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("login clock must return timezone-aware timestamps")
        return value.astimezone(UTC)


def _make_ref(tenant_id: str, platform: str | PlatformChannel, account_ref: str) -> PlatformAccountRef:
    try:
        return PlatformAccountRef(
            tenant_id=tenant_id,
            platform=platform if isinstance(platform, PlatformChannel) else PlatformChannel(str(platform)),
            account_ref=account_ref,
        )
    except Exception:
        raise PlatformLoginServiceError("PLATFORM_ACCOUNT_INVALID", "platform account reference is invalid", status_code=422) from None


def _parse_mode(value: str | LoginMode) -> LoginMode:
    try:
        return value if isinstance(value, LoginMode) else LoginMode(str(value).strip().casefold())
    except ValueError:
        raise PlatformLoginServiceError("LOGIN_MODE_INVALID", "login mode is invalid", status_code=422) from None


def _idempotency_key(value: str | None) -> str:
    if value is None or not str(value).strip():
        return f"request-{uuid4().hex}"
    text = str(value).strip()
    if len(text) > 128 or any(character.isspace() for character in text):
        raise PlatformLoginServiceError("IDEMPOTENCY_KEY_INVALID", "idempotency key is invalid", status_code=422)
    if any(not (character.isalnum() or character in "_.:-") for character in text):
        raise PlatformLoginServiceError("IDEMPOTENCY_KEY_INVALID", "idempotency key is invalid", status_code=422)
    return text


def _flow_id(ref: PlatformAccountRef, key: str) -> str:
    digest = hashlib.sha256(f"{ref.tenant_id}|{ref.platform.value}|{ref.account_ref}|{key}".encode()).hexdigest()
    return f"flow-{digest[:48]}"


def _normalise_permissions(values: Sequence[str | AccountGrantPermission] | None) -> tuple[AccountGrantPermission, ...]:
    if values is None:
        return (
            AccountGrantPermission.VIEW,
            AccountGrantPermission.USE,
            AccountGrantPermission.LOGIN,
            AccountGrantPermission.REFRESH,
        )
    result: list[AccountGrantPermission] = []
    for value in values:
        try:
            permission = value if isinstance(value, AccountGrantPermission) else AccountGrantPermission(str(value))
        except ValueError:
            raise PlatformLoginServiceError("PLATFORM_PERMISSION_INVALID", "account permission is invalid", status_code=422) from None
        if permission is AccountGrantPermission.ADMIN:
            raise PlatformLoginServiceError("PLATFORM_PERMISSION_INVALID", "admin permission requires an operator grant", status_code=422)
        if permission not in result:
            result.append(permission)
    if not result:
        raise PlatformLoginServiceError("PLATFORM_PERMISSION_INVALID", "at least one account permission is required", status_code=422)
    return tuple(result)


def _validate_alias(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise PlatformLoginServiceError("PLATFORM_ALIAS_INVALID", "account alias is invalid", status_code=422)


def _validate_principal(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(character.isspace() for character in value):
        raise PlatformLoginServiceError("PLATFORM_PRINCIPAL_INVALID", "principal reference is invalid", status_code=422)


def _validate_credential_ref(value: str | None) -> None:
    if value is None or not value or len(value) > 128 or value != value.strip() or any(character.isspace() for character in value):
        raise PlatformLoginServiceError("CREDENTIAL_REF_INVALID", "credential reference is invalid", status_code=422)
    if any(not (character.isalnum() or character in "_.-:") for character in value):
        raise PlatformLoginServiceError("CREDENTIAL_REF_INVALID", "credential reference is invalid", status_code=422)


def _safe_reason(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    # Reason is operator-authored but still bounded and assignment-free.  It
    # crosses the Temporal cancellation boundary, so redact common credential
    # assignments and bearer values before returning it.
    import re

    text = re.sub(
        r"(?i)([\"']?(?:cookie|authorization|bearer|token|password|passwd|secret|qruuid|"
        r"storage[_ -]?state|signer[_ -]?(?:input|state)|xsec[_ -]?token)[\"']?\s*[:=]\s*[\"']?)[^\"'\r\n,;}]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "bearer <redacted>", text)
    return text[:128]


def _redacted_flow(flow: PlatformLoginFlow) -> dict[str, Any]:
    """Serialize only flow metadata approved for API/transport responses."""

    return {
        "schema_version": flow.schema_version,
        "flow_id": flow.flow_id,
        "account": flow.account.model_dump(mode="json"),
        "state": flow.state.value,
        "created_at": flow.created_at,
        "expires_at": flow.expires_at,
        "updated_at": flow.updated_at,
        "qr_expires_at": flow.qr_expires_at,
        "provider_subject_id": flow.provider_subject_id,
        "error_code": flow.error_code,
        "error_message": flow.error_message,
    }


def _build_workflow_start(
    builder: WorkflowStartBuilder | None,
    request: PlatformLoginActivityRequest,
    *,
    workflow_id: str,
    idempotency_key: str,
    execution_policy: TemporalExecutionPolicy | None,
    task_queue: str,
) -> Any:
    if builder is None:
        raise PlatformLoginServiceError("LOGIN_WORKFLOW_UNAVAILABLE", "login execution is unavailable", status_code=503)
    kwargs: dict[str, Any] = {
        "workflow_id": workflow_id,
        "idempotency_key": idempotency_key,
        "task_queue": task_queue,
    }
    if execution_policy is not None:
        kwargs["execution_policy"] = execution_policy
    try:
        return builder(request, **kwargs)
    except TypeError:
        # Small test seams may accept only request/workflow/idempotency.  Keep
        # the fallback explicit and never pass credential-bearing fields.
        try:
            return builder(request, workflow_id, idempotency_key)
        except Exception:
            raise PlatformLoginServiceError("LOGIN_WORKFLOW_UNAVAILABLE", "login execution is unavailable", status_code=503) from None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "LoginMode",
    "LoginSubmission",
    "PlatformLoginService",
    "PlatformLoginServiceError",
    "QrPresentation",
]
