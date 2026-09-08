"""Focused contract tests for the adaptive investigation proposal."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xhs_food.contracts.adaptive_investigation import (
    BudgetUsage,
    CritiqueDecision,
    Hypothesis,
    HypothesisStatus,
    InvestigationBudget,
    InvestigationState,
    InvestigationStatus,
    Objective,
    ObservationCompleteness,
    ObservationEnvelope,
    ObservationOutcome,
    PlanAction,
    PlanActionKind,
    PlanProposal,
    Question,
    Termination,
    TerminationReason,
    ToolCapabilityMetadata,
)

NOW = datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC)


def _objective() -> Objective:
    return Objective(
        id="objective-1",
        description="Find evidence for a recommendation",
        success_criteria=("answer the primary question",),
        evidence_refs=("objective-evidence",),
        raw_payload={"provider_field_added_later": {"rank": 1}},
    )


def _question() -> Question:
    return Question(
        id="question-1",
        prompt="Which candidate is supported by comments?",
        objective_id="objective-1",
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        id="hypothesis-1",
        text="Candidate A has consistent positive evidence",
        question_refs=("question-1",),
        status=HypothesisStatus.TESTING,
    )


def _capability() -> ToolCapabilityMetadata:
    return ToolCapabilityMetadata(
        name="xhs_pc__notes_search",
        capability="notes.search",
        capability_version="1.0",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object"},
        produces_evidence=True,
        supports_pagination=True,
    )


def _action(action_id: str = "action-1", *, depends_on: tuple[str, ...] = ()) -> PlanAction:
    return PlanAction(
        id=action_id,
        kind=PlanActionKind.SEARCH,
        tool_capability="notes.search",
        tool_name="xhs_pc__notes_search",
        inputs={"query": "candidate A"},
        dependencies=depends_on,
        question_refs=("question-1",),
        expected_observation_kinds=("source",),
        raw_payload={"model_reason": "test", "unknown": [1, 2]},
    )


def test_contracts_round_trip_with_aliases_and_lossless_payloads() -> None:
    objective = _objective()
    question = _question()
    hypothesis = _hypothesis()
    capability = _capability()
    action = _action()
    proposal = PlanProposal(
        id="proposal-1",
        run_id="investigation-1",
        objective_id=objective.objective_id,
        revision=1,
        base_revision=0,
        actions=(action,),
        target_question_ids=(question.question_id,),
        tool_snapshot_ref="snapshot-1",
    )
    observation = ObservationEnvelope(
        id="observation-1",
        run_id="investigation-1",
        action_id=action.action_id,
        kind="source",
        source_id="xhs",
        capability="notes.search",
        observed_at=NOW,
        data={"notes": [{"id": "note-1"}]},
        raw={
            "notes": [{"id": "note-1", "new_provider_field": "preserve-me"}],
            "server_cursor": "cursor-1",
        },
        evidence_refs=("evidence-1",),
        next_cursor="cursor-2",
        has_more=True,
        completeness=ObservationCompleteness.PARTIAL,
    )
    critique = CritiqueDecision(
        id="critique-1",
        run_id="investigation-1",
        disposition="replan",
        rationale="The first source is partial",
        plan_revision=1,
        observation_ids=(observation.observation_id,),
        question_ids=(question.question_id,),
        evidence_refs=observation.evidence_refs,
    )
    state = InvestigationState(
        run_id="investigation-1",
        revision=1,
        status=InvestigationStatus.RUNNING,
        objective=objective,
        questions=(question,),
        hypotheses=(hypothesis,),
        plan=proposal,
        observations=(observation,),
        critique=critique,
        budget=InvestigationBudget(max_tool_calls=3),
        budget_usage=BudgetUsage(tool_calls=1, observations=1),
        tool_capabilities=(capability,),
        tool_snapshot_ref="snapshot-1",
    )

    payload = json.loads(state.model_dump_json())
    assert payload["schema_version"] == "adaptive-investigation/v1"
    assert payload["observations"][0]["raw_payload"]["notes"][0]["new_provider_field"] == "preserve-me"
    assert set(payload["evidence_refs"]) == {"objective-evidence", "evidence-1"}
    assert InvestigationState.model_validate_json(state.model_dump_json()) == state


def test_plan_graph_rejects_unknown_dependencies_and_cycles() -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        PlanProposal(
            proposal_id="proposal-1",
            investigation_id="investigation-1",
            objective_id="objective-1",
            actions=(_action(depends_on=("missing",)),),
        )

    with pytest.raises(ValidationError, match="dependency cycle"):
        PlanProposal(
            proposal_id="proposal-1",
            investigation_id="investigation-1",
            objective_id="objective-1",
            actions=(_action("a", depends_on=("b",)), _action("b", depends_on=("a",))),
        )


def test_contracts_are_strict_about_extra_fields_and_opaque_json() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Objective(objective_id="objective-1", statement="goal", unexpected="reject")

    with pytest.raises(ValidationError, match="NaN"):
        ObservationEnvelope(
            observation_id="observation-1",
            investigation_id="investigation-1",
            raw_payload={"score": float("nan")},
        )

    with pytest.raises(ValidationError, match="cannot be complete"):
        ObservationEnvelope(
            observation_id="observation-1",
            investigation_id="investigation-1",
            outcome=ObservationOutcome.FAILURE,
            completeness=ObservationCompleteness.COMPLETE,
        )


def test_supported_hypotheses_require_citations_and_state_scopes_nested_values() -> None:
    with pytest.raises(ValidationError, match="require evidence_refs"):
        Hypothesis(
            hypothesis_id="hypothesis-1",
            statement="supported claim",
            status=HypothesisStatus.SUPPORTED,
        )

    observation = ObservationEnvelope(
        observation_id="observation-1",
        investigation_id="other-investigation",
        evidence_refs=("evidence-1",),
    )
    with pytest.raises(ValidationError, match="observation investigation_id"):
        InvestigationState(
            investigation_id="investigation-1",
            objective=_objective(),
            observations=(observation,),
        )


def test_budget_is_bounded_and_reports_exhausted_dimensions() -> None:
    with pytest.raises(ValidationError, match="at least one finite ceiling"):
        InvestigationBudget(
            max_iterations=None,
            max_actions=None,
            max_tool_calls=None,
            max_cost_units=None,
            max_tokens=None,
            max_observations=None,
            max_wall_time_seconds=None,
            deadline_at=None,
        )

    budget = InvestigationBudget(max_iterations=2, max_tool_calls=3)
    usage = BudgetUsage(iterations=2, tool_calls=1)
    assert budget.is_exhausted(usage)
    assert budget.exhausted_dimensions(usage) == ("iterations",)


def test_resumable_termination_requires_continuation_and_terminal_state() -> None:
    with pytest.raises(ValidationError, match="continuation metadata"):
        Termination(
            investigation_id="investigation-1",
            reason=TerminationReason.BUDGET_EXHAUSTED,
            resumable=True,
        )

    termination = Termination(
        investigation_id="investigation-1",
        reason=TerminationReason.BUDGET_EXHAUSTED,
        occurred_at=NOW,
        continuation={"next_cursor": "cursor-3"},
        resumable=True,
        evidence_refs=("evidence-1",),
    )
    state = InvestigationState(
        investigation_id="investigation-1",
        status=InvestigationStatus.PARTIAL,
        objective=_objective(),
        termination=termination,
    )
    assert state.is_terminal
    assert state.budget_exhausted is False

    with pytest.raises(ValidationError, match="terminal investigation status"):
        InvestigationState(
            investigation_id="investigation-1",
            status=InvestigationStatus.RUNNING,
            objective=_objective(),
            termination=termination,
        )


def test_state_accepts_one_plan_history_entry() -> None:
    proposal = PlanProposal(
        proposal_id="proposal-1",
        investigation_id="investigation-1",
        objective_id="objective-1",
        revision=1,
        base_revision=0,
    )

    state = InvestigationState(
        investigation_id="investigation-1",
        revision=1,
        objective=_objective(),
        plan=proposal,
        plan_history=(proposal,),
    )

    assert state.plan_history == (proposal,)
