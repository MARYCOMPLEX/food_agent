"""Deterministic semantic planner for the single Food Research Agent.

The planner describes *work* in the versioned action vocabulary.  It never
selects a provider tool name and it never calls an LLM.  Provider capability
validation and execution remain responsibilities of :class:`ResearchRuntime`.
"""

from __future__ import annotations

from dataclasses import dataclass

from xhs_food.contracts import (
    ExpandResearch,
    ResearchState,
    SearchNotes,
    SemanticAction,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    """A bounded planner decision suitable for audit/progress metadata."""

    actions: tuple[SemanticAction, ...]
    reason: str
    replan_index: int = 0


class ResearchPlanner:
    """Create a small, reproducible semantic action plan.

    Search variants are intentionally compact.  The comment-first source
    collector owns cursor pagination; the planner only decides whether to
    start another bounded search wave after observing a typed gap.
    """

    def __init__(
        self,
        *,
        max_queries: int = 3,
        max_replans: int = 1,
    ) -> None:
        self.max_queries = max(1, int(max_queries))
        self.max_replans = max(0, int(max_replans))

    def initial(self, intent: FoodSearchIntent, *, run_id: str = "run") -> PlannerDecision:
        queries = self._queries(intent)
        action = SearchNotes(
            action_id=f"{run_id}:search:0",
            idempotency_key=f"{run_id}:search:0",
            queries=queries,
            reason="initial comment-first XHS search",
            inputs={"query_variants": list(queries)},
        )
        return PlannerDecision(
            actions=(action,),
            reason="initial comment-first search",
        )

    # Common aliases make the planner convenient at composition boundaries.
    plan = initial
    initial_plan = initial

    def replan(
        self,
        intent: FoodSearchIntent,
        state: ResearchState,
        *,
        run_id: str | None = None,
    ) -> PlannerDecision:
        """Emit at most one new search wave for an incomplete run.

        A replan is only useful when the state contains a typed gap and the
        configured bound has not been reached.  Existing query variants and
        action ids are excluded deterministically, so retrying this method is
        idempotent for a given state.
        """

        if state.replans >= self.max_replans:
            return PlannerDecision(actions=(), reason="replan budget exhausted", replan_index=state.replans)
        if not any(
            bool(gap.get("retryable", False) if isinstance(gap, dict) else gap.retryable)
            for gap in state.gaps
        ):
            return PlannerDecision(actions=(), reason="no typed gap requires expansion", replan_index=state.replans)

        existing_queries = {
            str(envelope.provenance.get("query"))
            for envelope in state.source_envelopes
            if envelope.provenance.get("query")
        }
        for envelope in state.source_envelopes:
            raw_queries = envelope.provenance.get("queries")
            if isinstance(raw_queries, (list, tuple)):
                existing_queries.update(
                    str(query) for query in raw_queries if str(query).strip()
                )
        # Keep expansion variants outside the initial query budget.  Otherwise
        # the default three initial variants exhaust the planner's own query
        # list and a retryable collection gap can never produce an expansion.
        candidates = tuple(
            query
            for query in self._expansion_queries(intent)
            if query not in existing_queries
        )
        # Add one high-information variant only; expansion must remain cheap.
        if not candidates:
            return PlannerDecision(actions=(), reason="no unseen query variant", replan_index=state.replans)
        selected = candidates[:1]
        effective_run_id = run_id or state.run_id
        index = state.replans + 1
        action = ExpandResearch(
            action_id=f"{effective_run_id}:expand:{index}",
            idempotency_key=f"{effective_run_id}:expand:{index}",
            query_variants=selected,
            dependencies=tuple(state.completed_action_ids),
            reason="typed collection gap requires one additional query",
            inputs={"query_variants": list(selected)},
        )
        return PlannerDecision(
            actions=(action,),
            reason=action.reason,
            replan_index=index,
        )

    def _queries(self, intent: FoodSearchIntent) -> tuple[str, ...]:
        return self._query_variants(intent)[: self.max_queries]

    def _query_variants(self, intent: FoodSearchIntent) -> tuple[str, ...]:
        base = " ".join(
            str(value).strip()
            for value in (intent.location, intent.food_type)
            if value and str(value).strip()
        )
        if not base:
            base = str(intent.location).strip()
        variants: list[str] = [base]
        if intent.requirements:
            variants.append(f"{base} {' '.join(intent.requirements[:2])}".strip())
        variants.append(f"{base} 争议 避雷".strip())
        return tuple(dict.fromkeys(item for item in variants if item))

    def _expansion_queries(self, intent: FoodSearchIntent) -> tuple[str, ...]:
        """Return deterministic, high-information variants reserved for gaps."""

        base = self._query_variants(intent)
        if not base:
            return ()
        root = base[0]
        variants = (
            f"{root} 真实评价",
            f"{root} 本地人推荐",
            f"{root} 菜品推荐",
        )
        return tuple(dict.fromkeys(item.strip() for item in variants if item.strip()))


__all__ = ["PlannerDecision", "ResearchPlanner"]
