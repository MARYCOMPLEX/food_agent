"""SQLAlchemy adapter for platform account/session authority.

The adapter owns no schema creation and never stores provider plaintext.  A
caller supplies either the project ``SQLAlchemyUnitOfWork`` factory or an
``AsyncSession`` factory.  Every operation is scoped by the composite
``(tenant_id, platform, account_ref)`` identity and translates driver failures
to the stable Foundation error boundary.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import secrets
from collections.abc import Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    NoSuchTableError,
    OperationalError,
    ProgrammingError,
)

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountHealthSignal,
    AccountLeaseRequest,
    EncryptedSessionEnvelope,
    ErrorScope,
    LoginFlowState,
    PlatformAccount,
    PlatformAccountGrant,
    PlatformAccountGrantPort,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountHealthPort,
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
)

from .database import SQLAlchemyUnitOfWork
from .failures import FoundationAdapterError, foundation_error_from_exception
from .platform_account_schema import (
    platform_account_grants,
    platform_account_health_events,
    platform_account_leases,
    platform_account_sessions,
    platform_accounts,
    platform_login_flows,
)
from .platform_accounts import (
    AccountAuthorityError,
    AccountLeaseConflict,
    AccountNotFoundError,
    AccountVersionConflict,
)

UnitOfWorkFactory = Callable[[], SQLAlchemyUnitOfWork]
SessionFactory = Callable[[], Any]
Clock = Callable[[], datetime]


class PlatformAccountRepositoryError(FoundationAdapterError):
    """Stable repository failure carrying a redacted ``ContractError``."""


class PlatformAccountSchemaNotReadyError(PlatformAccountRepositoryError):
    """Raised when Alembic has not provisioned the account authority tables."""


class SQLAlchemyPlatformAccountRepository(
    PlatformAccountRepositoryPort,
    PlatformAccountLeasePort,
    PlatformAccountGrantPort,
    PlatformLoginFlowPort,
    PlatformAccountHealthPort,
):
    """Persist platform account authority through one injected transaction.

    ``unit_of_work_factory`` is preferred in the application because it makes
    transaction ownership explicit.  ``session_factory``/``session`` are
    provided for adapter tests and integrations that already own an
    ``AsyncSession``.  The adapter never calls ``metadata.create_all`` or any
    other schema repair operation.
    """

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory | None = None,
        *,
        session_factory: SessionFactory | None = None,
        session: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        # Permit the concise ``Repository(async_session)`` form while keeping
        # the explicit keyword forms unambiguous.  A real UoW is callable via
        # the factory contract; an AsyncSession exposes ``execute`` instead.
        if (
            unit_of_work_factory is not None
            and session_factory is None
            and session is None
            and not callable(unit_of_work_factory)
            and callable(getattr(unit_of_work_factory, "execute", None))
        ):
            session = unit_of_work_factory
            unit_of_work_factory = None
        supplied = sum(value is not None for value in (unit_of_work_factory, session_factory, session))
        if supplied != 1:
            raise ValueError("provide exactly one unit_of_work_factory, session_factory, or session")
        self._unit_of_work_factory = unit_of_work_factory
        if session is not None:
            self._session_factory = lambda: session
            self._close_direct_session = False
        else:
            self._session_factory = session_factory
            self._close_direct_session = True
        self._clock = clock or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # Account/session authority
    # ------------------------------------------------------------------

    async def get_account(self, ref: PlatformAccountRef) -> PlatformAccount | None:
        statement = select(platform_accounts).where(*_account_clause(ref))
        async with self._scope("platform_account.get") as (db, _commit):
            row = _first_row(await self._execute(db, statement, "platform_account.get"))
        return _account_from_row(row) if row is not None else None

    async def save_account(self, account: PlatformAccount) -> PlatformAccount:
        ref = account.ref
        statement = insert(platform_accounts).values(
            tenant_id=ref.tenant_id,
            platform=ref.platform.value,
            account_ref=ref.account_ref,
            alias=account.alias,
            provider_subject_id=account.provider_subject_id,
            status=account.status.value,
            health=account.health.value,
            session_version=account.session_version,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                platform_accounts.c.tenant_id,
                platform_accounts.c.platform,
                platform_accounts.c.account_ref,
            ],
            set_={
                "alias": statement.excluded.alias,
                "provider_subject_id": statement.excluded.provider_subject_id,
                "status": statement.excluded.status,
                "health": statement.excluded.health,
                "session_version": statement.excluded.session_version,
                "updated_at": statement.excluded.updated_at,
            },
            where=(
                (platform_accounts.c.updated_at <= statement.excluded.updated_at)
                & (platform_accounts.c.session_version <= statement.excluded.session_version)
            ),
        )
        async with self._scope("platform_account.save") as (db, commit):
            try:
                result = await self._execute(
                    db,
                    statement,
                    "platform_account.save",
                    preserve=(IntegrityError,),
                )
            except IntegrityError as exc:
                raise _version_conflict("account metadata conflicts with existing identity") from exc
            if _rowcount(result) == 0:
                raise _version_conflict("account metadata is stale")
            await commit()
        return account

    async def activate_session(self, request: SessionActivationRequest) -> PlatformAccountSession:
        """Atomically advance the account version and activate one envelope."""

        ref = request.account
        now = _as_utc(request.requested_at)
        async with self._scope("platform_session.activate") as (db, commit):
            account_result = await self._execute(
                db,
                select(platform_accounts.c.session_version)
                .where(*_account_clause(ref))
                .with_for_update(),
                "platform_session.lookup_account",
            )
            account_row = _first_row(account_result)
            if account_row is None:
                raise _account_not_found()
            current_version = int(account_row["session_version"] or 0)
            if current_version != request.expected_session_version:
                raise _version_conflict()
            version = current_version + 1
            if (
                request.envelope.bound_version is not None
                and request.envelope.bound_version != version
            ):
                raise _version_conflict("session envelope version is stale")

            advance = (
                update(platform_accounts)
                .where(
                    *_account_clause(ref),
                    platform_accounts.c.session_version == request.expected_session_version,
                )
                .values(
                    session_version=version,
                    provider_subject_id=request.provider_subject_id,
                    status=PlatformAccountStatus.ACTIVE.value,
                    health=PlatformAccountHealth.HEALTHY.value,
                    updated_at=now,
                )
            )
            result = await self._execute(db, advance, "platform_session.cas")
            if _rowcount(result) == 0:
                raise _version_conflict()

            # Keep immutable history while ensuring exactly one active version.
            supersede = (
                update(platform_account_sessions)
                .where(
                    platform_account_sessions.c.tenant_id == ref.tenant_id,
                    platform_account_sessions.c.platform == ref.platform.value,
                    platform_account_sessions.c.account_ref == ref.account_ref,
                    platform_account_sessions.c.status == PlatformSessionStatus.ACTIVE.value,
                )
                .values(
                    status=PlatformSessionStatus.SUPERSEDED.value,
                    superseded_at=now,
                )
            )
            await self._execute(db, supersede, "platform_session.supersede")
            session_id = f"sess-{uuid4().hex}"
            await self._execute(
                db,
                insert(platform_account_sessions).values(
                    session_id=session_id,
                    tenant_id=ref.tenant_id,
                    platform=ref.platform.value,
                    account_ref=ref.account_ref,
                    version=version,
                    status=PlatformSessionStatus.ACTIVE.value,
                    ciphertext=_decode_envelope_part(request.envelope.ciphertext),
                    nonce=_decode_envelope_part(request.envelope.nonce),
                    auth_tag=_decode_envelope_part(request.envelope.auth_tag),
                    key_ref=request.envelope.key_ref,
                    key_version=request.envelope.key_version,
                    payload_digest=request.envelope.digest,
                    expires_at=request.expires_at,
                    created_at=now,
                    metadata={"bound_version": request.envelope.bound_version},
                ),
                "platform_session.insert",
            )
            await commit()

        return PlatformAccountSession(
            session_id=session_id,
            account=ref,
            version=version,
            envelope=request.envelope,
            expires_at=request.expires_at,
            status=PlatformSessionStatus.ACTIVE,
            created_at=now,
        )

    async def get_active_session(self, ref: PlatformAccountRef) -> PlatformAccountSession | None:
        statement = (
            select(platform_account_sessions)
            .where(
                platform_account_sessions.c.tenant_id == ref.tenant_id,
                platform_account_sessions.c.platform == ref.platform.value,
                platform_account_sessions.c.account_ref == ref.account_ref,
                platform_account_sessions.c.status == PlatformSessionStatus.ACTIVE.value,
            )
            .order_by(platform_account_sessions.c.version.desc())
            .limit(1)
        )
        async with self._scope("platform_session.get_active") as (db, commit):
            row = _first_row(await self._execute(db, statement, "platform_session.get_active"))
            if row is None:
                return None
            session = _session_from_row(row)
            now = _as_utc(self._clock())
            if session.expires_at <= now:
                await self._execute(
                    db,
                    update(platform_account_sessions)
                    .where(
                        platform_account_sessions.c.session_id == session.session_id,
                        platform_account_sessions.c.status == PlatformSessionStatus.ACTIVE.value,
                        platform_account_sessions.c.expires_at <= now,
                    )
                    .values(status=PlatformSessionStatus.EXPIRED.value),
                    "platform_session.expire",
                )
                await self._execute(
                    db,
                    update(platform_accounts)
                    .where(
                        *_account_clause(ref),
                        platform_accounts.c.session_version <= session.version,
                    )
                    .values(
                        status=PlatformAccountStatus.REAUTH_REQUIRED.value,
                        health=PlatformAccountHealth.SESSION_EXPIRED.value,
                        updated_at=now,
                    ),
                    "platform_session.expire_account",
                )
                await commit()
                return session.model_copy(update={"status": PlatformSessionStatus.EXPIRED})
            return session

    # ------------------------------------------------------------------
    # Grant authority
    # ------------------------------------------------------------------

    async def add_grant(self, grant: PlatformAccountGrant) -> PlatformAccountGrant:
        ref = grant.account
        async with self._scope("platform_grant.save") as (db, commit):
            account = await self._execute(
                db,
                select(platform_accounts.c.account_ref).where(*_account_clause(ref)),
                "platform_grant.lookup_account",
            )
            if _first_row(account) is None:
                raise _account_not_found()
            existing = await self._execute(
                db,
                select(platform_account_grants).where(
                    platform_account_grants.c.grant_id == grant.grant_id
                ),
                "platform_grant.lookup_existing",
            )
            existing_row = _first_row(existing)
            if existing_row is not None and _row_scope(existing_row) != ref.natural_key:
                raise _version_conflict("grant identity conflicts with another account")
            statement = insert(platform_account_grants).values(
                grant_id=grant.grant_id,
                tenant_id=ref.tenant_id,
                platform=ref.platform.value,
                account_ref=ref.account_ref,
                principal_id=grant.principal_id,
                permissions=[item.value for item in grant.permissions],
                issued_at=grant.issued_at,
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
                metadata={},
            ).on_conflict_do_update(
                index_elements=[platform_account_grants.c.grant_id],
                set_={
                    "principal_id": grant.principal_id,
                    "permissions": [item.value for item in grant.permissions],
                    "expires_at": grant.expires_at,
                    "revoked_at": grant.revoked_at,
                },
            )
            try:
                await self._execute(
                    db,
                    statement,
                    "platform_grant.save",
                    preserve=(IntegrityError,),
                )
            except IntegrityError as exc:
                raise _version_conflict("grant identity conflicts with existing row") from exc
            await commit()
        return grant

    async def authorize(
        self,
        account: PlatformAccountRef,
        principal_id: str,
        permission: AccountGrantPermission,
    ) -> PlatformAccountGrant | None:
        now = _as_utc(self._clock())
        statement = select(platform_account_grants).where(
            *_account_clause(account, platform_account_grants),
            platform_account_grants.c.principal_id == principal_id,
            platform_account_grants.c.issued_at <= now,
            platform_account_grants.c.revoked_at.is_(None),
            (platform_account_grants.c.expires_at.is_(None)
             | (platform_account_grants.c.expires_at > now)),
        )
        async with self._scope("platform_grant.authorize") as (db, _commit):
            rows = _all_rows(await self._execute(db, statement, "platform_grant.authorize"))
        for row in rows:
            grant = _grant_from_row(row)
            if grant.permits(permission):
                return grant
        return None

    # ------------------------------------------------------------------
    # Durable account lease
    # ------------------------------------------------------------------

    async def acquire(self, request: AccountLeaseRequest) -> PlatformAccountLease:
        ref = request.account
        now = _as_utc(self._clock())
        async with self._scope("platform_lease.acquire") as (db, commit):
            account = _first_row(
                await self._execute(
                    db,
                    select(
                        platform_accounts.c.account_ref,
                        platform_accounts.c.session_version,
                    ).where(*_account_clause(ref)).with_for_update(),
                    "platform_lease.lookup_account",
                )
            )
            if account is None:
                raise _account_not_found()
            if (
                request.expected_session_version is not None
                and int(account.get("session_version") or 0)
                != request.expected_session_version
            ):
                raise _version_conflict("session version is stale")
            expire = (
                update(platform_account_leases)
                .where(
                    *_account_clause(ref, platform_account_leases),
                    platform_account_leases.c.status == PlatformLeaseStatus.ACTIVE.value,
                    platform_account_leases.c.expires_at <= now,
                )
                .values(status=PlatformLeaseStatus.EXPIRED.value, released_at=now)
            )
            await self._execute(db, expire, "platform_lease.expire")
            active = (
                select(platform_account_leases.c.lease_id)
                .where(
                    *_account_clause(ref, platform_account_leases),
                    platform_account_leases.c.status == PlatformLeaseStatus.ACTIVE.value,
                    platform_account_leases.c.expires_at > now,
                )
                .with_for_update()
            )
            if _first_row(await self._execute(db, active, "platform_lease.check")) is not None:
                raise _lease_conflict()
            lease = PlatformAccountLease(
                lease_id=f"lease-{uuid4().hex}",
                account=ref,
                task_id=request.task_id,
                owner_id=request.owner_id,
                owner_token_digest=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                status=PlatformLeaseStatus.ACTIVE,
                acquired_at=now,
                expires_at=now + timedelta(seconds=request.ttl_seconds),
                last_heartbeat_at=now,
            )
            try:
                await self._execute(
                    db,
                    insert(platform_account_leases).values(
                        lease_id=lease.lease_id,
                        tenant_id=ref.tenant_id,
                        platform=ref.platform.value,
                        account_ref=ref.account_ref,
                        task_id=lease.task_id,
                        owner_id=lease.owner_id,
                        owner_token_digest=lease.owner_token_digest,
                        status=lease.status.value,
                        acquired_at=lease.acquired_at,
                        expires_at=lease.expires_at,
                        last_heartbeat_at=lease.last_heartbeat_at,
                        released_at=None,
                    ),
                    "platform_lease.insert",
                    preserve=(IntegrityError,),
                )
            except IntegrityError as exc:
                raise _lease_conflict() from exc
            await commit()
        return lease

    async def heartbeat(self, lease_id: str, *, ttl_seconds: int) -> PlatformAccountLease:
        if ttl_seconds < 1:
            raise ValueError("lease ttl must be positive")
        now = _as_utc(self._clock())
        expires = now + timedelta(seconds=ttl_seconds)
        statement = (
            update(platform_account_leases)
            .where(
                platform_account_leases.c.lease_id == lease_id,
                platform_account_leases.c.status == PlatformLeaseStatus.ACTIVE.value,
                platform_account_leases.c.expires_at > now,
            )
            .values(last_heartbeat_at=now, expires_at=expires)
        )
        async with self._scope("platform_lease.heartbeat") as (db, commit):
            result = await self._execute(db, statement, "platform_lease.heartbeat")
            if _rowcount(result) == 0:
                await self._execute(
                    db,
                    update(platform_account_leases)
                    .where(
                        platform_account_leases.c.lease_id == lease_id,
                        platform_account_leases.c.status == PlatformLeaseStatus.ACTIVE.value,
                        platform_account_leases.c.expires_at <= now,
                    )
                    .values(
                        status=PlatformLeaseStatus.EXPIRED.value,
                        released_at=now,
                    ),
                    "platform_lease.expire",
                )
                await commit()
                raise _lease_conflict("lease is not active")
            row = _first_row(
                await self._execute(
                    db,
                    select(platform_account_leases).where(
                        platform_account_leases.c.lease_id == lease_id
                    ),
                    "platform_lease.read",
                )
            )
            if row is None:
                raise _lease_conflict("lease is not active")
            await commit()
        return _lease_from_row(row)

    async def release(self, lease_id: str) -> bool:
        now = _as_utc(self._clock())
        statement = (
            update(platform_account_leases)
            .where(
                platform_account_leases.c.lease_id == lease_id,
                platform_account_leases.c.status == PlatformLeaseStatus.ACTIVE.value,
            )
            .values(status=PlatformLeaseStatus.RELEASED.value, released_at=now)
        )
        async with self._scope("platform_lease.release") as (db, commit):
            result = await self._execute(db, statement, "platform_lease.release")
            changed = _rowcount(result) != 0
            await commit()
        return changed

    # ------------------------------------------------------------------
    # Login flow and health authority
    # ------------------------------------------------------------------

    async def get_flow(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow | None:
        statement = select(platform_login_flows).where(
            platform_login_flows.c.flow_id == flow_id,
            platform_login_flows.c.tenant_id == tenant_id,
        )
        async with self._scope("platform_login.get") as (db, _commit):
            row = _first_row(await self._execute(db, statement, "platform_login.get"))
        return _flow_from_row(row) if row is not None else None

    async def save_flow(self, flow: PlatformLoginFlow) -> PlatformLoginFlow:
        try:
            # Keep the persistence boundary explicit and revalidate snapshots
            # so invalid terminal values never reach PostgreSQL, even if a
            # future model implementation changes its copy semantics.
            flow = PlatformLoginFlow.model_validate(flow.model_dump())
        except ValidationError as exc:
            raise _version_conflict("login flow snapshot is invalid") from exc
        ref = flow.account
        metadata: dict[str, Any] = {}
        if flow.qr_object_ref is not None:
            metadata["qr_object_ref"] = flow.qr_object_ref.model_dump(mode="json")
        statement = insert(platform_login_flows).values(
            flow_id=flow.flow_id,
            tenant_id=ref.tenant_id,
            platform=ref.platform.value,
            account_ref=ref.account_ref,
            state=flow.state.value,
            created_at=flow.created_at,
            expires_at=flow.expires_at,
            updated_at=flow.updated_at,
            qr_object_key=flow.qr_object_ref.key if flow.qr_object_ref else None,
            qr_expires_at=flow.qr_expires_at,
            provider_subject_id=flow.provider_subject_id,
            error_code=flow.error_code,
            error_message=flow.error_message,
            metadata=metadata,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[platform_login_flows.c.flow_id],
            set_={
                "state": statement.excluded.state,
                "expires_at": statement.excluded.expires_at,
                "updated_at": statement.excluded.updated_at,
                "qr_object_key": statement.excluded.qr_object_key,
                "qr_expires_at": statement.excluded.qr_expires_at,
                "provider_subject_id": statement.excluded.provider_subject_id,
                "error_code": statement.excluded.error_code,
                "error_message": statement.excluded.error_message,
                "metadata": statement.excluded.metadata,
            },
            # Keep the database predicate as a second line of defence in
            # addition to the in-memory snapshot validator.  A delayed worker
            # may have a newer timestamp but an older state; that update must
            # lose to the already persisted state.  Terminal rows accept only
            # an idempotent re-save of the same immutable payload.
            where=_flow_update_clause(statement, ref),
        )
        async with self._scope("platform_login.save") as (db, commit):
            try:
                result = await self._execute(
                    db,
                    statement,
                    "platform_login.save",
                    preserve=(IntegrityError,),
                )
            except IntegrityError as exc:
                raise _version_conflict("login flow identity conflicts with existing row") from exc
            if _rowcount(result) == 0:
                raise _version_conflict("login flow is stale or bound to another account")
            await commit()
        return flow

    async def record(self, event: PlatformAccountHealthEvent) -> None:
        ref = event.account
        async with self._scope("platform_health.record") as (db, commit):
            account = _first_row(
                await self._execute(
                    db,
                    select(
                        platform_accounts.c.account_ref,
                        platform_accounts.c.session_version,
                        platform_accounts.c.updated_at,
                    )
                    .where(*_account_clause(ref))
                    .with_for_update(),
                    "platform_health.lookup_account",
                )
            )
            if account is None:
                raise _account_not_found()
            event_statement = insert(platform_account_health_events).values(
                    event_id=event.event_id,
                    tenant_id=ref.tenant_id,
                    platform=ref.platform.value,
                    account_ref=ref.account_ref,
                    signal=event.signal.value,
                    health=event.health.value,
                    session_version=event.session_version,
                    task_id=event.task_id,
                    reason=event.reason,
                    metadata=event.metadata,
                    observed_at=event.observed_at,
                ).on_conflict_do_nothing(index_elements=[platform_account_health_events.c.event_id])
            event_result = await self._execute(db, event_statement, "platform_health.insert")
            # Duplicate event IDs are idempotent receipts; do not re-apply a
            # health transition or regress a newer account projection.
            if _rowcount(event_result) == 0:
                await commit()
                return
            status = _status_for_health_signal(event.signal)
            values: dict[str, Any] = {
                "health": event.health.value,
                "updated_at": event.observed_at,
            }
            if status is not None:
                values["status"] = status.value
            account_update = update(platform_accounts).where(
                *_account_clause(ref),
                platform_accounts.c.updated_at <= event.observed_at,
            )
            if event.session_version is not None:
                account_update = account_update.where(
                    platform_accounts.c.session_version <= event.session_version
                )
            await self._execute(
                db,
                account_update.values(**values),
                "platform_health.update_account",
            )
            await commit()

    # ------------------------------------------------------------------
    # Transaction/error boundary
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _scope(self, operation: str):
        """Yield ``(session, commit)`` and close/rollback on every path."""

        if self._unit_of_work_factory is not None:
            try:
                unit = self._unit_of_work_factory()
                if inspect.isawaitable(unit):
                    unit = await unit
                async with unit as active_unit:
                    owner = active_unit if active_unit is not None else unit
                    yield owner.session_for_adapter(), owner.commit
            except (AccountAuthorityError, PlatformAccountRepositoryError, FoundationAdapterError):
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _repository_error(exc, operation) from exc
            return

        assert self._session_factory is not None
        try:
            session = self._session_factory()
            if inspect.isawaitable(session):
                session = await session
            transaction: Any | None = None
            began = False
            begin = getattr(session, "begin", None)
            if callable(begin):
                candidate = begin()
                if inspect.isawaitable(candidate):
                    candidate = await candidate
                if hasattr(candidate, "__aenter__"):
                    transaction = candidate
                    assert transaction is not None
                    await transaction.__aenter__()
                    began = True

            async def commit() -> None:
                if not began:
                    callback = getattr(session, "commit", None)
                    if callable(callback):
                        result = callback()
                        if inspect.isawaitable(result):
                            await result

            try:
                yield session, commit
                if began:
                    assert transaction is not None
                    await transaction.__aexit__(None, None, None)
            except BaseException as exc:
                if began:
                    assert transaction is not None
                    await transaction.__aexit__(type(exc), exc, exc.__traceback__)
                else:
                    rollback = getattr(session, "rollback", None)
                    if callable(rollback):
                        result = rollback()
                        if inspect.isawaitable(result):
                            await result
                raise
        except (AccountAuthorityError, PlatformAccountRepositoryError, FoundationAdapterError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _repository_error(exc, operation) from exc
        finally:
            # A directly injected session belongs to the use-case owner.  A
            # session produced by a factory is owned by this adapter scope and
            # is therefore closed after commit/rollback.
            if self._close_direct_session and "session" in locals():
                close = getattr(session, "close", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    @staticmethod
    async def _execute(
        session: Any,
        statement: Any,
        operation: str,
        *,
        preserve: tuple[type[BaseException], ...] = (),
    ) -> Any:
        try:
            return await session.execute(statement)
        except preserve:
            raise
        except (AccountAuthorityError, PlatformAccountRepositoryError, FoundationAdapterError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _repository_error(exc, operation) from exc


# Explicit aliases keep naming stable for compositions that call the adapter
# an authority/repository while exposing one implementation and one transaction
# boundary.
SQLAlchemyPlatformAccountAuthority = SQLAlchemyPlatformAccountRepository
PlatformAccountRepository = SQLAlchemyPlatformAccountRepository
PostgresPlatformAccountRepository = SQLAlchemyPlatformAccountRepository
PostgresPlatformAccountAuthority = SQLAlchemyPlatformAccountRepository


def _account_clause(
    ref: PlatformAccountRef,
    table: Any = platform_accounts,
) -> tuple[Any, ...]:
    return (
        table.c.tenant_id == ref.tenant_id,
        table.c.platform == ref.platform.value,
        table.c.account_ref == ref.account_ref,
    )


_TERMINAL_FLOW_VALUES = tuple(
    state.value
    for state in (
        LoginFlowState.SUCCEEDED,
        LoginFlowState.EXPIRED,
        LoginFlowState.FAILED,
        LoginFlowState.CANCELLED,
    )
)


def _flow_state_rank(column: Any) -> Any:
    """Return the SQL rank used for non-terminal login flow states."""

    return case(
        (column == LoginFlowState.CREATED.value, 0),
        (column == LoginFlowState.QR_READY.value, 1),
        (column == LoginFlowState.WAITING_SCAN.value, 2),
        (column == LoginFlowState.WAITING_CONFIRMATION.value, 3),
        else_=None,
    )


def _flow_update_clause(statement: Any, ref: PlatformAccountRef) -> Any:
    """Build an atomic monotonic/CAS predicate for ``save_flow`` upserts."""

    current = platform_login_flows.c
    excluded = statement.excluded
    current_terminal = current.state.in_(_TERMINAL_FLOW_VALUES)
    candidate_terminal = excluded.state.in_(_TERMINAL_FLOW_VALUES)
    same_state = current.state == excluded.state

    # A terminal snapshot is immutable.  ``IS NOT DISTINCT FROM`` treats two
    # NULL values as equal, which is the desired idempotence for optional
    # fields such as ``error_message`` and ``qr_expires_at``.
    terminal_payload_same = and_(
        current.qr_object_key.is_not_distinct_from(excluded.qr_object_key),
        current.qr_expires_at.is_not_distinct_from(excluded.qr_expires_at),
        current.provider_subject_id.is_not_distinct_from(excluded.provider_subject_id),
        current.error_code.is_not_distinct_from(excluded.error_code),
        current.error_message.is_not_distinct_from(excluded.error_message),
        current.metadata.is_not_distinct_from(excluded.metadata),
    )

    # Fields are write-once while a flow is active.  A retry carrying an older
    # provider result can therefore not clear the subject marker or QR ref.
    sticky_fields_same = and_(
        or_(current.qr_object_key.is_(None), current.qr_object_key == excluded.qr_object_key),
        or_(current.qr_expires_at.is_(None), current.qr_expires_at == excluded.qr_expires_at),
        or_(
            current.provider_subject_id.is_(None),
            current.provider_subject_id == excluded.provider_subject_id,
        ),
        or_(current.error_code.is_(None), current.error_code == excluded.error_code),
        or_(current.error_message.is_(None), current.error_message == excluded.error_message),
    )

    current_rank = _flow_state_rank(current.state)
    candidate_rank = _flow_state_rank(excluded.state)
    forward_state = and_(
        ~current_terminal,
        or_(
            candidate_terminal,
            and_(
                candidate_rank.is_not(None),
                current_rank.is_not(None),
                candidate_rank > current_rank,
            ),
        ),
    )
    state_allowed = or_(
        and_(same_state, or_(~current_terminal, terminal_payload_same)),
        forward_state,
    )

    return and_(
        current.tenant_id == ref.tenant_id,
        current.platform == ref.platform.value,
        current.account_ref == ref.account_ref,
        # A flow's deadline is part of its durable identity.  Never let a
        # retry silently extend it (or replace its creation timestamp).
        current.created_at == excluded.created_at,
        current.expires_at == excluded.expires_at,
        current.updated_at <= excluded.updated_at,
        state_allowed,
        sticky_fields_same,
    )


def _row_scope(row: Mapping[str, Any]) -> tuple[str, PlatformChannel, str]:
    """Read a composite account identity from a row without exposing payloads."""

    return (
        str(row["tenant_id"]),
        PlatformChannel(str(row["platform"])),
        str(row["account_ref"]),
    )


def _first_row(result: Any) -> Mapping[str, Any] | None:
    if result is None:
        return None
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        mapped = mappings()
        first = getattr(mapped, "first", None)
        if callable(first):
            row = first()
            return _mapping_row(row)
    first = getattr(result, "first", None)
    if callable(first):
        row = first()
        return _mapping_row(row)
    if isinstance(result, Mapping):
        return result
    return None


def _all_rows(result: Any) -> tuple[Mapping[str, Any], ...]:
    if result is None:
        return ()
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        mapped = mappings()
        all_rows = getattr(mapped, "all", None)
        if callable(all_rows):
            values = cast(Iterable[object], all_rows())
            return tuple(row for value in values if (row := _mapping_row(value)) is not None)
    all_rows = getattr(result, "all", None)
    if callable(all_rows):
        values = cast(Iterable[object], all_rows())
        return tuple(row for value in values if (row := _mapping_row(value)) is not None)
    if isinstance(result, (list, tuple)):
        return tuple(row for value in result if (row := _mapping_row(value)) is not None)
    row = _first_row(result)
    return (row,) if row is not None else ()


def _mapping_row(value: object) -> Mapping[str, Any] | None:
    """Normalize SQLAlchemy Row/RowMapping and lightweight test doubles."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    # ``_first_row``/``_all_rows`` request ``Result.mappings()`` before this
    # helper is reached, so production SQLAlchemy rows arrive as the public
    # ``RowMapping`` (which already implements Mapping).  Lightweight doubles
    # may expose a public ``mapping`` view; do not reach through SQLAlchemy's
    # private ``_mapping`` attribute because that bypasses the architecture
    # boundary and makes adapter behavior depend on driver internals.
    mapping = getattr(value, "mapping", None)
    return mapping if isinstance(mapping, Mapping) else None


def _rowcount(result: Any) -> int | None:
    """Return a driver's affected-row count, preserving unknown test doubles."""

    value = getattr(result, "rowcount", None)
    return int(value) if isinstance(value, int) else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("platform account timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _decode_envelope_part(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("session envelope contains invalid base64") from exc
    if not decoded:
        raise ValueError("session envelope part must not be empty")
    return decoded


def _encode_envelope_part(value: object) -> str:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, (bytes, bytearray)) or not value:
        raise ValueError("stored session envelope part is invalid")
    return base64.urlsafe_b64encode(bytes(value)).decode("ascii")


def _account_from_row(row: Mapping[str, Any]) -> PlatformAccount:
    return PlatformAccount(
        tenant_id=str(row["tenant_id"]),
        platform=PlatformChannel(str(row["platform"])),
        account_ref=str(row["account_ref"]),
        alias=str(row["alias"]),
        provider_subject_id=row.get("provider_subject_id"),
        status=PlatformAccountStatus(str(row["status"])),
        health=PlatformAccountHealth(str(row["health"])),
        session_version=int(row.get("session_version") or 0),
        created_at=_as_utc(row["created_at"]),
        updated_at=_as_utc(row["updated_at"]),
    )


def _session_from_row(row: Mapping[str, Any]) -> PlatformAccountSession:
    metadata = row.get("metadata") or {}
    bound_version = metadata.get("bound_version") if isinstance(metadata, Mapping) else None
    envelope = EncryptedSessionEnvelope(
        ciphertext=_encode_envelope_part(row["ciphertext"]),
        nonce=_encode_envelope_part(row["nonce"]),
        auth_tag=_encode_envelope_part(row["auth_tag"]),
        key_ref=str(row["key_ref"]),
        key_version=str(row["key_version"]),
        digest=str(row["payload_digest"]),
        bound_version=bound_version,
    )
    return PlatformAccountSession(
        session_id=str(row["session_id"]),
        account=PlatformAccountRef(
            tenant_id=str(row["tenant_id"]),
            platform=PlatformChannel(str(row["platform"])),
            account_ref=str(row["account_ref"]),
        ),
        version=int(row["version"]),
        envelope=envelope,
        expires_at=_as_utc(row["expires_at"]),
        status=PlatformSessionStatus(str(row["status"])),
        created_at=_as_utc(row["created_at"]),
        superseded_at=_maybe_utc(row.get("superseded_at")),
        revoked_at=_maybe_utc(row.get("revoked_at")),
    )


def _grant_from_row(row: Mapping[str, Any]) -> PlatformAccountGrant:
    permissions = row.get("permissions") or ()
    if isinstance(permissions, str):
        permissions = [permissions]
    return PlatformAccountGrant(
        grant_id=str(row["grant_id"]),
        account=PlatformAccountRef(
            tenant_id=str(row["tenant_id"]),
            platform=PlatformChannel(str(row["platform"])),
            account_ref=str(row["account_ref"]),
        ),
        principal_id=str(row["principal_id"]),
        permissions=tuple(AccountGrantPermission(str(item)) for item in permissions),
        issued_at=_as_utc(row["issued_at"]),
        expires_at=_maybe_utc(row.get("expires_at")),
        revoked_at=_maybe_utc(row.get("revoked_at")),
    )


def _lease_from_row(row: Mapping[str, Any]) -> PlatformAccountLease:
    return PlatformAccountLease(
        lease_id=str(row["lease_id"]),
        account=PlatformAccountRef(
            tenant_id=str(row["tenant_id"]),
            platform=PlatformChannel(str(row["platform"])),
            account_ref=str(row["account_ref"]),
        ),
        task_id=str(row["task_id"]),
        owner_id=str(row["owner_id"]),
        owner_token_digest=str(row["owner_token_digest"]),
        status=PlatformLeaseStatus(str(row["status"])),
        acquired_at=_as_utc(row["acquired_at"]),
        expires_at=_as_utc(row["expires_at"]),
        last_heartbeat_at=_as_utc(row["last_heartbeat_at"]),
        released_at=_maybe_utc(row.get("released_at")),
    )


def _flow_from_row(row: Mapping[str, Any]) -> PlatformLoginFlow:
    metadata = row.get("metadata") or {}
    object_ref = None
    if isinstance(metadata, Mapping) and isinstance(metadata.get("qr_object_ref"), Mapping):
        from xhs_food.contracts import ObjectRef

        object_ref = ObjectRef.model_validate(metadata["qr_object_ref"])
    return PlatformLoginFlow(
        flow_id=str(row["flow_id"]),
        account=PlatformAccountRef(
            tenant_id=str(row["tenant_id"]),
            platform=PlatformChannel(str(row["platform"])),
            account_ref=str(row["account_ref"]),
        ),
        state=LoginFlowState(str(row["state"])),
        created_at=_as_utc(row["created_at"]),
        expires_at=_as_utc(row["expires_at"]),
        updated_at=_as_utc(row["updated_at"]),
        qr_object_ref=object_ref,
        qr_expires_at=_maybe_utc(row.get("qr_expires_at")),
        provider_subject_id=row.get("provider_subject_id"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )


def _maybe_utc(value: object) -> datetime | None:
    return _as_utc(value) if isinstance(value, datetime) else None


def _status_for_health_signal(signal: AccountHealthSignal) -> PlatformAccountStatus | None:
    if signal in {AccountHealthSignal.AUTHENTICATION, AccountHealthSignal.EXPIRED}:
        return PlatformAccountStatus.REAUTH_REQUIRED
    if signal is AccountHealthSignal.CHALLENGE:
        return PlatformAccountStatus.DEGRADED
    if signal in {AccountHealthSignal.THROTTLED, AccountHealthSignal.TRANSIENT}:
        return PlatformAccountStatus.DEGRADED
    if signal is AccountHealthSignal.REVOKED:
        return PlatformAccountStatus.DISABLED
    if signal is AccountHealthSignal.SUCCESS:
        return PlatformAccountStatus.ACTIVE
    return None


def _account_not_found(message: str = "account is not registered") -> AccountNotFoundError:
    return AccountNotFoundError(message)


def _version_conflict(message: str = "session version is stale") -> AccountVersionConflict:
    return AccountVersionConflict(message)


def _lease_conflict(message: str = "account lease is not available") -> AccountLeaseConflict:
    return AccountLeaseConflict(message)


def _repository_error(exc: BaseException, operation: str) -> FoundationAdapterError:
    if _is_schema_not_ready(exc):
        error = foundation_error_from_exception(
            RuntimeError("Alembic platform account schema is not ready"),
            scope=ErrorScope.REPOSITORY,
            operation=operation,
        )
        return PlatformAccountSchemaNotReadyError(
            error.model_copy(
                update={
                    "code": "REPOSITORY_SCHEMA_NOT_READY",
                    "retryable": False,
                    "terminal": True,
                }
            )
        )
    return FoundationAdapterError(
        foundation_error_from_exception(
            exc,
            scope=ErrorScope.REPOSITORY,
            operation=operation,
        )
    )


def _is_schema_not_ready(exc: BaseException) -> bool:
    """Recognize missing Alembic objects without treating a DB outage as schema drift."""

    if isinstance(exc, NoSuchTableError):
        return True
    if not isinstance(exc, (ProgrammingError, OperationalError, DBAPIError)):
        return False
    original = getattr(exc, "orig", exc)
    codes = {
        str(getattr(original, "sqlstate", "") or ""),
        str(getattr(original, "pgcode", "") or ""),
        str(getattr(exc, "sqlstate", "") or ""),
    }
    message = str(original).lower()
    codes.update(code.upper() for code in ("42p01", "42703", "42704", "42883") if code in message)
    # PostgreSQL undefined table/column/object/function.  These are emitted
    # when the account authority revision (or required extension) is absent.
    if codes & {"42P01", "42703", "42704", "42883"}:
        return True
    if "does not exist" in message and any(
        marker in message for marker in ("relation ", "table ", "column ", "undefined ")
    ):
        return True
    return "extension" in message and "not available" in message


__all__ = [
    "PlatformAccountRepository",
    "PlatformAccountRepositoryError",
    "PlatformAccountSchemaNotReadyError",
    "PostgresPlatformAccountAuthority",
    "PostgresPlatformAccountRepository",
    "SQLAlchemyPlatformAccountAuthority",
    "SQLAlchemyPlatformAccountRepository",
]
