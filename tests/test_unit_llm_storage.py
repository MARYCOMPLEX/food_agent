# -*- coding: utf-8 -*-
import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from food_agent.services.llm_service import LLMService
from food_agent.services.llm_storage import LLMConfigStorage, mask_api_key


@pytest.mark.asyncio
async def test_mask_api_key():
    assert mask_api_key(None) == "未设置"
    assert mask_api_key("") == "未设置"
    assert mask_api_key("shortkey") == "********"
    masked = mask_api_key("sk-1234567890abcdef1234")
    assert masked.startswith("sk-1234")
    assert masked.endswith("1234")
    assert "********" in masked


@pytest.mark.asyncio
async def test_llm_storage_crud(tmp_path):
    db_file = str(tmp_path / "test_llm.db")
    storage = LLMConfigStorage(db_file)
    await storage.initialize()

    # Initial seeding test (or empty if no env key)
    models = await storage.list_models()
    initial_count = len(models)

    # Save new model
    new_model = {
        "model_id": "test_deepseek",
        "model_name": "deepseek-chat",
        "display_name": "DeepSeek V3 (测试)",
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-deepseek-test-key-123456",
        "temperature": 0.5,
        "max_tokens": 2048,
        "reasoning_effort": "low",
        "is_default": False,
        "is_user_selectable": True,
    }
    saved = await storage.save_model(new_model)
    assert saved["model_id"] == "test_deepseek"
    assert "********" in saved["masked_api_key"]

    # Retrieve
    retrieved = await storage.get_model("test_deepseek", mask_key=False)
    assert retrieved is not None
    assert retrieved["api_key"] == "sk-deepseek-test-key-123456"
    assert retrieved["model_name"] == "deepseek-chat"

    # Set as default
    default_res = await storage.set_default_model("test_deepseek")
    assert default_res is not None
    assert default_res["is_default"] is True

    curr_default = await storage.get_default_model(mask_key=False)
    assert curr_default is not None
    assert curr_default["model_id"] == "test_deepseek"

    # Update preserving key
    update_data = {
        "model_id": "test_deepseek",
        "model_name": "deepseek-chat",
        "display_name": "DeepSeek V3 (已更新)",
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-deep********3456",  # masked
        "temperature": 0.7,
        "max_tokens": 4096,
        "is_default": True,
        "is_user_selectable": True,
    }
    updated = await storage.save_model(update_data)
    assert updated["display_name"] == "DeepSeek V3 (已更新)"
    check_key = await storage.get_model("test_deepseek", mask_key=False)
    assert check_key["api_key"] == "sk-deepseek-test-key-123456"
    assert check_key["temperature"] == 0.7

    # Delete
    deleted = await storage.delete_model("test_deepseek")
    assert deleted is True
    assert await storage.get_model("test_deepseek") is None


@pytest.mark.asyncio
async def test_llm_service_resolves_storage(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_service_llm.db")
    storage = LLMConfigStorage(db_file)
    await storage.initialize()

    # Seed custom model
    await storage.save_model(
        {
            "model_id": "custom_model_id",
            "model_name": "custom-gpt-test",
            "display_name": "Custom Model",
            "provider": "Custom",
            "base_url": "https://custom.api/v1",
            "api_key": "sk-custom-test-123456",
            "temperature": 0.3,
            "max_tokens": 1500,
            "is_default": True,
            "is_user_selectable": True,
        }
    )

    monkeypatch.setattr(LLMConfigStorage, "_instance", storage)
    LLMService.clear_cache()

    service = LLMService(model_name="custom-gpt-test")
    client = service.get_llm()
    assert client.model_name == "custom-gpt-test"
    assert str(client.openai_api_base).rstrip("/") == "https://custom.api/v1"


@pytest.mark.asyncio
async def test_chat_and_ops_endpoints(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_endpoints_llm.db")
    storage = LLMConfigStorage(db_file)
    await storage.initialize()
    monkeypatch.setattr(LLMConfigStorage, "_instance", storage)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Public chat models
        resp = await client.get("/v1/chat/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)

        # 2. Ops list models
        resp = await client.get("/v1/platform/ops/llm-models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # 3. Ops create model
        create_payload = {
            "model_id": "test_ops_model",
            "model_name": "test-mock-model",
            "display_name": "Mock Model for Test",
            "provider": "TestProvider",
            "base_url": "https://test.mock.com/v1",
            "api_key": "sk-test1234567890",
            "temperature": 0.1,
            "max_tokens": 512,
            "is_default": False,
            "is_user_selectable": True,
        }
        resp = await client.post("/v1/platform/ops/llm-models", json=create_payload)
        assert resp.status_code == 200
        assert resp.json()["data"]["model_id"] == "test_ops_model"

        # 4. Ops set default
        resp = await client.post("/v1/platform/ops/llm-models/test_ops_model/set-default")
        assert resp.status_code == 200
        assert resp.json()["data"]["is_default"] is True

        # 5. Ops delete model
        resp = await client.delete("/v1/platform/ops/llm-models/test_ops_model")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True
