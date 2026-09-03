"""Offline contracts for S3 adapters around the currently active services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import SecretStr

from xhs_food.composition.adapters import (
    DisabledPublicEvidenceRepository,
    LegacyEventBusAdapter,
    LegacyFavoritesRepositoryAdapter,
    LegacyHistoryRepositoryAdapter,
    LegacyLLMProviderAdapter,
    LegacySearchResultRepositoryAdapter,
    LegacySessionRepositoryAdapter,
    LegacySessionWindowAdapter,
    LegacyStateStoreAdapter,
    LegacyUserRepositoryAdapter,
    ProviderModelGateway,
)
from xhs_food.contracts import (
    EventBusPort,
    EventEnvelope,
    FavoritesRepositoryPort,
    HistoryRepositoryPort,
    LLMProvider,
    ModelGateway,
    ModelMessage,
    ModelRequest,
    PublicEvidenceRepositoryPort,
    SearchResultRepositoryPort,
    SessionRepositoryPort,
    SessionWindowPort,
    StateStorePort,
    UserRepositoryPort,
)
from xhs_food.events.types import SearchEvent, SearchEventType
from xhs_food.foundation import ModelConfigView, TargetAdapterDisabled
from xhs_food.services.llm_service import LLMService
from xhs_food.services.user_storage.repository import RepositoryMixin


class FakeLLMService:
    def __init__(self, response: AIMessage | BaseException) -> None:
        self.response = response
        self.calls: list[tuple[list[Any], dict[str, Any]]] = []

    async def call(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        self.calls.append((messages, kwargs))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _model_config(base_url: str = "https://api.siliconflow.cn/v1/") -> ModelConfigView:
    return ModelConfigView(
        api_key=SecretStr("fixture-secret"),
        base_url=base_url,
        model="fixture-model",
        temperature=0.2,
        max_tokens=256,
    )


def _model_request(model_role: str = "planner") -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model_role=model_role,
        messages=(
            ModelMessage(role="system", content="system"),
            ModelMessage(role="user", content="question"),
            ModelMessage(role="assistant", content="draft"),
            ModelMessage(role="tool", content="result", tool_call_id="tool-1"),
        ),
        provider_options={"seed": 7},
    )


@pytest.mark.unit
async def test_legacy_llm_adapter_preserves_messages_options_usage_and_tool_calls() -> None:
    service = FakeLLMService(
        AIMessage(
            content="answer",
            response_metadata={"token_usage": {"prompt_tokens": 11, "completion_tokens": 5}},
            tool_calls=[{"id": "tool-1", "name": "lookup", "args": {"q": "food"}}],
        )
    )
    adapter = LegacyLLMProviderAdapter(
        cast(LLMService, service),
        _model_config(),
    )

    response = await adapter.complete(_model_request())

    assert isinstance(adapter, LLMProvider)
    assert adapter.provider_id == "siliconflow"
    assert response.request_id == "request-1"
    assert response.content == "answer"
    assert response.provider_ref == "siliconflow"
    assert response.model_ref == "fixture-model"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 5
    assert response.tool_calls[0].model_dump() == {
        "call_id": "tool-1",
        "name": "lookup",
        "arguments": {"q": "food"},
    }
    messages, options = service.calls[0]
    assert [type(message) for message in messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        ToolMessage,
    ]
    assert options == {"seed": 7}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("base_url", "provider_id"),
    [
        ("https://api.deepseek.com/v1", "deepseek"),
        ("https://api.openai.com/v1", "openai"),
        ("https://provider.example/v1", "openai-compatible"),
    ],
)
async def test_model_gateway_selects_roles_and_preserves_provider_errors(
    base_url: str,
    provider_id: str,
) -> None:
    expected = RuntimeError("provider failed")
    service = FakeLLMService(expected)
    adapter = LegacyLLMProviderAdapter(cast(LLMService, service), _model_config(base_url))
    gateway = ProviderModelGateway({"planner": adapter})

    assert isinstance(gateway, ModelGateway)
    assert adapter.provider_id == provider_id
    with pytest.raises(RuntimeError) as raised:
        await gateway.generate(_model_request())
    assert raised.value is expected
    with pytest.raises(KeyError, match="no provider configured"):
        await gateway.generate(_model_request("missing"))


@dataclass
class PayloadModel:
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}


class FakeStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def get_user(self, user_id: str) -> PayloadModel:
        self.calls.append(("get_user", (user_id,), {}))
        return PayloadModel(user_id)

    async def get_or_create_user(self, device_id: str) -> PayloadModel:
        self.calls.append(("get_or_create_user", (device_id,), {}))
        return PayloadModel(device_id)

    async def update_user(self, user_id: str, **changes: Any) -> PayloadModel:
        self.calls.append(("update_user", (user_id,), changes))
        return PayloadModel(str(changes["name"]))

    async def get_history(self, user_id: str, *, limit: int, offset: int) -> list[Any]:
        self.calls.append(("get_history", (user_id,), {"limit": limit, "offset": offset}))
        return [PayloadModel("history")]

    async def get_history_count(self, user_id: str) -> int:
        return 1

    async def add_history(self, user_id: str, **item: Any) -> PayloadModel:
        self.calls.append(("add_history", (user_id,), item))
        return PayloadModel("added-history")

    async def delete_history(self, user_id: str, history_id: int) -> bool:
        return user_id == "user-1" and history_id == 1

    async def clear_history(self, user_id: str) -> int:
        return 2 if user_id == "user-1" else 0

    async def get_history_by_session(self, session_id: str) -> PayloadModel:
        return PayloadModel(session_id)

    async def get_favorites(self, user_id: str) -> list[Any]:
        return [PayloadModel(user_id)]

    async def add_favorite(self, user_id: str, restaurant_id: str) -> PayloadModel:
        return PayloadModel(f"{user_id}:{restaurant_id}")

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return True

    async def check_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return True

    async def save_search_result(
        self,
        session_id: str,
        restaurants: list[Any],
        **metadata: Any,
    ) -> bool:
        self.calls.append(("save_search_result", (session_id, restaurants), metadata))
        return True

    async def get_search_result(self, session_id: str, turn_id: int | None) -> PayloadModel:
        return PayloadModel(f"{session_id}:{turn_id}")

    async def get_all_search_results(self, session_id: str) -> list[Any]:
        return [PayloadModel(session_id)]


class FakeSessionManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def add_user_message(self, *args: Any) -> None:
        self.calls.append(("user", args))

    async def add_assistant_message(self, *args: Any) -> None:
        self.calls.append(("assistant", args))

    async def get_context(self, session_id: str, *, count: int) -> list[dict[str, Any]]:
        return [{"role": "user", "content": f"{session_id}:{count}"}]

    async def clear_session(self, session_id: str) -> None:
        self.calls.append(("clear", (session_id,)))


@pytest.mark.unit
async def test_legacy_repository_adapters_satisfy_owned_ports_and_keep_json_boundary() -> None:
    storage = FakeStorage()
    manager = FakeSessionManager()
    session = LegacySessionRepositoryAdapter(manager)
    users = LegacyUserRepositoryAdapter(storage)
    history = LegacyHistoryRepositoryAdapter(storage)
    favorites = LegacyFavoritesRepositoryAdapter(storage)
    results = LegacySearchResultRepositoryAdapter(storage)

    assert isinstance(session, SessionRepositoryPort)
    assert isinstance(users, UserRepositoryPort)
    assert isinstance(history, HistoryRepositoryPort)
    assert isinstance(favorites, FavoritesRepositoryPort)
    assert isinstance(results, SearchResultRepositoryPort)

    await session.append_message("session-1", "user", "hello", user_id="user-1")
    await session.append_message("session-1", "assistant", "answer")
    assert await session.list_messages("session-1", limit=3) == (
        {"role": "user", "content": "session-1:3"},
    )
    assert await session.delete_session("session-1") is True
    with pytest.raises(ValueError, match="user/assistant"):
        await session.append_message("session-1", "tool", "invalid")

    assert await users.get_user("user-1") == {"value": "user-1"}
    assert await users.get_or_create_user("device-1") == {"value": "device-1"}
    assert await users.update_user("user-1", {"name": "updated"}) == {"value": "updated"}
    with pytest.raises(ValueError, match="unsupported user fields"):
        await users.update_user("user-1", {"admin": True})

    assert await history.list_history("user-1", limit=5, offset=2) == ({"value": "history"},)
    assert await history.count_history("user-1") == 1
    assert await history.add_history("user-1", {"query": "food"}) == {"value": "added-history"}
    assert await history.delete_history("user-1", 1) is True
    assert await history.clear_history("user-1") == 2
    assert await history.get_history_by_session("session-1") == {"value": "session-1"}

    assert await favorites.list_favorites("user-1") == ({"value": "user-1"},)
    assert await favorites.add_favorite("user-1", "restaurant-1") == {
        "value": "user-1:restaurant-1"
    }
    assert await favorites.remove_favorite("user-1", "restaurant-1") is True
    assert await favorites.contains_favorite("user-1", "restaurant-1") is True

    result = {
        "restaurants": [{"id": "restaurant-1"}],
        "summary": "summary",
        "filtered_count": 4,
        "query": "query",
    }
    assert await results.save_result("session-1", result, turn_id=2) is True
    assert storage.calls[-1] == (
        "save_search_result",
        ("session-1", [{"id": "restaurant-1"}]),
        {"summary": "summary", "filtered_count": 4, "query": "query", "turn_id": 2},
    )
    assert await results.get_result("session-1", turn_id=2) == {"value": "session-1:2"}
    assert await results.list_results("session-1") == ({"value": "session-1"},)
    with pytest.raises(TypeError, match="JSON array"):
        await results.save_result("session-1", {"restaurants": {}})
    with pytest.raises(TypeError, match="integer"):
        await results.save_result("session-1", {"filtered_count": True})


class FakeMemory:
    def __init__(self) -> None:
        self.messages: dict[str, list[PayloadModel]] = {}

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: object,
    ) -> None:
        self.messages.setdefault(session_id, []).append(PayloadModel(f"{role}:{content}"))

    def get_recent_messages(self, session_id: str, count: int | None = None) -> list[PayloadModel]:
        messages = self.messages.get(session_id, [])
        return messages[-count:] if count else messages

    def session_exists(self, session_id: str) -> bool:
        return session_id in self.messages

    def clear_session(self, session_id: str) -> None:
        self.messages.pop(session_id, None)


class FakeLegacyStateStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    async def get(self, sid: str) -> dict[str, Any] | None:
        return self.values.get(sid)

    async def set(self, sid: str, value: dict[str, Any]) -> None:
        self.values[sid] = value

    async def delete(self, sid: str) -> None:
        self.deleted.append(sid)
        self.values.pop(sid, None)


class FakeLegacyEventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, SearchEvent]] = []
        self.replay: list[tuple[str, SearchEvent]] = []
        self.subscriptions: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, session_id: str, event: SearchEvent) -> str:
        self.published.append((session_id, event))
        return "7-0"

    def subscribe(
        self, session_id: str, last_id: str = "0"
    ) -> AsyncIterator[tuple[str, SearchEvent]]:
        self.subscriptions.append((session_id, last_id))
        return self._subscribe()

    async def _subscribe(self) -> AsyncIterator[tuple[str, SearchEvent]]:
        for item in self.replay:
            yield item

    async def close(self) -> None:
        self.closed = True


@pytest.mark.unit
async def test_legacy_state_and_event_adapters_freeze_existing_policy() -> None:
    state_backend = FakeLegacyStateStore()
    state = LegacyStateStoreAdapter(state_backend)
    event_backend = FakeLegacyEventBus()
    events = LegacyEventBusAdapter(event_backend)

    assert isinstance(state, StateStorePort)
    assert isinstance(events, EventBusPort)
    assert state.KEY_PATTERN == "task:{session_id}:state"
    assert state.TTL_SECONDS == 3_600
    await state.set("session-1", {"status": "loading"}, 3_600)
    assert await state.get("session-1") == {"status": "loading"}
    with pytest.raises(ValueError, match="task-state TTL changed"):
        await state.set("session-1", {}, 60)
    assert await state.delete("session-1") is True
    assert await state.delete("session-1") is False

    published_at = datetime(2026, 8, 20, 1, 2, 3, tzinfo=UTC)
    entry_id = await events.publish(
        EventEnvelope(
            event_id="contract-event-1",
            topic="session-1",
            payload={"type": "step_start", "data": {"step": "step2"}},
            published_at=published_at,
        )
    )
    assert entry_id == "7-0"
    topic, legacy_event = event_backend.published[0]
    assert topic == "session-1"
    assert legacy_event.type is SearchEventType.STEP_START
    assert legacy_event.data == {"step": "step2"}
    assert legacy_event.timestamp == published_at.timestamp()

    event_backend.replay = [
        (
            "8-0",
            SearchEvent(
                type=SearchEventType.DONE,
                data={"status": "completed"},
                timestamp=published_at.timestamp(),
            ),
        )
    ]
    replayed = [event async for event in events.subscribe("session-1", "7-0")]
    assert event_backend.subscriptions == [("session-1", "7-0")]
    assert replayed == [
        EventEnvelope(
            event_id="8-0",
            topic="session-1",
            payload={"type": "done", "data": {"status": "completed"}},
            published_at=published_at,
        )
    ]
    await events.close()
    assert event_backend.closed is True


@pytest.mark.unit
async def test_legacy_session_window_and_disabled_public_evidence_contracts() -> None:
    memory = FakeMemory()
    window = LegacySessionWindowAdapter(memory)
    evidence = DisabledPublicEvidenceRepository()

    assert isinstance(window, SessionWindowPort)
    assert isinstance(evidence, PublicEvidenceRepositoryPort)
    await window.append(
        "session-1",
        {"role": "user", "content": "hello", "metadata": {"turn": 1}},
        86_400,
    )
    assert await window.recent("session-1", 20) == ({"value": "user:hello"},)
    with pytest.raises(ValueError, match="TTL changed"):
        await window.append("session-1", {}, 60)
    assert await window.clear("session-1") is True
    assert await window.clear("session-1") is False

    with pytest.raises(TargetAdapterDisabled, match="public-evidence-repository"):
        await evidence.get_bundle("bundle-1")
