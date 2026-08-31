"""Account-bound source execution gateway.

The legacy :class:`~xhs_food.gateways.source_gateway.SourceGateway` routes a
public ``CollectRequest`` to a connector.  Platform connectors additionally
need an account, an encrypted session version, a grant, and a durable lease.
This module keeps those control-plane concerns outside the public query
identity and creates one short-lived provider connector per invocation.

Only contract ports are required here.  Concrete repositories, codecs, and
provider factories are supplied by the Composition Root, which keeps the
gateway portable across the in-memory test authority, PostgreSQL, and a
future sidecar transport.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import uuid4

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountHealthSignal,
    AccountLeaseRequest,
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    ContractError,
    ErrorCategory,
    ErrorScope,
    IsolationCoordinates,
    PlatformAccount,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountRef,
    PlatformAccountRepositoryPort,
    PlatformAccountSession,
    PlatformAccountSessionReaderPort,
    PlatformAccountStatus,
    PlatformChannel,
    PlatformSourceInvocation,
    SessionEnvelopeCodecPort,
    SourceCollectionOutcome,
    SourceConnector,
)


class PlatformGatewayCode(StrEnum):
    """Stable account-bound failure codes exposed to policy/API adapters."""

    INVOCATION_INVALID = "PLATFORM_INVOCATION_INVALID"
    ACCOUNT_NOT_FOUND = "PLATFORM_ACCOUNT_NOT_FOUND"
    ACCOUNT_DENIED = "PLATFORM_ACCOUNT_DENIED"
    ACCOUNT_UNAVAILABLE = "PLATFORM_ACCOUNT_UNAVAILABLE"
    SESSION_REQUIRED = "PLATFORM_SESSION_REQUIRED"
    SESSION_VERSION_CONFLICT = "PLATFORM_SESSION_VERSION_CONFLICT"
    LEASE_UNAVAILABLE = "PLATFORM_ACCOUNT_LEASE_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PLATFORM_PROVIDER_UNAVAILABLE"
    MALFORMED_RESPONSE = "PLATFORM_MALFORMED_RESPONSE"
    TIMEOUT = "PLATFORM_SOURCE_TIMEOUT"
    CANCELLED = "PLATFORM_SOURCE_CANCELLED"


class PlatformGatewayError(RuntimeError):
    """Exception form of a safe gateway error for command/API boundaries."""

    def __init__(self, error: ContractError) -> None:
        super().__init__(error.code)
        self.error = error


class PlatformConnectorFactory(Protocol):
    """Build one connector from one account/session material snapshot.

    ``session_material`` is a transient byte string owned by the gateway.  A
    factory must consume it immediately and never put it in a contract,
    logger, metric, or long-lived global cache.
    """

    def __call__(
        self,
        account: PlatformAccount,
        session: PlatformAccountSession,
        session_material: bytes,
    ) -> SourceConnector | Awaitable[SourceConnector]: ...


class PlatformSourceControl(Protocol):
    async def admit(self, source_id: str) -> Any: ...

    async def record_success(self, source_id: str) -> None: ...

    async def record_failure(self, source_id: str, *, retryable: bool) -> None: ...


class AccountBoundSourceGateway:
    """Resolve account authority before invoking a platform provider."""

    def __init__(
        self,
        *,
        accounts: PlatformAccountRepositoryPort,
        sessions: PlatformAccountSessionReaderPort | None = None,
        grants: Any | None = None,
        leases: Any | None = None,
        codec: SessionEnvelopeCodecPort | None = None,
        connector_factories: Mapping[PlatformChannel | str, PlatformConnectorFactory]
        | None = None,
        source_control: PlatformSourceControl | None = None,
        health: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_ttl_seconds: int = 180,
    ) -> None:
        if lease_ttl_seconds < 1:
            raise ValueError("lease_ttl_seconds must be positive")
        self._accounts = accounts
        self._sessions = sessions or accounts  # production repositories implement both
        self._grants = grants or accounts
        self._leases = leases or accounts
        self._codec = codec
        self._factories = {
            _channel_key(key): value for key, value in (connector_factories or {}).items()
        }
        self._source_control = source_control
        self._health = health
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lease_ttl = lease_ttl_seconds

    @property
    def connector_channels(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    async def collect(
        self,
        invocation: PlatformSourceInvocation,
        *,
        principal_id: str,
        owner_id: str | None = None,
    ) -> SourceCollectionOutcome:
        """Run ``search`` with account authority and return a safe outcome."""

        return await self.invoke(
            invocation,
            principal_id=principal_id,
            owner_id=owner_id,
            operation="search",
        )

    async def invoke(
        self,
        invocation: PlatformSourceInvocation,
        *,
        principal_id: str,
        owner_id: str | None = None,
        operation: str = "search",
        args: Sequence[Any] = (),
    ) -> SourceCollectionOutcome:
        """Invoke one connector operation without changing ``CollectRequest``."""

        source_id = _source_id(invocation.platform)
        invalid = self._validate_invocation(invocation, source_id, operation)
        if invalid is not None:
            return invalid

        # Admission is a source-level circuit/rate decision, not an account
        # fact.  Check it before resolving account metadata or decrypting a
        # session so a hot provider can be shed without revealing whether a
        # particular tenant/account exists.  The controller is deliberately
        # optional for local fixtures; when supplied it is the same
        # project-owned SourceControlPort used by the legacy gateway.
        if self._source_control is not None:
            try:
                admission = await self._source_control.admit(source_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                return self._failure(
                    source_id,
                    "PLATFORM_SOURCE_ADMISSION_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    retryable=True,
                )
            if admission is None or not bool(getattr(admission, "allowed", False)):
                retry_after = int(getattr(admission, "retry_after_seconds", 0) or 0)
                circuit_open = bool(getattr(admission, "circuit_open", False))
                return self._failure(
                    source_id,
                    "PLATFORM_SOURCE_ADMISSION_DENIED",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE
                    if circuit_open
                    else ErrorCategory.RATE_LIMITED,
                    retryable=True,
                    details={
                        "retry_after_seconds": max(0, retry_after),
                        "circuit_open": circuit_open,
                    },
                )

        # Grant checks deliberately precede account lookup.  A cross-tenant
        # caller therefore observes the same denied/not-found shape and no
        # account metadata is disclosed.
        try:
            grant = await cast(Any, self._grants).authorize(
                invocation.account,
                principal_id,
                AccountGrantPermission.USE,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._failure(
                source_id,
                PlatformGatewayCode.ACCOUNT_DENIED,
                ErrorCategory.POLICY_DENIED,
                retryable=False,
                message="account authorization unavailable",
            )
        if grant is None or (
            invocation.grant_id is not None and grant.grant_id != invocation.grant_id
        ):
            return self._failure(
                source_id,
                PlatformGatewayCode.ACCOUNT_DENIED,
                ErrorCategory.POLICY_DENIED,
                retryable=False,
            )

        try:
            account = await self._accounts.get_account(invocation.account)
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._failure(
                source_id,
                PlatformGatewayCode.ACCOUNT_NOT_FOUND,
                ErrorCategory.NOT_FOUND,
                retryable=False,
            )
        if account is None:
            return self._failure(
                source_id,
                PlatformGatewayCode.ACCOUNT_NOT_FOUND,
                ErrorCategory.NOT_FOUND,
                retryable=False,
            )
        unavailable = _account_unavailable(account)
        if unavailable is not None:
            return self._failure(
                source_id,
                PlatformGatewayCode.ACCOUNT_UNAVAILABLE,
                ErrorCategory.POLICY_DENIED,
                retryable=False,
                details={"status": account.status.value, "health": account.health.value},
            )

        if self._codec is None:
            return self._failure(
                source_id,
                PlatformGatewayCode.PROVIDER_UNAVAILABLE,
                ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=False,
                message="session codec is not configured",
            )
        get_session = getattr(self._sessions, "get_active_session", None)
        if not callable(get_session):
            return self._failure(
                source_id,
                PlatformGatewayCode.SESSION_REQUIRED,
                ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=False,
                message="active-session reader is not configured",
            )
        try:
            session = await cast(Any, get_session)(invocation.account)
        except asyncio.CancelledError:
            raise
        except Exception:
            session = None
        if session is None or session.status.value != "active":
            return self._failure(
                source_id,
                PlatformGatewayCode.SESSION_REQUIRED,
                ErrorCategory.POLICY_DENIED,
                retryable=False,
            )
        if invocation.expected_session_version is not None and (
            session.version != invocation.expected_session_version
        ):
            return self._failure(
                source_id,
                PlatformGatewayCode.SESSION_VERSION_CONFLICT,
                ErrorCategory.CONFLICT,
                retryable=True,
            )

        factory = self._factories.get(_channel_key(invocation.platform))
        if factory is None:
            return self._failure(
                source_id,
                PlatformGatewayCode.PROVIDER_UNAVAILABLE,
                ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=False,
                message="platform provider binding is disabled",
            )

        lease = None
        material = bytearray()
        connector: SourceConnector | None = None
        try:
            lease = await cast(Any, self._leases).acquire(
                AccountLeaseRequest(
                    account=invocation.account,
                    task_id=invocation.request_id,
                    owner_id=owner_id or principal_id,
                    ttl_seconds=self._lease_ttl,
                    expected_session_version=session.version,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._failure(
                source_id,
                PlatformGatewayCode.LEASE_UNAVAILABLE,
                ErrorCategory.CONFLICT,
                retryable=True,
            )

        try:
            plaintext = await self._codec.open(session)
            if not isinstance(plaintext, (bytes, bytearray)) or not plaintext:
                return self._failure(
                    source_id,
                    PlatformGatewayCode.SESSION_REQUIRED,
                    ErrorCategory.MALFORMED_RESPONSE,
                    retryable=False,
                )
            material = bytearray(plaintext)
            connector = await _build_factory(factory, account, session, bytes(material))
            if not _connector_matches(connector, invocation.platform):
                return self._failure(
                    source_id,
                    PlatformGatewayCode.INVOCATION_INVALID,
                    ErrorCategory.VALIDATION,
                    retryable=False,
                )
            if operation == "search":
                value = await connector.search(invocation.collect_request)
            elif operation == "fetch_document":
                value = await connector.fetch_document(*args)
            elif operation == "fetch_comments":
                value = await connector.fetch_comments(*args)
            elif operation == "list_media_refs":
                value = await connector.list_media_refs(*args)
            else:  # guarded by validation; kept explicit for future operations
                return self._failure(
                    source_id,
                    PlatformGatewayCode.INVOCATION_INVALID,
                    ErrorCategory.VALIDATION,
                    retryable=False,
                )
            outcome = _operation_outcome(
                source_id,
                value,
                isolation=invocation.collect_request.query.isolation,
            )
            await self._record_health(invocation.account, session, outcome)
            if self._source_control is not None:
                with suppress(Exception):
                    await self._record_control(source_id, outcome)
            return outcome
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = _safe_provider_error(exc, source_id)
            outcome = SourceCollectionOutcome(source_id=source_id, outcome="failure", error=error)
            await self._record_health(invocation.account, session, outcome)
            if self._source_control is not None:
                with suppress(Exception):
                    await self._record_control(source_id, outcome)
            return outcome
        finally:
            if connector is not None:
                close = getattr(connector, "aclose", None) or getattr(connector, "close", None)
                if callable(close):
                    try:
                        result = close()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass
            for index in range(len(material)):
                material[index] = 0
            if lease is not None:
                with suppress(Exception):
                    await cast(Any, self._leases).release(lease.lease_id)

    def _validate_invocation(
        self, invocation: PlatformSourceInvocation, source_id: str, operation: str
    ) -> SourceCollectionOutcome | None:
        if invocation.platform not in PlatformChannel:
            return self._failure(
                source_id,
                PlatformGatewayCode.INVOCATION_INVALID,
                ErrorCategory.VALIDATION,
                retryable=False,
            )
        if operation not in {"search", "fetch_document", "fetch_comments", "list_media_refs"}:
            return self._failure(
                source_id,
                PlatformGatewayCode.INVOCATION_INVALID,
                ErrorCategory.VALIDATION,
                retryable=False,
            )
        if invocation.operation != operation:
            return self._failure(
                source_id,
                PlatformGatewayCode.INVOCATION_INVALID,
                ErrorCategory.VALIDATION,
                retryable=False,
            )
        if invocation.platform is PlatformChannel.DIANPING and source_id not in invocation.collect_request.source_scope:
            return self._failure(
                source_id,
                PlatformGatewayCode.INVOCATION_INVALID,
                ErrorCategory.VALIDATION,
                retryable=False,
            )
        # XHS PC/Creator share the public ``xhs`` source ID but remain separate
        # account channels and connector factories.
        if invocation.platform in {PlatformChannel.XHS_PC, PlatformChannel.XHS_CREATOR} and "xhs" not in invocation.collect_request.source_scope:
            return self._failure(
                source_id,
                PlatformGatewayCode.INVOCATION_INVALID,
                ErrorCategory.VALIDATION,
                retryable=False,
            )
        return None

    async def _record_health(
        self,
        account: PlatformAccountRef,
        session: PlatformAccountSession,
        outcome: SourceCollectionOutcome,
    ) -> None:
        if self._health is None:
            return
        error = outcome.error
        signal = AccountHealthSignal.SUCCESS if error is None else _health_signal(error)
        health = _health_state(error)
        event = PlatformAccountHealthEvent(
            event_id=f"health-{uuid4().hex}",
            account=account,
            signal=signal,
            health=health,
            observed_at=_as_utc(self._clock()),
            session_version=session.version,
            task_id=None,
            reason=error.code if error is not None else None,
            metadata={"source": outcome.source_id, "outcome": outcome.outcome},
        )
        with suppress(Exception):
            await self._health.record(event)

    async def _record_control(self, source_id: str, outcome: SourceCollectionOutcome) -> None:
        assert self._source_control is not None
        if outcome.error is None:
            await self._source_control.record_success(source_id)
        else:
            await self._source_control.record_failure(
                source_id, retryable=outcome.error.retryable
            )

    @staticmethod
    def _failure(
        source_id: str,
        code: PlatformGatewayCode | str,
        category: ErrorCategory,
        *,
        retryable: bool,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> SourceCollectionOutcome:
        error = ContractError(
            code=_code_text(code),
            category=category,
            scope=ErrorScope.SOURCE,
            retryable=retryable,
            terminal=not retryable,
            message=message,
            boundary_ref=source_id,
            details=dict(details or {}),
        )
        return SourceCollectionOutcome(source_id=source_id, outcome="failure", error=error)


# Short names used by composition and integration tests.
PlatformSourceGateway = AccountBoundSourceGateway
AccountBoundGateway = AccountBoundSourceGateway


async def _build_factory(
    factory: PlatformConnectorFactory,
    account: PlatformAccount,
    session: PlatformAccountSession,
    material: bytes,
) -> SourceConnector:
    """Call both the canonical three-argument and test-friendly two-argument forms."""

    try:
        signature = inspect.signature(factory)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
    except (TypeError, ValueError):
        positional, has_varargs = (), True
    if has_varargs or len(positional) >= 3:
        def call() -> Any:
            return factory(account, session, material)
    elif len(positional) == 2:
        def call() -> Any:
            return factory(account, session)  # type: ignore[call-arg]
    else:
        def call() -> Any:
            return factory(account)  # type: ignore[call-arg]
    # Provider construction can import a pinned checkout, initialise a signer,
    # or create a browser client.  Keep all of that work off the event loop.
    result = await asyncio.to_thread(call)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, SourceConnector):
        raise TypeError("platform connector factory returned an invalid connector")
    return result


def _connector_matches(connector: SourceConnector, channel: PlatformChannel) -> bool:
    connector_channel = getattr(connector, "platform_channel", None)
    if connector_channel is None:
        # XHS PC and Creator deliberately share the public ``xhs`` source ID,
        # so a source-ID-only fallback would allow a connector from the wrong
        # account namespace to run.  Legacy Dianping connectors predate the
        # channel marker and may retain the narrow source-ID fallback.
        return (
            channel is PlatformChannel.DIANPING
            and str(getattr(connector, "source_id", "")).casefold() == "dianping"
        )
    if isinstance(connector_channel, PlatformChannel):
        return connector_channel is channel
    # Accept enum-like markers supplied by adapters while never treating the
    # shared XHS source ID as proof of channel identity.
    value = getattr(connector_channel, "value", connector_channel)
    return str(value).casefold() == channel.value


def _operation_outcome(
    source_id: str,
    value: object,
    *,
    isolation: IsolationCoordinates,
) -> SourceCollectionOutcome:
    """Normalize every SourceConnector operation to one batch outcome.

    ``SourceConnector`` intentionally returns a document for detail calls and
    a tuple of media references for media calls.  The account gateway has one
    outcome envelope, so it wraps those typed values in a minimal canonical
    batch using the invocation's public isolation coordinates.  This keeps
    detail/media results from being mistaken for malformed provider payloads
    while preserving the connector-owned metadata and validation.
    """

    if isinstance(value, CanonicalSourceBatch):
        items = value.documents or value.comments or value.authors or value.media_refs
        if value.errors:
            first = value.errors[0]
            return SourceCollectionOutcome(
                source_id=source_id,
                outcome="partial" if items else "failure",
                batch=value if items else None,
                error=first,
            )
        return SourceCollectionOutcome(
            source_id=source_id,
            outcome="success_nonempty" if items else "success_empty",
            batch=value,
        )
    batch: CanonicalSourceBatch | None = None
    if isinstance(value, CanonicalSourceDocument):
        batch = CanonicalSourceBatch(
            isolation=isolation,
            source_id=value.source_id,
            connector_id="platform-detail",
            connector_version="platform-detail/v1",
            normalizer_version="platform-detail-normalizer/v1",
            documents=(value,),
            watermark=None,
        )
    elif isinstance(value, CanonicalSourceComment):
        batch = CanonicalSourceBatch(
            isolation=isolation,
            source_id=value.source_id,
            connector_id="platform-comment",
            connector_version="platform-comment/v1",
            normalizer_version="platform-comment-normalizer/v1",
            comments=(value,),
            watermark=None,
        )
    elif isinstance(value, CanonicalAuthor):
        batch = CanonicalSourceBatch(
            isolation=isolation,
            source_id=value.source_id,
            connector_id="platform-author",
            connector_version="platform-author/v1",
            normalizer_version="platform-author-normalizer/v1",
            authors=(value,),
            watermark=None,
        )
    elif (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and all(isinstance(item, CanonicalMediaRef) for item in value)
    ):
        media_refs = tuple(value)
        batch = CanonicalSourceBatch(
            isolation=isolation,
            source_id=source_id,
            connector_id="platform-media",
            connector_version="platform-media/v1",
            normalizer_version="platform-media-normalizer/v1",
            media_refs=media_refs,
            watermark=None,
        )
    if batch is not None:
        items = batch.documents or batch.comments or batch.authors or batch.media_refs
        return SourceCollectionOutcome(
            source_id=source_id,
            outcome="success_nonempty" if items else "success_empty",
            batch=batch,
        )
    return SourceCollectionOutcome(
        source_id=source_id,
        outcome="failure",
        error=ContractError(
            code=_code_text(PlatformGatewayCode.MALFORMED_RESPONSE),
            category=ErrorCategory.MALFORMED_RESPONSE,
            scope=ErrorScope.SOURCE,
            retryable=False,
            terminal=True,
            boundary_ref=source_id,
        ),
    )


def _safe_provider_error(exc: BaseException, source_id: str) -> ContractError:
    error = getattr(exc, "error", None)
    if isinstance(error, ContractError):
        # Provider adapters normally redact before constructing ContractError,
        # but a custom bridge may attach one directly.  Re-apply the gateway
        # boundary redaction so cookies/tokens cannot escape through details.
        return error.model_copy(
            update={
                "boundary_ref": source_id,
                "message": _redact_provider_text(error.message),
                "details": {},
            }
        )
    if isinstance(exc, TimeoutError):
        code, category, retryable = (
            PlatformGatewayCode.TIMEOUT,
            ErrorCategory.TIMEOUT,
            True,
        )
    else:
        code, category, retryable = (
            PlatformGatewayCode.PROVIDER_UNAVAILABLE,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            True,
        )
    return ContractError(
        code=_code_text(code),
        category=category,
        scope=ErrorScope.PROVIDER,
        retryable=retryable,
        terminal=not retryable,
        boundary_ref=source_id,
    )


_SENSITIVE_PROVIDER_TEXT = re.compile(
    r"(?i)([\"']?(?:cookie|authorization|bearer|token|password|passwd|secret|"
    r"storage[_ -]?state|xsec[_ -]?token)[\"']?\s*[:=]\s*[\"']?)[^\"'\r\n,;}]+"
)


def _redact_provider_text(value: object) -> str | None:
    if value is None:
        return None
    text = _SENSITIVE_PROVIDER_TEXT.sub(r"\1<redacted>", str(value))
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "bearer <redacted>", text)
    return text[:256] or None


def _account_unavailable(account: PlatformAccount) -> str | None:
    if account.status in {
        PlatformAccountStatus.DISABLED,
        PlatformAccountStatus.REAUTH_REQUIRED,
        PlatformAccountStatus.PENDING_LOGIN,
    }:
        return account.status.value
    if account.health in {
        PlatformAccountHealth.DISABLED,
        PlatformAccountHealth.SESSION_INVALID,
        PlatformAccountHealth.SESSION_EXPIRED,
        PlatformAccountHealth.CHALLENGE_REQUIRED,
        PlatformAccountHealth.RISK_COOLDOWN,
        PlatformAccountHealth.THROTTLED,
    }:
        return account.health.value
    return None


def _health_signal(error: ContractError) -> AccountHealthSignal:
    code = error.code.casefold()
    if "auth" in code or "session" in code:
        return AccountHealthSignal.AUTHENTICATION
    if "challenge" in code or "risk" in code:
        return AccountHealthSignal.CHALLENGE
    if error.category is ErrorCategory.RATE_LIMITED:
        return AccountHealthSignal.THROTTLED
    if error.category is ErrorCategory.MALFORMED_RESPONSE:
        return AccountHealthSignal.PARSE
    return AccountHealthSignal.TRANSIENT


def _health_state(error: ContractError | None) -> PlatformAccountHealth:
    if error is None:
        return PlatformAccountHealth.HEALTHY
    signal = _health_signal(error)
    return {
        AccountHealthSignal.AUTHENTICATION: PlatformAccountHealth.SESSION_INVALID,
        AccountHealthSignal.CHALLENGE: PlatformAccountHealth.CHALLENGE_REQUIRED,
        AccountHealthSignal.THROTTLED: PlatformAccountHealth.THROTTLED,
        AccountHealthSignal.PARSE: PlatformAccountHealth.UNKNOWN,
    }.get(signal, PlatformAccountHealth.RISK_COOLDOWN if error.retryable else PlatformAccountHealth.UNKNOWN)


def _source_id(channel: PlatformChannel) -> str:
    return "dianping" if channel is PlatformChannel.DIANPING else "xhs"


def _channel_key(value: PlatformChannel | str) -> str:
    return value.value if isinstance(value, PlatformChannel) else str(value).casefold()


def _code_text(value: PlatformGatewayCode | str) -> str:
    """Serialize StrEnum codes without depending on Python's enum __str__."""

    return value.value if isinstance(value, PlatformGatewayCode) else str(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("platform gateway clock must return a timezone-aware value")
    return value.astimezone(UTC)


__all__ = [
    "AccountBoundGateway",
    "AccountBoundSourceGateway",
    "PlatformConnectorFactory",
    "PlatformGatewayCode",
    "PlatformGatewayError",
    "PlatformSourceGateway",
]
