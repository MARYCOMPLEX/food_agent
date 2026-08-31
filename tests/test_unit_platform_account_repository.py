"""Focused SQLAlchemy platform-account adapter tests.

The tests use a statement-recording unit of work rather than a live database;
the PostgreSQL dialect compilation assertions still exercise composite scope,
CAS predicates, and the no-schema-repair boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.exc import NoSuchTableError

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountHealthSignal,
    AccountLeaseRequest,
    EncryptedSessionEnvelope,
    LoginFlowState,
    PlatformAccount,
    PlatformAccountGrant,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountRef,
    PlatformChannel,
    PlatformLeaseStatus,
    PlatformLoginFlow,
    SessionActivationRequest,
)
from xhs_food.foundation.platform_account_repository import (
    PlatformAccountSchemaNotReadyError,
    SQLAlchemyPlatformAccountRepository,
)
from xhs_food.foundation.platform_accounts import (
    AccountLeaseConflict,
    AccountNotFoundError,
    AccountVersionConflict,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=1)


class Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int | None = None) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> Result:
        return self

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class Unit:
    def __init__(self, results: list[Result] | None = None) -> None:
        self.results = list(results or [])
        self.statements: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> Unit:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def session_for_adapter(self) -> Unit:
        return self

    async def execute(self, statement: Any) -> Result:
        self.statements.append(statement)
        return self.results.pop(0) if self.results else Result(rowcount=1)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def account_ref(tenant: str = "tenant-a", platform: PlatformChannel = PlatformChannel.XHS_PC) -> PlatformAccountRef:
    return PlatformAccountRef(tenant_id=tenant, platform=platform, account_ref="primary")


def account(ref: PlatformAccountRef | None = None) -> PlatformAccount:
    ref = ref or account_ref()
    return PlatformAccount(
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        alias="primary",
        created_at=NOW,
        updated_at=NOW,
    )


def envelope(version: int = 1) -> EncryptedSessionEnvelope:
    return EncryptedSessionEnvelope(
        ciphertext="Y2lwaGVydGV4dA==",
        nonce="bm9uY2U=",
        auth_tag="dGFn",
        key_ref="test-key",
        key_version="v1",
        digest="0" * 64,
        bound_version=version,
    )


@pytest.mark.unit
async def test_save_account_compiles_composite_upsert_and_commits() -> None:
    unit = Unit()
    repository = SQLAlchemyPlatformAccountRepository(lambda: unit)  # type: ignore[arg-type]
    saved = await repository.save_account(account())
    assert saved.alias == "primary"
    assert unit.commits == 1
    sql = str(unit.statements[0].compile(dialect=postgresql_dialect()))
    assert "ON CONFLICT (tenant_id, platform, account_ref)" in sql
    assert "updated_at" in sql


@pytest.mark.unit
async def test_activate_session_uses_locked_cas_and_preserves_stale_conflict() -> None:
    ref = account_ref()
    unit = Unit(
        [
            Result([{"session_version": 0}]),
            Result(rowcount=1),
            Result(rowcount=1),
            Result(rowcount=1),
        ]
    )
    repository = SQLAlchemyPlatformAccountRepository(lambda: unit)  # type: ignore[arg-type]
    session = await repository.activate_session(
        SessionActivationRequest(
            account=ref,
            expected_session_version=0,
            envelope=envelope(1),
            expires_at=EXPIRY,
            requested_at=NOW,
        )
    )
    assert session.version == 1
    assert unit.commits == 1
    assert any("FOR UPDATE" in str(statement.compile(dialect=postgresql_dialect())) for statement in unit.statements)

    stale_unit = Unit([Result([{"session_version": 1}])])
    stale = SQLAlchemyPlatformAccountRepository(lambda: stale_unit)  # type: ignore[arg-type]
    with pytest.raises(AccountVersionConflict):
        await stale.activate_session(
            SessionActivationRequest(
                account=ref,
                expected_session_version=0,
                envelope=envelope(1),
                expires_at=EXPIRY,
                requested_at=NOW,
            )
        )


@pytest.mark.unit
async def test_lease_scope_and_grant_authorization_are_tenant_channel_bound() -> None:
    ref = account_ref()
    unit = Unit(
        [
            Result([{"account_ref": "primary", "session_version": 0}]),
            Result(rowcount=1),
            Result([]),
            Result(rowcount=1),
        ]
    )
    repository = SQLAlchemyPlatformAccountRepository(lambda: unit)  # type: ignore[arg-type]
    lease = await repository.acquire(
        AccountLeaseRequest(account=ref, task_id="task-1", owner_id="worker")
    )
    assert lease.status is PlatformLeaseStatus.ACTIVE
    assert unit.commits == 1
    acquire_sql = str(unit.statements[2].compile(dialect=postgresql_dialect()))
    assert "tenant_id" in acquire_sql and "account_ref" in acquire_sql

    grant = PlatformAccountGrant(
        grant_id="grant-1",
        account=ref,
        principal_id="operator",
        permissions=(AccountGrantPermission.USE,),
        issued_at=NOW,
    )
    # A grant write performs an account lookup and an idempotent upsert.
    grant_unit = Unit([Result([{"account_ref": "primary"}]), Result([]), Result(rowcount=1)])
    grant_repo = SQLAlchemyPlatformAccountRepository(lambda: grant_unit)  # type: ignore[arg-type]
    await grant_repo.add_grant(grant)
    assert grant_unit.commits == 1


@pytest.mark.unit
async def test_missing_schema_is_terminal_and_does_not_attempt_create() -> None:
    class Broken(Unit):
        async def execute(self, statement: Any) -> Result:
            del statement
            raise NoSuchTableError("platform_accounts")

    repository = SQLAlchemyPlatformAccountRepository(lambda: Broken())  # type: ignore[arg-type]
    with pytest.raises(PlatformAccountSchemaNotReadyError) as caught:
        await repository.get_account(account_ref())
    assert caught.value.error.code == "REPOSITORY_SCHEMA_NOT_READY"
    assert caught.value.error.terminal is True


@pytest.mark.unit
async def test_health_event_is_idempotent_and_unknown_account_is_not_created() -> None:
    ref = account_ref(platform=PlatformChannel.DIANPING)
    event = PlatformAccountHealthEvent(
        event_id="health-1",
        account=ref,
        signal=AccountHealthSignal.AUTHENTICATION,
        health=PlatformAccountHealth.SESSION_INVALID,
        observed_at=NOW,
    )
    unknown = Unit([Result([])])
    repository = SQLAlchemyPlatformAccountRepository(lambda: unknown)  # type: ignore[arg-type]
    with pytest.raises(AccountNotFoundError):
        await repository.record(event)

    duplicate = Unit([Result([{"account_ref": "primary", "session_version": 1, "updated_at": NOW}]), Result(rowcount=0)])
    repository = SQLAlchemyPlatformAccountRepository(lambda: duplicate)  # type: ignore[arg-type]
    await repository.record(event)
    assert duplicate.commits == 1
    assert len(duplicate.statements) == 2


@pytest.mark.unit
async def test_active_lease_conflict_is_domain_error() -> None:
    ref = account_ref()
    unit = Unit(
        [
            Result([{"account_ref": "primary", "session_version": 0}]),
            Result(rowcount=0),
            Result([{"lease_id": "existing"}]),
        ]
    )
    repository = SQLAlchemyPlatformAccountRepository(lambda: unit)  # type: ignore[arg-type]
    with pytest.raises(AccountLeaseConflict):
        await repository.acquire(
            AccountLeaseRequest(account=ref, task_id="task-2", owner_id="worker")
        )


@pytest.mark.unit
async def test_login_flow_upsert_contains_monotonic_terminal_cas_predicate() -> None:
    ref = account_ref()
    flow = PlatformLoginFlow(
        flow_id="flow-repository-1",
        account=ref,
        state=LoginFlowState.WAITING_SCAN,
        created_at=NOW,
        expires_at=EXPIRY,
        updated_at=NOW,
    )
    unit = Unit([Result(rowcount=1)])
    repository = SQLAlchemyPlatformAccountRepository(lambda: unit)  # type: ignore[arg-type]
    await repository.save_flow(flow)
    sql = str(unit.statements[0].compile(dialect=postgresql_dialect()))
    assert "updated_at <=" in sql
    assert "created_at =" in sql and "expires_at =" in sql
    assert "state NOT IN" in sql
    assert "IS NOT DISTINCT FROM" in sql

    # PostgreSQL reports zero affected rows when the monotonic predicate loses
    # to a newer/terminal snapshot; the adapter translates that CAS miss into
    # the stable domain conflict.
    stale_unit = Unit([Result(rowcount=0)])
    stale_repository = SQLAlchemyPlatformAccountRepository(lambda: stale_unit)  # type: ignore[arg-type]
    with pytest.raises(AccountVersionConflict, match="login flow is stale"):
        await stale_repository.save_flow(flow)
