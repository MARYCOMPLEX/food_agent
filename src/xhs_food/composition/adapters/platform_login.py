"""Split-phase Spider_XHS login bridge.

The upstream project exposes convenient ``from_qrcode_login`` and
``from_phone_login`` helpers, but those helpers own an interactive, blocking
loop (and read from ``input``).  The application login control plane needs a
different seam: create a challenge in one Activity, poll it in another, and
commit the resulting session through the project-owned coordinator.

This adapter therefore calls only the pinned low-level login APIs.  A
``FlowStateStore`` owns the mutable provider state (cookies, QR identifiers,
and signer context) outside Temporal history.  The default store is an
ephemeral in-memory qualification store; production must inject an encrypted
store or sidecar implementation.  No state value is included in a contract,
log, exception, or telemetry label.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, cast

import qrcode

from xhs_food.contracts import PlatformAccountRef

from .platforms import (
    ProviderDependencyStatus,
    ProviderUnavailableError,
    checkout_missing,
    import_from_checkout,
)


class XhsLoginFlowStateStore(Protocol):
    """Opaque storage for one flow's mutable provider state.

    Implementations must encrypt values at rest when they outlive an Activity.
    The adapter never serializes or logs the value; an implementation may keep
    it in a local sidecar, a sealed vault, or an in-memory qualification map.
    """

    async def load(self, key: str) -> object | None: ...

    async def save(self, key: str, value: object, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


class XhsCredentialResolver(Protocol):
    """Resolve an opaque credential handle inside the worker boundary."""

    def __call__(
        self,
        credential_ref: str,
        *,
        account: PlatformAccountRef,
        operation: str,
    ) -> object | Awaitable[object]: ...


class InMemoryXhsLoginFlowStateStore:
    """Ephemeral state store for local qualification and synthetic tests.

    ``durable`` is intentionally false so readiness/reporting code can reject
    this implementation for a production rollout.  Values are never exposed
    through ``repr`` or a public projection.
    """

    durable = False

    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._lock = asyncio.Lock()

    async def load(self, key: str) -> object | None:
        async with self._lock:
            return self._values.get(key)

    async def save(self, key: str, value: object, *, ttl_seconds: int | None = None) -> None:
        del ttl_seconds
        async with self._lock:
            self._values[key] = value

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)


@dataclass(slots=True, repr=False)
class _XhsFlowContext:
    """Provider state kept behind the opaque flow-state store."""

    channel: str
    flow_id: str
    api: Any
    cookies: object
    qr_id: str | None = None
    qr_code: str | None = None
    qr_url: str | None = None
    mode: str = "qr"
    phone: str | None = None

    def __repr__(self) -> str:
        return "_XhsFlowContext(<redacted>)"


class XhsLoginProviderFactory:
    """Build an account-scoped :class:`PlatformLoginProvider` bridge.

    ``checkout`` is the pinned Spider_XHS checkout.  ``login_api_factory`` is
    an optional test/sidecar seam receiving ``channel`` and keyword context;
    when omitted, the allow-listed ``XHSLoginApi`` or
    ``XHSCreatorLoginApi`` is imported lazily from the checkout.
    """

    def __init__(
        self,
        checkout: str | Path,
        *,
        channel: str = "xhs_pc",
        provenance_ref: str | None = None,
        module_loader: Callable[[str], Any] | None = None,
        login_api_factory: Callable[..., object] | None = None,
        authenticated_api_factory: Callable[..., object] | None = None,
        credential_resolver: XhsCredentialResolver | Mapping[str, object] | None = None,
        flow_state_store: XhsLoginFlowStateStore | None = None,
        flow_state_restorer: Callable[..., object] | None = None,
        flow_ttl_seconds: int = 300,
        client_kwargs: Mapping[str, object] | None = None,
    ) -> None:
        normalized = str(channel).strip().casefold()
        if normalized not in {"xhs_pc", "xhs_creator"}:
            raise ValueError("XHS login channel must be xhs_pc or xhs_creator")
        if flow_ttl_seconds < 30:
            raise ValueError("XHS login flow TTL must be at least 30 seconds")
        self.channel = normalized
        self.checkout = Path(checkout).expanduser().resolve()
        self.provenance_ref = provenance_ref
        self._module_loader = module_loader
        self._login_api_factory = login_api_factory
        self._authenticated_api_factory = authenticated_api_factory
        self._credential_resolver = credential_resolver
        self._flow_state_store = flow_state_store or InMemoryXhsLoginFlowStateStore()
        self._flow_state_restorer = flow_state_restorer
        self._flow_ttl_seconds = int(flow_ttl_seconds)
        self._client_kwargs = dict(client_kwargs or {})
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def flow_state_store(self) -> XhsLoginFlowStateStore:
        return self._flow_state_store

    @property
    def authenticated_api_factory(self) -> Callable[..., object] | None:
        """Injected cookie-authenticated client factory, if configured."""

        return self._authenticated_api_factory

    @property
    def credential_resolver(self) -> XhsCredentialResolver | Mapping[str, object] | None:
        """Resolver for opaque credential handles."""

        return self._credential_resolver

    @property
    def flow_state_restorer(self) -> Callable[..., object] | None:
        """Restore an encrypted flow context supplied by a sidecar."""

        return self._flow_state_restorer

    @property
    def flow_ttl_seconds(self) -> int:
        return self._flow_ttl_seconds

    @property
    def client_kwargs(self) -> Mapping[str, object]:
        # Return a copy so a provider cannot mutate sibling account settings.
        return dict(self._client_kwargs)

    def status(self) -> ProviderDependencyStatus:
        required = (
            "apis/xhs_pc_login_apis.py",
            "xhs_utils/xhs_pc/auth.py",
        ) if self.channel == "xhs_pc" else (
            "apis/xhs_creator_login_apis.py",
            "xhs_utils/xhs_creator/auth.py",
        )
        # An explicitly injected API/module loader is the qualification and
        # sidecar seam; it does not need a local checkout on the host.
        missing = [] if (
            self._login_api_factory is not None
            or self._authenticated_api_factory is not None
            or self._module_loader is not None
        ) else checkout_missing(self.checkout, required)
        reason: str | None = None
        if missing:
            reason = f"missing login modules: {', '.join(missing)}"
        elif self._credential_resolver is None:
            # QR-only operation remains useful without a vault resolver; phone
            # and cookie operations will return a stable provider failure.
            reason = None
        return ProviderDependencyStatus(
            platform=self.channel,
            available=not missing,
            mode="in_process_login_protocol",
            checkout=str(self.checkout),
            reason=reason,
            provenance_ref=self.provenance_ref,
        )

    def __call__(self, account: PlatformAccountRef) -> XhsLoginProvider:
        if account.platform.value != self.channel:
            raise ProviderUnavailableError(
                "login channel does not match account channel",
                platform=self.channel,
                checkout=str(self.checkout),
            )
        return XhsLoginProvider(self, account)

    def lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def drop_lock(self, key: str) -> None:
        # Do not remove a lock while another waiter owns it.  Keeping a tiny
        # lock object until the next flow is harmless and avoids a race.
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            self._locks.pop(key, None)

    def _load(self, module_name: str) -> Any:
        if self._module_loader is not None:
            return self._module_loader(module_name)
        return import_from_checkout(self.checkout, module_name)

    def new_login_api(self, account: PlatformAccountRef, flow_id: str) -> Any:
        factory = self._login_api_factory
        if factory is not None:
            return _call_factory(
                factory,
                channel=self.channel,
                account=account,
                flow_id=flow_id,
                **self._client_kwargs,
            )
        module_name, class_name = (
            ("apis.xhs_pc_login_apis", "XHSLoginApi")
            if self.channel == "xhs_pc"
            else ("apis.xhs_creator_login_apis", "XHSCreatorLoginApi")
        )
        module = self._load(module_name)
        login_cls = getattr(module, class_name, None)
        if not callable(login_cls):
            raise ProviderUnavailableError(
                "pinned login API class is unavailable",
                platform=self.channel,
                checkout=str(self.checkout),
            )
        return login_cls(**self._client_kwargs)

    def load_auth_and_api(self) -> tuple[Any, Any]:
        if self.channel == "xhs_pc":
            auth_module = self._load("xhs_utils.xhs_pc.auth")
            api_module = self._load("apis.xhs_pc_apis")
            return auth_module.XHSPcAuth, api_module.XHS_Apis
        auth_module = self._load("xhs_utils.xhs_creator.auth")
        api_module = self._load("apis.xhs_creator_apis")
        return auth_module.XHSCreatorAuth, api_module.XHS_Creator_Apis


class XhsLoginProvider:
    """One account-scoped implementation of the provider login port."""

    def __init__(self, factory: XhsLoginProviderFactory, account: PlatformAccountRef) -> None:
        self._factory = factory
        self._account = account

    @property
    def channel(self) -> str:
        return self._factory.channel

    def _key(self, flow_id: str) -> str:
        # Contract validators already reject separators in account/flow IDs;
        # retain a fixed namespace to prevent accidental cross-channel reads.
        return (
            f"xhs-login/{self._account.tenant_id}/{self.channel}/"
            f"{self._account.account_ref}/{flow_id}"
        )

    def _check_account(self, account: PlatformAccountRef, flow_id: str) -> str:
        if account != self._account:
            raise ProviderUnavailableError(
                "login account does not match provider account",
                platform=self.channel,
                checkout=str(self._factory.checkout),
            )
        if not isinstance(flow_id, str) or not flow_id or flow_id != flow_id.strip():
            raise ValueError("flow_id must be a non-empty trimmed identifier")
        return self._key(flow_id)

    async def create_qr(self, account: PlatformAccountRef, flow_id: str) -> Any:
        """Create one QR challenge and retain mutable provider state."""

        key = self._check_account(account, flow_id)
        lock = self._factory.lock_for(key)
        async with lock:
            existing = await self._load_context(key, account, flow_id)
            if existing is not None and existing.qr_id and existing.mode == "qr":
                if not existing.qr_url:
                    # A restored state that omits the presentation URL cannot
                    # safely mint a new QR image; callers should start a new
                    # flow rather than guessing a provider URL.
                    raise ProviderUnavailableError(
                        "QR presentation state is unavailable",
                        platform=self.channel,
                        checkout=str(self._factory.checkout),
                    )
                image = _qr_png(existing.qr_url)
                return _qr_result(image)
            api = await _maybe_to_thread(self._factory.new_login_api, account, flow_id)
            try:
                cookies = await self._initialize_anonymous(api)
                raw = await self._api_call(api, "generate_qrcode", cookies)
                success, message, data = _parse_tuple_result(raw)
                if not success or not isinstance(data, Mapping):
                    raise ProviderUnavailableError(
                        "XHS QR challenge creation failed",
                        platform=self.channel,
                        checkout=str(self._factory.checkout),
                    )
                qr_id = _first_text(data, "qr_id", "id", "qrCodeId")
                qr_code = _first_text(data, "code", "qr_code", "qrCode")
                qr_url = _first_text(data, "qr_url", "url", "qrUrl")
                if not qr_id or not qr_url:
                    raise ProviderUnavailableError(
                        "XHS QR challenge response is malformed",
                        platform=self.channel,
                        checkout=str(self._factory.checkout),
                    )
                context = _XhsFlowContext(
                    channel=self.channel,
                    flow_id=flow_id,
                    api=api,
                    cookies=cookies,
                    qr_id=qr_id,
                    qr_code=qr_code,
                    qr_url=qr_url,
                )
                await self._save_context(key, context)
                return _qr_result(_qr_png(qr_url), provider_flow_ref=qr_id)
            except asyncio.CancelledError:
                await _close(api)
                raise
            except ProviderUnavailableError:
                await _close(api)
                raise
            except Exception as exc:
                await _close(api)
                raise ProviderUnavailableError(
                    "XHS QR provider operation failed",
                    platform=self.channel,
                    checkout=str(self._factory.checkout),
                ) from exc

    async def poll(self, account: PlatformAccountRef, flow_id: str) -> Any:
        """Poll a QR challenge and validate identity on success."""

        key = self._check_account(account, flow_id)
        lock = self._factory.lock_for(key)
        async with lock:
            context = await self._load_context(key, account, flow_id)
            if context is None or not context.qr_id:
                return _poll_result("failed", error_code="LOGIN_FLOW_STATE_UNAVAILABLE")
            try:
                raw = await self._api_call(
                    context.api,
                    "query_qrcode_status" if self.channel == "xhs_creator" else "check_qrcode_status",
                    context.qr_id,
                    *([context.qr_code, context.cookies] if self.channel == "xhs_pc" else [context.cookies]),
                )
                state, message, cookies = _parse_poll_result(raw, self.channel)
                context.cookies = cookies or context.cookies
                if state in {"waiting_scan", "waiting_confirmation"}:
                    await self._save_context(key, context)
                    return _poll_result(state)
                if state == "expired":
                    await self._finish(key, context)
                    return _poll_result("expired")
                if state != "succeeded":
                    await self._finish(key, context)
                    return _poll_result("failed", error_code=_error_code(message))
                result = await self._validated_success(context)
                await self._finish(key, context)
                return result
            except asyncio.CancelledError:
                raise
            except ProviderUnavailableError:
                await self._finish(key, context)
                return _poll_result("failed", error_code="LOGIN_PROVIDER_UNAVAILABLE")
            except Exception:
                await self._finish(key, context)
                return _poll_result("failed", error_code="LOGIN_PROVIDER_ERROR")

    async def phone_login(
        self,
        account: PlatformAccountRef,
        flow_id: str,
        credential_ref: str,
    ) -> Any:
        """Run a bounded phone login using a vault handle.

        A resolver may return ``{"phone": ..., "code": ...}`` for a one-shot
        operation or only ``{"phone": ...}`` to send the SMS and leave the
        flow in ``waiting_confirmation`` for a later submission.
        """

        key = self._check_account(account, flow_id)
        values = await self._resolve_credential(credential_ref, account, "phone_login")
        if values is None:
            return _poll_result("failed", error_code="LOGIN_CREDENTIAL_UNAVAILABLE")
        lock = self._factory.lock_for(key)
        async with lock:
            context = await self._load_context(key, account, flow_id)
            try:
                if context is None:
                    api = await _maybe_to_thread(self._factory.new_login_api, account, flow_id)
                    cookies = await self._initialize_anonymous(api)
                    context = _XhsFlowContext(
                        channel=self.channel,
                        flow_id=flow_id,
                        api=api,
                        cookies=cookies,
                        mode="phone",
                    )
                phone = _credential_text(values, "phone", "phone_number") or context.phone
                code = _credential_text(values, "code", "sms_code", "verification_code")
                if not phone:
                    await self._finish(key, context)
                    return _poll_result("failed", error_code="LOGIN_CREDENTIAL_INVALID")
                context.phone = phone
                if not code:
                    raw = await self._api_call(
                        context.api,
                        "send_phone_code",
                        phone,
                        context.cookies,
                    )
                    success, message, _ = _parse_tuple_result(raw)
                    if not success:
                        await self._finish(key, context)
                        return _poll_result("failed", error_code=_error_code(message))
                    await self._save_context(key, context)
                    return _poll_result("waiting_confirmation")
                raw = await self._api_call(
                    context.api,
                    "login_by_phone",
                    phone,
                    code,
                    context.cookies,
                )
                success, message, data = _parse_tuple_result(raw)
                if not success:
                    await self._finish(key, context)
                    return _poll_result("failed", error_code=_error_code(message))
                context.cookies = _cookies_from_result(data) or context.cookies
                result = await self._validated_success(context)
                await self._finish(key, context)
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                if context is not None:
                    await self._finish(key, context)
                return _poll_result("failed", error_code="LOGIN_PROVIDER_ERROR")

    async def cookie_import(
        self,
        account: PlatformAccountRef,
        flow_id: str,
        credential_ref: str,
    ) -> Any:
        """Validate a cookie handle and return a versionable session result."""

        key = self._check_account(account, flow_id)
        values = await self._resolve_credential(credential_ref, account, "cookie_import")
        if values is None:
            return _poll_result("failed", error_code="LOGIN_CREDENTIAL_UNAVAILABLE")
        cookie_value = _credential_value(values, "cookie", "cookies", "cookie_string")
        if cookie_value is None:
            return _poll_result("failed", error_code="LOGIN_CREDENTIAL_INVALID")
        lock = self._factory.lock_for(key)
        async with lock:
            api: Any | None = None
            try:
                auth = None
                if self._factory.authenticated_api_factory is not None:
                    resolved = await _maybe_to_thread(
                        _call_factory,
                        self._factory.authenticated_api_factory,
                        channel=self.channel,
                        account=account,
                        flow_id=flow_id,
                        cookie_value=cookie_value,
                        credential=cookie_value,
                        **self._factory.client_kwargs,
                    )
                    if isinstance(resolved, tuple) and len(resolved) >= 2:
                        api, auth = resolved[0], resolved[1]
                    else:
                        api = resolved
                else:
                    auth_cls, api_cls = self._factory.load_auth_and_api()
                    auth = await _maybe_to_thread(
                        _call_from_cookie,
                        auth_cls,
                        cookie_value,
                        self._factory.client_kwargs,
                    )
                    api = await _maybe_to_thread(api_cls, auth)
                raw = await self._api_call(
                    api,
                    "get_user_me" if self.channel == "xhs_pc" else "get_user_info",
                )
                success, message, data, cookies = _parse_user_result(raw)
                if not success:
                    return _poll_result("failed", error_code=_error_code(message))
                context = _XhsFlowContext(
                    channel=self.channel,
                    flow_id=flow_id,
                    api=api,
                    cookies=getattr(auth, "cookies", cookie_value),
                    mode="cookie",
                )
                context.cookies = cookies or _cookies_from_result(data) or context.cookies
                result = await self._validated_success(context, user_info=data)
                await _close(api)
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                if api is not None:
                    await _close(api)
                return _poll_result("failed", error_code="LOGIN_PROVIDER_ERROR")

    async def cancel(self, account: PlatformAccountRef, flow_id: str) -> None:
        key = self._check_account(account, flow_id)
        lock = self._factory.lock_for(key)
        async with lock:
            context = await self._load_context(key, account, flow_id)
            if context is not None:
                await self._finish(key, context)

    async def _initialize_anonymous(self, api: Any) -> object:
        initialize = getattr(api, "generate_init_cookies", None)
        if not callable(initialize):
            raise ProviderUnavailableError(
                "pinned login API does not expose anonymous initialization",
                platform=self.channel,
                checkout=str(self._factory.checkout),
            )
        cookies = await _maybe_to_thread(initialize)
        if cookies is None:
            raise ProviderUnavailableError(
                "XHS login API returned empty anonymous state",
                platform=self.channel,
                checkout=str(self._factory.checkout),
            )
        # Creator's initializer completes the security bootstrap by default;
        # PC needs the web-profile call before SMS login and QR polling.
        ensure = getattr(api, "ensure_webprofile", None)
        if self.channel == "xhs_pc" and callable(ensure):
            await _maybe_to_thread(ensure, cookies)
        return cookies

    async def _api_call(self, api: Any, name: str, *args: object) -> object:
        method = getattr(api, name, None)
        if not callable(method):
            raise ProviderUnavailableError(
                f"pinned login API capability {name} is unavailable",
                platform=self.channel,
                checkout=str(self._factory.checkout),
            )
        return await _maybe_to_thread(method, *args)

    async def _resolve_credential(
        self,
        credential_ref: str,
        account: PlatformAccountRef,
        operation: str,
    ) -> Mapping[str, object] | object | None:
        resolver = self._factory.credential_resolver
        if resolver is None:
            return None
        if isinstance(resolver, Mapping):
            value = resolver.get(credential_ref)
        else:
            # Vault/secret-manager adapters are commonly synchronous network
            # clients.  Dispatch them like the provider APIs so a credential
            # lookup cannot block the login control-plane event loop.  The
            # helper also handles callable async objects and awaitable return
            # values without exposing the resolved secret to a durable
            # boundary.
            value = await _maybe_to_thread(
                resolver,
                credential_ref,
                account=account,
                operation=operation,
            )
        return value

    async def _load_context(
        self,
        key: str,
        account: PlatformAccountRef,
        flow_id: str,
    ) -> _XhsFlowContext | None:
        value = await _store_call(self._factory.flow_state_store, "load", key)
        if value is None:
            return None
        if isinstance(value, _XhsFlowContext):
            return value
        restorer = self._factory.flow_state_restorer
        if restorer is None:
            # A process restart without an injected restorer must fail closed;
            # never fabricate a fresh QR flow or silently switch accounts.
            return None
        restored = _call_factory(
            restorer,
            value,
            account=account,
            flow_id=flow_id,
            channel=self.channel,
        )
        if inspect.isawaitable(restored):
            restored = await restored
        return restored if isinstance(restored, _XhsFlowContext) else None

    async def _save_context(self, key: str, context: _XhsFlowContext) -> None:
        await _store_call(
            self._factory.flow_state_store,
            "save",
            key,
            context,
            ttl_seconds=self._factory.flow_ttl_seconds,
        )

    async def _finish(self, key: str, context: _XhsFlowContext) -> None:
        await _close(context.api)
        await _store_call(self._factory.flow_state_store, "delete", key)
        await self._factory.drop_lock(key)

    async def _validated_success(self, context: _XhsFlowContext, *, user_info: object = None) -> Any:
        if user_info is None:
            raw = await self._api_call(
                context.api,
                "get_user_info",
                context.cookies,
            )
            success, message, user_info, cookies = _parse_user_result(raw)
            if not success:
                return _poll_result("failed", error_code=_error_code(message))
            context.cookies = cookies or _cookies_from_result(user_info) or context.cookies
        subject = _subject_id(user_info)
        if not subject:
            return _poll_result("failed", error_code="LOGIN_IDENTITY_MALFORMED")
        material = _session_material(context)
        if not material:
            return _poll_result("failed", error_code="LOGIN_SESSION_MALFORMED")
        return _poll_result(
            "succeeded",
            provider_subject_id=subject,
            session_material=material,
        )


def build_xhs_login_provider_factory(
    checkout: str | Path,
    *,
    channel: str = "xhs_pc",
    provenance_ref: str | None = None,
    **kwargs: Any,
) -> XhsLoginProviderFactory:
    """Convenience constructor used by deployment/composition wiring."""

    return XhsLoginProviderFactory(
        checkout,
        channel=channel,
        provenance_ref=provenance_ref,
        **kwargs,
    )


async def _store_call(store: object, operation: str, *args: object, **kwargs: object) -> object:
    method = getattr(store, operation, None)
    if not callable(method):
        raise ProviderUnavailableError(
            "XHS login flow-state store capability is unavailable",
            platform="xhs_login",
        )
    try:
        value = method(*args, **kwargs)
    except TypeError:
        # Small stores often omit the optional TTL keyword.  Retry without it
        # only for that shape; provider/store errors are not swallowed.
        if kwargs:
            value = method(*args)
        else:
            raise
    if inspect.isawaitable(value):
        return await value
    return value


async def _maybe_to_thread(function: Callable[..., object], *args: object, **kwargs: object) -> object:
    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    value = await asyncio.to_thread(function, *args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def _close(value: object) -> None:
    method = getattr(value, "close", None)
    if not callable(method):
        method = getattr(value, "aclose", None)
    if not callable(method):
        return
    try:
        result = method()
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Cleanup must not replace the authoritative flow result.
        return


def _call_factory(factory: Callable[..., object], *args: object, **kwargs: object) -> object:
    """Call injected factories across common one-/two-argument shapes."""

    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(*args, **kwargs)
    parameters = tuple(signature.parameters.values())
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return factory(*args, **kwargs)
    accepted = {
        parameter.name
        for parameter in parameters
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    filtered = {key: value for key, value in kwargs.items() if key in accepted}
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if args and positional:
        return factory(*args[: len(positional)], **filtered)
    return factory(**filtered)


def _call_from_cookie(auth_cls: Any, cookie_value: object, kwargs: Mapping[str, object]) -> object:
    from_cookie = getattr(auth_cls, "from_cookie", None)
    if not callable(from_cookie):
        raise ProviderUnavailableError("pinned auth class does not support cookie import", platform="xhs_login")
    allowed = {
        key: value
        for key, value in kwargs.items()
        if key in {"b1", "dsl", "host_cookies", "host_cookie_state", "cookie_source_url"}
    }
    return from_cookie(cookie_value, **allowed)


def _parse_tuple_result(value: object) -> tuple[bool, str, object]:
    if isinstance(value, tuple):
        if len(value) >= 3:
            return bool(value[0]), _safe_text(value[1]), value[2]
        if len(value) == 2:
            return bool(value[0]), _safe_text(value[1]), None
    if isinstance(value, Mapping):
        success = bool(value.get("success", value.get("ok", False)))
        message = _safe_text(value.get("msg", value.get("message", "")))
        payload = value.get("data", value.get("result", value))
        return success, message, payload
    return False, "provider returned an invalid result", None


def _parse_user_result(value: object) -> tuple[bool, str, object, object | None]:
    """Normalize PC/Creator identity probe tuple shapes.

    PC login returns ``(success, user_info, cookies)`` while Creator and most
    fakes return ``(success, message, response_json)``.  Keep both the
    identity payload and updated cookie map so the session envelope is
    complete without ever exposing either value in a public result.
    """

    if isinstance(value, tuple) and len(value) >= 3:
        success = bool(value[0])
        second, third = value[1], value[2]
        if isinstance(second, Mapping) and not isinstance(third, Mapping):
            return success, "", second, third
        # A PC cookie map is usually a mapping containing ``a1``/``web_session``;
        # distinguish it from an ordinary response payload by known cookie keys.
        if isinstance(third, Mapping) and any(
            key in third for key in ("a1", "web_session", "gid", "websectiga")
        ):
            return success, _safe_text(second), second, third
        return success, _safe_text(second), third, _cookies_from_result(third)
    success, message, payload = _parse_tuple_result(value)
    return success, message, payload, _cookies_from_result(payload)


def _parse_poll_result(value: object, channel: str) -> tuple[str, str, object | None]:
    if channel == "xhs_creator" and isinstance(value, Mapping):
        data = value.get("data") if isinstance(value.get("data"), Mapping) else value
        status = data.get("status") if isinstance(data, Mapping) else None
        cookies = _cookies_from_result(value)
        if status in {1, "1", "success", "succeeded"}:
            return "succeeded", _safe_text(value.get("message", "")), cookies
        if status in {2, "2", "waiting_scan", "wait_scan"}:
            return "waiting_scan", _safe_text(value.get("message", "")), cookies
        if status in {3, "3", "waiting_confirmation", "wait_confirm"}:
            return "waiting_confirmation", _safe_text(value.get("message", "")), cookies
        if status in {4, "4", "expired"}:
            return "expired", _safe_text(value.get("message", "")), cookies
        return "failed", _safe_text(value.get("message", "")), cookies

    success, message, payload = _parse_tuple_result(value)
    cookies = _cookies_from_result(payload)
    text = message.casefold()
    if success:
        return "succeeded", message, cookies
    if any(token in text for token in ("扫描", "scan", "wait_scan", "waiting_scan")):
        return "waiting_scan", message, cookies
    if any(token in text for token in ("确认", "confirm", "wait_confirm", "waiting_confirmation")):
        return "waiting_confirmation", message, cookies
    if any(token in text for token in ("过期", "expired", "timeout")):
        return "expired", message, cookies
    return "failed", message, cookies


def _qr_result(image_bytes: bytes, *, provider_flow_ref: str | None = None) -> Any:
    from xhs_food.foundation.platform_login import QrProviderResult

    return QrProviderResult(
        image_bytes=image_bytes,
        content_type="image/png",
        provider_flow_ref=provider_flow_ref,
    )


def _poll_result(
    state: str,
    *,
    provider_subject_id: str | None = None,
    session_material: Mapping[str, object] | None = None,
    error_code: str | None = None,
) -> Any:
    from xhs_food.foundation.platform_login import LoginPollResult, LoginProviderState

    mapped = {
        "waiting_scan": LoginProviderState.WAITING_SCAN,
        "waiting_confirmation": LoginProviderState.WAITING_CONFIRMATION,
        "succeeded": LoginProviderState.SUCCEEDED,
        "expired": LoginProviderState.EXPIRED,
        "failed": LoginProviderState.FAILED,
    }.get(state, LoginProviderState.FAILED)
    return LoginPollResult(
        state=mapped,
        provider_subject_id=provider_subject_id,
        session_material=session_material,
        error_code=error_code,
        error_message=None,
    )


def _qr_png(url: str) -> bytes:
    if not url:
        raise ProviderUnavailableError("XHS QR URL is empty", platform="xhs_login")
    try:
        # ``qrcode.make`` returns the configured image factory subtype; its
        # third-party stub exposes only the abstract base signature even
        # though Pillow-backed images accept an explicit output format.
        image = cast(Any, qrcode.make(url))
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except Exception as exc:
        raise ProviderUnavailableError("QR renderer is unavailable", platform="xhs_login") from exc


def _first_text(value: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return None


def _credential_text(value: object, *keys: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _first_text(value, *keys)


def _credential_value(value: object, *keys: str) -> object | None:
    if isinstance(value, Mapping):
        for key in keys:
            item = value.get(key)
            if item is not None:
                return item
        return None
    return value


def _cookies_from_result(value: object) -> object | None:
    if isinstance(value, Mapping):
        for key in ("cookies", "cookie", "xhr_cookie"):
            if key in value and value[key] is not None:
                return value[key]
        nested = value.get("data")
        if nested is not value:
            found = _cookies_from_result(nested)
            if found is not None:
                return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _cookies_from_result(item)
            if found is not None:
                return found
    return None


def _subject_id(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key in ("user_id", "userId", "subject_id", "subjectId", "id"):
            item = value.get(key)
            if item is not None and str(item).strip():
                return str(item).strip()
        for key in ("data", "user", "user_info", "userInfo"):
            nested = value.get(key)
            found = _subject_id(nested)
            if found:
                return found
    return None


def _session_material(context: _XhsFlowContext) -> dict[str, object] | None:
    cookies = context.cookies
    if cookies is None:
        return None
    material: dict[str, object] = {"cookie": cookies}
    api = context.api
    profile = getattr(api, "profile", None)
    auth = getattr(api, "auth", None)
    for owner in (api, auth, profile):
        if owner is None:
            continue
        for name, key in (("dsl", "dsl"), ("_login_b1", "b1"), ("b1", "b1")):
            value = getattr(owner, name, None)
            if value:
                material.setdefault(key, str(value))
        for name, key in (("host_cookies_snapshot", "host_cookies"), ("host_cookie_state", "host_cookie_state")):
            method = getattr(owner, name, None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    continue
                if value:
                    material[key] = value
    return material


def _error_code(message: object) -> str:
    text = _safe_text(message).casefold()
    if any(token in text for token in ("406", "risk", "challenge", "风控")):
        return "LOGIN_RISK_CHALLENGE"
    if any(token in text for token in ("429", "rate", "频繁", "限流")):
        return "LOGIN_RATE_LIMITED"
    if any(token in text for token in ("401", "登录态", "auth", "认证")):
        return "LOGIN_AUTHENTICATION_FAILED"
    if "expired" in text or "过期" in text:
        return "LOGIN_FLOW_EXPIRED"
    return "LOGIN_PROVIDER_FAILED"


def _safe_text(value: object) -> str:
    text = str(value or "")
    # Messages are never returned to clients by this adapter.  Keep this
    # bounded anyway so an upstream response cannot become a large exception.
    return text[:256]


__all__ = [
    "InMemoryXhsLoginFlowStateStore",
    "XhsCredentialResolver",
    "XhsLoginFlowStateStore",
    "XhsLoginProvider",
    "XhsLoginProviderFactory",
    "build_xhs_login_provider_factory",
]
