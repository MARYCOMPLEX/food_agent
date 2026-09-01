from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user_id
from api.platform import router
from xhs_food.account_services.fixture import create_fixture_app
from xhs_food.contracts import PlatformChannel
from xhs_food.contracts.account_service import (
    AccountServiceConfig,
    McpToolCallResult,
    McpToolDescriptor,
)
from xhs_food.gateways.account_service import HttpAccountServiceClient, McpAccountServiceClient


@pytest.mark.asyncio
async def test_fixture_supports_isolated_qr_flow_and_mcp_discovery() -> None:
    app = create_fixture_app(
        service_id="xhs-fixture",
        channels=(PlatformChannel.XHS_PC, PlatformChannel.XHS_CREATOR),
    )
    transport = httpx.ASGITransport(app=app)
    config = AccountServiceConfig(
        service_id="xhs-fixture",
        base_url="http://fixture.test",
        channels=(PlatformChannel.XHS_PC, PlatformChannel.XHS_CREATOR),
        capabilities=("account.register", "account.read", "account.login", "notes.search", "place.lookup"),
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture.test") as http_client:
        client = HttpAccountServiceClient(config, client=http_client)
        await client.capabilities()
        account = await client.register_account(
            platform=PlatformChannel.XHS_PC,
            account_ref="primary",
            alias="Primary",
            tenant_ref="tenant-a",
        )
        flow = await client.start_qr_login(
            platform=PlatformChannel.XHS_PC,
            account_ref=account.account_ref,
            tenant_ref="tenant-a",
        )
        qr = await client.qr_presentation(flow_id=flow.flow_id, tenant_ref="tenant-a")
        assert qr.object_ref.startswith("fixture://")
        polled = await client.poll_login(flow_id=flow.flow_id, tenant_ref="tenant-a")
        assert polled.state == "succeeded"
        denied = await http_client.get(
            f"/v1/login/{flow.flow_id}/status",
            params={"tenant_ref": "tenant-b"},
        )
        assert denied.status_code == 404

    async with httpx.AsyncClient(transport=transport) as mcp_http:
        mcp_config = config.model_copy(update={"mcp_url": "http://fixture.test/mcp"})
        mcp = McpAccountServiceClient(mcp_config, client=mcp_http)
        tools = await mcp.list_tools()
        assert [item.name for item in tools] == ["notes.search", "account.login"]


def test_platform_api_exposes_allow_listed_mcp_tools_with_tenant_ref() -> None:
    class Registry:
        def tools_for(self, platform: PlatformChannel) -> tuple[McpToolDescriptor, ...]:
            assert platform is PlatformChannel.XHS_PC
            return (McpToolDescriptor(name="notes.search", capability="notes.search"),)

        async def call_tool(
            self,
            *,
            platform: PlatformChannel,
            tool_name: str,
            arguments: dict[str, object],
        ) -> McpToolCallResult:
            assert platform is PlatformChannel.XHS_PC
            assert tool_name == "notes.search"
            assert arguments["tenant_ref"] == "tenant-a"
            return McpToolCallResult(tool_name=tool_name, content={"ok": True})

        async def invoke_for_platform(self, **kwargs: object) -> dict[str, object]:
            assert kwargs["tenant_ref"] == "tenant-a"
            assert kwargs["account_ref"] == "primary"
            return {"items": [], "capability": kwargs["capability"]}

    application = FastAPI()
    application.state.account_service_registry = Registry()
    application.include_router(router)
    application.dependency_overrides[get_current_user_id] = lambda: "tenant-a"
    with TestClient(application) as client:
        catalog = client.get("/v1/platform/account-services/xhs_pc/tools")
        called = client.post(
            "/v1/platform/account-services/xhs_pc/tools/notes.search",
            json={"arguments": {"query": "food"}},
        )
        invoked = client.post(
            "/v1/platform/account-services/xhs_pc/invoke",
            json={
                "account_ref": "primary",
                "capability": "notes.search",
                "correlation_id": "corr-1",
                "query": {"keyword": "food"},
            },
        )
    assert catalog.status_code == 200
    assert catalog.json()["data"][0]["name"] == "notes.search"
    assert called.status_code == 200
    assert called.json()["data"]["tool_name"] == "notes.search"
    assert invoked.status_code == 200
    assert invoked.json()["data"]["capability"] == "notes.search"


def test_platform_api_redacts_secret_shaped_remote_arguments() -> None:
    application = FastAPI()
    application.state.account_service_registry = object()
    application.include_router(router)
    application.dependency_overrides[get_current_user_id] = lambda: "tenant-a"
    with TestClient(application) as client:
        response = client.post(
            "/v1/platform/account-services/xhs_pc/tools/notes.search",
            json={"arguments": {"cookie": "sid=secret"}},
        )
    assert response.status_code == 422
    assert "secret" not in response.text
