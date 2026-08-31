"""Synthetic split-phase tests for the Spider_XHS login bridge."""

from __future__ import annotations

import asyncio

import pytest

from xhs_food.composition.adapters.platform_login import (
    InMemoryXhsLoginFlowStateStore,
    XhsLoginProviderFactory,
)
from xhs_food.contracts import PlatformAccountRef, PlatformChannel
from xhs_food.foundation.platform_login import LoginProviderState

pytestmark = pytest.mark.unit


def _account(channel: PlatformChannel, account_ref: str) -> PlatformAccountRef:
    return PlatformAccountRef(
        tenant_id="tenant-a",
        platform=channel,
        account_ref=account_ref,
    )


class _PcLoginApi:
    def __init__(self, subject: str = "subject-pc") -> None:
        self.subject = subject
        self.cookies = {"a1": "a1-fixture", "web_session": "session-fixture"}
        self.poll_count = 0
        self.closed = False

    def generate_init_cookies(self) -> dict[str, str]:
        return self.cookies

    def ensure_webprofile(self, cookies: object) -> None:
        assert cookies is self.cookies

    def generate_qrcode(self, cookies: object) -> tuple[bool, str, dict[str, object]]:
        assert cookies is self.cookies
        return True, "ok", {
            "qr_id": f"qr-{self.subject}",
            "code": "code-fixture",
            "url": "https://login.example.test/qr/fixture",
        }

    def check_qrcode_status(
        self, qr_id: str, code: str, cookies: object
    ) -> tuple[bool, str, object]:
        assert qr_id.startswith("qr-")
        assert code == "code-fixture"
        assert cookies is self.cookies
        self.poll_count += 1
        if self.poll_count == 1:
            return False, "请扫描二维码", cookies
        return True, "成功", cookies

    def get_user_info(self, cookies: object) -> tuple[bool, dict[str, str], object]:
        return True, {"user_id": self.subject}, cookies

    def send_phone_code(self, phone: str, cookies: object) -> tuple[bool, str, object]:
        assert phone == "+8613800000000"
        return True, "成功", {"cookies": cookies}

    def login_by_phone(
        self, phone: str, code: str, cookies: object
    ) -> tuple[bool, str, dict[str, object]]:
        assert phone == "+8613800000000"
        assert code == "123456"
        return True, "成功", {"cookies": cookies}

    def close(self) -> None:
        self.closed = True


class _CreatorLoginApi(_PcLoginApi):
    def generate_qrcode(self, cookies: object) -> tuple[bool, str, dict[str, object]]:
        return True, "ok", {
            "id": f"qr-{self.subject}",
            "url": "https://creator.example.test/qr/fixture",
        }

    def query_qrcode_status(self, qr_id: str, cookies: object) -> dict[str, object]:
        assert qr_id.startswith("qr-")
        self.poll_count += 1
        return {
            "success": True,
            "message": "ok",
            "data": {
                "status": 2 if self.poll_count == 1 else 1,
                "cookies": cookies,
            },
        }


def test_xhs_pc_qr_state_isolated_and_session_result_is_redacted() -> None:
    async def scenario() -> None:
        store = InMemoryXhsLoginFlowStateStore()
        created: list[_PcLoginApi] = []

        def api_factory(**_: object) -> _PcLoginApi:
            api = _PcLoginApi(subject=f"subject-{len(created)}")
            created.append(api)
            return api

        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_pc",
            login_api_factory=api_factory,
            flow_state_store=store,
        )
        account_a = _account(PlatformChannel.XHS_PC, "account-a")
        account_b = _account(PlatformChannel.XHS_PC, "account-b")
        provider_a = factory(account_a)
        provider_b = factory(account_b)

        challenge = await provider_a.create_qr(account_a, "flow-a")
        assert challenge.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert challenge.content_type == "image/png"
        assert challenge.provider_flow_ref == "qr-subject-0"

        # The second account gets a different state key and client; no mutable
        # signer/cookie state is shared between account namespaces.
        challenge_b = await provider_b.create_qr(account_b, "flow-b")
        assert challenge_b.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(store._values) == 2  # noqa: SLF001 - synthetic isolation assertion
        assert set(store._values) == {
            "xhs-login/tenant-a/xhs_pc/account-a/flow-a",
            "xhs-login/tenant-a/xhs_pc/account-b/flow-b",
        }

        # Recreate the account-scoped provider wrapper to model a worker
        # replacement. Durable flow state resumes without minting a second QR
        # or API client.
        resumed_provider = factory(account_a)
        waiting = await resumed_provider.poll(account_a, "flow-a")
        assert waiting.state is LoginProviderState.WAITING_SCAN
        succeeded = await resumed_provider.poll(account_a, "flow-a")
        assert succeeded.state is LoginProviderState.SUCCEEDED
        assert succeeded.provider_subject_id == "subject-0"
        assert succeeded.session_material is not None
        assert "qr_id" not in str(succeeded.session_material)
        assert "code-fixture" not in str(succeeded.session_material)
        assert await store.load("xhs-login/tenant-a/xhs_pc/account-a/flow-a") is None
        assert created[0].closed is True

    asyncio.run(scenario())


def test_xhs_risk_challenge_is_terminal_redacted_and_cleans_flow_state() -> None:
    async def scenario() -> None:
        class RiskApi(_PcLoginApi):
            def check_qrcode_status(
                self, qr_id: str, code: str, cookies: object
            ) -> tuple[bool, str, object]:
                del qr_id, code
                return False, "406 risk cookie=credential-fixture-never-emit", cookies

        store = InMemoryXhsLoginFlowStateStore()
        api = RiskApi()
        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_pc",
            login_api_factory=lambda **_: api,
            flow_state_store=store,
        )
        account = _account(PlatformChannel.XHS_PC, "risk-account")
        provider = factory(account)
        await provider.create_qr(account, "risk-flow")
        result = await provider.poll(account, "risk-flow")
        assert result.state is LoginProviderState.FAILED
        assert result.error_code == "LOGIN_RISK_CHALLENGE"
        assert "credential-fixture" not in str(result)
        assert await store.load("xhs-login/tenant-a/xhs_pc/risk-account/risk-flow") is None
        assert api.closed is True

    asyncio.run(scenario())


def test_xhs_cancel_destroys_mutable_client_without_activating_session() -> None:
    async def scenario() -> None:
        store = InMemoryXhsLoginFlowStateStore()
        api = _PcLoginApi()
        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_pc",
            login_api_factory=lambda **_: api,
            flow_state_store=store,
        )
        account = _account(PlatformChannel.XHS_PC, "cancel-account")
        provider = factory(account)
        await provider.create_qr(account, "cancel-flow")
        await provider.cancel(account, "cancel-flow")
        assert await store.load("xhs-login/tenant-a/xhs_pc/cancel-account/cancel-flow") is None
        assert api.closed is True
        result = await provider.poll(account, "cancel-flow")
        assert result.state is LoginProviderState.FAILED
        assert result.session_material is None

    asyncio.run(scenario())


def test_xhs_creator_qr_status_and_phone_flow_use_provider_api() -> None:
    async def scenario() -> None:
        store = InMemoryXhsLoginFlowStateStore()
        apis: list[_CreatorLoginApi] = []

        def api_factory(**_: object) -> _CreatorLoginApi:
            api = _CreatorLoginApi(subject="creator-subject")
            apis.append(api)
            return api

        resolver = {
            "phone-ref": {"phone": "+8613800000000"},
            "code-ref": {"code": "123456"},
        }
        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_creator",
            login_api_factory=api_factory,
            credential_resolver=resolver,
            flow_state_store=store,
        )
        account = _account(PlatformChannel.XHS_CREATOR, "creator-account")
        provider = factory(account)

        challenge = await provider.create_qr(account, "creator-flow")
        assert challenge.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert (await provider.poll(account, "creator-flow")).state is LoginProviderState.WAITING_SCAN
        assert (await provider.poll(account, "creator-flow")).state is LoginProviderState.SUCCEEDED

        # A phone submission may be split into send-code and verify-code
        # calls.  The second call reuses the account/flow-local API context.
        waiting = await provider.phone_login(account, "phone-flow", "phone-ref")
        assert waiting.state is LoginProviderState.WAITING_CONFIRMATION
        done = await provider.phone_login(account, "phone-flow", "code-ref")
        assert done.state is LoginProviderState.SUCCEEDED
        assert done.provider_subject_id == "creator-subject"
        assert len(apis) == 2

    asyncio.run(scenario())


def test_cookie_import_uses_opaque_resolver_and_validates_identity() -> None:
    async def scenario() -> None:
        class AuthenticatedApi:
            cookies = {"a1": "a1-fixture", "web_session": "session-fixture"}
            closed = False

            def get_user_me(self) -> tuple[bool, str, dict[str, object]]:
                return True, "ok", {"data": {"user_id": "cookie-subject"}}

            def close(self) -> None:
                self.closed = True

        resolved_refs: list[str] = []

        def resolve(ref: str, **_: object) -> dict[str, str]:
            resolved_refs.append(ref)
            return {"cookie": "a1=a1-fixture; web_session=session-fixture"}

        api = AuthenticatedApi()
        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_pc",
            authenticated_api_factory=lambda **_: api,
            credential_resolver=resolve,
        )
        account = _account(PlatformChannel.XHS_PC, "cookie-account")
        result = await factory(account).cookie_import(account, "cookie-flow", "vault-cookie")
        assert result.state is LoginProviderState.SUCCEEDED
        assert result.provider_subject_id == "cookie-subject"
        assert resolved_refs == ["vault-cookie"]
        assert api.closed is True
        assert result.session_material is not None
        assert "a1-fixture" in str(result.session_material)

    asyncio.run(scenario())


def test_login_factory_rejects_channel_mismatch_and_missing_state() -> None:
    async def scenario() -> None:
        factory = XhsLoginProviderFactory(
            ".",
            channel="xhs_pc",
            login_api_factory=lambda **_: _PcLoginApi(),
        )
        pc = _account(PlatformChannel.XHS_PC, "pc-account")
        creator = _account(PlatformChannel.XHS_CREATOR, "creator-account")
        with pytest.raises(Exception, match="channel"):
            factory(creator)
        provider = factory(pc)
        result = await provider.poll(pc, "missing-flow")
        assert result.state is LoginProviderState.FAILED
        assert result.error_code == "LOGIN_FLOW_STATE_UNAVAILABLE"

    asyncio.run(scenario())
