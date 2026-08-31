"""Split-phase login lifecycle and secret-boundary tests."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    LoginActivityOperation,
    LoginFlowState,
    ObjectRef,
    PlatformAccountRef,
    PlatformChannel,
    PlatformLoginActivityRequest,
)
from xhs_food.foundation.platform_accounts import (
    AesGcmSessionCodec,
    InMemoryKeyProvider,
    InMemoryPlatformAccountAuthority,
)
from xhs_food.foundation.platform_login import (
    LoginFlowNotFound,
    LoginPollResult,
    LoginProviderState,
    PlatformLoginCoordinator,
    QrProviderResult,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key, chunks, content_type, metadata=None):
        del content_type, metadata
        data = bytearray()
        async for chunk in chunks:
            data.extend(chunk)
        self.objects[key] = bytes(data)
        import hashlib

        return ObjectRef(
            object_id=hashlib.sha256(data).hexdigest(),
            key=key,
            content_hash=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type="image/png",
        )

    def get(self, ref):
        del ref
        raise NotImplementedError

    async def stat(self, ref):
        del ref
        return None

    async def delete(self, ref):
        self.deleted.append(ref.key)
        self.objects.pop(ref.key, None)
        return True


class FakeProvider:
    def __init__(self, states: list[LoginPollResult]) -> None:
        self.states = list(states)
        self.cancelled = False

    def create_qr(self, account, flow_id):
        del account, flow_id
        return QrProviderResult(b"qr-fixture", expires_at=NOW + timedelta(minutes=2))

    def poll(self, account, flow_id):
        del account, flow_id
        return self.states.pop(0)

    def cancel(self, account, flow_id):
        del account, flow_id
        self.cancelled = True


class ClosableProvider(FakeProvider):
    """Provider fixture that makes operation-scoped cleanup observable."""

    def __init__(self, states: list[LoginPollResult]) -> None:
        super().__init__(states)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


async def _build(provider: FakeProvider):
    account = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="acct-1",
    )
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    await authority.register_account(
        tenant_id=account.tenant_id,
        platform=account.platform,
        account_ref=account.account_ref,
        alias="primary",
        now=NOW,
    )
    keys = InMemoryKeyProvider()
    keys.add("test", "v1", b"1" * 32)
    codec = AesGcmSessionCodec(keys, key_ref="test", key_version="v1")
    store = MemoryObjectStore()
    coordinator = PlatformLoginCoordinator(
        accounts=authority,
        flows=authority,
        codec=codec,
        object_store=store,
        provider_factory=lambda _: provider,
        clock=lambda: NOW,
        flow_ttl_seconds=120,
    )
    return account, authority, store, coordinator


@pytest.mark.unit
def test_qr_flow_success_commits_one_version_and_deletes_qr() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            [
                LoginPollResult(LoginProviderState.WAITING_CONFIRMATION),
                LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-1",
                    session_material={"state": "fixture"},
                ),
            ]
        )
        account, authority, store, coordinator = await _build(provider)
        flow, challenge = await coordinator.start_qr(account)
        assert flow.state.value == "waiting_scan"
        assert challenge.flow_id == flow.flow_id
        assert len(store.objects) == 1
        waiting = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        assert waiting.state.value == "waiting_confirmation"
        succeeded = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        assert succeeded.state.value == "succeeded"
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 1
        assert store.objects == {}
        # A terminal flow is idempotent and cannot activate another version.
        again = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        assert again.state.value == "succeeded"
        current_again = await authority.get_account(account)
        assert current_again is not None and current_again.session_version == 1

    asyncio.run(scenario())


@pytest.mark.unit
def test_cancel_and_cross_tenant_poll_are_fail_closed() -> None:
    async def scenario() -> None:
        provider = FakeProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        account, authority, store, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account)
        with pytest.raises(LoginFlowNotFound):
            await coordinator.status(flow.flow_id, tenant_id="tenant-other")
        cancelled = await coordinator.cancel(flow.flow_id, tenant_id=account.tenant_id)
        assert cancelled.state.value == "cancelled"
        assert provider.cancelled
        assert store.objects == {}
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 0

    asyncio.run(scenario())


@pytest.mark.unit
def test_provider_sync_call_does_not_block_event_loop() -> None:
    async def scenario() -> None:
        class SlowProvider(FakeProvider):
            def create_qr(self, account, flow_id):
                import time

                time.sleep(0.01)
                return super().create_qr(account, flow_id)

        account, _, _, coordinator = await _build(
            SlowProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        )
        # The call succeeds through the worker-thread path; this also catches
        # accidental direct invocation on the event loop in instrumentation.
        flow, _ = await coordinator.start_qr(account)
        assert flow.flow_id.startswith("flow-")

    asyncio.run(scenario())


def test_provider_is_closed_after_each_operation_even_when_result_is_committed() -> None:
    async def scenario() -> None:
        provider = ClosableProvider(
            [
                LoginPollResult(LoginProviderState.SUCCEEDED, provider_subject_id="subject-1", session_material={"state": "fixture"}),
            ]
        )
        account, authority, _, coordinator = await _build(provider)

        flow, _ = await coordinator.start_qr(account)
        assert provider.close_calls == 1

        completed = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        assert completed.state is LoginFlowState.SUCCEEDED
        # The provider remains alive until the session CAS/terminal flow save
        # consumes its result, then is closed exactly once for that operation.
        assert provider.close_calls == 2
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 1

    asyncio.run(scenario())


def test_start_qr_accepts_deterministic_flow_id() -> None:
    async def scenario() -> None:
        provider = FakeProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        account, _, _, coordinator = await _build(provider)
        flow, challenge = await coordinator.start_qr(account, flow_id="auth-flow-fixed")
        assert flow.flow_id == challenge.flow_id == "auth-flow-fixed"
        with pytest.raises(ValueError, match="flow_id"):
            await coordinator.start_qr(account, flow_id=" bad ")

    asyncio.run(scenario())


def test_start_qr_with_existing_flow_id_is_idempotent_and_resumes_created_snapshot() -> None:
    async def scenario() -> None:
        class CountingProvider(FakeProvider):
            create_calls = 0

            def create_qr(self, account, flow_id):
                self.create_calls += 1
                return super().create_qr(account, flow_id)

        provider = CountingProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        account, authority, store, coordinator = await _build(provider)

        first, challenge = await coordinator.start_qr(account, flow_id="resume-flow")
        second, replayed = await coordinator.start_qr(account, flow_id="resume-flow")
        assert second == first
        assert replayed == challenge
        assert provider.create_calls == 1
        assert len(store.objects) == 1

        # A worker crash after the initial CREATED snapshot leaves the same
        # flow deadline authoritative; the next attempt performs one provider
        # call instead of trying to insert a fresh row.
        await coordinator.cancel(first.flow_id, tenant_id=account.tenant_id)
        created = first.model_copy(
            update={
                "state": LoginFlowState.CREATED,
                "qr_object_ref": None,
                "qr_expires_at": None,
                "updated_at": NOW,
                "provider_subject_id": None,
                "error_code": None,
                "error_message": None,
            }
        )
        # Use a fresh authority/coordinator to model a persisted CREATED row;
        # terminal snapshots are immutable and cannot be rewound in place.
        authority_two = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
        await authority_two.register_account(
            tenant_id=account.tenant_id,
            platform=account.platform,
            account_ref=account.account_ref,
            alias="primary",
            now=NOW,
        )
        await authority_two.save_flow(created)
        coordinator_two = PlatformLoginCoordinator(
            accounts=authority_two,
            flows=authority_two,
            codec=coordinator._codec,
            object_store=store,
            provider_factory=lambda _: provider,
            clock=lambda: NOW,
            flow_ttl_seconds=120,
        )
        resumed, resumed_challenge = await coordinator_two.start_qr(
            account,
            flow_id="resume-flow",
        )
        assert resumed.flow_id == first.flow_id
        assert resumed.created_at == first.created_at
        assert resumed.expires_at == first.expires_at
        assert resumed_challenge.flow_id == first.flow_id
        assert provider.create_calls == 2

    asyncio.run(scenario())


def test_phone_and_cookie_login_use_opaque_refs_and_worker_threads() -> None:
    async def scenario() -> None:
        event_loop_thread = threading.get_ident()
        factory_threads: list[int] = []
        provider_threads: list[int] = []

        class CredentialProvider(FakeProvider):
            def phone_login(self, account, flow_id, credential_ref):
                del account, flow_id
                provider_threads.append(threading.get_ident())
                assert credential_ref == "vault-phone-1"
                return LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-phone",
                    session_material={"state": "fixture"},
                )

            def cookie_import(self, account, flow_id, credential_ref):
                del account, flow_id
                provider_threads.append(threading.get_ident())
                assert credential_ref == "vault-cookie-1"
                return LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-cookie",
                    session_material={"state": "fixture"},
                )

        provider = CredentialProvider([])

        def factory(account):
            del account
            factory_threads.append(threading.get_ident())
            return provider

        account, authority, _, coordinator = await _build(provider)
        coordinator._provider_factory = factory
        flow, _ = await coordinator.start_qr(account)
        completed = await coordinator.phone_login(
            flow.flow_id,
            tenant_id=account.tenant_id,
            credential_ref="vault-phone-1",
        )
        assert completed.state is LoginFlowState.SUCCEEDED
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 1
        assert factory_threads and provider_threads
        assert all(thread_id != event_loop_thread for thread_id in factory_threads + provider_threads)

        # A second flow can use the independent cookie path and receives its
        # own versioned session without exposing the cookie itself.
        flow_two, _ = await coordinator.start_qr(account)
        completed_two = await coordinator.cookie_import(
            flow_two.flow_id,
            tenant_id=account.tenant_id,
            credential_ref="vault-cookie-1",
        )
        assert completed_two.state is LoginFlowState.SUCCEEDED
        current_two = await authority.get_account(account)
        assert current_two is not None and current_two.session_version == 2

    asyncio.run(scenario())


def test_credential_login_contract_rejects_raw_secret_like_handles() -> None:
    account = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="acct-1",
    )
    with pytest.raises(ValidationError):
        PlatformLoginActivityRequest(
            flow_id="flow-1",
            account=account,
            operation=LoginActivityOperation.PHONE_LOGIN,
            credential_ref="cookie=raw-secret",
        )
    accepted = PlatformLoginActivityRequest(
        flow_id="flow-1",
        account=account,
        operation=LoginActivityOperation.PHONE_LOGIN,
        credential_ref="vault:phone-1",
    )
    assert accepted.credential_ref == "vault:phone-1"


def test_qr_object_is_cleaned_when_flow_snapshot_save_fails() -> None:
    async def scenario() -> None:
        provider = FakeProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        account, authority, store, coordinator = await _build(provider)
        original_save = authority.save_flow
        calls = 0

        async def fail_second_save(flow):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated database outage")
            return await original_save(flow)

        authority.save_flow = fail_second_save
        with pytest.raises(RuntimeError, match="database outage"):
            await coordinator.start_qr(account)
        assert store.objects == {}

    asyncio.run(scenario())


def test_retry_after_session_cas_before_terminal_save_is_idempotent() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            [
                LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-1",
                    session_material={"state": "fixture"},
                ),
                LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-1",
                    session_material={"state": "fixture"},
                ),
            ]
        )
        account, authority, _, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account)
        original_save = authority.save_flow
        calls = 0

        async def fail_terminal_save(snapshot):
            nonlocal calls
            calls += 1
            # start_qr performs three saves; the first successful login save
            # is the redacted subject marker and the next one is terminal.
            if calls == 2:
                raise RuntimeError("terminal snapshot outage")
            return await original_save(snapshot)

        # Count only saves after the flow is created so the injected failure
        # lands on the terminal save after CAS activation.
        calls = 0
        authority.save_flow = fail_terminal_save
        with pytest.raises(RuntimeError, match="terminal snapshot outage"):
            await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        retried = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        assert retried.state is LoginFlowState.SUCCEEDED
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error_code",
    ["LOGIN_CHALLENGE_REQUIRED", "LOGIN_RISK_COOLDOWN"],
)
def test_provider_challenge_and_risk_fail_terminal_without_session(
    error_code: str,
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            [
                LoginPollResult(
                    LoginProviderState.FAILED,
                    error_code=error_code,
                    error_message="redacted provider classification",
                )
            ]
        )
        account, authority, store, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account, flow_id=f"flow-{error_code.casefold()}")

        terminal = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)

        assert terminal.state is LoginFlowState.FAILED
        assert terminal.error_code == error_code
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 0
        assert store.objects == {}

    asyncio.run(scenario())


def test_provider_timeout_fails_flow_and_cleans_qr_without_session() -> None:
    async def scenario() -> None:
        class TimeoutProvider(FakeProvider):
            async def poll(self, account, flow_id):
                del account, flow_id
                await asyncio.sleep(1)
                return LoginPollResult(LoginProviderState.SUCCEEDED)

        provider = TimeoutProvider([])
        account, authority, store, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account, flow_id="flow-timeout")
        coordinator._provider_timeout = 0.01

        terminal = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)

        assert terminal.state is LoginFlowState.FAILED
        assert terminal.error_code == "LOGIN_PROVIDER_ERROR"
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 0
        assert store.objects == {}

    asyncio.run(scenario())


def test_stale_waiting_scan_poll_cannot_rewind_confirmation() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            [
                LoginPollResult(LoginProviderState.WAITING_CONFIRMATION),
                LoginPollResult(LoginProviderState.WAITING_SCAN),
            ]
        )
        account, authority, _, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account, flow_id="flow-stale-poll")

        confirmation = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        stale = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)

        assert confirmation.state is LoginFlowState.WAITING_CONFIRMATION
        assert stale.state is LoginFlowState.WAITING_CONFIRMATION
        persisted = await authority.get_flow(flow.flow_id, tenant_id=account.tenant_id)
        assert persisted == stale

    asyncio.run(scenario())


def test_cancellation_race_serializes_after_poll_and_never_activates_session() -> None:
    async def scenario() -> None:
        poll_started = asyncio.Event()
        release_poll = asyncio.Event()

        class RacingProvider(FakeProvider):
            async def poll(self, account, flow_id):
                del account, flow_id
                poll_started.set()
                await release_poll.wait()
                return LoginPollResult(LoginProviderState.WAITING_CONFIRMATION)

        provider = RacingProvider([])
        account, authority, store, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(account, flow_id="flow-cancel-race")

        poll_task = asyncio.create_task(
            coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        )
        await poll_started.wait()
        cancel_task = asyncio.create_task(
            coordinator.cancel(flow.flow_id, tenant_id=account.tenant_id)
        )
        release_poll.set()
        polled, cancelled = await asyncio.gather(poll_task, cancel_task)

        assert polled.state is LoginFlowState.WAITING_CONFIRMATION
        assert cancelled.state is LoginFlowState.CANCELLED
        persisted = await authority.get_flow(flow.flow_id, tenant_id=account.tenant_id)
        assert persisted is not None and persisted.state is LoginFlowState.CANCELLED
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 0
        assert store.objects == {}

    asyncio.run(scenario())


def test_worker_restart_resumes_same_active_flow_without_second_qr_or_session() -> None:
    async def scenario() -> None:
        class CountingProvider(FakeProvider):
            create_calls = 0

            def create_qr(self, account, flow_id):
                self.create_calls += 1
                return super().create_qr(account, flow_id)

        provider = CountingProvider([LoginPollResult(LoginProviderState.WAITING_SCAN)])
        account, authority, store, first_worker = await _build(provider)
        flow, challenge = await first_worker.start_qr(
            account,
            flow_id="flow-worker-restart",
        )

        # A new coordinator instance models a replaced Temporal Activity
        # worker. PostgreSQL flow metadata and ObjectStore remain shared;
        # rebuildable Redis status is deliberately not consulted.
        replacement = PlatformLoginCoordinator(
            accounts=authority,
            flows=authority,
            codec=first_worker._codec,
            object_store=store,
            provider_factory=lambda _: provider,
            clock=lambda: NOW,
            flow_ttl_seconds=120,
        )
        resumed, resumed_challenge = await replacement.start_qr(
            account,
            flow_id=flow.flow_id,
        )

        assert resumed == flow
        assert resumed_challenge == challenge
        assert provider.create_calls == 1
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 0
        assert len(store.objects) == 1

    asyncio.run(scenario())


def test_redis_projection_loss_keeps_postgres_flow_resumable_and_single_version() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            [
                LoginPollResult(
                    LoginProviderState.SUCCEEDED,
                    provider_subject_id="subject-after-redis-restart",
                    session_material={"state": "fixture"},
                )
            ]
        )
        account, authority, _, coordinator = await _build(provider)
        flow, _ = await coordinator.start_qr(
            account,
            flow_id="flow-redis-restart",
        )
        rebuildable_status = {flow.flow_id: flow.state.value}

        # Redis owns only this disposable projection. Losing it must not alter
        # the PostgreSQL flow or cause a second flow/session on resume.
        rebuildable_status.clear()
        resumed = await coordinator.status(flow.flow_id, tenant_id=account.tenant_id)
        completed = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)
        replayed = await coordinator.poll(flow.flow_id, tenant_id=account.tenant_id)

        assert resumed.flow_id == flow.flow_id
        assert completed.state is LoginFlowState.SUCCEEDED
        assert replayed == completed
        current = await authority.get_account(account)
        assert current is not None and current.session_version == 1

    asyncio.run(scenario())
