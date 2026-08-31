"""Project-owned account/session authority and authenticated session envelopes.

The production implementation can replace the in-memory repository with a
PostgreSQL adapter without changing the contracts.  This module is useful for
local development and contract tests: it enforces the same tenant/channel
isolation, compare-and-set session versions, and single-flight account-lease
rules.  Volatile cache state is deliberately not used here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from Crypto.Cipher import AES
from pydantic import ValidationError

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountHealthSignal,
    AccountLeaseRequest,
    EncryptedSessionEnvelope,
    PlatformAccount,
    PlatformAccountGrant,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountLease,
    PlatformAccountLeasePort,
    PlatformAccountRef,
    PlatformAccountRepositoryPort,
    PlatformAccountSession,
    PlatformAccountStatus,
    PlatformChannel,
    PlatformLeaseStatus,
    PlatformLoginFlow,
    PlatformLoginFlowPort,
    PlatformSessionStatus,
    SessionActivationRequest,
    SessionEnvelopeCodecPort,
    Timestamp,
    validate_login_flow_update,
)


class AccountAuthorityError(RuntimeError):
    """Base class for safe, non-secret account authority errors."""

    code = "ACCOUNT_AUTHORITY_ERROR"


class AccountNotFoundError(AccountAuthorityError):
    code = "ACCOUNT_NOT_FOUND"


class AccountVersionConflict(AccountAuthorityError):
    code = "ACCOUNT_SESSION_VERSION_CONFLICT"


class AccountLeaseConflict(AccountAuthorityError):
    code = "ACCOUNT_LEASE_CONFLICT"


class SessionEnvelopeError(AccountAuthorityError):
    code = "SESSION_ENVELOPE_INVALID"


class SessionKeyProvider(Protocol):
    """Resolve a key by opaque reference/version (KMS/Vault can implement it)."""

    async def get_key(self, key_ref: str, key_version: str) -> bytes: ...


class InMemoryKeyProvider:
    """Deterministic test key provider; never use as a production KMS."""

    def __init__(self, keys: Mapping[tuple[str, str], bytes] | None = None) -> None:
        self._keys = dict(keys or {})

    def add(self, key_ref: str, key_version: str, key: bytes) -> None:
        if len(key) not in {16, 24, 32}:
            raise ValueError("AES key must be 128, 192, or 256 bits")
        self._keys[(key_ref, key_version)] = bytes(key)

    async def get_key(self, key_ref: str, key_version: str) -> bytes:
        try:
            key = self._keys[(key_ref, key_version)]
        except KeyError as exc:
            raise SessionEnvelopeError("session encryption key is unavailable") from exc
        return key


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise SessionEnvelopeError("session envelope encoding is invalid") from exc


def _aad(account: PlatformAccountRef, version: int) -> bytes:
    # AAD binds ciphertext to the tenant/channel/account and version.  The
    # values are opaque references and contain no credential material.
    return f"platform-session/v1|{account.tenant_id}|{account.platform.value}|{account.account_ref}|{version}".encode()


class AesGcmSessionCodec(SessionEnvelopeCodecPort):
    """AES-GCM codec with key rotation and authenticated associated data."""

    def __init__(
        self,
        key_provider: SessionKeyProvider,
        *,
        key_ref: str = "local-test",
        key_version: str = "v1",
        max_plaintext_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if not key_ref or not key_version:
            raise ValueError("session key reference and version are required")
        if max_plaintext_bytes < 1:
            raise ValueError("session plaintext limit must be positive")
        self._key_provider = key_provider
        self._key_ref = key_ref
        self._key_version = key_version
        self._max_plaintext_bytes = max_plaintext_bytes

    async def seal(
        self,
        account: PlatformAccountRef,
        plaintext: bytes,
        *,
        expires_at: Timestamp,
        version: int = 1,
    ) -> EncryptedSessionEnvelope:
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ValueError("session plaintext must be non-empty bytes")
        if len(plaintext) > self._max_plaintext_bytes:
            raise ValueError("session plaintext exceeds configured limit")
        key = await self._key_provider.get_key(self._key_ref, self._key_version)
        if len(key) not in {16, 24, 32}:
            raise SessionEnvelopeError("session encryption key has an invalid size")
        nonce = secrets.token_bytes(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        cipher.update(_aad(account, version))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        digest = hashlib.sha256(plaintext).hexdigest()
        # ``expires_at`` is intentionally consumed by the caller/row; keeping
        # it in the envelope AAD would make rotation unnecessarily coupled.
        del expires_at
        return EncryptedSessionEnvelope(
            ciphertext=_b64(ciphertext),
            nonce=_b64(nonce),
            auth_tag=_b64(tag),
            key_ref=self._key_ref,
            key_version=self._key_version,
            digest=digest,
            bound_version=version,
        )

    async def open(self, session: PlatformAccountSession) -> bytes:
        bound_version = session.envelope.bound_version
        if bound_version is not None and bound_version != session.version:
            raise SessionEnvelopeError("session envelope version does not match session")
        key = await self._key_provider.get_key(
            session.envelope.key_ref,
            session.envelope.key_version,
        )
        ciphertext = _unb64(session.envelope.ciphertext)
        nonce = _unb64(session.envelope.nonce)
        tag = _unb64(session.envelope.auth_tag)
        if len(nonce) != 12 or len(tag) != 16:
            raise SessionEnvelopeError("session envelope parameters are invalid")
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            cipher.update(_aad(session.account, session.version))
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        except (ValueError, KeyError) as exc:
            raise SessionEnvelopeError("session envelope authentication failed") from exc
        if len(plaintext) > self._max_plaintext_bytes:
            raise SessionEnvelopeError("session plaintext exceeds configured limit")
        if not hmac.compare_digest(hashlib.sha256(plaintext).hexdigest(), session.digest):
            raise SessionEnvelopeError("session envelope digest mismatch")
        return plaintext


def encode_session_material(value: Mapping[str, object]) -> bytes:
    """Canonicalize provider state before sealing; callers own the byte lifetime."""

    if not isinstance(value, Mapping) or not value:
        raise ValueError("session material must be a non-empty mapping")
    # Provider state is deliberately opaque to contracts, but it must still be
    # JSON-compatible so the sidecar and persistence implementations agree.
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("session material must be JSON-compatible") from exc


def decode_session_material(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionEnvelopeError("session material is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SessionEnvelopeError("session material must be an object")
    return decoded


@dataclass(slots=True, repr=False)
class SessionMaterial:
    """Activity-local plaintext holder; it is never a Pydantic contract."""

    value: bytearray

    def __repr__(self) -> str:
        return "SessionMaterial(<redacted>)"

    def wipe(self) -> None:
        for index in range(len(self.value)):
            self.value[index] = 0

    def __enter__(self) -> SessionMaterial:
        return self

    def __exit__(self, *_: object) -> None:
        self.wipe()


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryPlatformAccountAuthority(
    PlatformAccountRepositoryPort,
    PlatformAccountLeasePort,
    PlatformLoginFlowPort,
):
    """Concurrency-safe local authority used by tests and development."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _now
        self._accounts: dict[tuple[str, PlatformChannel, str], PlatformAccount] = {}
        self._sessions: dict[tuple[str, PlatformChannel, str], list[PlatformAccountSession]] = {}
        self._grants: dict[str, PlatformAccountGrant] = {}
        self._leases: dict[tuple[str, PlatformChannel, str], PlatformAccountLease] = {}
        self._flows: dict[str, PlatformLoginFlow] = {}
        self._health_events: list[PlatformAccountHealthEvent] = []
        self._lock = asyncio.Lock()

    def _key(self, ref: PlatformAccountRef) -> tuple[str, PlatformChannel, str]:
        return ref.natural_key

    async def get_account(self, ref: PlatformAccountRef) -> PlatformAccount | None:
        async with self._lock:
            return self._accounts.get(self._key(ref))

    async def save_account(self, account: PlatformAccount) -> PlatformAccount:
        async with self._lock:
            key = self._key(account.ref)
            current = self._accounts.get(key)
            if current is not None and current.updated_at > account.updated_at:
                raise AccountVersionConflict("account metadata is stale")
            self._accounts[key] = account
            self._sessions.setdefault(key, [])
            return account

    async def register_account(
        self,
        *,
        tenant_id: str,
        platform: PlatformChannel,
        account_ref: str,
        alias: str,
        now: datetime | None = None,
    ) -> PlatformAccount:
        timestamp = _as_utc(now or self._clock())
        account = PlatformAccount(
            tenant_id=tenant_id,
            platform=platform,
            account_ref=account_ref,
            alias=alias,
            created_at=timestamp,
            updated_at=timestamp,
        )
        async with self._lock:
            key = self._key(account.ref)
            if key in self._accounts:
                raise AccountVersionConflict("account reference already exists")
            if any(
                item.tenant_id == tenant_id
                and item.platform is platform
                and item.alias == alias
                for item in self._accounts.values()
            ):
                raise AccountVersionConflict("account alias already exists")
            self._accounts[key] = account
            self._sessions[key] = []
        return account

    async def activate_session(self, request: SessionActivationRequest) -> PlatformAccountSession:
        now = _as_utc(request.requested_at)
        async with self._lock:
            key = self._key(request.account)
            account = self._accounts.get(key)
            if account is None:
                raise AccountNotFoundError("account is not registered")
            if account.session_version != request.expected_session_version:
                raise AccountVersionConflict("session version is stale")
            version = account.session_version + 1
            # Bind codec-produced envelopes to their allocated version.  An
            # unbound legacy fixture may still be admitted for migration tests,
            # but a bound envelope with a stale version is rejected before the
            # active pointer changes.
            if (
                request.envelope.bound_version is not None
                and request.envelope.bound_version != account.session_version + 1
            ):
                raise AccountVersionConflict("session envelope version is stale")
            sessions = self._sessions.setdefault(key, [])
            for index, prior in enumerate(sessions):
                if prior.status is PlatformSessionStatus.ACTIVE:
                    sessions[index] = prior.model_copy(
                        update={
                            "status": PlatformSessionStatus.SUPERSEDED,
                            "superseded_at": now,
                        }
                    )
            session = PlatformAccountSession(
                session_id=f"sess-{uuid4().hex}",
                account=request.account,
                version=version,
                envelope=request.envelope,
                expires_at=request.expires_at,
                status=PlatformSessionStatus.ACTIVE,
                created_at=now,
            )
            sessions.append(session)
            updated = account.model_copy(
                update={
                    "session_version": version,
                    "provider_subject_id": request.provider_subject_id,
                    "status": PlatformAccountStatus.ACTIVE,
                    "health": PlatformAccountHealth.HEALTHY,
                    "updated_at": now,
                }
            )
            self._accounts[key] = updated
            return session

    async def get_active_session(self, ref: PlatformAccountRef) -> PlatformAccountSession | None:
        now = _as_utc(self._clock())
        async with self._lock:
            sessions = self._sessions.get(self._key(ref), [])
            for index in range(len(sessions) - 1, -1, -1):
                session = sessions[index]
                if session.status is PlatformSessionStatus.ACTIVE:
                    if session.expires_at <= now:
                        expired = session.model_copy(update={"status": PlatformSessionStatus.EXPIRED})
                        sessions[index] = expired
                        account = self._accounts.get(self._key(ref))
                        if account is not None:
                            self._accounts[self._key(ref)] = account.model_copy(
                                update={
                                    "status": PlatformAccountStatus.REAUTH_REQUIRED,
                                    "health": PlatformAccountHealth.SESSION_EXPIRED,
                                    "updated_at": now,
                                }
                            )
                        return expired
                    return session
            return None

    async def open_active_session(
        self, ref: PlatformAccountRef, codec: AesGcmSessionCodec
    ) -> SessionMaterial:
        session = await self.get_active_session(ref)
        if session is None or session.status is not PlatformSessionStatus.ACTIVE:
            raise AccountNotFoundError("active session is unavailable")
        if session.expires_at <= _as_utc(self._clock()):
            raise AccountNotFoundError("active session is expired")
        plaintext = await codec.open(session)
        return SessionMaterial(bytearray(plaintext))

    async def add_grant(self, grant: PlatformAccountGrant) -> PlatformAccountGrant:
        async with self._lock:
            if self._key(grant.account) not in self._accounts:
                raise AccountNotFoundError("account is not registered")
            self._grants[grant.grant_id] = grant
            return grant

    async def authorize(
        self,
        account: PlatformAccountRef,
        principal_id: str,
        permission: AccountGrantPermission,
    ) -> PlatformAccountGrant | None:
        now = _as_utc(self._clock())
        async with self._lock:
            if self._key(account) not in self._accounts:
                return None
            for grant in self._grants.values():
                if (
                    grant.account.natural_key == account.natural_key
                    and grant.principal_id == principal_id
                    and grant.revoked_at is None
                    and (grant.expires_at is None or grant.expires_at > now)
                    and grant.permits(permission)
                ):
                    return grant
            return None

    async def acquire(self, request: AccountLeaseRequest) -> PlatformAccountLease:
        now = _as_utc(self._clock())
        async with self._lock:
            key = self._key(request.account)
            account = self._accounts.get(key)
            if account is None:
                raise AccountNotFoundError("account is not registered")
            if (
                request.expected_session_version is not None
                and account.session_version != request.expected_session_version
            ):
                raise AccountVersionConflict("session version is stale")
            current = self._leases.get(key)
            if current is not None and current.status is PlatformLeaseStatus.ACTIVE:
                if current.expires_at > now:
                    raise AccountLeaseConflict("account already has an active lease")
                current = current.model_copy(
                    update={"status": PlatformLeaseStatus.EXPIRED, "released_at": now}
                )
                self._leases[key] = current
            raw_owner_token = secrets.token_bytes(32)
            token_digest = hashlib.sha256(raw_owner_token).hexdigest()
            lease = PlatformAccountLease(
                lease_id=f"lease-{uuid4().hex}",
                account=request.account,
                task_id=request.task_id,
                owner_id=request.owner_id,
                owner_token_digest=token_digest,
                acquired_at=now,
                expires_at=now + timedelta(seconds=request.ttl_seconds),
                last_heartbeat_at=now,
            )
            self._leases[key] = lease
            return lease

    async def heartbeat(self, lease_id: str, *, ttl_seconds: int) -> PlatformAccountLease:
        now = _as_utc(self._clock())
        async with self._lock:
            lease = next((item for item in self._leases.values() if item.lease_id == lease_id), None)
            if lease is None or lease.status is not PlatformLeaseStatus.ACTIVE:
                raise AccountLeaseConflict("lease is not active")
            if lease.expires_at <= now:
                self._leases[self._key(lease.account)] = lease.model_copy(
                    update={"status": PlatformLeaseStatus.EXPIRED, "released_at": now}
                )
                raise AccountLeaseConflict("lease has expired")
            updated = lease.model_copy(
                update={
                    "last_heartbeat_at": now,
                    "expires_at": now + timedelta(seconds=ttl_seconds),
                }
            )
            self._leases[self._key(lease.account)] = updated
            return updated

    async def release(self, lease_id: str) -> bool:
        now = _as_utc(self._clock())
        async with self._lock:
            for key, lease in tuple(self._leases.items()):
                if lease.lease_id != lease_id:
                    continue
                if lease.status is PlatformLeaseStatus.RELEASED:
                    return False
                self._leases[key] = lease.model_copy(
                    update={"status": PlatformLeaseStatus.RELEASED, "released_at": now}
                )
                return True
            return False

    async def record(self, event: PlatformAccountHealthEvent) -> None:
        async with self._lock:
            key = self._key(event.account)
            account = self._accounts.get(key)
            if account is None:
                raise AccountNotFoundError("account is not registered")
            status = account.status
            if event.signal in {AccountHealthSignal.AUTHENTICATION, AccountHealthSignal.EXPIRED}:
                status = PlatformAccountStatus.REAUTH_REQUIRED
            elif event.signal is AccountHealthSignal.CHALLENGE:
                status = PlatformAccountStatus.DEGRADED
            elif event.signal is AccountHealthSignal.REVOKED:
                status = PlatformAccountStatus.DISABLED
            elif event.signal is AccountHealthSignal.SUCCESS:
                status = PlatformAccountStatus.ACTIVE
            self._accounts[key] = account.model_copy(
                update={"health": event.health, "status": status, "updated_at": event.observed_at}
            )
            self._health_events.append(event)

    async def save_flow(self, flow: PlatformLoginFlow) -> PlatformLoginFlow:
        try:
            # Callers commonly build retry snapshots with ``model_copy``.  Keep
            # the authority boundary explicit and revalidate before applying
            # the CAS rule, even if a future model implementation changes its
            # copy semantics.
            validated = PlatformLoginFlow.model_validate(flow.model_dump())
        except ValidationError as exc:
            raise AccountVersionConflict("login flow snapshot is invalid") from exc
        async with self._lock:
            existing = self._flows.get(validated.flow_id)
            if existing is not None:
                try:
                    validate_login_flow_update(existing, validated)
                except ValueError as exc:
                    raise AccountVersionConflict(str(exc)) from exc
            self._flows[validated.flow_id] = validated
            return validated

    async def get_flow(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow | None:
        async with self._lock:
            flow = self._flows.get(flow_id)
            if flow is None or flow.account.tenant_id != tenant_id:
                return None
            return flow

    @property
    def health_events(self) -> tuple[PlatformAccountHealthEvent, ...]:
        return tuple(self._health_events)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("account authority timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "AccountAuthorityError",
    "AccountLeaseConflict",
    "AccountNotFoundError",
    "AccountVersionConflict",
    "AesGcmSessionCodec",
    "InMemoryKeyProvider",
    "InMemoryPlatformAccountAuthority",
    "SessionEnvelopeError",
    "SessionKeyProvider",
    "SessionMaterial",
    "decode_session_material",
    "encode_session_material",
]
