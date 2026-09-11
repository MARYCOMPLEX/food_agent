"""Focused production-boundary tests for the adaptive Food workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from food_agent.contracts import (
    AgentToolExecutionContext,
    ObservationKind,
    PlatformChannel,
    SourceCall,
)
from food_agent.domain_packs.food.adaptive_pack import ObservationEnvelope
from food_agent.research.adaptive.food_workflow import (
    AdaptiveFoodResearchWorkflow,
    ManagedMcpToolPort,
    _items_from_data,
)
from food_agent.research.mcp import ManagedMcpToolSession
from food_agent.schemas import ConversationContext


class _FakeSession(ManagedMcpToolSession):
    def __init__(self, *, include_shop: bool = True) -> None:
        super().__init__(None, None)
        self.calls: list[tuple[PlatformChannel, str, dict[str, Any]]] = []
        self.closed = False
        self.include_shop = include_shop

    async def open(self, context: AgentToolExecutionContext) -> None:
        self._context = context
        self._closed = False

    async def call(
        self,
        platform: PlatformChannel,
        capability: str,
        arguments: dict[str, Any],
    ) -> SourceCall:
        self.calls.append((platform, capability, dict(arguments)))
        comment = {
            "id": "comment-1",
            "note_id": "note-1",
            "content": "老店毛肚很香",
            "mentioned_dishes": ["毛肚"],
            "sentiment": "positive",
        }
        if self.include_shop:
            comment["mentioned_shops"] = ["老店"]
        return SourceCall(
            source="xhs",
            operation=capability,
            success=True,
            data={
                "comments": [comment]
            },
            raw_payload={"provider": "untouched", "nested": {"value": 1}},
            metadata={"payload_ref": "payload://comment-1", "completeness": "complete"},
        )

    async def close(self) -> None:
        self.closed = True
        await super().close()


class _Planner:
    async def plan(self, goal: Any, *, state: Any = None, **_: Any) -> dict[str, Any]:
        if state is not None and getattr(state, "observations", ()):
            return {"stop": True, "reason": "evidence collected"}
        return {
            "actions": [
                {
                    "id": "search-comments",
                    "kind": "search",
                    "capability": "comments.search",
                    "inputs": {"query": "成都 毛肚", "limit": 20},
                }
            ]
        }


class _Critic:
    async def critique(self, goal: Any, *, state: Any = None, **_: Any) -> dict[str, Any]:
        return {"stop": True, "reason": "test critic stop"}


class _EvidenceCritic:
    async def critique(self, goal: Any, *, state: Any = None, **_: Any) -> dict[str, Any]:
        return {
            "stop": True,
            "reason": "评论证据支持老店，但结构化资料仍需补充",
            "findings": [
                {
                    "statement": "评论中反复出现毛肚正向反馈",
                    "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
                }
            ],
            "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
        }


class _BareStopCritic:
    async def critique(self, goal: Any, *, state: Any = None, **_: Any) -> dict[str, Any]:
        return {"stop": True}


class _ShopFindingCritic:
    async def critique(self, goal: Any, *, state: Any = None, **_: Any) -> dict[str, Any]:
        return {
            "stop": True,
            "reason": "结构化评论证据支持探针老店",
            "findings": [
                {
                    "shop": "探针老店",
                    "claim": "评论证据支持毛肚",
                    "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
                }
            ],
            "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
        }


class _CaptureObservationPort:
    def __init__(self, *, fail: bool = False) -> None:
        self.records = []
        self.fail = fail

    def observe(self, record: Any) -> bool:
        if self.fail:
            raise RuntimeError("exporter unavailable")
        self.records.append(record)
        return True

    async def flush(self, deadline_seconds: float | None = None) -> str:
        del deadline_seconds
        return "ok"

    def health(self) -> dict[str, str]:
        return {"status": "ready"}


@pytest.mark.asyncio
async def test_managed_mcp_tool_port_routes_semantic_action_to_platform() -> None:
    session = _FakeSession()
    await session.open(
        AgentToolExecutionContext(
            tenant_ref="test",
            platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        )
    )
    port = ManagedMcpToolPort(session)

    result = await port.call("comments.search", {"query": "成都 毛肚"})

    assert result.success is True
    assert session.calls == [(PlatformChannel.XHS_PC, "comments.search", {"query": "成都 毛肚"})]
    assert result.raw_payload == {"provider": "untouched", "nested": {"value": 1}}


@pytest.mark.asyncio
async def test_adaptive_food_workflow_keeps_raw_source_call_and_food_projection() -> None:
    session = _FakeSession()
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: session,
        planner=_Planner(),
        critic=_Critic(),
        capabilities={"comments.search"},
        max_rounds=2,
    )
    context = ConversationContext()

    execution = await workflow.execute("成都毛肚", context)

    assert session.closed is True
    # A comment-only run is intentionally partial: the Food pack reports the
    # missing secondary shop profile instead of pretending structured data was
    # collected.  Comment evidence and the candidate still remain usable.
    assert execution.run.outcome.value == "partial"
    assert execution.adaptation is not None
    assert execution.adaptation.comments[0]["content"] == "老店毛肚很香"
    raw_call = execution.run.raw_payload["raw_observations"][0]
    assert raw_call.raw_payload["provider"] == "untouched"
    assert execution.response.recommendations[0].name == "老店"
    assert execution.response.research_metadata["strategy"] == "adaptive_investigation/v1"


@pytest.mark.asyncio
async def test_final_summary_is_evidence_aware_and_keeps_audit_refs() -> None:
    session = _FakeSession()
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: session,
        planner=_Planner(),
        critic=_EvidenceCritic(),
        capabilities={"comments.search"},
        max_rounds=2,
    )

    execution = await workflow.execute("成都毛肚", ConversationContext())

    assert "终局结论：评论证据支持老店，但结构化资料仍需补充" in execution.response.summary
    assert "关键发现：评论中反复出现毛肚正向反馈" in execution.response.summary
    assert "依据证据：2 条" in execution.response.summary
    synthesis = execution.response.research_metadata["evidenceSynthesis"]
    assert synthesis["schemaVersion"] == "evidence-synthesis/v1"
    assert synthesis["terminationReason"] == "evidence_sufficient"
    assert synthesis["critiqueDecision"] == "terminate"
    assert synthesis["critiqueConclusion"] == "评论证据支持老店，但结构化资料仍需补充"
    assert synthesis["evidenceRefs"] == [
        "payload://comment-1",
        "xhs:note:note-1:comment:comment-1",
    ]
    assert synthesis["findingRecords"][0]["evidenceRefs"] == [
        "xhs:note:note-1:comment:comment-1"
    ]
    assert synthesis["findings"][0]["statement"] == "评论中反复出现毛肚正向反馈"
    raw_call = execution.run.raw_payload["raw_observations"][0]
    assert raw_call.raw_payload["provider"] == "untouched"


@pytest.mark.asyncio
async def test_final_summary_falls_back_to_deterministic_counts_when_critic_is_generic() -> None:
    session = _FakeSession()
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: session,
        planner=_Planner(),
        critic=_BareStopCritic(),
        capabilities={"comments.search"},
        max_rounds=2,
    )

    execution = await workflow.execute("成都毛肚", ConversationContext())

    assert execution.response.summary.startswith(
        "已从评论证据识别 1 家候选店铺，补充 0 份结构化店铺资料（partial）"
    )
    assert "终局结论：" not in execution.response.summary
    # A bare stop has no evidence-sufficiency semantics; the runtime keeps it
    # distinguishable from an explicit "enough evidence" conclusion.
    assert execution.response.research_metadata["evidenceSynthesis"]["terminationReason"] == (
        "no_progress"
    )


@pytest.mark.asyncio
async def test_structured_critic_finding_restores_candidate_without_shop_mentions() -> None:
    session = _FakeSession(include_shop=False)
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: session,
        planner=_Planner(),
        critic=_ShopFindingCritic(),
        capabilities={"comments.search"},
        max_rounds=2,
    )

    execution = await workflow.execute("成都毛肚", ConversationContext())

    assert [item.name for item in execution.response.recommendations] == ["探针老店"]
    assert execution.adaptation is not None
    entity = next(item for item in execution.adaptation.entities if item["name"] == "探针老店")
    assert entity["source"] == "model_critic"
    assert entity["evidence_refs"] == ["xhs:note:note-1:comment:comment-1"]
    assert execution.adaptation.comments[0]["content"] == "老店毛肚很香"
    raw_call = execution.run.raw_payload["raw_observations"][0]
    assert raw_call.raw_payload["provider"] == "untouched"
    assert execution.response.research_metadata["evidenceSynthesis"]["findings"][0]["shop"] == (
        "探针老店"
    )


@pytest.mark.asyncio
async def test_adaptive_lifecycle_observations_are_bounded_and_redacted() -> None:
    port = _CaptureObservationPort()
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: _FakeSession(),
        planner=_Planner(),
        critic=_Critic(),
        capabilities={"comments.search"},
        observation_port=port,
    )

    execution = await workflow.execute("成都毛肚", ConversationContext())

    assert execution.run.outcome.value == "partial"
    kinds = {record.kind for record in port.records}
    assert ObservationKind.AGENT_RUN in kinds
    assert ObservationKind.MODEL_CALL in kinds
    assert ObservationKind.MCP_TOOL_CALL in kinds
    assert ObservationKind.EVIDENCE_TRANSFORM in kinds
    serialized = [record.model_dump(mode="json") for record in port.records]
    assert all("raw" not in str(item).casefold() for item in serialized)
    assert all("老店毛肚很香" not in str(item) for item in serialized)
    assert all("content" not in record.attributes for record in port.records)
    assert all("query" not in record.attributes for record in port.records)


@pytest.mark.asyncio
async def test_observation_export_failure_does_not_change_food_result() -> None:
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: _FakeSession(),
        planner=_Planner(),
        critic=_Critic(),
        capabilities={"comments.search"},
        observation_port=_CaptureObservationPort(fail=True),
    )

    execution = await workflow.execute("成都毛肚", ConversationContext())

    assert execution.run.outcome.value == "partial"
    assert execution.adaptation is not None
    assert execution.adaptation.comments[0]["content"] == "老店毛肚很香"


def test_mcp_snapshot_projection_preserves_capability_metadata() -> None:
    session = _FakeSession()
    definition = SimpleNamespace(
        name="xhs_pc__comments_search",
        description="Search public comments",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"comments": {"type": "array"}},
        },
        side_effect="read_only",
        timeout_ms=1_250,
        cost_units=2.5,
        produces_evidence=True,
        supports_pagination=True,
        metadata={"provider_schema": "comments/v2"},
        model_dump=lambda **_: {"opaque": "definition"},
    )
    projection = SimpleNamespace(
        public_name="xhs_pc__comments_search",
        capability="comments.search",
        capability_version="2.1.0",
        platform=PlatformChannel.XHS_PC,
        side_effect="read_only",
    )
    session._snapshot = SimpleNamespace(tools=(definition,), projection=(projection,))
    workflow = AdaptiveFoodResearchWorkflow(
        session_factory=lambda: session,
        planner=_Planner(),
        critic=_Critic(),
    )

    capabilities = workflow._effective_tool_capabilities(
        session,
        frozenset({"comments.search"}),
    )

    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability.side_effect.value == "read_only"
    assert capability.cost_units == 2.5
    assert capability.produces_evidence is True
    assert capability.supports_pagination is True
    assert capability.timeout_ms == 1_250
    assert capability.version == "2.1.0"
    assert capability.input_schema["required"] == ["query"]
    assert capability.output_schema["properties"]["comments"]["type"] == "array"
    assert capability.metadata["provider_schema"] == "comments/v2"
    assert capability.raw_payload == {"opaque": "definition"}


def test_food_observation_contract_accepts_source_call_projection_shape() -> None:
    envelope = ObservationEnvelope(
        source="xhs",
        operation="comments.search",
        items=({"id": "comment-1", "content": "保留"},),
        raw_payload={"raw": True},
        completeness="complete",
    )

    assert envelope.items[0]["content"] == "保留"
    assert envelope.raw_payload == {"raw": True}


@pytest.mark.parametrize(
    ("operation", "payload", "expected_id"),
    (
        (
            "notes.search",
            {"search_items": [{"id": "note-1", "model_type": "note"}]},
            "note-1",
        ),
        (
            "notes.detail",
            {"detail": {"data": {"items": [{"id": "note-2", "model_type": "note"}]}}},
            "note-2",
        ),
        (
            "comments.search",
            {"comments": {"items": [{"id": "comment-1", "content": "好吃"}]}},
            "comment-1",
        ),
        (
            "places.search",
            {"items": [{"shop_id": "shop-1", "name": "老店"}]},
            "shop-1",
        ),
        (
            "places.detail",
            {"shop": {"shop_id": "shop-2", "name": "另一家"}},
            "shop-2",
        ),
        (
            "reviews.search",
            {"reviews": {"items": [{"review_id": "review-1", "content": "值得"}]}},
            "review-1",
        ),
    ),
)
def test_items_from_data_unwraps_probe_provider_collections(
    operation: str,
    payload: dict[str, Any],
    expected_id: str,
) -> None:
    wrapped = {"content": [{"type": "json", "json": payload}], "isError": False}

    items = _items_from_data(wrapped, operation=operation)

    assert len(items) == 1
    item = items[0]
    assert isinstance(item, dict)
    assert expected_id in {item.get("id"), item.get("shop_id"), item.get("review_id")}


def test_observation_envelope_preserves_mcp_payload_and_nested_dianping_pagination() -> None:
    provider = {
        "shop": {"shop_id": "shop-1", "name": "老店"},
        "items": [{"review_id": "review-1", "content": "值得"}],
        "pagination": {
            "start_index": 0,
            "next_start_index": 5,
            "has_next": True,
            "page_size": 5,
        },
        "completeness": {
            "status": "partial",
            "complete": False,
            "continuation": {"next_offset": 5},
        },
        "unknown_provider_field": {"kept": True},
    }
    raw_mcp = {"content": [{"type": "json", "json": provider}], "isError": False}

    envelope = ObservationEnvelope(
        source="dianping",
        operation="reviews.search",
        data=raw_mcp,
    )

    assert envelope.items[0]["review_id"] == "review-1"
    assert envelope.cursor == "0"
    assert envelope.next_cursor == "5"
    assert envelope.has_more is True
    assert envelope.completeness == "partial"
    assert envelope.raw_payload == raw_mcp
    assert envelope.metadata["pagination"]["next_start_index"] == 5
    assert envelope.metadata["completeness_manifest"]["status"] == "partial"
    assert envelope.data["unknown_provider_field"] == {"kept": True}
