"""Focused tests for bounded, deterministic comment-batch analysis."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.research.resource_limits import BudgetExceededError, ResourceCallTimeoutError


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _DelayedLLM:
    def __init__(self, *, delays: dict[int, float], failures: set[int] | None = None) -> None:
        self.delays = delays
        self.failures = failures or set()
        self.calls: list[int] = []
        self.active = 0
        self.max_active = 0

    async def call(self, messages: list[Any], **_: Any) -> _Message:
        text = str(messages[1].content)
        batch_index = int(text.split("[c", 1)[1].split("]", 1)[0]) // 2
        self.calls.append(batch_index)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays.get(batch_index, 0))
            if batch_index in self.failures:
                raise RuntimeError(f"batch {batch_index} unavailable")
            first_id = batch_index * 2
            return _Message(
                json.dumps(
                    {
                            "batch": batch_index,
                            "results": [
                            {
                                "id": f"c{first_id + offset}",
                                "identity": "none",
                                "sentiment": "positive",
                                "is_correction": False,
                                "mentioned_shops": [f"shop-{batch_index}"],
                            }
                            for offset in range(2)
                        ],
                    }
                )
            )
        finally:
            self.active -= 1


def _comments(count: int) -> list[dict[str, Any]]:
    return [{"id": f"c{index}", "text": f"评论 {index}", "likes": 1} for index in range(count)]


async def test_comment_batches_overlap_but_respect_concurrency_limit() -> None:
    llm = _DelayedLLM(delays={0: 0.04, 1: 0.01, 2: 0.01})
    agent = AnalyzerAgent(
        llm_service=llm,
        analysis_batch_size=2,
        analysis_concurrency=2,
        analysis_token_budget=None,
        token_estimator=lambda _: 1,
    )

    result = await agent.analyze("title", "content", _comments(6), [], "note-1")

    assert result.success is True
    assert llm.max_active == 2
    assert set(llm.calls) == {0, 1, 2}


async def test_token_budget_bounds_weighted_in_flight_batches() -> None:
    llm = _DelayedLLM(delays={0: 0.03, 1: 0.03, 2: 0.03})
    agent = AnalyzerAgent(
        llm_service=llm,
        analysis_batch_size=2,
        analysis_concurrency=3,
        analysis_token_budget=2,
        token_estimator=lambda _: 1,
    )

    result = await agent.analyze("title", "content", _comments(6), [], "note-1")

    assert result.success is True
    assert llm.max_active == 2


async def test_batch_merge_is_index_ordered_and_failed_batch_keeps_raw_comments() -> None:
    llm = _DelayedLLM(
        delays={0: 0.04, 1: 0.0, 2: 0.01},
        failures={1},
    )
    agent = AnalyzerAgent(
        llm_service=llm,
        analysis_batch_size=2,
        analysis_concurrency=3,
        analysis_token_budget=None,
        token_estimator=lambda _: 1,
    )

    result = await agent.analyze("title", "content", _comments(6), [], "note-1")

    assert result.success is True
    assert result.partial is True
    assert [gap.code for gap in result.gaps] == ["analysis_batch_failed"]
    assert result.gaps[0].details["batch_index"] == 1
    assert result.gaps[0].details["comment_ids"] == ["c2", "c3"]
    assert [comment["id"] for comment in result.raw_comments] == [
        "c0",
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
    ]
    # Responses complete in 1/2/0 order, but the merged raw output follows
    # stable batch order and only successful provider responses are joined.
    assert [json.loads(item)["batch"] for item in result.raw_output.splitlines()] == [0, 2]


class _TypedFailureLLM:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def call(self, messages: list[Any], **_: Any) -> _Message:
        _ = messages
        raise self.error


async def test_batch_resource_failures_keep_actionable_gap_codes() -> None:
    budget_result = await AnalyzerAgent(
        llm_service=_TypedFailureLLM(
            BudgetExceededError("token ceiling", dimension="tokens")
        ),
        analysis_batch_size=2,
        analysis_token_budget=None,
    ).analyze("title", "content", _comments(2), [], "note-budget")
    assert budget_result.gaps[0].code == "budget_tokens_exhausted"
    assert budget_result.gaps[0].retryable is False
    assert budget_result.gaps[0].details["failure_kind"] == "budget_tokens_exhausted"

    timeout_result = await AnalyzerAgent(
        llm_service=_TypedFailureLLM(ResourceCallTimeoutError("deadline")),
        analysis_batch_size=2,
        analysis_token_budget=None,
    ).analyze("title", "content", _comments(2), [], "note-timeout")
    assert timeout_result.gaps[0].code == "resource_timeout"
    assert timeout_result.gaps[0].retryable is True
