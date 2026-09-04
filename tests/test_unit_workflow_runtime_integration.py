"""The active workflow must use one run-scoped semantic runtime."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.agents.analyzer import AnalyzeResult
from xhs_food.agents.intent_parser import IntentParseResult
from xhs_food.contracts import (
    AgentToolExecutionContext,
    CommentEvidence,
    CommentIdentity,
    CommentInsight,
    CommentSentiment,
    PlatformChannel,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research import ResearchRuntime
from xhs_food.research import workflow as workflow_module
from xhs_food.research.workflow import CommentFirstResearchWorkflow
from xhs_food.schemas import ConversationContext, RestaurantRecommendation


def _note(note_id: str) -> XhsNoteLead:
    return XhsNoteLead(
        note_id=note_id,
        title=note_id,
        summary="评论摘要",
        comments=(
            CommentEvidence(
                note_id=note_id,
                comment_id=f"{note_id}-comment",
                text="老客说这家店值得去",
                raw_payload={"opaque": note_id},
            ),
        ),
        comment_count=1,
        comment_collected_count=1,
        raw_payload={"note": note_id},
    )


class _Parser:
    async def parse(self, _: str, __: ConversationContext) -> IntentParseResult:
        return IntentParseResult(True, FoodSearchIntent(location="成都", food_type="火锅"))


class _Session:
    snapshot = None

    async def open(self, _: AgentToolExecutionContext) -> None:
        return

    async def close(self) -> None:
        return


class _Collector:
    def __init__(self, _: Any, *, max_notes: int) -> None:
        self._notes = tuple(_note(f"note-{index}") for index in range(1, max_notes + 1))
        self.last_stream_result = None

    async def iter_notes(self, _: FoodSearchIntent, *, queries: tuple[str, ...] | None = None):
        _ = queries
        for note in self._notes:
            yield note


class _Analyzer:
    async def analyze(
        self,
        _: str,
        __: str,
        ___: list[Any],
        ____: list[str],
        note_id: str,
    ) -> AnalyzeResult:
        sentiment = (
            CommentSentiment.POSITIVE
            if note_id == "note-1"
            else CommentSentiment.NEGATIVE
        )
        insight = CommentInsight(
            note_id=note_id,
            comment_id=f"{note_id}-comment",
            identity=CommentIdentity.STRONG,
            sentiment=sentiment,
            mentioned_shops=("同一家店",),
            evidence_refs=(f"xhs:note:{note_id}:comment:{note_id}-comment",),
        )
        return AnalyzeResult(
            success=True,
            restaurants=[
                RestaurantRecommendation(
                    name="同一家店",
                    source_notes=[note_id],
                    features=["评论线索"],
                )
            ],
            insights=[insight],
        )


@pytest.mark.asyncio
async def test_workflow_routes_collection_and_notes_through_one_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _Collector)
    runtimes: list[ResearchRuntime] = []
    progress: list[dict[str, Any]] = []

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    workflow = CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=_Analyzer(),
        max_notes=2,
        max_restaurants=2,
        analysis_concurrency=2,
        runtime_factory=runtime_factory,
    )
    execution = await workflow.execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
        progress_sink=progress.append,
    )

    assert len(runtimes) == 1
    runtime = runtimes[0]
    assert runtime.state is not None
    assert runtime.state.run_id.startswith("food-research:")
    assert runtime.state.in_flight_action_ids == ()
    assert any(item.event_type.value == "action_started" for item in runtime.events)
    assert any(item.event_type.value == "action_completed" for item in runtime.events)
    assert any(item.get("kind") == "runtime_event" for item in progress)
    assert execution.run.raw_payload["runtime"]["event_count"] == len(runtime.events)
    assert execution.run.raw_payload["controversies"][0]["kind"] == "mixed_sentiment"
    assert execution.response.research_metadata["commentInsightCount"] == 2
