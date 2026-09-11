"""Unit coverage for the provider-neutral rolling-horizon investigation loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from food_agent.contracts import ModelResponse, SourceCall
from food_agent.contracts.adaptive_investigation import (
    CritiqueDecision as CanonicalCritiqueDecision,
)
from food_agent.contracts.adaptive_investigation import (
    PlanProposal,
)
from food_agent.research.adaptive import (
    ActionScheduler,
    ActionStatus,
    AdaptiveCritic,
    AdaptivePlanner,
    InvestigationBudget,
    InvestigationLoop,
    ScriptedModelPort,
    ScriptedToolPort,
    parse_critic_decision,
    parse_planner_decision,
)
from food_agent.research.adaptive.critic import CRITIC_OUTPUT_SCHEMA
from food_agent.research.adaptive.planner import (
    PLANNER_OUTPUT_SCHEMA,
    build_model_context,
    parse_model_response,
    prepare_output_schema,
)


def _action(action_id: str, capability: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": action_id,
        "kind": capability,
        "capability": capability,
        "inputs": {"action": action_id},
        **extra,
    }


def _loop(
    model_responses: list[Any],
    handlers: dict[str, Any],
    *,
    capabilities: set[str] | None = None,
    **kwargs: Any,
) -> tuple[InvestigationLoop, ScriptedToolPort, ScriptedModelPort]:
    model = ScriptedModelPort(model_responses)
    tool = ScriptedToolPort(handlers, delay=kwargs.pop("tool_delay", 0.0))
    loop = InvestigationLoop(
        AdaptivePlanner(model),
        AdaptiveCritic(model),
        tool_port=tool,
        capabilities=capabilities,
        **kwargs,
    )
    return loop, tool, model


@pytest.mark.unit
async def test_initial_plan_executes_independent_actions_in_one_concurrent_wave() -> None:
    loop, tool, model = _loop(
        [
            {"actions": [_action("a", "lookup"), _action("b", "lookup")]},
            {"stop": True, "reason": "enough evidence"},
        ],
        {"lookup": lambda _action, args: {"output": args["action"], "evidence_refs": [f"ref:{args['action']}"]}},
        capabilities={"lookup"},
        max_concurrency=2,
        tool_delay=0.02,
    )

    state = await loop.run("find evidence", run_id="initial")

    assert model.calls == 2
    assert tool.max_active == 2
    assert [item.action_id for item in state.observations] == ["a", "b"]
    assert state.evidence_refs == ("ref:a", "ref:b")
    assert state.raw_tool_returns[0]["output"] == "a"
    assert state.status.value == "stopped"
    assert state.outcome.value == "complete"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider_return", "gap_code"),
    (
        (None, "missing_result"),
        ({"unexpected": True}, "unsupported_result_shape"),
        (object(), "unsupported_result_shape"),
    ),
)
async def test_scheduler_does_not_treat_empty_or_opaque_returns_as_success(
    provider_return: Any,
    gap_code: str,
) -> None:
    async def execute(_action: Any) -> Any:
        return provider_return

    scheduler = ActionScheduler(executor=execute, capabilities={"lookup"})
    result = await scheduler.execute([_action("shape", "lookup")])

    observation = result.observations[0]
    assert observation.success is False
    assert observation.status is ActionStatus.FAILED
    assert observation.gap is not None
    assert observation.gap.code == gap_code
    assert observation.raw_return is provider_return


@pytest.mark.unit
async def test_injected_scheduler_lease_rejects_concurrent_reset() -> None:
    scheduler = ActionScheduler(
        executor=lambda _action: {"output": "ok"},
        capabilities={"lookup"},
    )
    scheduler.acquire_run("first")
    with pytest.raises(RuntimeError, match="already leased"):
        scheduler.acquire_run("second")
    with pytest.raises(RuntimeError, match="leased"):
        scheduler.reset(run_id="second")
    scheduler.release_run("first")


@pytest.mark.unit
async def test_round_raw_returns_are_json_safe_while_native_audit_is_retained() -> None:
    class OpaqueSdkReturn:
        def __repr__(self) -> str:
            return "<opaque-sdk-return>"

    raw = OpaqueSdkReturn()
    loop, _tool, _model = _loop(
        [
            {"actions": [_action("opaque", "lookup")]},
            {"stop": True, "reason": "enough evidence"},
        ],
        {"lookup": raw},
        capabilities={"lookup"},
    )

    state = await loop.run("retain provider audit", run_id="opaque-audit")

    assert state.rounds[0].raw_tool_returns == ("<opaque-sdk-return>",)
    assert state.rounds[0].native_raw_tool_returns == (raw,)
    state.model_dump_json()


@pytest.mark.unit
async def test_source_call_without_explicit_raw_payload_keeps_data_as_lossless_fallback() -> None:
    loop, tool, _ = _loop(
        [
            {"actions": [_action("lookup", "web.search")]},
            {"stop": True, "reason": "enough evidence"},
        ],
        {
            "web.search": SourceCall(
                source="public-web",
                operation="web.search",
                success=True,
                data={"items": [{"title": "kept"}], "unknown_field": {"value": 1}},
            )
        },
        capabilities={"web.search"},
    )

    state = await loop.run("find public evidence", run_id="source-call-fallback")

    assert tool.calls == [("web.search", {"action": "lookup"})]
    observation = state.observations[0]
    assert observation.source == "public-web"
    assert observation.data == {
        "items": [{"title": "kept"}],
        "unknown_field": {"value": 1},
    }
    assert observation.raw_payload == observation.data


@pytest.mark.unit
async def test_wrapped_provider_pagination_is_retained_when_normalized_data_is_empty() -> None:
    loop, _tool, _ = _loop(
        [
            {"actions": [_action("page", "web.search")]},
            {"stop": True, "reason": "partial evidence is explicit"},
        ],
        {
            "web.search": SourceCall(
                source="public-web",
                operation="web.search",
                success=True,
                data=None,
                raw_payload={
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "pagination": {
                                    "has_next": True,
                                    "next_start_index": 10,
                                }
                            },
                        }
                    ]
                },
            )
        },
        capabilities={"web.search"},
    )

    state = await loop.run("find more public evidence", run_id="raw-pagination")

    observation = state.observations[0]
    assert observation.next_cursor == "10"
    assert observation.has_more is True
    assert observation.completeness.value == "partial"


@pytest.mark.unit
async def test_provider_more_signal_without_cursor_is_partial_instead_of_false_complete() -> None:
    loop, _tool, _ = _loop(
        [
            {"actions": [_action("page", "web.search")]},
            {"stop": True, "reason": "provider cursor missing"},
        ],
        {
            "web.search": SourceCall(
                source="public-web",
                operation="web.search",
                success=True,
                data={"items": [], "has_more": True},
            )
        },
        capabilities={"web.search"},
    )

    state = await loop.run("inspect incomplete evidence", run_id="missing-cursor")

    observation = state.observations[0]
    assert observation.has_more is False
    assert observation.completeness.value == "partial"
    assert observation.continuation["has_more_without_cursor"] is True


@pytest.mark.unit
async def test_critic_can_append_action_after_discovering_a_new_controversy() -> None:
    loop, tool, _ = _loop(
        [
            {"actions": [_action("search", "search")]},
            {
                "new_controversies": [{"entity": "店 A", "kind": "mixed_sentiment"}],
                "additional_actions": [_action("verify", "verify", dependencies=["search"])],
            },
            {"stop": True, "reason": "controversy verified"},
        ],
        {
            "search": {"output": {"claim": "x"}, "evidence_refs": ["ref:search"]},
            "verify": {"output": {"verified": True}, "evidence_refs": ["ref:verify"]},
        },
        capabilities={"search", "verify"},
    )

    state = await loop.run("find disputed restaurants", run_id="controversy")

    assert [item.action_id for item in state.observations] == ["search", "verify"]
    assert [call[0] for call in tool.calls] == ["search", "verify"]
    assert state.controversies == ({"entity": "店 A", "kind": "mixed_sentiment"},)
    assert state.evidence_refs == ("ref:search", "ref:verify")


@pytest.mark.unit
async def test_conflict_requests_a_cross_validation_replan() -> None:
    loop, tool, _ = _loop(
        [
            {"actions": [_action("primary", "search")]},
            {"replan_required": True, "findings": [{"conflict": "rating"}]},
            {"actions": [_action("cross-check", "verify", dependencies=["primary"]) ]},
            {"stop": True, "reason": "cross validation completed"},
        ],
        {
            "search": {"output": {"rating": 4.2}, "evidence_refs": ["ref:primary"]},
            "verify": {"output": {"rating": 4.1}, "evidence_refs": ["ref:cross"]},
        },
        capabilities={"search", "verify"},
    )

    state = await loop.run("check disputed rating", run_id="cross-validation")

    assert [item.action_id for item in state.observations] == ["primary", "cross-check"]
    assert [call[0] for call in tool.calls] == ["search", "verify"]
    assert state.findings == ({"conflict": "rating"},)
    assert len(state.rounds) == 2
    assert state.rounds[1].plan.actions[0].action_id == "cross-check"


@pytest.mark.unit
async def test_critic_stop_is_terminal_and_preserves_round_audit() -> None:
    loop, tool, model = _loop(
        [{"actions": [_action("one", "lookup")]}, {"stop": True, "reason": "minimum coverage"}],
        {"lookup": {"output": {"ok": True}, "evidence_refs": ["ref:one"]}},
        capabilities={"lookup"},
    )

    state = await loop.investigate("minimum search", run_id="stop")

    assert state.stop_reason == "minimum coverage"
    assert state.continuation["critic_stop"] is True
    assert len(state.rounds) == 1
    assert state.rounds[0].critique is not None
    assert model.requests[0].model_role == "research_planner"
    assert model.requests[1].model_role == "research_critic"
    assert tool.calls == [("lookup", {"action": "one"})]


@pytest.mark.unit
async def test_unknown_capability_and_budget_refusal_make_typed_gaps_without_tool_calls() -> None:
    loop, tool, _ = _loop(
        [{"actions": [_action("unknown", "missing"), _action("over", "allowed")]}, {"stop": True}],
        {"allowed": {"output": {"ok": True}, "evidence_refs": ["ref:allowed"]}},
        capabilities={"allowed"},
        budget=InvestigationBudget(max_actions=0),
    )

    state = await loop.run("bounded search", run_id="policy")

    assert tool.calls == []
    assert {item.gap.code for item in state.observations if item.gap} == {
        "unknown_capability",
        "budget_exhausted",
    }
    assert state.outcome.value == "failed"


@pytest.mark.unit
async def test_unreserved_rejections_consume_the_observation_budget() -> None:
    scheduler = ActionScheduler(
        executor=lambda _action: {"output": "must not run"},
        capabilities={"allowed"},
        budget=InvestigationBudget(max_observations=0),
    )

    result = await scheduler.execute(
        [_action("blocked", "missing")],
        round_index=0,
    )

    assert result.observations[0].gap is not None
    assert result.observations[0].gap.code == "unknown_capability"
    assert scheduler.usage.observations == 1
    assert scheduler.budget.is_exhausted(scheduler.usage)


@pytest.mark.unit
async def test_scheduler_repeated_action_and_dependency_failures_are_idempotent() -> None:
    calls: list[str] = []

    async def execute(action: Any) -> dict[str, Any]:
        calls.append(action.action_id)
        return {"output": action.action_id, "evidence_refs": [f"ref:{action.action_id}"]}

    scheduler = ActionScheduler(executor=execute, capabilities={"lookup"}, run_id="repeat")
    action = _action("same", "lookup", idempotency_key="same-key")
    first = await scheduler.execute([action], round_index=0)
    replay = await scheduler.execute([action], round_index=1)
    rejected = await scheduler.execute(
        [_action("other", "lookup", idempotency_key="same-key")], round_index=1
    )

    assert calls == ["same"]
    assert first.observations[0].status is ActionStatus.COMPLETED
    assert replay.observations == ()
    assert rejected.observations[0].gap is not None
    assert rejected.observations[0].gap.code == "duplicate_idempotency_key"


@pytest.mark.unit
async def test_scheduler_dependency_actions_run_in_order_but_independent_nodes_overlap() -> None:
    started: list[str] = []
    release = asyncio.Event()

    async def execute(action: Any) -> dict[str, Any]:
        started.append(action.action_id)
        if action.action_id in {"a", "b"}:
            await release.wait()
        return {"output": action.action_id}

    scheduler = ActionScheduler(executor=execute, capabilities={"lookup"}, max_concurrency=2)
    task = asyncio.create_task(
        scheduler.execute(
            [
                _action("a", "lookup"),
                _action("b", "lookup"),
                _action("child", "lookup", dependencies=["a"]),
            ],
            round_index=0,
        )
    )
    await asyncio.sleep(0)
    assert started == ["a", "b"]
    release.set()
    result = await task

    assert [item.action_id for item in result.observations] == ["a", "b", "child"]
    assert started[-1] == "child"


@pytest.mark.unit
async def test_scheduler_cancellation_records_terminal_observation_and_settles_reservation() -> None:
    started = asyncio.Event()

    async def execute(_action: Any) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {}

    scheduler = ActionScheduler(
        executor=execute,
        capabilities={"lookup"},
        budget=InvestigationBudget(
            max_iterations=1,
            max_actions=1,
            max_tool_calls=1,
            max_tokens=8,
            max_cost_units=1,
            max_observations=1,
            max_wall_time_seconds=30,
        ),
    )
    task = asyncio.create_task(
        scheduler.execute(
            [_action("cancelled", "lookup", token_estimate=5, cost_units=0.25)],
            round_index=0,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    observation = scheduler.observations[0]
    assert observation.gap is not None
    assert observation.gap.code == "cancelled"
    assert observation.success is False
    assert scheduler.state.pending_action_ids == ()
    assert scheduler.usage.actions == 1
    assert scheduler.usage.tool_calls == 1
    assert scheduler.usage.tokens == 5
    assert scheduler.usage.cost_units == 0.25
    assert scheduler.usage.observations == 1


@pytest.mark.unit
async def test_loop_cancellation_preserves_scheduler_tail_and_canonical_termination() -> None:
    started = asyncio.Event()

    async def handler(_action: Any, _arguments: Any) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {}

    loop, _tool, _model = _loop(
        [{"actions": [_action("cancelled", "lookup")]}],
        {"lookup": handler},
        capabilities={"lookup"},
    )
    task = asyncio.create_task(loop.run("cancel safely", run_id="cancel-run"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    state = loop.state
    assert state is not None
    assert state.status.value == "cancelled"
    assert state.termination is not None
    assert state.termination.reason.value == "cancelled"
    assert state.termination.resumable is True
    assert [item.action_id for item in state.observations] == ["cancelled"]
    assert state.observations[0].gap is not None
    assert state.observations[0].gap.code == "cancelled"


@pytest.mark.unit
async def test_model_roles_receive_safe_rolling_state_and_pinned_capability_schemas() -> None:
    loop, tool, model = _loop(
        [
            {"actions": [_action("search", "notes.search")]},
            {
                "replan_required": True,
                "findings": [{"missing": "profile"}],
                "evidence_refs": ["ref:search"],
            },
            {"stop": True, "reason": "evidence is sufficient"},
        ],
        {
            "notes.search": {
                "output": {"notes": [{"id": "note-1"}]},
                "evidence_refs": ["ref:search"],
            }
        },
        capabilities={"notes.search"},
        tool_snapshot_ref="snapshot-1",
        tool_capabilities=(
            {
                "name": "xhs_pc__notes_search",
                "capability": "notes.search",
                "description": "Search public notes",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"notes": {"type": "array"}},
                },
                "metadata": {"tenant_ref": "tenant-secret", "safe": "kept"},
            },
        ),
    )

    state = await loop.run("find note evidence", run_id="context")

    assert state.status.value == "stopped"
    planner_request, critic_request, second_planner_request = model.requests
    for request in model.requests:
        assert request.tools == ()
        assert request.output_schema is not None
        assert request.output_schema["additionalProperties"] is False
        assert "raw_output" not in request.output_schema.get("properties", {})

    assert tool.calls == [("notes.search", {"action": "search"})]

    planner_context = json.loads(planner_request.messages[-1].content.split("CONTEXT=", 1)[1])
    critic_context = json.loads(critic_request.messages[-1].content.split("CONTEXT=", 1)[1])
    second_context = json.loads(
        second_planner_request.messages[-1].content.split("CONTEXT=", 1)[1]
    )
    for context in (planner_context, critic_context, second_context):
        capability = context["tool_capabilities"][0]
        assert context["tool_snapshot_ref"] == "snapshot-1"
        canonical_state = context["canonical_state"]
        assert canonical_state["tool_snapshot_ref"] == "snapshot-1"
        assert canonical_state["tool_capabilities"] == context["tool_capabilities"]
        assert capability["capability"] == "notes.search"
        assert capability["input_schema"]["properties"]["query"]["type"] == "string"
        assert capability["output_schema"]["properties"]["notes"]["type"] == "array"
        assert "tenant-secret" not in json.dumps(context)
        assert "raw_provider_payloads" not in json.dumps(context)
        assert "raw_comments" not in json.dumps(context)

    assert planner_request.output_schema == PLANNER_OUTPUT_SCHEMA
    assert critic_request.output_schema == CRITIC_OUTPUT_SCHEMA
    for request, expected_schema in (
        (planner_request, PLANNER_OUTPUT_SCHEMA),
        (critic_request, CRITIC_OUTPUT_SCHEMA),
    ):
        content = request.messages[-1].content
        encoded_schema = content.split("OUTPUT_SCHEMA=", 1)[1].split("\nCONTEXT=", 1)[0]
        assert json.loads(encoded_schema) == expected_schema

    assert second_context["current_plan"]["actions"][0]["action_id"] == "search"
    assert second_context["observation_history"][0]["observation_id"].endswith(
        ":observation:search"
    )
    assert second_context["previous_critique"]["decision"] == "replan"
    assert critic_context["latest_observations"][0]["action_id"] == "search"
    assert "raw_payload" not in json.dumps(critic_context["latest_observations"])


def test_food_policy_is_available_on_the_initial_model_context() -> None:
    from food_agent.domain_packs.food.adaptive_pack import FoodAdaptivePack
    from food_agent.research.adaptive.food_workflow import _enrich_goal

    enriched = _enrich_goal("找成都火锅", None, pack=FoodAdaptivePack())

    policy = enriched["food_projection"]["domain_policy"]
    assert policy["source_priority"][0]["source"] == "xhs"
    assert policy["source_priority"][0]["role"] == "primary"
    assert policy["source_priority"][1]["source"] == "dianping"
    assert policy["source_priority"][1]["role"] == "secondary"


def test_model_context_keeps_full_comment_once_and_indexes_latest_wave() -> None:
    marker = "unique-complete-comment-evidence"
    observation = {
        "observation_id": "context:observation:comments",
        "action_id": "comments",
        "kind": "tool_result",
        "outcome": "success",
        "source": "xhs",
        "capability": "comments.search",
        "data": {"comments": [{"content": marker}]},
        "raw_payload": {"provider_duplicate": marker},
        "evidence_refs": ["xhs:note:n1:comment:c1"],
        "completeness": "complete",
    }
    context = build_model_context(
        "investigate",
        {
            "investigation_id": "context",
            "revision": 1,
            "observations": [observation],
        },
        observations=[observation],
    )

    assert json.dumps(context, ensure_ascii=False).count(marker) == 1
    assert context["latest_observations"][0]["action_id"] == "comments"
    assert "data" not in context["latest_observations"][0]


@pytest.mark.unit
async def test_model_response_content_is_structured_and_model_tool_calls_are_rejected() -> None:
    model = ScriptedModelPort(
        [
            ModelResponse(
                request_id="response-1",
                content=json.dumps({"actions": [_action("one", "lookup")]}),
            )
        ]
    )
    decision = await AdaptivePlanner(model).plan("lookup", run_id="response")

    assert decision.actions[0].action_id == "one"
    with pytest.raises(ValueError, match="tool calls are not permitted"):
        parse_planner_decision(
            ModelResponse(
                request_id="response-2",
                structured_output={
                    "tool_calls": [{"name": "notes.search", "arguments": {}}]
                },
            )
        )
    with pytest.raises(ValueError, match="tool calls are not permitted"):
        parse_planner_decision({"tool_calls": [{"name": "notes.search", "arguments": {}}]})
    with pytest.raises(ValidationError, match="extra"):
        parse_planner_decision({"actions": [], "stop": True, "unexpected": True})


def test_canonical_plan_and_continue_critique_are_adapted_strictly() -> None:
    proposal = PlanProposal(
        proposal_id="proposal-1",
        investigation_id="investigation-1",
        objective_id="objective-1",
        actions=(),
    )
    decision = parse_planner_decision(proposal, run_id="investigation-1")
    assert decision.actions == ()

    critique = parse_critic_decision(
        CanonicalCritiqueDecision(
            decision_id="critique-1",
            investigation_id="investigation-1",
            decision="continue",
            plan_revision=0,
        )
    )
    assert critique.stop is False
    assert critique.replan_required is True


def test_public_model_boundary_helpers_keep_schemas_strict_and_reject_calls() -> None:
    content = {"actions": [], "stop": True}
    response = ModelResponse(
        request_id="response-3",
        structured_output=content,
    )
    assert parse_model_response(response) == content

    source_schema = {
        "type": "object",
        "properties": {
            "result": {"type": "object"},
            "raw_output": {"type": "string"},
        },
        "required": ["result", "raw_output"],
    }
    prepared = prepare_output_schema(source_schema)
    assert prepared is not None
    assert prepared["additionalProperties"] is False
    assert "raw_output" not in prepared["properties"]
    assert "raw_output" not in prepared["required"]
    assert "raw_output" in source_schema["properties"]

    with pytest.raises(ValueError, match="tool calls are not permitted"):
        parse_model_response(
            {"structured_output": {"tool_calls": [{"name": "notes.search"}]}}
        )
