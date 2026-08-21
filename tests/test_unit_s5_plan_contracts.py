"""S5.1 contract tests for the typed research-plan DAG."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    PlanBudget,
    PlanStatus,
    PlanStepStatus,
    ResearchPlan,
    ResearchPlanStep,
    SchemaVersion,
)


def _step(
    step_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    status: PlanStepStatus = PlanStepStatus.PENDING,
    evidence_refs: tuple[str, ...] = (),
) -> ResearchPlanStep:
    return ResearchPlanStep(
        step_id=step_id,
        capability=f"capability.{step_id}",
        dependencies=dependencies,
        status=status,
        evidence_refs=evidence_refs,
    )


def _plan(
    steps: tuple[ResearchPlanStep, ...],
    *,
    status: PlanStatus = PlanStatus.DRAFT,
    budget: PlanBudget | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> ResearchPlan:
    return ResearchPlan(
        plan_id="plan-1",
        task_id="task-1",
        goal="collect fixture evidence",
        status=status,
        steps=steps,
        budget=budget or PlanBudget(),
        evidence_refs=evidence_refs,
    )


@pytest.mark.unit
def test_plan_uses_named_schema_and_reads_legacy_schema_version() -> None:
    plan = _plan(())

    payload = json.loads(plan.model_dump_json())
    assert payload["schema_version"] == "research-plan/v1"
    assert ResearchPlan.model_validate({**payload, "schema_version": "1.0"}).schema_version == "1.0"
    assert (
        ResearchPlan.model_validate(
            {**payload, "schema_version": SchemaVersion("1.0")}
        ).schema_version
        == "1.0"
    )


@pytest.mark.unit
def test_legacy_plan_payload_keeps_s1_loose_dag_semantics() -> None:
    legacy_payload = {
        "schema_version": "1.0",
        "plan_id": "legacy-plan",
        "task_id": "legacy-task",
        "goal": "legacy goal",
        "steps": [
            {
                "step_id": "duplicate",
                "capability": "legacy.capability",
                "dependencies": ["missing", "missing"],
                "evidence_refs": [""],
            },
            {
                "step_id": "duplicate",
                "capability": "legacy.capability.2",
            },
        ],
        "evidence_refs": ["legacy-only-evidence"],
    }

    restored = ResearchPlan.model_validate(legacy_payload)

    assert restored.schema_version == "1.0"
    assert restored.evidence_refs == ("legacy-only-evidence",)
    assert restored.steps[0].dependencies == ("missing", "missing")


@pytest.mark.unit
def test_valid_multilevel_dag_round_trips_through_json() -> None:
    plan = _plan(
        (
            _step("collect"),
            _step("normalize", dependencies=("collect",)),
            _step("rank", dependencies=("normalize",)),
        ),
        budget=PlanBudget(max_steps=3),
    )

    restored = ResearchPlan.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert restored.steps[2].dependencies == ("normalize",)


@pytest.mark.unit
def test_duplicate_step_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="step_id values must be unique"):
        _plan((_step("collect"), _step("collect")))


@pytest.mark.unit
def test_unknown_and_self_dependencies_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown dependency"):
        _plan((_step("normalize", dependencies=("collect",)),))

    with pytest.raises(ValidationError, match="cannot depend on itself"):
        _plan((_step("collect", dependencies=("collect",)),))


@pytest.mark.unit
def test_dependency_cycles_are_rejected() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        _plan(
            (
                _step("collect", dependencies=("rank",)),
                _step("rank", dependencies=("collect",)),
            )
        )


@pytest.mark.unit
def test_duplicate_dependencies_and_budget_overflow_are_rejected() -> None:
    with pytest.raises(ValidationError, match="dependencies must not contain duplicates"):
        _plan(
            (
                _step("collect"),
                _step("normalize", dependencies=("collect", "collect")),
            )
        )

    with pytest.raises(ValidationError, match="budget.max_steps"):
        _plan(
            (_step("collect"), _step("normalize")),
            budget=PlanBudget(max_steps=1),
        )


@pytest.mark.unit
def test_active_step_requires_completed_dependencies() -> None:
    with pytest.raises(ValidationError, match="requires all dependencies to be completed"):
        _plan(
            (
                _step("collect"),
                _step("normalize", dependencies=("collect",), status=PlanStepStatus.READY),
            )
        )

    valid = _plan(
        (
            _step("collect", status=PlanStepStatus.COMPLETED),
            _step("normalize", dependencies=("collect",), status=PlanStepStatus.RUNNING),
        )
    )
    assert valid.steps[1].status is PlanStepStatus.RUNNING


@pytest.mark.unit
def test_evidence_refs_are_nonempty_unique_and_plan_consistent() -> None:
    with pytest.raises(ValidationError, match="evidence_refs must contain non-empty values"):
        _plan((_step("collect", evidence_refs=("",)),))

    with pytest.raises(ValidationError, match="evidence_refs must not contain duplicates"):
        _plan((_step("collect", evidence_refs=("evidence-1", "evidence-1")),))

    with pytest.raises(ValidationError, match="plan evidence_refs"):
        _plan((_step("collect", status=PlanStepStatus.COMPLETED, evidence_refs=("evidence-1",)),))

    valid = _plan(
        (_step("collect", status=PlanStepStatus.RUNNING, evidence_refs=("evidence-1",)),),
        evidence_refs=("evidence-1",),
    )
    assert valid.evidence_refs == ("evidence-1",)


@pytest.mark.unit
def test_completed_plan_requires_terminal_step_states() -> None:
    with pytest.raises(ValidationError, match="completed plan"):
        _plan(
            (_step("collect"),),
            status=PlanStatus.COMPLETED,
        )
