"""Pure planner and controversy reducer tests."""

from __future__ import annotations

from xhs_food.contracts import CommentInsight, CommentSentiment, InsightClaim, ResearchState
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research import EntityControversyAggregator, ResearchPlanner


def _insight(comment_id: str, sentiment: CommentSentiment, *, correction: bool = False) -> CommentInsight:
    ref = f"xhs:note:n1:comment:{comment_id}"
    return CommentInsight(
        note_id="n1",
        comment_id=comment_id,
        sentiment=sentiment,
        is_correction=correction,
        mentioned_shops=(" 老店 ",),
        mentioned_dishes=("毛肚",),
        evidence_refs=(ref,),
        claims=(
            InsightClaim(
                claim_id=f"claim-{comment_id}",
                text="评论中的事实",
                evidence_refs=(ref,),
            ),
        ),
    )


def test_planner_emits_only_one_initial_semantic_action_and_bounds_replan() -> None:
    planner = ResearchPlanner(max_queries=3, max_replans=1)
    intent = FoodSearchIntent(location="成都", food_type="火锅")
    initial = planner.initial(intent, run_id="run-1")
    assert len(initial.actions) == 1
    assert initial.actions[0].kind.value == "SearchNotes"
    state = ResearchState(run_id="run-1", replans=0)
    state = state.model_copy(
        update={
            "gaps": (
                {"source": "xhs", "operation": "notes.search", "code": "partial"},
            )
        }
    )
    # Pydantic re-validates the mapping above to a typed gap on model copy.
    decision = planner.replan(intent, state)
    assert len(decision.actions) <= 1
    assert planner.replan(intent, state.model_copy(update={"replans": 1})).actions == ()


def test_aggregator_is_deterministic_and_keeps_disagreement_refs() -> None:
    values = (
        _insight("c2", CommentSentiment.NEGATIVE),
        _insight("c1", CommentSentiment.POSITIVE),
        _insight("c3", CommentSentiment.NEUTRAL, correction=True),
    )
    result = EntityControversyAggregator().aggregate(reversed(values))
    assert [item.comment_id for item in result.insights] == ["c1", "c2", "c3"]
    assert result.entities[0]["mention_count"] == 3
    assert result.entities[0]["evidence_refs"] == sorted(
        [item.evidence_refs[0] for item in values]
    )
    assert result.controversies[0]["kind"] == "correction"
    assert result.controversies[0]["positive_evidence_refs"]
    assert result.controversies[0]["negative_evidence_refs"]
