# -*- coding: utf-8 -*-
"""Unit tests for dynamic database persistence and hot-reloading of MCP services."""

import asyncio
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from food_agent.contracts.account_service import AccountServiceProtocol, PlatformChannel
from food_agent.services.mcp_service_storage import MCPServiceStorage
from food_agent.composition.account_services import AccountServiceRegistry
from api.main import app


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_mcp_services.db")


@pytest.mark.asyncio
async def test_mcp_service_storage_lifecycle(tmp_db_path: str):
    storage = MCPServiceStorage(tmp_db_path)
    await storage.initialize()

    # Initial state should be empty
    services = await storage.list_services()
    assert len(services) == 0

    # 1. Create a service
    record = {
        "service_id": "dianping-service",
        "name": "大众点评数据增强微服务",
        "base_url": "http://127.0.0.1:8103",
        "mcp_url": "http://127.0.0.1:8103/mcp",
        "protocol": "http+mcp",
        "channels": ["dianping"],
        "capabilities": ["notes.search", "shop.profile"],
        "timeout_seconds": 25.0,
        "enabled": True,
    }
    saved = await storage.save_service(record)
    assert saved["service_id"] == "dianping-service"
    assert saved["name"] == "大众点评数据增强微服务"
    assert saved["channels"] == ["dianping"]
    assert saved["enabled"] is True

    # 2. Retrieve by ID
    fetched = await storage.get_service("dianping-service")
    assert fetched is not None
    assert fetched["base_url"] == "http://127.0.0.1:8103"

    # 3. Toggle enabled
    toggled = await storage.set_service_enabled("dianping-service", False)
    assert toggled is not None
    assert toggled["enabled"] is False

    enabled_only = await storage.list_services(enabled_only=True)
    assert len(enabled_only) == 0

    all_services = await storage.list_services(enabled_only=False)
    assert len(all_services) == 1

    # 4. Convert to AccountServiceConfig
    config = storage.to_account_service_config(saved)
    assert config.service_id == "dianping-service"
    assert config.channels == (PlatformChannel.DIANPING,)
    assert config.protocol == AccountServiceProtocol.HTTP_MCP

    # 5. Delete service
    deleted = await storage.delete_service("dianping-service")
    assert deleted is True
    assert await storage.get_service("dianping-service") is None


@pytest.mark.asyncio
async def test_account_service_registry_dynamic_lifecycle():
    registry = AccountServiceRegistry(())
    assert registry.enabled is False

    config = AccountServiceRegistry.from_json(
        '[{"service_id": "probe-svc", "base_url": "http://127.0.0.1:8999", "protocol": "mcp", "channels": ["dianping"]}]'
    ).configs[0]

    # Dynamically register without probing (or mock probe failure)
    health = await registry.register_service(config, probe=False)
    assert health.service_id == "probe-svc"
    assert registry.enabled is True
    assert "probe-svc" in [c.service_id for c in registry.configs]

    # Dynamically unregister
    await registry.unregister_service("probe-svc")
    assert registry.enabled is False
    assert len(registry.configs) == 0


@pytest.mark.asyncio
async def test_ops_mcp_api_endpoints(tmp_db_path: str):
    # Prepare app state
    storage = MCPServiceStorage(tmp_db_path)
    await storage.initialize()
    app.state.mcp_storage = storage
    app.state.account_service_registry = AccountServiceRegistry(())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List initially
        res = await client.get("/v1/platform/ops/mcp-services")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["data"]) == 0

        # 2. Create
        payload = {
            "service_id": "xhs-service",
            "name": "小红书采集微服务",
            "base_url": "http://127.0.0.1:8102",
            "protocol": "http+mcp",
            "channels": ["xhs_pc"],
            "capabilities": ["notes.search"],
            "timeout_seconds": 15.0,
            "enabled": True,
        }
        res = await client.post("/v1/platform/ops/mcp-services", json=payload)
        assert res.status_code == 200
        created = res.json()["data"]["service"]
        assert created["service_id"] == "xhs-service"

        # 3. Verify in list
        res = await client.get("/v1/platform/ops/mcp-services")
        services = res.json()["data"]
        assert len(services) == 1
        assert services[0]["service_id"] == "xhs-service"

        # 4. Toggle
        res = await client.post("/v1/platform/ops/mcp-services/xhs-service/toggle", json={"enabled": False})
        assert res.status_code == 200
        assert res.json()["data"]["service"]["enabled"] is False

        # 5. Delete
        res = await client.delete("/v1/platform/ops/mcp-services/xhs-service")
        assert res.status_code == 200
        assert res.json()["data"]["deleted"] is True

        res = await client.get("/v1/platform/ops/mcp-services")
        assert len(res.json()["data"]) == 0


@pytest.mark.asyncio
async def test_custom_platform_channel_support(tmp_db_path: str):
    """Verify that arbitrary new/custom platforms (e.g. meituan, douyin, amap) are supported."""
    storage = MCPServiceStorage(tmp_db_path)
    await storage.initialize()

    # Save service with custom platforms
    custom_record = {
        "service_id": "meituan-service",
        "name": "美团外卖与商户服务",
        "base_url": "http://127.0.0.1:8105",
        "protocol": "http+mcp",
        "channels": ["meituan", "amap"],
        "capabilities": ["poi.search", "deals.get"],
        "timeout_seconds": 20.0,
        "enabled": True,
    }
    saved = await storage.save_service(custom_record)
    assert saved["channels"] == ["meituan", "amap"]

    config = storage.to_account_service_config(saved)
    assert config.channels[0] == PlatformChannel("meituan")
    assert config.channels[1] == PlatformChannel("amap")

    registry = AccountServiceRegistry(())
    health = await registry.register_service(config, probe=False)
    assert health.service_id == "meituan-service"
    assert registry.enabled is True

