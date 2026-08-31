"""Failure and isolation tests for the local platform account authority."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountLeaseRequest,
    LoginFlowState,
    PlatformAccountGrant,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountRef,
    PlatformChannel,
    PlatformLoginFlow,
    SessionActivationRequest,
)
from xhs_food.foundation.platform_accounts import (
    AccountLeaseConflict,
    AccountVersionConflict,
    AesGcmSessionCodec,
    InMemoryKeyProvider,
    InMemoryPlatformAccountAuthority,
    SessionEnvelopeError,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def ref(tenant: str, channel: PlatformChannel, account: str = "same") -> PlatformAccountRef:
    return PlatformAccountRef(tenant_id=tenant, platform=channel, account_ref=account)


async def _authority_with_account(
    account: PlatformAccountRef,
) -> tuple[InMemoryPlatformAccountAuthority, AesGcmSessionCodec]:
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    await authority.register_account(
        tenant_id=account.tenant_id,
        platform=account.platform,
        account_ref=account.account_ref,
        alias="primary",
        now=NOW,
    )
    keys = InMemoryKeyProvider()
    keys.add("test", "v1", b"0" * 32)
    return authority, AesGcmSessionCodec(keys, key_ref="test", key_version="v1")


@pytest.mark.unit
def test_aes_gcm_round_trip_binds_account_and_session_version() -> None:
    async def scenario() -> None:
        account = ref("tenant-a", PlatformChannel.XHS_PC)
        authority, codec = await _authority_with_account(account)
        expiry = NOW + timedelta(hours=1)
        first = await codec.seal(account, b'{"cookie":"fixture"}', expires_at=expiry, version=1)
        session = await authority.activate_session(
            SessionActivationRequest(
                account=account,
                expected_session_version=0,
                envelope=first,
                expires_at=expiry,
                requested_at=NOW,
            )
        )
        assert await codec.open(session) == b'{"cookie":"fixture"}'

        second = await codec.seal(account, b'{"cookie":"rotated"}', expires_at=expiry, version=2)
        session2 = await authority.activate_session(
            SessionActivationRequest(
                account=account,
                expected_session_version=1,
                envelope=second,
                expires_at=expiry,
                requested_at=NOW,
            )
        )
        assert await codec.open(session2) == b'{"cookie":"rotated"}'
        with pytest.raises(AccountVersionConflict):
            await authority.activate_session(
                SessionActivationRequest(
                    account=account,
                    expected_session_version=1,
                    envelope=second,
                    expires_at=expiry,
                    requested_at=NOW,
                )
            )

        # A ciphertext sealed for another account cannot be replayed here.
        other = ref("tenant-a", PlatformChannel.XHS_PC, "other")
        forged = await codec.seal(other, b"payload", expires_at=expiry, version=1)
        with pytest.raises(SessionEnvelopeError):
            await codec.open(session2.model_copy(update={"envelope": forged}))

    asyncio.run(scenario())


@pytest.mark.unit
def test_same_reference_isolated_by_tenant_and_channel_and_lease() -> None:
    async def scenario() -> None:
        authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
        refs = (
            ref("tenant-a", PlatformChannel.XHS_PC),
            ref("tenant-b", PlatformChannel.XHS_PC),
            ref("tenant-a", PlatformChannel.XHS_CREATOR),
        )
        for item in refs:
            await authority.register_account(
                tenant_id=item.tenant_id,
                platform=item.platform,
                account_ref=item.account_ref,
                alias="primary",
                now=NOW,
            )
        leases = await asyncio.gather(
            *(
                authority.acquire(
                    AccountLeaseRequest(
                        account=item,
                        task_id=f"task-{index}",
                        owner_id="worker",
                        ttl_seconds=30,
                    )
                )
                for index, item in enumerate(refs)
            )
        )
        assert len({lease.lease_id for lease in leases}) == 3
        with pytest.raises(AccountLeaseConflict):
            await authority.acquire(
                AccountLeaseRequest(
                    account=refs[0],
                    task_id="contender",
                    owner_id="worker-2",
                    ttl_seconds=30,
                )
            )
        assert await authority.release(leases[0].lease_id)

        assert await authority.get_flow("missing", tenant_id="tenant-b") is None

    asyncio.run(scenario())


@pytest.mark.unit
def test_concurrent_cas_and_lease_contenders_preserve_composite_isolation() -> None:
    async def scenario() -> None:
        authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
        account = ref("tenant-a", PlatformChannel.XHS_PC, "shared-alias")
        sibling_channel = ref("tenant-a", PlatformChannel.DIANPING, "shared-alias")
        sibling_tenant = ref("tenant-b", PlatformChannel.XHS_PC, "shared-alias")
        await asyncio.gather(
            *(
                authority.register_account(
                    tenant_id=item.tenant_id,
                    platform=item.platform,
                    account_ref=item.account_ref,
                    alias="shared",
                    now=NOW,
                )
                for item in (account, sibling_channel, sibling_tenant)
            )
        )
        keys = InMemoryKeyProvider({("test", "v1"): b"k" * 32})
        codec = AesGcmSessionCodec(keys, key_ref="test", key_version="v1")
        expiry = NOW + timedelta(hours=1)
        envelopes = await asyncio.gather(
            codec.seal(account, b'{"cookie":"writer-a"}', expires_at=expiry, version=1),
            codec.seal(account, b'{"cookie":"writer-b"}', expires_at=expiry, version=1),
        )

        writes = await asyncio.gather(
            *(
                authority.activate_session(
                    SessionActivationRequest(
                        account=account,
                        expected_session_version=0,
                        envelope=envelope,
                        expires_at=expiry,
                        requested_at=NOW,
                    )
                )
                for envelope in envelopes
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in writes) == 1
        assert sum(isinstance(item, AccountVersionConflict) for item in writes) == 1
        active = await authority.get_active_session(account)
        assert active is not None and active.version == 1

        contenders = await asyncio.gather(
            *(
                authority.acquire(
                    AccountLeaseRequest(
                        account=account,
                        task_id=f"task-{index}",
                        owner_id=f"worker-{index}",
                        expected_session_version=1,
                    )
                )
                for index in range(2)
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in contenders) == 1
        assert sum(isinstance(item, AccountLeaseConflict) for item in contenders) == 1

        # The same alias in another channel/tenant remains an independent
        # identity, while grant lookup reveals no metadata for either scope.
        independent = await asyncio.gather(
            authority.acquire(
                AccountLeaseRequest(
                    account=sibling_channel,
                    task_id="dp-task",
                    owner_id="dp-worker",
                )
            ),
            authority.acquire(
                AccountLeaseRequest(
                    account=sibling_tenant,
                    task_id="tenant-b-task",
                    owner_id="tenant-b-worker",
                )
            ),
        )
        assert len({item.lease_id for item in independent}) == 2
        denied = await asyncio.gather(
            authority.authorize(account, "unknown", AccountGrantPermission.USE),
            authority.authorize(sibling_tenant, "unknown", AccountGrantPermission.USE),
        )
        assert denied == [None, None]

    asyncio.run(scenario())


@pytest.mark.unit
def test_lease_acquire_enforces_expected_session_version_cas() -> None:
    async def scenario() -> None:
        account = ref("tenant-a", PlatformChannel.XHS_PC)
        authority, codec = await _authority_with_account(account)
        expiry = NOW + timedelta(hours=1)

        # Account registration starts at session version zero.  A caller that
        # supplies a version assertion must not acquire a lease against a
        # different session, even when no lease currently exists.
        with pytest.raises(AccountVersionConflict, match="session version is stale"):
            await authority.acquire(
                AccountLeaseRequest(
                    account=account,
                    task_id="task-stale-before-login",
                    owner_id="worker",
                    expected_session_version=1,
                )
            )

        first_envelope = await codec.seal(
            account,
            b'{"cookie":"v1"}',
            expires_at=expiry,
            version=1,
        )
        await authority.activate_session(
            SessionActivationRequest(
                account=account,
                expected_session_version=0,
                envelope=first_envelope,
                expires_at=expiry,
                requested_at=NOW,
            )
        )
        first_lease = await authority.acquire(
            AccountLeaseRequest(
                account=account,
                task_id="task-v1",
                owner_id="worker",
                expected_session_version=1,
            )
        )
        assert await authority.release(first_lease.lease_id)

        # Rotate the account session.  The old lease assertion must fail, while
        # the current assertion remains valid after the prior lease is released.
        second_envelope = await codec.seal(
            account,
            b'{"cookie":"v2"}',
            expires_at=expiry,
            version=2,
        )
        await authority.activate_session(
            SessionActivationRequest(
                account=account,
                expected_session_version=1,
                envelope=second_envelope,
                expires_at=expiry,
                requested_at=NOW,
            )
        )
        with pytest.raises(AccountVersionConflict, match="session version is stale"):
            await authority.acquire(
                AccountLeaseRequest(
                    account=account,
                    task_id="task-stale-v1",
                    owner_id="worker",
                    expected_session_version=1,
                )
            )
        current_lease = await authority.acquire(
            AccountLeaseRequest(
                account=account,
                task_id="task-v2",
                owner_id="worker",
                expected_session_version=2,
            )
        )
        assert current_lease.status.value == "active"

    asyncio.run(scenario())


@pytest.mark.unit
def test_grant_and_health_boundaries_are_fail_closed() -> None:
    async def scenario() -> None:
        account = ref("tenant-a", PlatformChannel.DIANPING)
        authority, _ = await _authority_with_account(account)
        grant = PlatformAccountGrant(
            grant_id="grant-1",
            account=account,
            principal_id="operator",
            permissions=(AccountGrantPermission.USE,),
            issued_at=NOW,
        )
        await authority.add_grant(grant)
        assert await authority.authorize(account, "operator", AccountGrantPermission.USE)
        assert await authority.authorize(account, "other", AccountGrantPermission.USE) is None
        event = PlatformAccountHealthEvent(
            event_id="health-1",
            account=account,
            signal="authentication",
            health=PlatformAccountHealth.SESSION_INVALID,
            observed_at=NOW,
            reason="provider session expired",
        )
        await authority.record(event)
        updated = await authority.get_account(account)
        assert updated is not None and updated.status.value == "reauth_required"

    asyncio.run(scenario())


@pytest.mark.unit
def test_login_flow_authority_rejects_newer_timestamp_regressions_and_terminal_rewrites() -> None:
    async def scenario() -> None:
        account = ref("tenant-a", PlatformChannel.XHS_PC)
        authority, _ = await _authority_with_account(account)
        flow = PlatformLoginFlow(
            flow_id="flow-authority-1",
            account=account,
            state=LoginFlowState.WAITING_CONFIRMATION,
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            updated_at=NOW,
        )
        await authority.save_flow(flow)

        # A delayed waiting-scan callback must lose even when its timestamp is
        # newer than the durable confirmation snapshot.
        stale_state = flow.model_copy(
            update={
                "state": LoginFlowState.WAITING_SCAN,
                "updated_at": NOW + timedelta(seconds=1),
            }
        )
        with pytest.raises(AccountVersionConflict, match="state transition"):
            await authority.save_flow(stale_state)
        assert await authority.get_flow(flow.flow_id, tenant_id=account.tenant_id) == flow

        succeeded = flow.model_copy(
            update={
                "state": LoginFlowState.SUCCEEDED,
                "provider_subject_id": "subject-1",
                "updated_at": NOW + timedelta(seconds=2),
            }
        )
        await authority.save_flow(succeeded)
        # Re-saving the same terminal snapshot is idempotent, but a different
        # terminal payload or any non-terminal state is rejected.
        await authority.save_flow(succeeded.model_copy(update={"updated_at": NOW + timedelta(seconds=3)}))
        with pytest.raises(AccountVersionConflict, match="terminal login flow"):
            await authority.save_flow(
                succeeded.model_copy(
                    update={
                        "state": LoginFlowState.WAITING_SCAN,
                        "updated_at": NOW + timedelta(seconds=4),
                    }
                )
            )
        with pytest.raises(AccountVersionConflict, match="payload is immutable"):
            await authority.save_flow(
                succeeded.model_copy(
                    update={
                        "provider_subject_id": "subject-2",
                        "updated_at": NOW + timedelta(seconds=4),
                    }
                )
            )

    asyncio.run(scenario())
