from __future__ import annotations

import httpx
import pytest

from xhs_food.contracts import PlatformChannel
from xhs_food.contracts.account_service import (
    MCP_PROTOCOL_VERSION,
    AccountServiceConfig,
    McpToolDescriptor,
    RemoteErrorCategory,
    RemoteSideEffect,
)
from xhs_food.gateways.account_service import McpAccountServiceClient, RemoteAccountServiceError


def _config() -> AccountServiceConfig:
    return AccountServiceConfig(
        service_id="xhs-account",
        base_url="http://account.test",
        protocol="mcp",
        mcp_url="http://account.test/mcp",
        channels=(PlatformChannel.XHS_PC,),
        capabilities=("notes.search", "account.login"),
    )


@pytest.mark.asyncio
async def test_mcp_negotiates_session_filters_tools_and_sanitizes_results() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        payload = httpx._models.jsonlib.loads(body)
        calls.append(payload)
        method = payload["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-1"},
                json={"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": "2025-06-18"}},
            )
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {"name": "notes.search", "capability": "notes.search", "inputSchema": {}, "side_effect": "read_only"},
                            {"name": "account.login", "capability": "account.login", "inputSchema": {}, "side_effect": "account_login"},
                            {"name": "provider.publish", "capability": "provider.publish", "inputSchema": {}, "side_effect": "publish"},
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "fallback"}],
                    "structuredContent": {"ok": True, "cookie": "sid=secret"},
                    "isError": False,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as transport_client:
        client = McpAccountServiceClient(_config(), client=transport_client)
        tools = await client.list_tools()
        result = await client.call_tool("notes.search", {"query": "z贡"})
        assert [tool.name for tool in tools] == ["notes.search", "account.login"]
        assert result.content == {"ok": True}

    assert calls[1]["method"] == "tools/list"


@pytest.mark.asyncio
async def test_mcp_rejects_unknown_tools_and_secret_arguments_before_transport() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = httpx._models.jsonlib.loads(request.read())
        calls.append(payload["method"])
        if payload["method"] == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"protocolVersion": MCP_PROTOCOL_VERSION},
                },
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [{"name": "notes.search", "capability": "notes.search"}]}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as transport_client:
        client = McpAccountServiceClient(_config(), client=transport_client)
        await client.list_tools()
        with pytest.raises(RemoteAccountServiceError) as unknown:
            await client.call_tool("provider.publish")
        assert unknown.value.category is RemoteErrorCategory.AUTHORIZATION
        with pytest.raises(RemoteAccountServiceError) as secret:
            await client.call_tool("notes.search", {"cookie": "secret"})
        assert secret.value.category is RemoteErrorCategory.INVALID

        approved = McpToolDescriptor(
            name="notes.search",
            capability="notes.search",
            side_effect=RemoteSideEffect.PUBLISH,
        )
        with pytest.raises(RemoteAccountServiceError) as pinned:
            await client.call_tool("notes.search", approved_descriptor=approved)
        assert pinned.value.category is RemoteErrorCategory.AUTHORIZATION
        assert calls == ["initialize", "tools/list"]
