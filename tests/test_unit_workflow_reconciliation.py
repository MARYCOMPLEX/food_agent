"""Regression coverage for late comments in the terminal collector snapshot."""

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
from xhs_food.research import workflow as workflow_module
from xhs_food.research.evidence import evidence_ref
from xhs_food.research.sources import LeadCollectionResult
from xhs_food.research.workflow import CommentFirstResearchWorkflow
from xhs_food.schemas import ConversationContext, RestaurantRecommendation


def _comment(note_id: str, comment_id: str, text: str) -> CommentEvidence:
    return CommentEvidence(
        note_id=note_id,
        comment_id=comment_id,
        text=text,
        raw_payload={"provider_comment": comment_id},
    )


class _Parser:
    async def parse(self, _: str, __: ConversationContext) -> IntentParseResult:
        return IntentParseResult(
            True,
            FoodSearchIntent(location="成都", food_type="火锅"),
        )


class _Session:
    async def open(self, _: AgentToolExecutionContext) -> None:
        return None

    async def close(self) -> None:
        return None


class _LateCommentCollector:
    def __init__(self, _: Any, *, max_notes: int) -> None:
        _ = max_notes
        note_id = "note-late"
        early_comment = _comment(note_id, "comment-early", "先到的评论")
        late_comment = _comment(note_id, "comment-late", "迟到的评论提到晚到店")
        self._early = XhsNoteLead(
            note_id=note_id,
            title="成都火锅实测",
            summary="评论区线索",
            comments=(early_comment,),
            comment_count=2,
            comment_collected_count=1,
            raw_payload={"note": "early"},
        )
        self._final = self._early.model_copy(
            update={
                "comments": (early_comment, late_comment),
                "comment_collected_count": 2,
                "raw_payload": {"note": "final", "late_search": True},
            }
        )
        self.last_stream_result: LeadCollectionResult | None = None

    async def iter_notes(
        self,
        _: FoodSearchIntent,
        *,
        queries: tuple[str, ...] | None = None,
    ):
        _ = queries
        # The workflow starts evidence and analysis from this early snapshot.
        yield self._early
        # The collector's terminal projection contains one additional comment
        # discovered by a slower search variant.
        self.last_stream_result = LeadCollectionResult(
            notes=(self._final,),
            raw_payload={"search": [{"variant": "late"}]},
        )


class _Analyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def analyze(
        self,
        _: str,
        __: str,
        comments: list[dict[str, Any]],
        ___: list[str],
        note_id: str,
    ) -> AnalyzeResult:
        comment_ids = tuple(str(comment["comment_id"]) for comment in comments)
        self.calls.append(comment_ids)
        insights: list[CommentInsight] = []
        recommendations: list[RestaurantRecommendation] = []
        if "comment-late" in comment_ids:
            late_ref = evidence_ref(
                _comment(note_id, "comment-late", "迟到的评论提到晚到店")
            )
            insights.append(
                CommentInsight(
                    note_id=note_id,
                    comment_id="comment-late",
                    identity=CommentIdentity.STRONG,
                    sentiment=CommentSentiment.POSITIVE,
                    mentioned_shops=("晚到店",),
                    evidence_refs=(late_ref,),
                )
            )
            recommendations.append(
                RestaurantRecommendation(
                    name="晚到店",
                    source_notes=[note_id],
                    features=["迟到评论线索"],
                )
            )
        return AnalyzeResult(
            success=True,
            restaurants=recommendations,
            raw_comments=comments,
            insights=insights,
        )


@pytest.mark.asyncio
async def test_terminal_stream_delta_enters_evidence_and_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = _Analyzer()
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _LateCommentCollector)

    workflow = CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=analyzer,
        max_notes=1,
        max_restaurants=3,
    )
    execution = await workflow.execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    late_ref = "xhs:note:note-late:comment:comment-late"
    assert analyzer.calls == [("comment-early",), ("comment-late",)]
    assert len(execution.run.notes) == 1
    assert [comment.comment_id for comment in execution.run.notes[0].comments] == [
        "comment-early",
        "comment-late",
    ]
    assert execution.run.evidence_refs == (
        "xhs:note:note-late:comment:comment-early",
        late_ref,
    )
    assert workflow.evidence.get(late_ref) is not None
    assert execution.run.insights
    assert any(insight["comment_id"] == "comment-late" for insight in execution.run.insights)
    assert execution.run.raw_payload["analysis"][-1]["reconciliation"]["reconciliation"] is True


@pytest.mark.asyncio
async def test_reconciliation_reanalyzes_an_updated_comment_with_the_same_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider correction is a new evidence version, not an exact replay."""

    note_id = "note-corrected"
    early_comment = _comment(note_id, "comment-same", "先说一般")
    changed_comment = _comment(note_id, "comment-same", "回访后很惊艳")
    early = XhsNoteLead(
        note_id=note_id,
        title="成都火锅实测",
        comments=(early_comment,),
        comment_count=1,
        comment_collected_count=1,
        raw_payload={"note": "early"},
    )
    final = early.model_copy(
        update={
            "comments": (changed_comment,),
            "raw_payload": {"note": "corrected"},
        }
    )

    class CorrectedCollector:
        def __init__(self, _: Any, *, max_notes: int) -> None:
            _ = max_notes
            self.last_stream_result: LeadCollectionResult | None = None

        async def iter_notes(self, _: FoodSearchIntent, *, queries: tuple[str, ...] | None = None):
            _ = queries
            yield early
            self.last_stream_result = LeadCollectionResult(notes=(final,))

    class CorrectedAnalyzer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def analyze(
            self,
            _: str,
            __: str,
            comments: list[dict[str, Any]],
            ___: list[str],
            note_id: str,
        ) -> AnalyzeResult:
            self.calls.extend((note_id, str(item["text"])) for item in comments)
            return AnalyzeResult(success=True, raw_comments=comments)

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", CorrectedCollector)
    analyzer = CorrectedAnalyzer()
    workflow = CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=analyzer,
        max_notes=1,
    )
    execution = await workflow.execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert analyzer.calls == [
        (note_id, "先说一般"),
        (note_id, "回访后很惊艳"),
    ]
    assert execution.run.notes[0].comments[0].text == "回访后很惊艳"
    record = workflow.evidence.records[0]
    assert len(record.versions) == 2
    assert [version.text for version in record.history] == ["先说一般"]
