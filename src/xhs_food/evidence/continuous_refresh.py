"""Public-signal refresh priority without user-specific scheduling data."""

from __future__ import annotations

from datetime import timedelta

from xhs_food.contracts import (
    RefreshPriorityDecision,
    RefreshPriorityPolicy,
    RefreshPriorityReason,
    RefreshPrioritySignals,
)


class ContinuousRefreshCoordinator:
    """Rank refresh candidates using versioned public scheduling policy."""

    def __init__(self, policy: RefreshPriorityPolicy | None = None) -> None:
        self._policy = policy or RefreshPriorityPolicy()

    @property
    def policy(self) -> RefreshPriorityPolicy:
        return self._policy

    def decide(self, signals: RefreshPrioritySignals) -> RefreshPriorityDecision:
        policy = self._policy
        reasons: list[RefreshPriorityReason] = []
        priority = 0

        if signals.popularity_score >= policy.popular_threshold:
            reasons.append(RefreshPriorityReason.POPULAR)
            priority += policy.popular_weight
        if (
            signals.expires_at is not None
            and signals.expires_at
            <= signals.observed_at + timedelta(seconds=policy.expiring_within_seconds)
        ):
            reasons.append(RefreshPriorityReason.EXPIRING)
            priority += policy.expiring_weight
        coverage_decline = signals.previous_coverage - signals.current_coverage
        if coverage_decline >= policy.coverage_decline_threshold:
            reasons.append(RefreshPriorityReason.COVERAGE_DECLINE)
            priority += policy.coverage_decline_weight
        if signals.source_watermark_advanced:
            reasons.append(RefreshPriorityReason.SOURCE_WATERMARK_ADVANCED)
            priority += policy.watermark_weight
        if signals.has_new_source:
            reasons.append(RefreshPriorityReason.NEW_SOURCE)
            priority += policy.new_source_weight
        if signals.has_new_time_window:
            reasons.append(RefreshPriorityReason.NEW_TIME_WINDOW)
            priority += policy.new_time_window_weight
        if (
            signals.feedback_subject_count >= policy.feedback_min_subjects
            and signals.feedback_change_score >= policy.feedback_change_threshold
        ):
            reasons.append(RefreshPriorityReason.PRIVACY_SAFE_FEEDBACK)
            priority += policy.feedback_weight

        return RefreshPriorityDecision(
            family_id=signals.family_id,
            policy_version=policy.policy_version,
            priority=priority,
            eligible=bool(reasons),
            reasons=tuple(reasons),
        )

    def rank(
        self, candidates: tuple[RefreshPrioritySignals, ...]
    ) -> tuple[RefreshPriorityDecision, ...]:
        decisions = (self.decide(signals) for signals in candidates)
        return tuple(
            sorted(
                (decision for decision in decisions if decision.eligible),
                key=lambda item: (-item.priority, item.family_id),
            )
        )


__all__ = ["ContinuousRefreshCoordinator"]
