"""Model-backed evidence critique for the adaptive investigation loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from xhs_food.contracts import ContractModel, ResearchGap

from .planner import (
    ActionSpec,
    ModelPort,
    attach_model_usage,
    build_model_context,
    build_model_request,
    coerce_action,
    invoke_model,
    parse_model_response,
    prepare_output_schema,
    strict_output_schema,
)


class CriticDecision(ContractModel):
    """Structured critique returned after one action wave.

    ``actions`` and ``additional_actions`` are both accepted because model
    prompts in the wild use either spelling.  The engine treats both as
    append-only actions and still applies scheduler idempotency checks.
    """

    # Compatibility spellings are normalized before validation; an unknown
    # field must not be silently discarded at the model boundary.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    stop: bool = False
    replan_required: bool = False
    reason: str = ""
    findings: tuple[Any, ...] = ()
    new_controversies: tuple[Any, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    additional_actions: tuple[ActionSpec, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_output: Any = None

    @field_validator("actions", "additional_actions", mode="before")
    @classmethod
    def _coerce_actions(cls, values: Any) -> tuple[ActionSpec, ...]:
        if values is None:
            return ()
        if isinstance(values, Mapping):
            values = (values,)
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError("critic actions must be a sequence")
        return tuple(coerce_action(value) for value in values)

    @field_validator("evidence_refs")
    @classmethod
    def _unique_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("critic evidence references must be non-empty")
        if len(values) != len(set(values)):
            raise ValueError("critic evidence references must be unique")
        return values

    @field_validator("gaps", mode="before")
    @classmethod
    def _coerce_gaps(cls, values: Any) -> tuple[ResearchGap, ...]:
        if values is None:
            return ()
        if isinstance(values, Mapping):
            values = (values,)
        return tuple(
            item if isinstance(item, ResearchGap) else ResearchGap.model_validate(item)
            for item in values
        )

    @property
    def replan(self) -> bool:
        return self.replan_required

    @property
    def appended_actions(self) -> tuple[ActionSpec, ...]:
        return (*self.actions, *self.additional_actions)


EvidenceCritique = CriticDecision
CritiqueResult = CriticDecision


CRITIC_OUTPUT_SCHEMA = strict_output_schema(
    CriticDecision,
    title="AdaptiveCriticDecision",
    required=("stop", "replan_required"),
)


def parse_critic_decision(value: Any) -> CriticDecision:
    """Normalize common model response wrappers into a typed critique."""

    payload = parse_model_response(value)
    if isinstance(payload, CriticDecision):
        return payload
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        payload = {"actions": list(payload), "replan_required": True}
    if not isinstance(payload, Mapping):
        raise ValueError("critic response must be an object or action list")
    data = dict(payload)
    for nested_key in ("critique", "decision", "review"):
        nested = data.get(nested_key)
        if isinstance(nested, Mapping):
            merged = dict(nested)
            merged.update({key: item for key, item in data.items() if key != nested_key})
            data = merged
            break
    for source, target in (
        ("should_stop", "stop"),
        ("replan", "replan_required"),
        ("actions_to_add", "additional_actions"),
        ("next_actions", "additional_actions"),
    ):
        if source in data and target not in data:
            data[target] = data[source]
        data.pop(source, None)

    # Also accept the canonical contract's disposition vocabulary.  The
    # engine owns identity and observation references, so those fields are
    # deliberately removed after the decision signal is extracted.
    canonical_critique = data.get("schema_version") == "adaptive-critique/v1" or (
        "decision_id" in data
        and "plan_revision" in data
        and any(key in data for key in ("decision", "disposition"))
    )
    disposition = data.get("decision", data.get("disposition", data.get("action")))
    if isinstance(disposition, str):
        disposition_name = disposition.casefold()
        data.setdefault("stop", disposition_name in {"terminate", "synthesize"})
        data.setdefault(
            "replan_required",
            disposition_name in {"continue", "replan", "request_evidence"},
        )
        data.setdefault("reason", data.get("rationale") or disposition)
        for key in ("decision", "disposition", "action"):
            data.pop(key, None)
    if "rationale" in data and "reason" not in data:
        data["reason"] = data["rationale"]
    data.pop("rationale", None)
    if canonical_critique:
        for key in (
            "schema_version",
            "decision_id",
            "investigation_id",
            "plan_revision",
            "observation_ids",
            "question_ids",
            "hypothesis_ids",
            "requested_capabilities",
            "budget_usage",
            "raw_payload",
        ):
            data.pop(key, None)
    if "replan_required" in data and not isinstance(data["replan_required"], bool):
        data["replan_required"] = str(data["replan_required"]).casefold() in {
            "true",
            "yes",
            "replan",
            "request_evidence",
        }
    data["raw_output"] = data.get("raw_output", payload)
    return CriticDecision.model_validate(data)


class AdaptiveCritic:
    """Critique observations and decide whether the horizon should continue."""

    def __init__(
        self,
        model: ModelPort | Any,
        *,
        model_role: str = "research_critic",
        output_schema: Mapping[str, Any] | None = None,
    ) -> None:
        if model is None:
            raise ValueError("adaptive critic requires an async model port")
        self.model = model
        self.model_role = model_role
        self.output_schema = (
            prepare_output_schema(output_schema)
            if output_schema is not None
            else deepcopy(CRITIC_OUTPUT_SCHEMA)
        )

    async def critique(
        self,
        goal: str | Mapping[str, Any] | Any,
        *,
        state: Any = None,
        observations: Sequence[Any] = (),
        round_index: int = 0,
        previous_critique: Any = None,
        tool_capabilities: Any = None,
        tool_snapshot_ref: str | None = None,
    ) -> CriticDecision:
        context = build_model_context(
            goal,
            state,
            previous_critique,
            observations=observations,
            tool_capabilities=tool_capabilities,
            tool_snapshot_ref=tool_snapshot_ref,
        )
        context["round_index"] = round_index
        request = build_model_request(
            run_id=_run_id(state),
            role=self.model_role,
            instruction=(
                "Critique the latest research observations. Identify unsupported "
                "claims, new disputes, missing evidence, and whether to stop. "
                "For every finding, emit a concise statement and include its "
                "evidence_refs when the observation supports it. Put the final "
                "user-safe conclusion in reason and repeat the relevant refs in "
                "evidence_refs. Do not claim a finding is supported when its "
                "source is missing. When needed, append typed verification "
                "actions; return only the strict critique object and never call "
                "tools."
            ),
            context=context,
            output_schema=self.output_schema,
        )
        raw = await invoke_model(self.model, request, output_model=CriticDecision)
        return attach_model_usage(parse_critic_decision(raw), raw)

    review = critique


Critic = AdaptiveCritic
ModelCritic = AdaptiveCritic


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _run_id(state: Any) -> str:
    if state is not None and getattr(state, "run_id", None):
        return str(state.run_id)
    if isinstance(state, Mapping) and state.get("run_id"):
        return str(state["run_id"])
    return "run"


__all__ = [
    "AdaptiveCritic",
    "Critic",
    "CriticDecision",
    "CRITIC_OUTPUT_SCHEMA",
    "CritiqueResult",
    "EvidenceCritique",
    "ModelCritic",
    "parse_critic_decision",
]
