"""Unit tests for :class:`xhs_food.agents.analyzer.AnalyzerAgent`.

These tests verify the 3-stage pipeline end-to-end with a stubbed LLM
and a small, deterministic comment list. The focus is the WanghongScore
mapping the agent applies on top of the scoring service.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.schemas import WanghongScore


def _build_comments(texts: List[str]) -> List[Dict[str, Any]]:
    """Build a tiny set of comment dicts the preprocessor accepts."""
    return [{"text": t, "likes": 100} for t in texts]


# ---------------------------------------------------------------------------
# DEFINITELY_LOCAL mapping
# ---------------------------------------------------------------------------


async def test_pipeline_marks_strong_local_endorsement_as_definitely_local(
    mock_llm,
) -> None:
    # Arrange — two local-strong endorsements of the same shop
    comments = _build_comments(["本地人推荐XX老店", "我家就在附近，XX老店真不错"])

    llm_results = {
        "results": [
            {
                "id": "c0",
                "identity": "strong",
                "sentiment": "positive",
                "is_correction": False,
                "mentioned_shops": ["XX老店"],
            },
            {
                "id": "c1",
                "identity": "strong",
                "sentiment": "positive",
                "is_correction": False,
                "mentioned_shops": ["XX老店"],
            },
        ]
    }
    mock_llm.set_response(json.dumps(llm_results, ensure_ascii=False))
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="成都美食",
        content="分享几家本地店",
        comments=comments,
        exclude_keywords=[],
        note_id="note-1",
    )

    # Assert
    assert result.success is True
    assert len(result.restaurants) == 1
    rec = result.restaurants[0]
    assert rec.name == "XX老店"
    assert rec.wanghong_analysis is not None
    assert rec.wanghong_analysis.score == WanghongScore.DEFINITELY_LOCAL
    assert rec.wanghong_analysis.confidence == 0.9
    assert rec.is_recommended is True
    assert rec.source_notes == ["note-1"]


# ---------------------------------------------------------------------------
# LIKELY_LOCAL mapping (one local mention, moderate score)
# ---------------------------------------------------------------------------


async def test_pipeline_marks_single_local_signal_as_likely_local(mock_llm) -> None:
    # Arrange — single comment, medium-likes → still triggers >5 total_score
    # (interaction 2.0 × identity 3.0 × content 1.0 = 6.0)
    comments = _build_comments(["本地人都吃YY店"])
    llm_results = {
        "results": [
            {
                "id": "c0",
                "identity": "strong",
                "sentiment": "positive",
                "is_correction": False,
                "mentioned_shops": ["YY店"],
            }
        ]
    }
    mock_llm.set_response(json.dumps(llm_results, ensure_ascii=False))
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="t", content="c", comments=comments, exclude_keywords=[], note_id="n1"
    )

    # Assert
    assert result.success is True
    rec = result.restaurants[0]
    assert rec.wanghong_analysis.score == WanghongScore.LIKELY_LOCAL
    assert rec.wanghong_analysis.confidence == 0.75


# ---------------------------------------------------------------------------
# UNKNOWN (no local identity, no correction) — recommended by default
# ---------------------------------------------------------------------------


async def test_pipeline_defaults_to_unknown_without_local_signals(
    mock_llm,
) -> None:
    # Arrange — two non-local comments, sentiment negative. The scoring
    # service does not currently increment positive_count/negative_count
    # from sentiment, so the mapping falls through to UNKNOWN.
    comments = _build_comments(["ZZ店踩雷", "ZZ店难吃"])
    llm_results = {
        "results": [
            {
                "id": "c0",
                "identity": "none",
                "sentiment": "negative",
                "is_correction": False,
                "mentioned_shops": ["ZZ店"],
            },
            {
                "id": "c1",
                "identity": "none",
                "sentiment": "negative",
                "is_correction": False,
                "mentioned_shops": ["ZZ店"],
            },
        ]
    }
    mock_llm.set_response(json.dumps(llm_results, ensure_ascii=False))
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="t", content="c", comments=comments, exclude_keywords=[], note_id="n1"
    )

    # Assert
    rec = result.restaurants[0]
    assert rec.wanghong_analysis.score == WanghongScore.UNKNOWN
    assert rec.wanghong_analysis.confidence == 0.5
    # UNKNOWN is not in the wanghong filter set, so still recommended.
    assert rec.is_recommended is True


# ---------------------------------------------------------------------------
# Empty comments → success with empty restaurants list
# ---------------------------------------------------------------------------


async def test_pipeline_returns_empty_when_no_comments(mock_llm) -> None:
    # Arrange
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="t", content="c", comments=[], exclude_keywords=[], note_id="n1"
    )

    # Assert — short-circuits without calling the LLM
    assert result.success is True
    assert result.restaurants == []
    assert mock_llm.calls == []


# ---------------------------------------------------------------------------
# Exclude keyword causes filter_reason to be set
# ---------------------------------------------------------------------------


async def test_pipeline_excludes_shops_matching_keyword(mock_llm) -> None:
    # Arrange
    comments = _build_comments(["本地人推荐 WangHongStore"])
    llm_results = {
        "results": [
            {
                "id": "c0",
                "identity": "strong",
                "sentiment": "positive",
                "is_correction": False,
                "mentioned_shops": ["WangHongStore"],
            }
        ]
    }
    mock_llm.set_response(json.dumps(llm_results, ensure_ascii=False))
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="t",
        content="c",
        comments=comments,
        exclude_keywords=["wanghong"],  # case-insensitive
        note_id="n1",
    )

    # Assert
    rec = result.restaurants[0]
    assert rec.is_recommended is False
    assert rec.filter_reason == "匹配用户排除关键词"


# ---------------------------------------------------------------------------
# Malformed LLM output → failure
# ---------------------------------------------------------------------------


async def test_pipeline_returns_failure_for_unparseable_llm_output(mock_llm) -> None:
    # Arrange — non-JSON prose
    comments = _build_comments(["xxx"])
    mock_llm.set_response("LLM is currently unavailable, please retry.")
    agent = AnalyzerAgent(llm_service=mock_llm)

    # Act
    result = await agent.analyze(
        title="t", content="c", comments=comments, exclude_keywords=[], note_id="n1"
    )

    # Assert
    assert result.success is False
    assert result.error == "Failed to parse JSON from LLM output"
