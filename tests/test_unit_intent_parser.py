"""Unit tests for :class:`xhs_food.agents.intent_parser.IntentParserAgent`."""

from __future__ import annotations

import pytest

from xhs_food.agents.intent_parser import IntentParseResult, IntentParserAgent
from xhs_food.schemas import FollowUpType


# ---------------------------------------------------------------------------
# Happy path: well-formed JSON with location → success
# ---------------------------------------------------------------------------


async def test_parse_returns_success_when_location_present(mock_llm) -> None:
    # Arrange — LLM returns a clean JSON object with required fields
    mock_llm.set_response(
        '{"location": "成都", "food_type": "火锅", '
        '"requirements": ["本地老店"], "exclude_keywords": ["网红"]}'
    )
    agent = IntentParserAgent(llm_service=mock_llm)

    # Act
    result: IntentParseResult = await agent.parse("我想在成都吃火锅，找本地老店")

    # Assert
    assert result.success is True
    assert result.need_clarify is False
    assert result.intent is not None
    assert result.intent.location == "成都"
    assert result.intent.food_type == "火锅"
    assert "本地老店" in result.intent.requirements
    assert result.follow_up_type == FollowUpType.NEW_SEARCH
    # Ensure the LLM was invoked exactly once
    assert len(mock_llm.calls) == 1


# ---------------------------------------------------------------------------
# Location missing → need_clarify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"location": "", "food_type": "火锅"}',
        '{"location": "未指定", "food_type": "烧烤"}',
        '{"location": "不明确"}',
        '{"location": "未知"}',
    ],
)
async def test_parse_returns_need_clarify_for_missing_location(
    mock_llm, raw: str
) -> None:
    # Arrange
    mock_llm.set_response(raw)
    agent = IntentParserAgent(llm_service=mock_llm)

    # Act
    result = await agent.parse("我想吃点东西")

    # Assert
    assert result.success is False
    assert result.need_clarify is True
    assert result.questions, "should include at least one clarify question"
    assert any("城市" in q or "区域" in q for q in result.questions)


# ---------------------------------------------------------------------------
# LLM-driven clarify (need_clarify flag in JSON)
# ---------------------------------------------------------------------------


async def test_parse_returns_need_clarify_when_llm_signals_so(mock_llm) -> None:
    # Arrange — LLM explicitly says we need clarification
    mock_llm.set_response(
        '{"need_clarify": true, "questions": ["请提供具体位置"]}'
    )
    agent = IntentParserAgent(llm_service=mock_llm)

    # Act
    result = await agent.parse("吃饭")

    # Assert
    assert result.success is False
    assert result.need_clarify is True
    assert result.questions == ["请提供具体位置"]


# ---------------------------------------------------------------------------
# LLM returns junk → success=False
# ---------------------------------------------------------------------------


async def test_parse_returns_failure_for_unparseable_output(mock_llm) -> None:
    # Arrange — LLM output is plain prose, no JSON anywhere
    mock_llm.set_response("抱歉，我无法理解你的请求")
    agent = IntentParserAgent(llm_service=mock_llm)

    # Act
    result = await agent.parse("@#$%")

    # Assert
    assert result.success is False
    assert result.need_clarify is False
    assert result.error == "Failed to parse JSON from LLM output"


# ---------------------------------------------------------------------------
# Fenced JSON → still parsed via extract_json fallback
# ---------------------------------------------------------------------------


async def test_parse_handles_fenced_json(mock_llm) -> None:
    # Arrange — LLM wraps the JSON in a ```json``` code fence
    fenced = (
        "好的，这是结构化结果：\n"
        "```json\n"
        '{"location": "重庆", "food_type": "串串"}\n'
        "```\n"
    )
    mock_llm.set_response(fenced)
    agent = IntentParserAgent(llm_service=mock_llm)

    # Act
    result = await agent.parse("重庆串串")

    # Assert
    assert result.success is True
    assert result.intent is not None
    assert result.intent.location == "重庆"
    assert result.intent.food_type == "串串"


# ---------------------------------------------------------------------------
# Exception path → success=False with error
# ---------------------------------------------------------------------------


class _RaisingLLM:
    """LLM stub whose ``.call`` raises immediately."""

    async def call(self, messages, **kwargs):
        _ = messages, kwargs
        raise RuntimeError("network down")


async def test_parse_returns_error_when_llm_raises() -> None:
    # Arrange
    agent = IntentParserAgent(llm_service=_RaisingLLM())

    # Act
    result = await agent.parse("北京烤鸭")

    # Assert
    assert result.success is False
    assert result.error == "network down"
