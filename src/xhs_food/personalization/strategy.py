"""Resolve versioned, private research strategy from personalization feedback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from xhs_food.contracts import ContractPayload, PreferenceSnapshot, ResearchStrategy


class ResearchStrategyResolver:
    """Keep strategy feedback out of Query Family and public evidence identity."""

    def resolve(
        self,
        snapshot: PreferenceSnapshot,
        *,
        strategy_id: str,
        strategy_version: str,
        default_research_depth: str = "fast",
        default_source_priority: Sequence[str] = (),
        default_stopping_conditions: Mapping[str, object] | None = None,
        selected_source_subset: Sequence[str] = (),
    ) -> ResearchStrategy:
        feedback = snapshot.strategy_feedback
        research_depth = _feedback_scalar(feedback.get("research_depth")) or default_research_depth
        if research_depth not in {"fast", "deep"}:
            raise ValueError("research_depth must be fast or deep")

        source_priority = tuple(default_source_priority)
        selected_subset = tuple(selected_source_subset)
        source_feedback = feedback.get("source_trust")
        if isinstance(source_feedback, Mapping):
            source_priority = _string_tuple(
                source_feedback.get("sourcePriority")
                or source_feedback.get("priority")
                or source_priority
            )
            if not selected_subset:
                selected_subset = _string_tuple(source_feedback.get("selectedSources", ()))
        elif source_feedback is not None:
            source_priority = _string_tuple(source_feedback)

        hard_filters: ContractPayload = dict(snapshot.session_requirements)
        hard_filters.update(snapshot.explicit_hard_constraints)
        return ResearchStrategy(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            isolation_key=snapshot.isolation_key,
            preference_snapshot_id=snapshot.snapshot_id,
            preference_snapshot_version=snapshot.snapshot_version,
            research_depth=research_depth,
            source_priority=_dedupe(source_priority),
            selected_source_subset=_dedupe(selected_subset),
            stopping_conditions=dict(default_stopping_conditions or {}),
            hard_filters=hard_filters,
        )


def _feedback_scalar(value: object) -> str | None:
    if isinstance(value, Mapping):
        candidate = value.get("value")
        return candidate if isinstance(candidate, str) and candidate else None
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if not all(isinstance(item, str) and item for item in value):
            raise ValueError("strategy source selection must contain non-empty strings")
        return tuple(value)
    raise ValueError("strategy source selection must be a string or sequence")


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = ["ResearchStrategyResolver"]
