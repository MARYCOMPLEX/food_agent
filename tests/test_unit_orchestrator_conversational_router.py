"""Unit tests for XHSFoodOrchestrator conversational routing and intent classification.

Ensures that casual greetings and ambiguous chats trigger Conversational Mode
(empty pipeline steps, natural LLM dialogue, no crawler execution) while
explicit dining requests trigger Deep Research Mode (6-step research workflow).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
from langchain_core.messages import AIMessage

from food_agent.events.bus import InMemoryEventBus
from food_agent.events.emitter import SearchEventEmitter
from food_agent.orchestrator import XHSFoodOrchestrator
from food_agent.schemas import ConversationContext, RestaurantRecommendation, XHSFoodResponse


@pytest.fixture
def mock_llm_service() -> MagicMock:
    llm = MagicMock()
    llm.call = AsyncMock(
        return_value=AIMessage(
            content="您好！我是您的小红书美食向导 🍜，请问您在哪个城市，想吃什么类型的风味？"
        )
    )
    return llm


@pytest.fixture
def mock_workflow() -> MagicMock:
    workflow = MagicMock()
    mock_run = MagicMock()
    mock_run.notes = []
    mock_run.restaurants = [
        RestaurantRecommendation(
            name="老牌蹄花店",
            location="成都市青羊区",
            features=["老字号", "软烂入味"],
            confidence=0.92,
        )
    ]
    mock_run.evidence_map = {}
    mock_run.evidence_vault = []
    mock_run.final_summary = "为您精选成都地道老牌蹄花店"

    mock_execution = MagicMock()
    mock_execution.intent = MagicMock()
    mock_execution.intent.to_dict.return_value = {"location": "成都", "food_category": "蹄花"}
    mock_execution.run = mock_run
    mock_execution.to_food_response.return_value = XHSFoodResponse(
        status="ok",
        summary="为您精选成都地道老牌蹄花店",
        recommendations=mock_run.restaurants,
        filtered_count=0,
    )

    workflow.execute = AsyncMock(return_value=mock_execution)
    return workflow


@pytest.fixture
def test_emitter() -> SearchEventEmitter:
    bus = InMemoryEventBus()
    return SearchEventEmitter("test-session-conv", bus)


@pytest.mark.asyncio
async def test_fast_path_greetings_classified_as_chat(
    mock_llm_service: MagicMock,
    mock_workflow: MagicMock,
) -> None:
    orchestrator = XHSFoodOrchestrator(workflow=mock_workflow, llm_service=mock_llm_service)

    greetings = ["hi", "Hi", "hello", "你好", "哈喽", "在吗", "早上好", "晚上好", "谢谢", "你是谁", "嗨"]
    for query in greetings:
        intent = await orchestrator._classify_intent(query)
        assert intent == "chat", f"Expected '{query}' to be classified as 'chat'"

    # LLM should not even be called for fast-path greetings
    mock_llm_service.call.assert_not_called()


@pytest.mark.asyncio
async def test_llm_fallback_intent_classification(
    mock_llm_service: MagicMock,
    mock_workflow: MagicMock,
) -> None:
    orchestrator = XHSFoodOrchestrator(workflow=mock_workflow, llm_service=mock_llm_service)

    # 1. Ambiguous query classified as chat by LLM
    mock_llm_service.call.return_value = AIMessage(
        content='{"intent": "chat", "reason": "极度模糊，未指定城市和菜系"}'
    )
    intent1 = await orchestrator._classify_intent("今天晚上好饿啊，到底吃什么好呢")
    assert intent1 == "chat"

    # 2. Specific dining query classified as research by LLM
    mock_llm_service.call.return_value = AIMessage(
        content='{"intent": "research", "reason": "包含明确城市与商圈"}'
    )
    intent2 = await orchestrator._classify_intent("成华区建设路小吃街推荐")
    assert intent2 == "research"


@pytest.mark.asyncio
async def test_handle_conversational_updates_history(
    mock_llm_service: MagicMock,
    mock_workflow: MagicMock,
) -> None:
    mock_llm_service.call.return_value = AIMessage(
        content="你好！想吃点什么呢？"
    )
    orchestrator = XHSFoodOrchestrator(workflow=mock_workflow, llm_service=mock_llm_service)

    response = await orchestrator._handle_conversational("hi")

    assert response.status == "ok"
    assert "你好" in response.summary
    assert response.recommendations == []
    assert orchestrator.context.turn_count == 1
    assert len(orchestrator.context.conversation_history) == 2
    assert orchestrator.context.conversation_history[0] == {"role": "user", "content": "hi"}
    assert orchestrator.context.conversation_history[1] == {"role": "assistant", "content": response.summary}


@pytest.mark.asyncio
async def test_search_stream_greeting_keeps_steps_empty_and_does_not_call_workflow(
    mock_llm_service: MagicMock,
    mock_workflow: MagicMock,
    test_emitter: SearchEventEmitter,
) -> None:
    orchestrator = XHSFoodOrchestrator(workflow=mock_workflow, llm_service=mock_llm_service)

    await orchestrator.search_stream("hi", test_emitter)

    # Key assertion: steps list must be EMPTY for chat greetings (no 6-step crawler timeline)
    assert test_emitter.steps == []
    # Workflow should not be executed for greetings
    mock_workflow.execute.assert_not_called()
    # Context should record the conversation turn
    assert orchestrator.context.turn_count == 1
    assert len(orchestrator.context.conversation_history) == 2


@pytest.mark.asyncio
async def test_search_stream_research_initializes_steps_and_calls_workflow(
    mock_llm_service: MagicMock,
    mock_workflow: MagicMock,
    test_emitter: SearchEventEmitter,
) -> None:
    mock_llm_service.call.return_value = AIMessage(
        content='{"intent": "research", "reason": "明确的美食探店需求"}'
    )
    orchestrator = XHSFoodOrchestrator(workflow=mock_workflow, llm_service=mock_llm_service)

    await orchestrator.search_stream("成都玉林老火锅推荐", test_emitter)

    # In research mode, 6 steps must be initialized
    assert len(test_emitter.steps) == 6
    # Workflow must be executed
    mock_workflow.execute.assert_called_once()
