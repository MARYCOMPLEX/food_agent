"""Streaming integration tests for the single comment-first workflow."""

from __future__ import annotations

import asyncio
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
    ResearchGap,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research import workflow as workflow_module
from xhs_food.research.runtime import ResearchRuntimeConfig
from xhs_food.research.sources import LeadCollectionResult
from xhs_food.research.workflow import CommentFirstResearchWorkflow
from xhs_food.schemas import ConversationContext, RestaurantRecommendation


def _note(note_id: str) -> XhsNoteLead:
    return XhsNoteLead(
        note_id=note_id,
        title=f"标题 {note_id}",
        summary=f"摘要 {note_id}",
        comments=(
            CommentEvidence(
                note_id=note_id,
                comment_id=f"{note_id}-comment",
                text=f"评论 {note_id}",
                raw_payload={"opaque": note_id},
            ),
        ),
        comment_count=1,
        comment_collected_count=1,
        raw_payload={"note_raw": note_id},
    )


class _Parser:
    async def parse(self, _: str, __: ConversationContext) -> IntentParseResult:
        return IntentParseResult(True, FoodSearchIntent(location="成都", food_type="火锅"))


class _Session:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self, _: AgentToolExecutionContext) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _StreamingCollector:
    def __init__(
        self,
        _: Any,
        *,
        max_notes: int,
        events: list[str],
        analysis_started: asyncio.Event,
    ) -> None:
        self._notes = tuple(_note(f"note-{index}") for index in range(1, max_notes + 1))
        self._events = events
        self._analysis_started = analysis_started
        self.last_stream_result: LeadCollectionResult | None = None

    async def iter_notes(self, _: FoodSearchIntent):
        emitted: list[XhsNoteLead] = []
        self.last_stream_result = None
        try:
            for index, note in enumerate(self._notes):
                if index == 1:
                    await asyncio.wait_for(self._analysis_started.wait(), timeout=1)
                self._events.append(f"yield:{note.note_id}")
                emitted.append(note)
                yield note
        finally:
            self.last_stream_result = LeadCollectionResult(
                notes=tuple(emitted),
                gaps=(
                    ResearchGap(
                        source="xhs",
                        operation="notes.search",
                        code="search_warning",
                        message="provider returned a non-fatal warning",
                    ),
                ),
                raw_payload={
                    "queries": ["成都 火锅"],
                    "search": [{"opaque_search": True}],
                },
            )


class _Analyzer:
    def __init__(self, events: list[str], first_started: asyncio.Event) -> None:
        self.events = events
        self.first_started = first_started
        self.active = 0
        self.maximum_active = 0
        self.calls: list[str] = []

    async def analyze(
        self,
        _: str,
        __: str,
        comments: list[Any],
        ___: list[str],
        note_id: str,
    ) -> AnalyzeResult:
        self.calls.append(note_id)
        self.events.append(f"analyze:{note_id}")
        self.first_started.set()
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0.01)
            gap = (
                ResearchGap(
                    source="agent",
                    operation="comments.analyze",
                    code="one_batch_partial",
                    message="one comment batch was incomplete",
                    retryable=True,
                    details={"note_id": note_id},
                )
                if note_id == "note-2"
                else None
            )
            return AnalyzeResult(
                success=True,
                restaurants=[
                    RestaurantRecommendation(
                        name=f"店铺 {note_id}",
                        source_notes=[note_id],
                        features=["评论线索"],
                    )
                ],
                raw_output=f'{{"note_id": "{note_id}"}}',
                raw_comments=comments,
                gaps=(gap,) if gap else (),
                partial=gap is not None,
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_workflow_streams_note_into_analysis_and_preserves_raw_and_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first_analysis_started = asyncio.Event()
    analyzer = _Analyzer(events, first_analysis_started)
    session = _Session()
    collector_instances: list[_StreamingCollector] = []

    def collector_factory(source: Any, *, max_notes: int) -> _StreamingCollector:
        collector = _StreamingCollector(
            source,
            max_notes=max_notes,
            events=events,
            analysis_started=first_analysis_started,
        )
        collector_instances.append(collector)
        return collector

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", collector_factory)
    workflow = CommentFirstResearchWorkflow(
        session_factory=lambda: session,
        intent_parser=_Parser(),
        analyzer=analyzer,
        max_notes=3,
        max_restaurants=5,
        analysis_concurrency=2,
        note_queue_size=1,
    )

    execution = await workflow.execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert session.opened and session.closed
    assert len(collector_instances) == 1
    assert events.index("analyze:note-1") < events.index("yield:note-2")
    assert analyzer.maximum_active <= 2
    assert analyzer.calls == ["note-1", "note-2", "note-3"]
    assert [note.note_id for note in execution.run.notes] == [
        "note-1",
        "note-2",
        "note-3",
    ]
    assert len(execution.run.evidence_refs) == 3
    assert execution.run.raw_payload["xhs"]["search"] == [{"opaque_search": True}]
    assert [item["note_id"] for item in execution.run.raw_payload["analysis"]] == [
        "note-1",
        "note-2",
        "note-3",
    ]
    assert any(gap.code == "search_warning" for gap in execution.run.gaps)
    assert any(gap.code == "one_batch_partial" for gap in execution.run.gaps)
    assert execution.run.outcome.value == "partial"
    assert [item.name for item in execution.response.recommendations] == [
        "店铺 note-1",
        "店铺 note-2",
        "店铺 note-3",
    ]


@pytest.mark.asyncio
async def test_workflow_analyzes_a_late_top_k_replacement_before_final_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collector replacement is analyzed, while the early slot stays auditable."""

    low = _note("low-note")
    high = _note("high-note")

    class ReplacementCollector:
        def __init__(self, _: Any, *, max_notes: int) -> None:
            _ = max_notes
            self.last_stream_result: LeadCollectionResult | None = None

        async def iter_notes(self, _: FoodSearchIntent):
            yield low
            self.last_stream_result = LeadCollectionResult(
                notes=(high,),
                raw_payload={"search": [{"candidate": "high"}]},
            )

    monkeypatch.setattr(
        workflow_module,
        "XhsCommentLeadCollector",
        lambda source, *, max_notes: ReplacementCollector(source, max_notes=max_notes),
    )
    analyzer = _Analyzer([], asyncio.Event())
    execution = await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=analyzer,
        max_notes=1,
        max_restaurants=5,
        analysis_concurrency=2,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert analyzer.calls == ["low-note", "high-note"]
    assert [note.note_id for note in execution.run.notes] == ["high-note"]
    # The superseded early note remains in the evidence/audit projection.
    assert len(execution.run.evidence_refs) == 2
    assert any(item.get("superseded") for item in execution.run.raw_payload["analysis"])


@pytest.mark.asyncio
async def test_workflow_opens_one_bounded_expansion_for_retryable_collection_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retryable first-wave gap triggers one ordered, lossless expansion."""

    first = _note("note-1")
    second = _note("note-0")

    class TwoWaveCollector:
        def __init__(self, _: Any, *, max_notes: int) -> None:
            _ = max_notes
            self.calls: list[tuple[str, ...]] = []
            self.last_stream_result: LeadCollectionResult | None = None

        async def iter_notes(
            self,
            _: FoodSearchIntent,
            *,
            queries: tuple[str, ...] | None = None,
        ):
            current = tuple(queries or ())
            self.calls.append(current)
            if len(self.calls) == 1:
                self.last_stream_result = LeadCollectionResult(
                    notes=(first,),
                    gaps=(
                        ResearchGap(
                            source="xhs",
                            operation="notes.search",
                            code="search_partial",
                            message="one provider search variant was incomplete",
                            retryable=True,
                        ),
                    ),
                    raw_payload={
                        "queries": list(current),
                        "search": [{"wave": 1, "opaque": "first"}],
                    },
                )
                yield first
                return
            self.last_stream_result = LeadCollectionResult(
                notes=(second,),
                raw_payload={
                    "queries": list(current),
                    "search": [{"wave": 2, "opaque": "second"}],
                },
            )
            yield second

    collectors: list[TwoWaveCollector] = []

    def collector_factory(source: Any, *, max_notes: int) -> TwoWaveCollector:
        collector = TwoWaveCollector(source, max_notes=max_notes)
        collectors.append(collector)
        return collector

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", collector_factory)
    runtimes: list[Any] = []

    def runtime_factory(**kwargs: Any) -> Any:
        runtime = workflow_module.ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    execution = await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=_Analyzer([], asyncio.Event()),
        max_notes=2,
        max_restaurants=2,
        analysis_concurrency=2,
        runtime_config=ResearchRuntimeConfig(max_replans=1),
        runtime_factory=runtime_factory,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert len(collectors) == 1
    assert len(collectors[0].calls) == 2
    assert collectors[0].calls[1] == ("成都 火锅 真实评价",)
    assert [note.note_id for note in execution.run.notes] == ["note-1", "note-0"]
    assert [item["wave"] for item in execution.run.raw_payload["xhs"]["search"]] == [1, 2]
    assert len(execution.run.raw_payload["xhs"]["waves"]) == 2

    runtime = runtimes[0]
    assert runtime.state is not None
    assert runtime.state.replans == 1
    expansion_actions = [
        action
        for action in runtime.events
        if action.action_id and ":expand:" in action.action_id
    ]
    assert expansion_actions
    expansion_ids = {action.action_id for action in expansion_actions}
    assert len(expansion_ids) == 1
    assert ":expand:1" in next(iter(expansion_ids))


@pytest.mark.asyncio
async def test_workflow_reconciles_late_duplicate_note_comments_into_evidence_and_insights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late search envelope may add comments, but none may remain raw-only."""

    analysis_started = asyncio.Event()
    initial = _note("note-late")
    late_comment = CommentEvidence(
        note_id=initial.note_id,
        comment_id="note-late-comment-2",
        text="迟到搜索发现的争议评论",
        raw_payload={"late": True},
    )

    class LateSnapshotCollector:
        def __init__(self, _: Any, *, max_notes: int) -> None:
            _ = max_notes
            self.last_stream_result: LeadCollectionResult | None = None

        async def iter_notes(
            self,
            _: FoodSearchIntent,
            *,
            queries: tuple[str, ...] | None = None,
        ):
            _ = queries
            try:
                yield initial
                await analysis_started.wait()
            finally:
                late = initial.model_copy(
                    update={
                        "comments": (*initial.comments, late_comment),
                        "comment_count": 2,
                        "comment_collected_count": 2,
                        "raw_payload": {"late_search": True},
                    }
                )
                self.last_stream_result = LeadCollectionResult(
                    notes=(late,),
                    raw_payload={"search": [{"late": True}]},
                )

    class LateInsightAnalyzer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        async def analyze(
            self,
            _: str,
            __: str,
            comments: list[Any],
            ___: list[str],
            note_id: str,
        ) -> AnalyzeResult:
            ids = tuple(str(item["id"]) for item in comments)
            self.calls.append(ids)
            analysis_started.set()
            insights = [
                CommentInsight(
                    note_id=note_id,
                    comment_id=comment_id,
                    identity=CommentIdentity.STRONG,
                    sentiment=CommentSentiment.NEGATIVE,
                    mentioned_shops=("争议店",),
                    evidence_refs=(f"xhs:note:{note_id}:comment:{comment_id}",),
                )
                for comment_id in ids
            ]
            return AnalyzeResult(
                success=True,
                restaurants=[
                    RestaurantRecommendation(
                        name="争议店",
                        source_notes=[note_id],
                        features=["评论线索"],
                    )
                ],
                insights=insights,
                raw_comments=comments,
            )

    analyzer = LateInsightAnalyzer()
    monkeypatch.setattr(
        workflow_module,
        "XhsCommentLeadCollector",
        lambda source, *, max_notes: LateSnapshotCollector(source, max_notes=max_notes),
    )

    execution = await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=analyzer,
        max_notes=1,
        max_restaurants=2,
        analysis_concurrency=1,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert analyzer.calls == [("note-late-comment",), ("note-late-comment-2",)]
    assert len(execution.run.evidence_refs) == 2
    assert "xhs:note:note-late:comment:note-late-comment-2" in execution.run.evidence_refs
    assert {item["comment_id"] for item in execution.run.insights} == {
        "note-late-comment",
        "note-late-comment-2",
    }


@pytest.mark.asyncio
async def test_workflow_does_not_expand_when_replan_budget_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed gap alone cannot bypass the runtime replan policy."""

    class GapCollector:
        def __init__(self, _: Any, *, max_notes: int) -> None:
            _ = max_notes
            self.calls = 0
            self.last_stream_result: LeadCollectionResult | None = None

        async def iter_notes(
            self,
            _: FoodSearchIntent,
            *,
            queries: tuple[str, ...] | None = None,
        ):
            self.calls += 1
            self.last_stream_result = LeadCollectionResult(
                notes=(_note("note-only"),),
                gaps=(
                    ResearchGap(
                        source="xhs",
                        operation="notes.search",
                        code="search_partial",
                        retryable=True,
                    ),
                ),
                raw_payload={"queries": list(queries or ()), "search": [{"wave": 1}]},
            )
            yield self.last_stream_result.notes[0]

    collectors: list[GapCollector] = []

    def collector_factory(source: Any, *, max_notes: int) -> GapCollector:
        collector = GapCollector(source, max_notes=max_notes)
        collectors.append(collector)
        return collector

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", collector_factory)
    runtimes: list[Any] = []

    def runtime_factory(**kwargs: Any) -> Any:
        runtime = workflow_module.ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=_Analyzer([], asyncio.Event()),
        runtime_config=ResearchRuntimeConfig(max_replans=0),
        runtime_factory=runtime_factory,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert collectors[0].calls == 1
    assert runtimes[0].state is not None
    assert runtimes[0].state.replans == 0


@pytest.mark.asyncio
async def test_workflow_stream_failure_becomes_a_typed_gap_without_dropping_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = asyncio.Event()

    class FailingCollector(_StreamingCollector):
        async def iter_notes(self, intent: FoodSearchIntent):
            self.last_stream_result = None
            self._events.append("yield:note-1")
            yield self._notes[0]
            await first_started.wait()
            raise RuntimeError("stream broke")

    def collector_factory(source: Any, *, max_notes: int) -> FailingCollector:
        return FailingCollector(
            source,
            max_notes=max_notes,
            events=[],
            analysis_started=first_started,
        )

    class AnalyzerWithStart(_Analyzer):
        async def analyze(self, *args: Any, **kwargs: Any) -> AnalyzeResult:
            result = await super().analyze(*args, **kwargs)
            first_started.set()
            return result

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", collector_factory)
    execution = await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=AnalyzerWithStart([], first_started),
        max_notes=1,
        analysis_concurrency=1,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    assert [note.note_id for note in execution.run.notes] == ["note-1"]
    assert any(gap.code == "stream_exception" for gap in execution.run.gaps)
