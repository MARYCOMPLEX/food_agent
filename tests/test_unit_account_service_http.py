from __future__ import annotations

import json

import httpx
import pytest

from xhs_food.contracts import PlatformChannel
from xhs_food.contracts.account_service import AccountServiceConfig, RemoteErrorCategory
from xhs_food.gateways.account_service import HttpAccountServiceClient, RemoteAccountServiceError


def _config() -> AccountServiceConfig:
    return AccountServiceConfig(
        service_id="xhs-account",
        base_url="http://account.test",
        protocol="http",
        channels=(PlatformChannel.XHS_PC,),
        capabilities=("account.register", "account.read", "account.login", "notes.search"),
    )


def _descriptor() -> dict[str, object]:
    return {
        "service_id": "xhs-account",
        "service_version": "fixture-v1",
        "contract_version": "account-service/v1",
        "protocol": "http",
        "platform_channels": ["xhs_pc"],
        "capabilities": ["account.register", "account.read", "account.login", "notes.search"],
        "login_modes": ["qr", "credential"],
        "expires_at": "2030-01-01T00:00:00Z",
        "refreshed_at": "2029-12-31T23:55:00Z",
    }


def _account() -> dict[str, object]:
    return {
        "service_id": "xhs-account",
        "platform": "xhs_pc",
        "account_ref": "primary",
        "alias": "Primary",
        "status": "pending_login",
        "health": "unknown",
        "session_version": None,
        "provider_subject_ref": None,
    }


@pytest.mark.asyncio
async def test_http_client_propagates_tenant_and_idempotency_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"success": True, "data": _descriptor()})
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json={"success": True, "data": _account()})
        if request.url.path == "/v1/accounts/xhs_pc/primary":
            assert request.url.params["tenant_ref"] == "tenant-a"
            return httpx.Response(200, json={"success": True, "data": _account()})
        if request.url.path.endswith("/login/qr"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "service_id": "xhs-account",
                        "platform": "xhs_pc",
                        "account_ref": "primary",
                        "flow_id": "flow-1",
                        "state": "qr_ready",
                        "created_at": "2029-01-01T00:00:00Z",
                        "expires_at": "2029-01-01T00:05:00Z",
                        "updated_at": "2029-01-01T00:00:00Z",
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://account.test") as transport_client:
        client = HttpAccountServiceClient(_config(), client=transport_client)
        await client.capabilities()
        await client.register_account(
            platform=PlatformChannel.XHS_PC,
            account_ref="primary",
            alias="Primary",
            tenant_ref="tenant-a",
            idempotency_key="idem-1",
        )
        await client.account(platform=PlatformChannel.XHS_PC, account_ref="primary", tenant_ref="tenant-a")
        await client.start_qr_login(
            platform=PlatformChannel.XHS_PC,
            account_ref="primary",
            tenant_ref="tenant-a",
            idempotency_key="idem-2",
        )

    assert seen[1].headers["Idempotency-Key"] == "idem-1"
    assert json.loads(seen[1].content)["tenant_ref"] == "tenant-a"


@pytest.mark.asyncio
async def test_http_client_maps_timeout_and_redacts_error_payload() -> None:
    def timeout_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://account.test") as transport_client:
        client = HttpAccountServiceClient(_config(), client=transport_client)
        with pytest.raises(RemoteAccountServiceError) as exc_info:
            await client.account(platform=PlatformChannel.XHS_PC, account_ref="primary", tenant_ref="tenant-a")
    assert exc_info.value.category is RemoteErrorCategory.TIMEOUT
    assert "secret" not in str(exc_info.value)
