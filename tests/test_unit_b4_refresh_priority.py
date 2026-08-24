"""B4 continuous-refresh public priority policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xhs_food.contracts import (
    RefreshPriorityPolicy,
    RefreshPriorityReason,
    RefreshPrioritySignals,
)
from xhs_food.evidence import ContinuousRefreshCoordinator

NOW = datetime(2026, 8, 24, tzinfo=UTC)


@pytest.mark.unit
def test_refresh_priority_records_all_public_reasons_deterministically() -> None:
    coordinator = ContinuousRefreshCoordinator()
    decision = coordinator.decide(
        RefreshPrioritySignals(
            family_id="family.hot",
            observed_at=NOW,
            popularity_score=0.9,
            expires_at=NOW + timedelta(minutes=10),
            current_coverage=0.7,
            previous_coverage=0.9,
            source_watermark_advanced=True,
            has_new_source=True,
            has_new_time_window=True,
            feedback_subject_count=25,
            feedback_change_score=0.5,
        )
    )

    assert decision.priority == 200
    assert decision.reasons == (
        RefreshPriorityReason.POPULAR,
        RefreshPriorityReason.EXPIRING,
        RefreshPriorityReason.COVERAGE_DECLINE,
        RefreshPriorityReason.SOURCE_WATERMARK_ADVANCED,
        RefreshPriorityReason.NEW_SOURCE,
        RefreshPriorityReason.NEW_TIME_WINDOW,
        RefreshPriorityReason.PRIVACY_SAFE_FEEDBACK,
    )


@pytest.mark.unit
def test_feedback_below_privacy_threshold_cannot_schedule_refresh() -> None:
    coordinator = ContinuousRefreshCoordinator(
        RefreshPriorityPolicy(feedback_min_subjects=20)
    )
    decision = coordinator.decide(
        RefreshPrioritySignals(
            family_id="family.private",
            observed_at=NOW,
            feedback_subject_count=19,
            feedback_change_score=1.0,
        )
    )

    assert decision.eligible is False
    assert decision.priority == 0
    assert decision.reasons == ()
    assert {"user_id", "session_id", "preference"}.isdisjoint(
        RefreshPrioritySignals.model_fields
    )


@pytest.mark.unit
def test_refresh_candidates_rank_by_priority_then_stable_family_id() -> None:
    coordinator = ContinuousRefreshCoordinator()
    decisions = coordinator.rank(
        (
            RefreshPrioritySignals(
                family_id="family.b",
                observed_at=NOW,
                source_watermark_advanced=True,
            ),
            RefreshPrioritySignals(
                family_id="family.a",
                observed_at=NOW,
                source_watermark_advanced=True,
            ),
            RefreshPrioritySignals(family_id="family.none", observed_at=NOW),
        )
    )

    assert tuple(item.family_id for item in decisions) == ("family.a", "family.b")
