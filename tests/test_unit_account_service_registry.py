from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from xhs_food.composition.account_services import (
    AccountServiceRegistry,
    AccountServiceRegistryError,
    RemoteAccountServiceFacade,
    build_account_service_registry,
)
from xhs_food.contracts import PlatformChannel
from xhs_food.contracts.account_service import (
    AccountServiceConfig,
    AccountServiceDescriptor,
    McpToolDescriptor,
    RemoteAccountProjection,
    RemoteLoginFlowProjection,
    RemoteQrPresentation,
)


def _config(service_id: str, channel: PlatformChannel) -> AccountServiceConfig:
    return AccountServiceConfig(
        service_id=service_id,
        base_url=f"http://{service_id}.test",
        channels=(channel,),
        capabilities=("account.register", "account.read", "account.login", "notes.search"),
    )


class _FakeClient:
    def __init__(self, config: AccountServiceConfig) -> None:
        self.config = config
        self.closed = 0
        self.descriptor = AccountServiceDescriptor(
            service_id=config.service_id,
            service_version="fixture-v1",
            protocol=config.protocol,
            platform_channels=config.channels,
            capabilities=config.capabilities,
            login_modes=("qr",),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.flow = RemoteLoginFlowProjection(
            service_id=config.service_id,
            platform=config.channels[0],
            account_ref="primary",
            flow_id=f"{config.service_id}-flow-1",
            state="qr_ready",
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            updated_at=datetime.now(UTC),
        )

    async def capabilities(self) -> AccountServiceDescriptor:
        return self.descriptor

    async def register_account(self, **_: Any) -> RemoteAccountProjection:
        return RemoteAccountProjection(
            service_id=self.config.service_id,
            platform=self.config.channels[0],
            account_ref="primary",
            alias="Primary",
            status="pending_login",
            health="unknown",
        )

    async def account(self, **_: Any) -> RemoteAccountProjection:
        return await self.register_account()

    async def start_qr_login(self, **_: Any) -> RemoteLoginFlowProjection:
        return self.flow

    async def start_login(self, **_: Any) -> RemoteLoginFlowProjection:
        return self.flow

    async def flow_status(self, **_: Any) -> RemoteLoginFlowProjection:
        return self.flow

    async def qr_presentation(self, **_: Any) -> RemoteQrPresentation:
        return RemoteQrPresentation(
            service_id=self.config.service_id,
            flow_id=self.flow.flow_id,
            object_ref=f"fixture://{self.flow.flow_id}",
            expires_at=self.flow.expires_at,
        )

    async def poll_login(self, **_: Any) -> RemoteLoginFlowProjection:
        return self.flow

    async def cancel_login(self, **_: Any) -> RemoteLoginFlowProjection:
        return self.flow

    async def invoke(self, request: object) -> object:
        return {"capability": getattr(request, "capability", "unknown")}

    async def aclose(self) -> None:
        self.closed += 1


class _FakeMcp:
    def __init__(self, config: AccountServiceConfig) -> None:
        self.config = config
        self.closed = 0

    async def list_tools(self) -> tuple[McpToolDescriptor, ...]:
        return (McpToolDescriptor(name="notes.search", capability="notes.search"),)

    async def call_tool(self, name: str, arguments: object = None) -> object:
        del arguments
        return {"tool_name": name}

    async def aclose(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_registry_isolates_channels_refreshes_tools_and_closes_clients() -> None:
    http_clients: dict[str, _FakeClient] = {}
    mcp_clients: dict[str, _FakeMcp] = {}

    def http_factory(config: AccountServiceConfig) -> _FakeClient:
        client = _FakeClient(config)
        http_clients[config.service_id] = client
        return client

    def mcp_factory(config: AccountServiceConfig) -> _FakeMcp:
        client = _FakeMcp(config)
        mcp_clients[config.service_id] = client
        return client

    registry = AccountServiceRegistry(
        (
            _config("xhs-account", PlatformChannel.XHS_PC),
            _config("dianping-account", PlatformChannel.DIANPING),
        ),
        http_client_factory=http_factory,
        mcp_client_factory=mcp_factory,
    )
    health = await registry.refresh()
    assert health["xhs-account"].state == "ready"
    assert health["dianping-account"].state == "ready"
    assert [tool.name for tool in registry.tools_for(PlatformChannel.XHS_PC)] == ["notes.search"]
    flow = await registry.start_qr_login(
        platform=PlatformChannel.XHS_PC,
        account_ref="primary",
        tenant_ref="tenant-a",
    )
    assert registry.flow_platform(flow.flow_id) is PlatformChannel.XHS_PC
    assert registry.readiness()["ready"] is True
    await registry.aclose()
    await registry.aclose()
    assert http_clients["xhs-account"].closed == 1
    assert http_clients["dianping-account"].closed == 1
    assert mcp_clients["xhs-account"].closed == 1
    assert mcp_clients["dianping-account"].closed == 1


def test_registry_rejects_duplicate_channel_ownership() -> None:
    with pytest.raises(AccountServiceRegistryError, match="claimed by both"):
        AccountServiceRegistry(
            (_config("one", PlatformChannel.XHS_PC), _config("two", PlatformChannel.XHS_PC))
        )


def test_registry_parses_configuration_and_rejects_embedded_service_credentials() -> None:
    registry = build_account_service_registry(
        type(
            "Settings",
            (),
            {
                "account_services_json": (
                    '[{"service_id":"xhs-account","base_url":"http://account.test",'
                    '"channels":["xhs_pc"],"capabilities":["account.login"]}]'
                ),
                "account_services_file": None,
            },
        )()
    )
    assert registry is not None
    assert registry.configs[0].service_id == "xhs-account"
    with pytest.raises(AccountServiceRegistryError):
        build_account_service_registry(
            type(
                "Settings",
                (),
                {
                    "account_services_json": (
                        '[{"service_id":"xhs-account","base_url":"http://user:secret@account.test",'
                        '"channels":["xhs_pc"]}]'
                    ),
                    "account_services_file": None,
                },
            )()
        )


@pytest.mark.asyncio
async def test_registry_keeps_http_healthy_when_mcp_discovery_is_down() -> None:
    class FailingMcp(_FakeMcp):
        async def list_tools(self) -> tuple[McpToolDescriptor, ...]:
            from xhs_food.contracts.account_service import RemoteErrorCategory
            from xhs_food.gateways.account_service import RemoteAccountServiceError

            raise RemoteAccountServiceError(
                RemoteErrorCategory.DEPENDENCY_UNAVAILABLE,
                "mcp unavailable",
                service_id=self.config.service_id,
            )

    registry = AccountServiceRegistry(
        (_config("xhs-account", PlatformChannel.XHS_PC),),
        http_client_factory=_FakeClient,
        mcp_client_factory=FailingMcp,
    )
    health = await registry.refresh()
    assert health["xhs-account"].state == "ready"
    assert registry.readiness()["services"][0]["mcp_state"] == "degraded"
    await registry.aclose()


@pytest.mark.asyncio
async def test_remote_platform_adapter_translates_existing_login_shape() -> None:
    registry = AccountServiceRegistry(
        (_config("xhs-account", PlatformChannel.XHS_PC),),
        http_client_factory=_FakeClient,
        mcp_client_factory=_FakeMcp,
    )
    await registry.refresh()
    adapter = RemoteAccountServiceFacade(registry)
    account = await adapter.register_account(
        tenant_id="tenant-a",
        principal_id="principal-a",
        platform="xhs_pc",
        account_ref="primary",
        alias="Primary",
    )
    assert account.account_ref == "primary"
    submission = await adapter.start_login(
        tenant_id="tenant-a",
        principal_id="principal-a",
        platform="xhs_pc",
        account_ref="primary",
        mode="qr",
    )
    assert submission.flow.flow_id.startswith("xhs-account-flow")
    qr = await adapter.get_qr(
        tenant_id="tenant-a",
        principal_id="principal-a",
        flow_id=submission.flow.flow_id,
    )
    assert qr.presentation_ref.startswith("fixture://")
    await registry.aclose()
