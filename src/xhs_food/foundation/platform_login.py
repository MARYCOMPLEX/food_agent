"""Split-phase, account-scoped login orchestration.

Provider-specific browser and signer implementations are injected at this
boundary.  The coordinator owns only durable flow transitions, expiring QR
object references, and session-version CAS; it never serializes provider
cookies or QR bytes into a workflow/API contract.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import uuid4

from xhs_food.contracts import (
    LOGIN_FLOW_TERMINAL_STATES,
    LoginChallenge,
    LoginFlowState,
    PlatformAccountRef,
    PlatformAccountRepositoryPort,
    PlatformLoginFlow,
    PlatformLoginFlowPort,
    SessionActivationRequest,
    SessionEnvelopeCodecPort,
    transition_login_flow,
)
from xhs_food.contracts.ports import ObjectStore

from .platform_accounts import (
    AccountAuthorityError,
    AccountNotFoundError,
    AccountVersionConflict,
    encode_session_material,
)


class LoginProviderState(StrEnum):
    WAITING_SCAN = "waiting_scan"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SUCCEEDED = "succeeded"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QrProviderResult:
    """Provider QR bytes kept in memory until they are uploaded to ObjectStore."""

    image_bytes: bytes
    content_type: str = "image/png"
    expires_at: datetime | None = None
    provider_flow_ref: str | None = None


@dataclass(frozen=True, slots=True)
class LoginPollResult:
    state: LoginProviderState
    provider_subject_id: str | None = None
    session_material: Mapping[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


class PlatformLoginProvider(Protocol):
    """Minimal provider surface; methods may be sync or async at the edge.

    Credential-bearing phone/cookie values are resolved by the provider from
    an activity-local vault.  The coordinator receives only an opaque
    ``credential_ref`` handle, so no secret crosses the Temporal boundary.
    """

    def create_qr(self, account: PlatformAccountRef, flow_id: str) -> QrProviderResult | Awaitable[QrProviderResult]: ...

    def poll(self, account: PlatformAccountRef, flow_id: str) -> LoginPollResult | Awaitable[LoginPollResult]: ...

    def phone_login(
        self,
        account: PlatformAccountRef,
        flow_id: str,
        credential_ref: str,
    ) -> LoginPollResult | Awaitable[LoginPollResult]: ...

    def cookie_import(
        self,
        account: PlatformAccountRef,
        flow_id: str,
        credential_ref: str,
    ) -> LoginPollResult | Awaitable[LoginPollResult]: ...

    def cancel(self, account: PlatformAccountRef, flow_id: str) -> object | Awaitable[object]: ...


class LoginFlowNotFound(AccountAuthorityError):
    code = "LOGIN_FLOW_NOT_FOUND"


class LoginFlowConflict(AccountAuthorityError):
    code = "LOGIN_FLOW_CONFLICT"


class LoginFlowExpired(AccountAuthorityError):
    code = "LOGIN_FLOW_EXPIRED"


class PlatformLoginCoordinator:
    """Coordinate QR/poll/cancel without putting secrets on durable boundaries."""

    def __init__(
        self,
        *,
        accounts: PlatformAccountRepositoryPort,
        flows: PlatformLoginFlowPort,
        codec: SessionEnvelopeCodecPort,
        object_store: ObjectStore,
        provider_factory: Callable[[PlatformAccountRef], PlatformLoginProvider],
        health: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        flow_ttl_seconds: int = 300,
        provider_timeout_seconds: float = 30.0,
    ) -> None:
        if flow_ttl_seconds < 30:
            raise ValueError("login flow TTL must be at least 30 seconds")
        if provider_timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._accounts = accounts
        self._flows = flows
        self._codec = codec
        self._object_store = object_store
        self._provider_factory = provider_factory
        self._health = health
        self._clock = clock or (lambda: datetime.now(UTC))
        self._flow_ttl = flow_ttl_seconds
        self._provider_timeout = provider_timeout_seconds
        self._lock = asyncio.Lock()

    async def start_qr(
        self,
        account: PlatformAccountRef,
        *,
        flow_id: str | None = None,
    ) -> tuple[PlatformLoginFlow, LoginChallenge | None]:
        """Create or resume one flow and upload one short-lived QR object.

        A deterministic ``flow_id`` is the retry/idempotency key used by the
        account-auth workflow.  If a durable snapshot already exists, its
        deadline and QR reference are authoritative: an active flow with a
        persisted QR is returned without another provider call, while a
        ``created`` snapshot resumes QR creation with the original deadline.
        Terminal snapshots are returned with no challenge because their QR
        object has been cleaned up (or is no longer discoverable).
        """

        if flow_id is not None:
            _validate_flow_id(flow_id)
        async with self._lock:
            registered = await self._accounts.get_account(account)
            if registered is None:
                raise AccountNotFoundError("account is not registered")

            requested_flow_id = flow_id or f"flow-{uuid4().hex}"
            flow = await self._load_or_create_flow(account, requested_flow_id)
            flow = await self._expire_if_needed(flow)
            if flow.state in LOGIN_FLOW_TERMINAL_STATES:
                return flow, None

            existing_challenge = _challenge_from_flow(flow)
            if existing_challenge is not None:
                return flow, existing_challenge
            if flow.state is not LoginFlowState.CREATED:
                # A non-terminal snapshot without a QR reference cannot be
                # safely reconstructed.  Do not mint a second challenge or
                # silently extend the durable deadline.
                raise LoginFlowConflict("active login flow has no QR challenge")

            return await self._create_qr_for_flow(account, flow)

    async def _load_or_create_flow(
        self,
        account: PlatformAccountRef,
        flow_id: str,
    ) -> PlatformLoginFlow:
        """Load an existing flow or win the create race without changing its deadline."""

        existing = await self._flows.get_flow(flow_id, tenant_id=account.tenant_id)
        if existing is not None:
            if existing.account.natural_key != account.natural_key:
                raise LoginFlowConflict("login flow is bound to another account")
            return existing

        now = self._now()
        candidate = PlatformLoginFlow(
            flow_id=flow_id,
            account=account,
            state=LoginFlowState.CREATED,
            created_at=now,
            expires_at=now + timedelta(seconds=self._flow_ttl),
            updated_at=now,
        )
        try:
            return await self._flows.save_flow(candidate)
        except Exception as exc:
            # Another worker may have inserted the same deterministic flow
            # between get and save.  Re-read and resume that authoritative
            # snapshot; if the authority itself is unavailable, preserve the
            # original failure instead of fabricating a new deadline.
            try:
                raced = await self._flows.get_flow(flow_id, tenant_id=account.tenant_id)
            except Exception:
                raise exc from None
            if raced is None:
                raise
            if raced.account.natural_key != account.natural_key:
                raise LoginFlowConflict("login flow is bound to another account") from exc
            return raced

    async def _create_qr_for_flow(
        self,
        account: PlatformAccountRef,
        flow: PlatformLoginFlow,
    ) -> tuple[PlatformLoginFlow, LoginChallenge]:
        """Run provider QR creation for an authoritative ``created`` snapshot."""

        uploaded_ref: Any | None = None
        provider: PlatformLoginProvider | None = None
        try:
            # Browser/signer construction may block; keep it off the API
            # event loop just like the provider operation itself.
            provider = cast(
                PlatformLoginProvider,
                await self._call(self._provider_factory, account),
            )
            qr = await self._call(provider.create_qr, account, flow.flow_id)
            if not isinstance(qr.image_bytes, bytes) or not qr.image_bytes:
                raise LoginFlowConflict("provider returned an empty QR challenge")
            qr_expiry = min(
                _as_utc(qr.expires_at) if qr.expires_at is not None else flow.expires_at,
                flow.expires_at,
            )
            object_key = f"login-qr/{account.tenant_id}/{account.platform.value}/{flow.flow_id}.bin"
            object_ref = await self._object_store.put(
                object_key,
                _one_chunk(qr.image_bytes),
                qr.content_type or "image/png",
                metadata={
                    "flow_id": flow.flow_id,
                    "platform": account.platform.value,
                    "expires_at": qr_expiry.isoformat(),
                },
            )
            # Keep the reference separately until the flow snapshot is
            # durably saved.  A database failure in the transition window
            # must not leave an orphaned QR object behind.
            uploaded_ref = object_ref
            flow = transition_login_flow(
                flow,
                LoginFlowState.QR_READY,
                updated_at=self._now(),
                qr_object_ref=object_ref,
                qr_expires_at=qr_expiry,
            )
            await self._flows.save_flow(flow)
            flow = transition_login_flow(
                flow,
                LoginFlowState.WAITING_SCAN,
                updated_at=self._now(),
            )
            await self._flows.save_flow(flow)
            challenge = _challenge_from_flow(flow)
            if challenge is None:
                raise LoginFlowConflict("QR challenge snapshot is incomplete")
            return flow, challenge
        except asyncio.CancelledError:
            await self._safe_delete(uploaded_ref or flow.qr_object_ref)
            raise
        except Exception as exc:
            cleanup_ref = uploaded_ref or flow.qr_object_ref
            try:
                await self._fail_flow(flow, "LOGIN_QR_CREATE_FAILED", _safe_message(exc))
            finally:
                # ``_fail_flow`` can only see a reference present on the
                # current snapshot; explicitly clean the uploaded ref when a
                # transition/save failed before that snapshot was committed.
                if cleanup_ref is not None and cleanup_ref is not flow.qr_object_ref:
                    await self._safe_delete(cleanup_ref)
            raise
        finally:
            # Provider instances may own browser/session resources.  The
            # coordinator creates one for this operation, so close it on every
            # success, failure, and cancellation path.  ``_close_provider``
            # dispatches synchronous cleanup off the event loop and suppresses
            # cleanup errors without masking the authoritative flow result.
            await self._close_provider(provider)

    async def poll(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow:
        """Poll one flow and commit a session only after verified success."""

        async with self._lock:
            flow = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
            if flow is None:
                raise LoginFlowNotFound("login flow is not found")
            flow = await self._expire_if_needed(flow)
            if flow.state in {
                LoginFlowState.SUCCEEDED,
                LoginFlowState.EXPIRED,
                LoginFlowState.FAILED,
                LoginFlowState.CANCELLED,
            }:
                return flow
            provider: PlatformLoginProvider | None = None
            try:
                provider = cast(
                    PlatformLoginProvider,
                    await self._call(self._provider_factory, flow.account),
                )
                result = await self._call(provider.poll, flow.account, flow.flow_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return await self._fail_flow(flow, "LOGIN_PROVIDER_ERROR", _safe_message(exc))
            else:
                # Keep the provider alive while the result is consumed: some
                # adapters return a session-material mapping backed by their
                # client object.  More importantly, process provider failures
                # separately from project-authority failures.  If session CAS
                # succeeds and the terminal flow save then fails, that storage
                # exception must propagate so Temporal retries the operation;
                # rewriting it as a provider failure would attempt to erase
                # the durable subject marker and mask the recoverable state.
                return await self._apply_provider_result(flow, result)
            finally:
                await self._close_provider(provider)

    async def phone_login(
        self,
        flow_id: str,
        *,
        tenant_id: str,
        credential_ref: str,
    ) -> PlatformLoginFlow:
        """Complete a phone login using an activity-local credential handle."""

        return await self._credential_login(
            flow_id,
            tenant_id=tenant_id,
            credential_ref=credential_ref,
            operation="phone_login",
        )

    async def cookie_import(
        self,
        flow_id: str,
        *,
        tenant_id: str,
        credential_ref: str,
    ) -> PlatformLoginFlow:
        """Import cookie/storage state through a vault-backed provider.

        ``credential_ref`` is an opaque vault key.  Raw cookie strings and
        storage-state paths are deliberately not accepted by this boundary.
        """

        return await self._credential_login(
            flow_id,
            tenant_id=tenant_id,
            credential_ref=credential_ref,
            operation="cookie_import",
        )

    # Provider implementations historically called this ``import_cookie``;
    # retain the alias while keeping one canonical operation name in contracts.
    async def import_cookie(
        self,
        flow_id: str,
        *,
        tenant_id: str,
        credential_ref: str,
    ) -> PlatformLoginFlow:
        return await self.cookie_import(
            flow_id,
            tenant_id=tenant_id,
            credential_ref=credential_ref,
        )

    async def cancel(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow:
        async with self._lock:
            flow = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
            if flow is None:
                raise LoginFlowNotFound("login flow is not found")
            if flow.state in {
                LoginFlowState.SUCCEEDED,
                LoginFlowState.EXPIRED,
                LoginFlowState.FAILED,
                LoginFlowState.CANCELLED,
            }:
                return flow
            provider: PlatformLoginProvider | None = None
            try:
                provider = cast(
                    PlatformLoginProvider,
                    await self._call(self._provider_factory, flow.account),
                )
                await self._call(provider.cancel, flow.account, flow.flow_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Cancellation remains authoritative even if the provider is
                # already gone; no session can be activated after this point.
                pass
            finally:
                await self._close_provider(provider)
            cancelled = transition_login_flow(
                flow,
                LoginFlowState.CANCELLED,
                updated_at=self._now(),
            )
            await self._flows.save_flow(cancelled)
            await self._safe_delete(cancelled.qr_object_ref)
            return cancelled

    async def status(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow:
        flow = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
        if flow is None:
            raise LoginFlowNotFound("login flow is not found")
        return await self._expire_if_needed(flow)

    async def _credential_login(
        self,
        flow_id: str,
        *,
        tenant_id: str,
        credential_ref: str,
        operation: str,
    ) -> PlatformLoginFlow:
        """Run a phone/cookie provider operation under the account lock.

        The provider receives only an opaque vault reference.  Synchronous
        implementations are dispatched by :meth:`_call` to a worker thread,
        preserving the API event loop and allowing Temporal cancellation and
        timeout policy to apply at the Activity boundary.
        """

        _validate_credential_ref(credential_ref)
        async with self._lock:
            flow = await self._flows.get_flow(flow_id, tenant_id=tenant_id)
            if flow is None:
                raise LoginFlowNotFound("login flow is not found")
            flow = await self._expire_if_needed(flow)
            if flow.state in {
                LoginFlowState.SUCCEEDED,
                LoginFlowState.EXPIRED,
                LoginFlowState.FAILED,
                LoginFlowState.CANCELLED,
            }:
                return flow
            provider: PlatformLoginProvider | None = None
            try:
                provider = cast(
                    PlatformLoginProvider,
                    await self._call(self._provider_factory, flow.account),
                )
                function = getattr(provider, operation, None)
                if function is None or not callable(function):
                    return await self._fail_flow(
                        flow,
                        "LOGIN_OPERATION_UNSUPPORTED",
                        operation,
                    )
                result = await self._call(
                    function,
                    flow.account,
                    flow.flow_id,
                    credential_ref,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return await self._fail_flow(flow, "LOGIN_PROVIDER_ERROR", _safe_message(exc))
            else:
                # Authority/CAS failures are durable execution failures, not
                # provider responses.  Let Temporal retry them without
                # replacing the already-persisted redacted subject marker.
                return await self._apply_provider_result(flow, result)
            finally:
                await self._close_provider(provider)

    async def _apply_provider_result(
        self,
        flow: PlatformLoginFlow,
        result: object,
    ) -> PlatformLoginFlow:
        """Map a provider result and atomically activate a validated session."""

        if not isinstance(result, LoginPollResult):
            return await self._fail_flow(flow, "LOGIN_PROVIDER_RESULT_INVALID", None)
        try:
            state = (
                result.state
                if isinstance(result.state, LoginProviderState)
                else LoginProviderState(result.state)
            )
        except (TypeError, ValueError):
            return await self._fail_flow(flow, "LOGIN_PROVIDER_STATE_INVALID", None)
        if state is LoginProviderState.WAITING_SCAN:
            return await self._advance(flow, LoginFlowState.WAITING_SCAN)
        if state is LoginProviderState.WAITING_CONFIRMATION:
            return await self._advance(flow, LoginFlowState.WAITING_CONFIRMATION)
        if state is LoginProviderState.EXPIRED:
            return await self._expire_flow(flow)
        if state is LoginProviderState.FAILED:
            return await self._fail_flow(
                flow,
                result.error_code or "LOGIN_PROVIDER_FAILED",
                result.error_message,
            )
        if state is not LoginProviderState.SUCCEEDED:
            return await self._fail_flow(flow, "LOGIN_PROVIDER_STATE_INVALID", None)

        if not result.provider_subject_id or not result.session_material:
            return await self._fail_flow(flow, "LOGIN_IDENTITY_MALFORMED", None)
        try:
            account = await self._accounts.get_account(flow.account)
        except Exception as exc:
            return await self._fail_flow(flow, "LOGIN_SESSION_LOOKUP_FAILED", _safe_message(exc))
        if account is None:
            return await self._fail_flow(flow, "LOGIN_ACCOUNT_NOT_FOUND", None)
        expected = account.session_version
        # A provider Activity may be retried after the session CAS succeeded
        # but before the flow snapshot was persisted.  Recognize that exact
        # subject/version as an idempotent completion instead of activating a
        # second session version; a different active subject is a conflict.
        if (
            expected >= 1
            and flow.provider_subject_id == result.provider_subject_id
            and account.provider_subject_id == result.provider_subject_id
        ):
            succeeded = transition_login_flow(
                flow,
                LoginFlowState.SUCCEEDED,
                updated_at=self._now(),
                provider_subject_id=result.provider_subject_id,
            )
            await self._flows.save_flow(succeeded)
            await self._safe_delete(succeeded.qr_object_ref)
            return succeeded
        try:
            encoded_material = encode_session_material(result.session_material)
        except Exception as exc:
            return await self._fail_flow(flow, "LOGIN_SESSION_MALFORMED", _safe_message(exc))
        plaintext = bytearray(encoded_material)
        try:
            # Persist a redacted subject marker before the CAS.  If the
            # process crashes after activation but before the terminal flow
            # save, a retry can identify the already-committed completion and
            # avoid creating a second session version.
            if flow.provider_subject_id != result.provider_subject_id:
                flow = flow.model_copy(
                    update={
                        "provider_subject_id": result.provider_subject_id,
                        "updated_at": self._now(),
                    }
                )
                await self._flows.save_flow(flow)
            envelope = await self._codec.seal(
                flow.account,
                bytes(plaintext),
                expires_at=flow.expires_at,
                version=expected + 1,
            )
            await self._accounts.activate_session(
                SessionActivationRequest(
                    account=flow.account,
                    expected_session_version=expected,
                    envelope=envelope,
                    expires_at=flow.expires_at,
                    requested_at=self._now(),
                    provider_subject_id=result.provider_subject_id,
                )
            )
        except AccountVersionConflict as exc:
            return await self._fail_flow(flow, exc.code, None)
        except Exception as exc:
            return await self._fail_flow(flow, "LOGIN_SESSION_COMMIT_FAILED", _safe_message(exc))
        finally:
            for index in range(len(plaintext)):
                plaintext[index] = 0
        succeeded = transition_login_flow(
            flow,
            LoginFlowState.SUCCEEDED,
            updated_at=self._now(),
            provider_subject_id=result.provider_subject_id,
        )
        await self._flows.save_flow(succeeded)
        await self._safe_delete(succeeded.qr_object_ref)
        return succeeded

    async def _advance(self, flow: PlatformLoginFlow, state: LoginFlowState) -> PlatformLoginFlow:
        if flow.state is state:
            return flow
        # A provider may report ``waiting_scan`` after a browser already moved
        # to confirmation.  Keep the durable state monotonic and return it.
        try:
            updated = transition_login_flow(flow, state, updated_at=self._now())
        except ValueError:
            return flow
        await self._flows.save_flow(updated)
        return updated

    async def _expire_if_needed(self, flow: PlatformLoginFlow) -> PlatformLoginFlow:
        if flow.state in {
            LoginFlowState.SUCCEEDED,
            LoginFlowState.EXPIRED,
            LoginFlowState.FAILED,
            LoginFlowState.CANCELLED,
        }:
            return flow
        if self._now() >= flow.expires_at:
            return await self._expire_flow(flow)
        if flow.qr_expires_at is not None and self._now() >= flow.qr_expires_at:
            return await self._expire_flow(flow)
        return flow

    async def _expire_flow(self, flow: PlatformLoginFlow) -> PlatformLoginFlow:
        expired = transition_login_flow(
            flow,
            LoginFlowState.EXPIRED,
            updated_at=self._now(),
            error_code="LOGIN_FLOW_EXPIRED",
        )
        await self._flows.save_flow(expired)
        await self._safe_delete(expired.qr_object_ref)
        return expired

    async def _fail_flow(
        self,
        flow: PlatformLoginFlow,
        code: str,
        message: str | None,
    ) -> PlatformLoginFlow:
        safe_code = _safe_code(code)
        failed = transition_login_flow(
            flow,
            LoginFlowState.FAILED,
            updated_at=self._now(),
            error_code=safe_code,
            error_message=_safe_message(message) if message else None,
        )
        await self._flows.save_flow(failed)
        await self._safe_delete(failed.qr_object_ref)
        return failed

    async def _safe_delete(self, ref: Any) -> None:
        if ref is None:
            return
        try:
            await self._object_store.delete(ref)
        except Exception:
            # Orphan reconciliation handles a failed delete; never expose the
            # provider or object-store exception to a login client.
            return

    async def _close_provider(self, provider: PlatformLoginProvider | None) -> None:
        """Best-effort close for one operation-scoped provider instance."""

        if provider is None:
            return
        close = getattr(provider, "aclose", None)
        if not callable(close):
            close = getattr(provider, "close", None)
        if not callable(close):
            return
        try:
            await self._call(close)
        except asyncio.CancelledError:
            # Preserve task cancellation; cleanup must never turn a cancelled
            # operation into a successful-looking login result.
            raise
        except Exception:
            # A provider cleanup failure is non-authoritative.  The flow/session
            # transition already records the operation result and can be
            # reconciled independently.
            return

    async def _call(self, function: Callable[..., Any], *args: Any) -> Any:
        if inspect.iscoroutinefunction(function):
            result = function(*args)
            return await asyncio.wait_for(cast(Awaitable[Any], result), self._provider_timeout)
        result = await asyncio.wait_for(
            asyncio.to_thread(function, *args),
            self._provider_timeout,
        )
        if inspect.isawaitable(result):
            return await asyncio.wait_for(cast(Awaitable[Any], result), self._provider_timeout)
        return result

    def _now(self) -> datetime:
        return _as_utc(self._clock())


def _one_chunk(value: bytes):
    async def generator():
        yield value

    return generator()


def _challenge_from_flow(flow: PlatformLoginFlow) -> LoginChallenge | None:
    """Rebuild the redacted challenge envelope from durable flow metadata."""

    object_ref = flow.qr_object_ref
    if object_ref is None:
        return None
    return LoginChallenge(
        flow_id=flow.flow_id,
        object_ref=object_ref,
        expires_at=flow.qr_expires_at or flow.expires_at,
        content_type=object_ref.content_type,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("login timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _safe_code(value: str) -> str:
    normalized = "".join(character for character in value.upper() if character.isalnum() or character in "_.-")
    return normalized[:128] or "LOGIN_PROVIDER_FAILED"


def _validate_flow_id(value: str) -> None:
    """Validate the path-safe AccountId grammar used by durable flow IDs."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value != value.strip()
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "_.-") for character in value)
    ):
        raise ValueError("flow_id must be a non-empty path-safe identifier")


def _validate_credential_ref(value: str) -> None:
    """Reject anything that could be a raw credential rather than a handle."""

    if not isinstance(value, str) or not value:
        raise ValueError("credential_ref must be a non-empty opaque handle")
    if value != value.strip() or any(character.isspace() for character in value):
        raise ValueError("credential_ref must not contain whitespace")
    if (
        len(value) > 128
        or not value[0].isalnum()
        or not all(character.isalnum() or character in "_.:-" for character in value)
    ):
        raise ValueError("credential_ref must use an opaque reference format")


def _safe_message(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    # Keep only a short diagnostic and remove common credential assignments.
    # The quoted-key form also covers JSON-ish provider errors such as
    # ``{"cookie":"..."}``, not just ``cookie=...`` headers.
    import re

    # Consume an optional ``Bearer`` marker as well as the token value; a
    # narrower assignment-only pattern would leak the value after
    # ``authorization: Bearer ...``.
    text = re.sub(
        r"(?i)([\"']?(?:cookie|cookie[_ -]?str|authorization|bearer|token|password|passwd|secret|"
        r"qruuid|storage[_ -]?state|signer[_ -]?(?:input|state)|xsec[_ -]?token)[\"']?"
        r"\s*[:=]\s*[\"']?)[^\"'\r\n,;}]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "bearer <redacted>", text)
    return text[:256] or None


__all__ = [
    "LoginFlowConflict",
    "LoginFlowExpired",
    "LoginFlowNotFound",
    "LoginPollResult",
    "LoginProviderState",
    "PlatformLoginCoordinator",
    "PlatformLoginProvider",
    "QrProviderResult",
]
