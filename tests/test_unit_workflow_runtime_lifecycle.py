"""Lifecycle regressions for the split evidence and analysis actions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from xhs_food.agents.analyzer import AnalyzeResult
from xhs_food.agents.intent_parser import IntentParseResult
from xhs_food.contracts import (
    AgentToolExecutionContext,
    CommentEvidence,
    PlatformChannel,
    ResearchEventType,
    ResourceClass,
    ShopProfile,
    SourceCall,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research import workflow as workflow_module
from xhs_food.research.runtime import ResearchRuntime
from xhs_food.research.sources import EnrichmentResult, LeadCollectionResult
from xhs_food.research.workflow import CommentFirstResearchWorkflow
from xhs_food.schemas import ConversationContext, RestaurantRecommendation


def _note(note_id: str = "note-1") -> XhsNoteLead:
    return XhsNoteLead(
        note_id=note_id,
        title="成都火锅实测",
        summary="评论区有明确店铺线索",
        comments=(
            CommentEvidence(
                note_id=note_id,
                comment_id=f"{note_id}:comment-1",
                text="老客推荐这家店",
                raw_payload={"provider_comment": True},
            ),
        ),
        comment_count=1,
        comment_collected_count=1,
        raw_payload={"provider_note": note_id},
    )


class _Parser:
    async def parse(self, _: str, __: ConversationContext) -> IntentParseResult:
        return IntentParseResult(True, FoodSearchIntent(location="成都", food_type="火锅"))


class _Session:
    def __init__(self, *, capabilities: tuple[Any, ...] | None = None) -> None:
        self.snapshot = (
            None
            if capabilities is None
            else SimpleNamespace(projection=capabilities)
        )
        self.opened = False
        self.closed = False

    async def open(self, _: AgentToolExecutionContext) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _OpenFailingSession(_Session):
    async def open(self, _: AgentToolExecutionContext) -> None:
        self.opened = True
        raise RuntimeError("session open failed")


class _Collector:
    called = False

    def __init__(self, _: Any, *, max_notes: int) -> None:
        self._notes = (_note(),)[:max_notes]
        self.last_stream_result: LeadCollectionResult | None = None

    async def iter_notes(
        self,
        _: FoodSearchIntent,
        *,
        queries: tuple[str, ...] | None = None,
    ):
        _ = queries
        type(self).called = True
        self.last_stream_result = LeadCollectionResult(
            notes=self._notes,
            raw_payload={"search": [{"provider_note": "note-1"}]},
        )
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
        return AnalyzeResult(
            success=True,
            restaurants=(
                RestaurantRecommendation(
                    name="评论推荐店",
                    source_notes=[note_id],
                    features=["评论线索"],
                ),
            ),
        )


@pytest.mark.asyncio
async def test_workflow_emits_separate_evidence_and_analysis_action_lifecycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Collector.called = False
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _Collector)
    runtimes: list[ResearchRuntime] = []

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    execution = await CommentFirstResearchWorkflow(
        session_factory=_Session,
        intent_parser=_Parser(),
        analyzer=_Analyzer(),
        max_notes=1,
        max_restaurants=1,
        runtime_factory=runtime_factory,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC,),
        ),
    )

    runtime = runtimes[0]
    started = {
        event.action_id: event
        for event in runtime.events
        if event.event_type is ResearchEventType.ACTION_STARTED
    }
    completed = {
        event.action_id: event
        for event in runtime.events
        if event.event_type is ResearchEventType.ACTION_COMPLETED
    }
    evidence_ids = tuple(action_id for action_id in started if action_id.endswith(":evidence"))
    analysis_ids = tuple(action_id for action_id in started if action_id.endswith(":analysis"))

    assert _Collector.called is True
    assert len(evidence_ids) == len(analysis_ids) == 1
    assert evidence_ids[0] in completed
    assert analysis_ids[0] in completed
    assert started[evidence_ids[0]].resource_class is ResourceClass.XHS_COMMENTS
    assert started[analysis_ids[0]].resource_class is ResourceClass.LLM
    assert completed[evidence_ids[0]].result is not None
    assert completed[evidence_ids[0]].result.source_envelopes[0].operation == "comments.search"
    assert completed[analysis_ids[0]].result is not None
    assert execution.run.evidence_refs


@pytest.mark.asyncio
async def test_missing_search_capability_finishes_without_waiting_for_consumers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Collector.called = False
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _Collector)
    session = _Session(capabilities=())
    runtimes: list[ResearchRuntime] = []

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    execution = await asyncio.wait_for(
        CommentFirstResearchWorkflow(
            session_factory=lambda: session,
            intent_parser=_Parser(),
            analyzer=_Analyzer(),
            max_notes=1,
            runtime_factory=runtime_factory,
        ).execute(
            "成都火锅",
            ConversationContext(),
            tool_context=AgentToolExecutionContext(
                tenant_ref="test",
                platforms=(PlatformChannel.XHS_PC,),
            ),
        ),
        timeout=1,
    )

    runtime = runtimes[0]
    assert _Collector.called is False
    assert execution.run.notes == ()
    assert any(gap.code == "capability_unavailable" for gap in execution.run.gaps)
    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert any(
        event.event_type is ResearchEventType.RUN_COMPLETED for event in runtime.events
    )


@pytest.mark.asyncio
async def test_session_open_failure_still_closes_partial_session() -> None:
    session = _OpenFailingSession()
    workflow = CommentFirstResearchWorkflow(
        session_factory=lambda: session,
        intent_parser=_Parser(),
    )

    with pytest.raises(RuntimeError, match="session open failed"):
        await workflow.execute(
            "成都火锅",
            ConversationContext(),
            tool_context=AgentToolExecutionContext(
                tenant_ref="test",
                platforms=(PlatformChannel.XHS_PC,),
            ),
        )

    assert session.opened is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_profile_coordinator_cancels_and_drains_pending_prepare_tasks() -> None:
    plan_started = asyncio.Event()
    plan_cancelled = asyncio.Event()

    class BlockingProfileService:
        async def plan(self, candidates: tuple[str, ...]) -> Any:
            _ = candidates
            plan_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                plan_cancelled.set()
                raise

    class ResourceRuntime:
        async def invoke_resource(
            self,
            _: ResourceClass,
            operation: Any,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            _ = kwargs
            return await operation(*args)

    coordinator = workflow_module._ProfileEnrichmentCoordinator(
        service=BlockingProfileService(),  # type: ignore[arg-type]
        enricher=object(),  # type: ignore[arg-type]
        runtime=ResourceRuntime(),  # type: ignore[arg-type]
        router=workflow_module._WorkflowActionRouter(),
        intent=FoodSearchIntent(location="成都", food_type="火锅"),
        run_id="prepare-cancel",
        max_profiles=1,
        enabled=False,
    )

    await coordinator.submit(("候选店",))
    await asyncio.wait_for(plan_started.wait(), timeout=1)
    await coordinator.close()

    assert plan_cancelled.is_set()
    assert coordinator._closed is True
    assert all(task.done() for task in coordinator._tasks)


@pytest.mark.asyncio
async def test_cancelling_workflow_closes_session_and_runtime_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    session = _Session()
    runtimes: list[ResearchRuntime] = []
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _Collector)

    class BlockingAnalyzer(_Analyzer):
        async def analyze(self, *args: Any, **kwargs: Any) -> AnalyzeResult:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return await super().analyze(*args, **kwargs)

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    task = asyncio.create_task(
        CommentFirstResearchWorkflow(
            session_factory=lambda: session,
            intent_parser=_Parser(),
            analyzer=BlockingAnalyzer(),
            max_notes=1,
            runtime_factory=runtime_factory,
        ).execute(
            "成都火锅",
            ConversationContext(),
            tool_context=AgentToolExecutionContext(
                tenant_ref="test",
                platforms=(PlatformChannel.XHS_PC,),
            ),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled.is_set()
    assert session.opened is True
    assert session.closed is True
    runtime = runtimes[0]
    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert any(
        event.event_type is ResearchEventType.RUN_CANCELLED for event in runtime.events
    )


@pytest.mark.asyncio
async def test_profile_enrichment_starts_before_later_note_analysis_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comment candidate opens the Dianping wave without a global phase barrier."""

    first_analysis_done = asyncio.Event()
    second_analysis_started = asyncio.Event()
    second_analysis_done = asyncio.Event()
    second_analysis_release = asyncio.Event()
    profile_started = asyncio.Event()
    profile_release = asyncio.Event()
    timeline: list[str] = []

    class StreamingCollector:
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
            first = _note("note-1")
            second = _note("note-2")
            yield first
            await first_analysis_done.wait()
            yield second
            self.last_stream_result = LeadCollectionResult(
                notes=(first, second),
                raw_payload={"search": [{"provider_note": "note-1"}, {"provider_note": "note-2"}]},
            )

    class StreamingAnalyzer:
        async def analyze(
            self,
            _: str,
            __: str,
            ___: list[Any],
            ____: list[str],
            note_id: str,
        ) -> AnalyzeResult:
            if note_id == "note-1":
                timeline.append("first_analysis_done")
                first_analysis_done.set()
            else:
                timeline.append("second_analysis_started")
                second_analysis_started.set()
                await second_analysis_release.wait()
                timeline.append("second_analysis_done")
                second_analysis_done.set()
            return AnalyzeResult(
                success=True,
                restaurants=(
                    RestaurantRecommendation(
                        name="评论推荐店",
                        source_notes=[note_id],
                        features=["评论线索"],
                    ),
                ),
            )

    class BlockingProfileEnricher:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args, kwargs

        async def enrich(
            self,
            candidates: tuple[str, ...],
            intent: FoodSearchIntent,
        ) -> EnrichmentResult:
            _ = candidates, intent
            timeline.append("profile_started")
            profile_started.set()
            await profile_release.wait()
            timeline.append("profile_done")
            return EnrichmentResult(
                profiles=(
                    ShopProfile(
                        name="评论推荐店",
                        provider_refs={"dianping": "dp-1"},
                        city="成都",
                    ),
                ),
                raw_payload={"provider": "dianping", "shop_id": "dp-1"},
            )

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", StreamingCollector)
    monkeypatch.setattr(workflow_module, "DianpingShopEnricher", BlockingProfileEnricher)
    runtimes: list[ResearchRuntime] = []

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    task = asyncio.create_task(
        CommentFirstResearchWorkflow(
            session_factory=_Session,
            intent_parser=_Parser(),
            analyzer=StreamingAnalyzer(),
            max_notes=2,
            max_restaurants=1,
            analysis_concurrency=1,
            runtime_factory=runtime_factory,
        ).execute(
            "成都火锅",
            ConversationContext(),
            tool_context=AgentToolExecutionContext(
                tenant_ref="test",
                platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
            ),
        )
    )

    await asyncio.wait_for(
        asyncio.gather(profile_started.wait(), second_analysis_started.wait()),
        timeout=1,
    )
    assert second_analysis_done.is_set() is False

    second_analysis_release.set()
    profile_release.set()
    execution = await asyncio.wait_for(task, timeout=2)
    assert timeline.index("profile_started") < timeline.index("second_analysis_done")

    runtime = runtimes[0]
    profile_started_events = [
        event
        for event in runtime.events
        if event.event_type is ResearchEventType.ACTION_STARTED
        and ":profile:" in event.action_id
    ]
    analysis_completed_events = [
        event
        for event in runtime.events
        if event.event_type is ResearchEventType.ACTION_COMPLETED
        and ":analysis" in event.action_id
    ]
    assert len(profile_started_events) == 1
    assert analysis_completed_events
    assert profile_started_events[0].sequence < max(
        event.sequence for event in analysis_completed_events
    )
    assert execution.run.profiles[0].name == "评论推荐店"
    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert sum(
        event.event_type is ResearchEventType.RUN_COMPLETED
        for event in runtime.events
    ) == 1
    assert not any(
        event.event_type is ResearchEventType.RUN_CANCELLED
        for event in runtime.events
    )


@pytest.mark.asyncio
async def test_cancelling_streaming_profile_wave_leaves_one_cancelled_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling during later-note work also cancels the profile action."""

    first_analysis_done = asyncio.Event()
    second_analysis_started = asyncio.Event()
    profile_started = asyncio.Event()
    profile_cancelled = asyncio.Event()
    second_analysis_release = asyncio.Event()

    class StreamingCollector:
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
            first = _note("note-1")
            second = _note("note-2")
            yield first
            await first_analysis_done.wait()
            yield second
            self.last_stream_result = LeadCollectionResult(notes=(first, second))

    class StreamingAnalyzer:
        async def analyze(
            self,
            _: str,
            __: str,
            ___: list[Any],
            ____: list[str],
            note_id: str,
        ) -> AnalyzeResult:
            if note_id == "note-1":
                first_analysis_done.set()
            else:
                second_analysis_started.set()
                try:
                    await second_analysis_release.wait()
                except asyncio.CancelledError:
                    raise
            return AnalyzeResult(
                success=True,
                restaurants=(
                    RestaurantRecommendation(
                        name="评论推荐店",
                        source_notes=[note_id],
                    ),
                ),
            )

    class BlockingProfileEnricher:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args, kwargs

        async def enrich(
            self,
            candidates: tuple[str, ...],
            intent: FoodSearchIntent,
        ) -> EnrichmentResult:
            _ = candidates, intent
            profile_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                profile_cancelled.set()
                raise
            raise AssertionError("profile enrichment unexpectedly completed")

    session = _Session()
    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", StreamingCollector)
    monkeypatch.setattr(workflow_module, "DianpingShopEnricher", BlockingProfileEnricher)
    runtimes: list[ResearchRuntime] = []

    def runtime_factory(**kwargs: Any) -> ResearchRuntime:
        runtime = ResearchRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    task = asyncio.create_task(
        CommentFirstResearchWorkflow(
            session_factory=lambda: session,
            intent_parser=_Parser(),
            analyzer=StreamingAnalyzer(),
            max_notes=2,
            analysis_concurrency=1,
            runtime_factory=runtime_factory,
        ).execute(
            "成都火锅",
            ConversationContext(),
            tool_context=AgentToolExecutionContext(
                tenant_ref="test",
                platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
            ),
        )
    )

    await asyncio.wait_for(
        asyncio.gather(profile_started.wait(), second_analysis_started.wait()),
        timeout=1,
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(profile_cancelled.wait(), timeout=1)
    assert session.opened is True
    assert session.closed is True
    runtime = runtimes[0]
    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
    assert sum(
        event.event_type is ResearchEventType.RUN_CANCELLED
        for event in runtime.events
    ) == 1
    assert not any(
        event.event_type is ResearchEventType.RUN_COMPLETED
        for event in runtime.events
    )


class _RecordingRuntime(ResearchRuntime):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.resource_calls: list[tuple[ResourceClass, str]] = []
        super().__init__(*args, **kwargs)

    async def invoke_resource(
        self,
        resource_class: ResourceClass,
        operation: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.resource_calls.append(
            (ResourceClass(resource_class), getattr(operation, "__name__", "call"))
        )
        return await super().invoke_resource(resource_class, operation, *args, **kwargs)


class _CallableDianpingSession(_Session):
    async def call(
        self,
        platform: PlatformChannel,
        capability: str,
        arguments: dict[str, Any],
    ) -> SourceCall:
        assert platform is PlatformChannel.DIANPING
        if capability == "places.search":
            return SourceCall(
                source="dianping",
                operation=capability,
                success=True,
                data={"items": [{"shop_id": "dp-1", "name": "评论推荐店"}]},
                raw_payload={"transport": "places-search"},
            )
        if capability == "places.detail":
            return SourceCall(
                source="dianping",
                operation=capability,
                success=True,
                data={"shop": {"address": "成都地址", "city": "成都"}},
                raw_payload={"transport": "places-detail", "shop_id": arguments["shop_id"]},
            )
        if capability == "reviews.search":
            return SourceCall(
                source="dianping",
                operation=capability,
                success=True,
                data={"items": []},
                raw_payload={"transport": "reviews-search", "shop_id": arguments["shop_id"]},
            )
        raise AssertionError(f"unexpected capability: {capability}")


@pytest.mark.asyncio
async def test_profile_composite_and_commit_use_runtime_resource_invoker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile child I/O and durable commit must share the run resource boundary."""

    monkeypatch.setattr(workflow_module, "XhsCommentLeadCollector", _Collector)
    runtimes: list[_RecordingRuntime] = []

    def runtime_factory(**kwargs: Any) -> _RecordingRuntime:
        runtime = _RecordingRuntime(**kwargs)
        runtimes.append(runtime)
        return runtime

    execution = await CommentFirstResearchWorkflow(
        session_factory=_CallableDianpingSession,
        intent_parser=_Parser(),
        analyzer=_Analyzer(),
        max_notes=1,
        max_restaurants=1,
        runtime_factory=runtime_factory,
    ).execute(
        "成都火锅",
        ConversationContext(),
        tool_context=AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        ),
    )

    runtime = runtimes[0]
    resource_classes = [resource_class for resource_class, _ in runtime.resource_calls]
    assert resource_classes.count(ResourceClass.DIANPING_SEARCH) == 1
    assert resource_classes.count(ResourceClass.DIANPING_DETAIL) == 1
    assert resource_classes.count(ResourceClass.DIANPING_REVIEWS) == 1
    assert any(
        resource_class is ResourceClass.PERSISTENCE and operation == "plan"
        for resource_class, operation in runtime.resource_calls
    )
    assert any(
        resource_class is ResourceClass.PERSISTENCE and operation == "commit"
        for resource_class, operation in runtime.resource_calls
    )
    assert execution.run.profiles[0].provider_refs == {"dianping": "dp-1"}
    assert runtime.state is not None
    assert runtime.state.in_flight_action_ids == ()
