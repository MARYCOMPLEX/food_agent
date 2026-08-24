"""B3 versioned research strategy and public-identity isolation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import MemoryRecord, UserIsolationKey
from xhs_food.personalization import PreferenceResolver, ResearchStrategyResolver

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"


def _snapshot():
    records = tuple(
        MemoryRecord.model_validate(item)
        for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["exampleRecords"][1:]
    )
    scope = UserIsolationKey(tenant_id="tenant-cn-1", user_id="user-2b4aa1b95c884d64")
    return PreferenceResolver().resolve(
        records,
        scope=scope,
        snapshot_id="snapshot-strategy",
        snapshot_version=2,
        policy_version="memory-policy/v1",
        generated_at=datetime(2026, 8, 24, tzinfo=UTC),
    )


@pytest.mark.unit
def test_strategy_uses_feedback_for_depth_but_keeps_hard_filters_and_identity_flags() -> None:
    strategy = ResearchStrategyResolver().resolve(
        _snapshot(),
        strategy_id="strategy-food",
        strategy_version="research-strategy/v1.1",
        default_stopping_conditions={"max_steps": 4, "require_evidence": True},
    )
    assert strategy.research_depth == "deep"
    assert strategy.hard_filters["diet.spice"]["hardConstraint"] is True
    assert strategy.stopping_conditions["max_steps"] == 4
    assert strategy.mutates_query_family_identity is False
    assert strategy.mutates_public_evidence is False
    assert strategy.public_refresh_influence is False


@pytest.mark.unit
def test_strategy_feedback_can_prioritize_sources_without_granting_access() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "strategy_feedback": {
                "source_trust": {
                    "dimension": "source_trust",
                    "value": "reviews.search",
                    "sourcePriority": ["reviews.search", "place.lookup"],
                    "selectedSources": ["reviews.search"],
                }
            }
        }
    )
    strategy = ResearchStrategyResolver().resolve(
        snapshot,
        strategy_id="strategy-sources",
        strategy_version="research-strategy/v1.2",
    )
    assert strategy.source_priority == ("reviews.search", "place.lookup")
    assert strategy.selected_source_subset == ("reviews.search",)


@pytest.mark.unit
def test_strategy_rejects_unknown_depth_instead_of_silently_changing_workflow() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "strategy_feedback": {
                "research_depth": {"dimension": "research_depth", "value": "unbounded"}
            }
        }
    )
    with pytest.raises(ValueError, match="fast or deep"):
        ResearchStrategyResolver().resolve(
            snapshot,
            strategy_id="strategy-invalid",
            strategy_version="research-strategy/v1.3",
        )

