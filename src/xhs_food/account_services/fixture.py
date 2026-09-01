"""Deterministic FastAPI account-service fixture.

This module is a local contract fixture, not a provider implementation.  It
contains no credentials, browser state, SQLite authority, or external calls.
An upstream XHS or Dianping service can replace it while preserving the same
HTTP and MCP envelopes.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Response

from xhs_food.contracts.account import PlatformChannel
from xhs_food.contracts.account_service import (
    ACCOUNT_SERVICE_CONTRACT_VERSION,
    MCP_PROTOCOL_VERSION,
    RemotePayloadRejected,
    validate_remote_payload,
)


def create_fixture_app(
    *,
    service_id: str = "fixture-account",
    channels: tuple[PlatformChannel, ...] = (PlatformChannel.XHS_PC,),
) -> FastAPI:
    """Create an isolated in-memory service for tests and local demos."""

    app = FastAPI(title=f"{service_id} fixture", version="1.0.0")
    accounts: dict[tuple[str, str, str], dict[str, Any]] = {}
    flows: dict[str, dict[str, Any]] = {}
    flow_numbers = itertools.count(1)

    def now() -> datetime:
        return datetime.now(UTC)

    def account_key(tenant_ref: str, platform: str, account_ref: str) -> tuple[str, str, str]:
        if platform not in {item.value for item in channels}:
            raise HTTPException(status_code=404, detail="account not found")
        return tenant_ref, platform, account_ref

    def validate_body(body: dict[str, Any]) -> None:
        try:
            validate_remote_payload(body)
        except RemotePayloadRejected as exc:
            raise HTTPException(status_code=422, detail="request contains forbidden material") from exc

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service_id": service_id}

    @app.get("/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "success": True,
            "data": {
                "service_id": service_id,
                "service_version": "fixture-v1",
                "contract_version": ACCOUNT_SERVICE_CONTRACT_VERSION,
                "protocol": "http+mcp",
                "platform_channels": [item.value for item in channels],
                "capabilities": ["account.register", "account.read", "account.login", "source.invoke", "notes.search", "place.lookup"],
                "login_modes": ["qr", "credential"],
                "expires_at": (now() + timedelta(minutes=5)).isoformat(),
                "refreshed_at": now().isoformat(),
                "mcp_endpoint": None,
            },
        }

    @app.post("/v1/accounts")
    async def register_account(body: dict[str, Any]) -> dict[str, Any]:
        validate_body(body)
        key = account_key(str(body.get("tenant_ref", "")), str(body.get("platform", "")), str(body.get("account_ref", "")))
        value = accounts.setdefault(
            key,
            {
                "service_id": service_id,
                "platform": key[1],
                "account_ref": key[2],
                "alias": str(body.get("alias", key[2])),
                "status": "pending_login",
                "health": "unknown",
                "session_version": None,
                "provider_subject_ref": None,
            },
        )
        return {"success": True, "data": value}

    @app.get("/v1/accounts/{platform}/{account_ref}")
    async def get_account(platform: str, account_ref: str, tenant_ref: str = "anonymous") -> dict[str, Any]:
        value = accounts.get(account_key(tenant_ref, platform, account_ref))
        if value is None:
            raise HTTPException(status_code=404, detail="account not found")
        return {"success": True, "data": value}

    @app.post("/v1/accounts/{platform}/{account_ref}/login/qr")
    async def start_qr(platform: str, account_ref: str, body: dict[str, Any]) -> dict[str, Any]:
        validate_body(body)
        tenant_ref = str(body.get("tenant_ref", "anonymous"))
        key = account_key(tenant_ref, platform, account_ref)
        if key not in accounts:
            raise HTTPException(status_code=404, detail="account not found")
        flow_id = f"{service_id}-flow-{next(flow_numbers)}"
        created = now()
        value = {
            "service_id": service_id,
            "platform": platform,
            "account_ref": account_ref,
            "flow_id": flow_id,
            "state": "qr_ready",
            "created_at": created.isoformat(),
            "expires_at": (created + timedelta(minutes=5)).isoformat(),
            "updated_at": created.isoformat(),
            "qr_expires_at": (created + timedelta(minutes=2)).isoformat(),
            "provider_subject_ref": None,
            "error_code": None,
            "error_message": None,
        }
        flows[flow_id] = {**value, "tenant_ref": tenant_ref}
        return {"success": True, "data": value}

    @app.post("/v1/accounts/{platform}/{account_ref}/login")
    async def start_login(platform: str, account_ref: str, body: dict[str, Any]) -> dict[str, Any]:
        return await start_qr(platform, account_ref, body)

    def flow_or_404(flow_id: str, tenant_ref: str = "anonymous") -> dict[str, Any]:
        flow = flows.get(flow_id)
        if flow is None or flow["tenant_ref"] != tenant_ref:
            raise HTTPException(status_code=404, detail="login flow not found")
        return flow

    @app.get("/v1/login/{flow_id}/status")
    async def flow_status(flow_id: str, tenant_ref: str = "anonymous") -> dict[str, Any]:
        return {"success": True, "data": {key: value for key, value in flow_or_404(flow_id, tenant_ref).items() if key != "tenant_ref"}}

    @app.get("/v1/login/{flow_id}/qr")
    async def flow_qr(flow_id: str, tenant_ref: str = "anonymous") -> dict[str, Any]:
        flow = flow_or_404(flow_id, tenant_ref)
        return {
            "success": True,
            "data": {
                "service_id": service_id,
                "flow_id": flow_id,
                "object_ref": f"fixture://{service_id}/qr/{flow_id}",
                "expires_at": flow["qr_expires_at"],
                "content_type": "image/png",
            },
        }

    @app.post("/v1/login/{flow_id}/poll")
    async def flow_poll(flow_id: str, body: dict[str, Any]) -> dict[str, Any]:
        validate_body(body)
        flow = flow_or_404(flow_id, str(body.get("tenant_ref", "anonymous")))
        if flow["state"] == "qr_ready":
            flow["state"] = "succeeded"
            flow["provider_subject_ref"] = f"subject:{flow['account_ref']}"
            flow["updated_at"] = now().isoformat()
        return {"success": True, "data": {key: value for key, value in flow.items() if key != "tenant_ref"}}

    @app.post("/v1/login/{flow_id}/cancel")
    async def flow_cancel(flow_id: str, body: dict[str, Any]) -> dict[str, Any]:
        validate_body(body)
        flow = flow_or_404(flow_id, str(body.get("tenant_ref", "anonymous")))
        if flow["state"] not in {"succeeded", "expired", "failed", "cancelled"}:
            flow["state"] = "cancelled"
            flow["updated_at"] = now().isoformat()
        return {"success": True, "data": {key: value for key, value in flow.items() if key != "tenant_ref"}}

    @app.post("/v1/source/invoke")
    async def source_invoke(body: dict[str, Any]) -> dict[str, Any]:
        validate_body(body)
        account_key(str(body.get("tenant_ref", "anonymous")), str(body.get("platform", "")), str(body.get("account_ref", "")))
        return {"success": True, "data": {"outcome": "empty", "items": [], "next_cursor": None, "capability": body.get("capability")}}

    @app.post("/mcp")
    async def mcp(body: dict[str, Any], response: Response) -> dict[str, Any]:
        validate_body(body)
        method = body.get("method")
        request_id = body.get("id")
        if method == "initialize":
            response.headers["Mcp-Session-Id"] = f"{service_id}-session"
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": service_id, "version": "fixture-v1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": "notes.search", "description": "Read notes", "capability": "notes.search", "inputSchema": {"type": "object"}, "side_effect": "read_only"},
                    {"name": "account.login", "description": "Start account login", "capability": "account.login", "inputSchema": {"type": "object"}, "side_effect": "account_login"},
                    {"name": "provider.publish", "description": "Not enabled", "capability": "provider.publish", "inputSchema": {"type": "object"}, "side_effect": "publish"},
                ]
            }
        elif method == "tools/call":
            params: dict[str, Any] = {}
            raw_params = body.get("params")
            if isinstance(raw_params, dict):
                params = raw_params
            result = {"content": [{"type": "json", "json": {"outcome": "empty", "tool": params.get("name")}}], "isError": False}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    return app


__all__ = ["create_fixture_app"]
