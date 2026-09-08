"""Model-backed, provider-neutral planning contracts for adaptive research.

The adaptive loop deliberately has no knowledge of MCP.  A planner receives a
serializable snapshot of the investigation and returns semantic action specs;
the scheduler is the only component that maps those specs to an injected
executor.  The small adapters in this module also make the contract usable
with the project's existing ``ModelGateway`` as well as deterministic fakes.
"""

from __future__ import annotations

import inspect
import json
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import ConfigDict, Field, field_validator

from xhs_food.contracts import (
    ContractModel,
    ModelMessage,
    ModelRequest,
    PlanAction,
    PlanActionKind,
    ResearchActionResult,
    ResearchGap,
)

# The canonical contract is the only action model owned by the adaptive
# runtime.  ``ActionSpec`` remains a source-compatible spelling for callers
# migrating from the first prototype; it is an alias, not another model.
ActionSpec = PlanAction
ActionKind = PlanActionKind
InvestigationAction = PlanAction
AdaptiveAction = PlanAction
TypedAction = PlanAction


@runtime_checkable
class ModelPort(Protocol):
    """Minimal async model boundary used by Planner and Critic.

    The preferred implementation is ``generate(ModelRequest)`` (the same
    shape as ``contracts.ModelGateway``).  ``invoke_model`` below also accepts
    ``complete``/``call`` adapters so tests and small integrations need not
    wrap an otherwise compatible model.
    """

    async def generate(self, request: ModelRequest) -> Any: ...


class PlannerDecision(ContractModel):
    """Structured result of one model planning turn."""

    # Planner output is a model boundary.  Compatibility aliases are
    # normalized before validation, but an unrecognised field must never be
    # silently accepted and then lost from the audit trail.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    actions: tuple[ActionSpec, ...] = ()
    append_actions: tuple[ActionSpec, ...] = ()
    stop: bool = False
    reason: str = ""
    round_index: int = Field(default=0, ge=0)
    investigation_id: str | None = None
    objective_id: str | None = None
    revision: int | None = Field(default=None, ge=0)
    base_revision: int | None = Field(default=None, ge=0)
    tool_snapshot_ref: str | None = None
    raw_output: Any = None
    gaps: tuple[ResearchGap, ...] = ()

    @field_validator("actions", "append_actions", mode="before")
    @classmethod
    def _coerce_actions(cls, values: Any) -> tuple[ActionSpec, ...]:
        if values is None:
            return ()
        if isinstance(values, Mapping):
            values = (values,)
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError("planner actions must be a sequence")
        return tuple(coerce_action(item) for item in values)

    @property
    def all_actions(self) -> tuple[ActionSpec, ...]:
        return (*self.actions, *self.append_actions)


# Compatibility names used by callers that call the result a plan.
InvestigationPlan = PlannerDecision
PlanDecision = PlannerDecision


def strict_output_schema(
    model: type[Any],
    *,
    title: str,
    required: Sequence[str],
) -> dict[str, Any]:
    """Return a provider-neutral, strict schema for a model boundary.

    The internal decision models retain ``raw_output``/``raw_payload`` for
    auditability, but those fields are runtime-owned and must not be requested
    from the model.  The schema is copied on every call so a provider adapter
    cannot mutate the module-level contract used by another turn.
    """

    schema = deepcopy(model.model_json_schema())
    schema["title"] = title
    schema["additionalProperties"] = False
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("raw_output", None)
        properties.pop("raw_payload", None)
    schema["required"] = list(dict.fromkeys(str(field) for field in required))

    # ``PlanAction`` is nested below both planner and critic schemas.  Remove
    # runtime-only opaque fields recursively while preserving free-form JSON
    # arguments and the capability schemas shown in context.
    _strip_runtime_payload_fields(schema)
    return schema


def _strip_runtime_payload_fields(value: Any) -> None:
    if not isinstance(value, Mapping):
        return
    properties = value.get("properties")
    if isinstance(properties, dict):
        properties.pop("raw_output", None)
        properties.pop("raw_payload", None)
        required = value.get("required")
        if isinstance(required, list):
            value["required"] = [
                field for field in required if field not in {"raw_output", "raw_payload"}
            ]
    for child in value.values():
        _strip_runtime_payload_fields(child)


PLANNER_OUTPUT_SCHEMA = strict_output_schema(
    PlannerDecision,
    title="AdaptivePlannerDecision",
    required=("actions", "stop"),
)


def prepare_output_schema(output_schema: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Copy a caller schema while keeping the model boundary strict.

    This is the public companion to :func:`strict_output_schema` for callers
    that already have a JSON Schema mapping.  Returning a deep copy prevents
    provider adapters from mutating a schema shared by later turns.
    """

    if output_schema is None:
        return None
    result = deepcopy(dict(output_schema))
    if result.get("type", "object") != "object":
        raise ValueError("adaptive planner and critic output schemas must be objects")
    result["additionalProperties"] = False
    _strip_runtime_payload_fields(result)
    return result


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def stable_json(value: Any) -> str:
    """Encode a model context deterministically and without provider objects."""

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=_json_default)


def coerce_action(
    value: Any,
    *,
    run_id: str = "run",
    round_index: int = 0,
    position: int = 0,
) -> ActionSpec:
    """Convert model/legacy spellings into the canonical ``PlanAction``.

    The model boundary is intentionally forgiving about input aliases, while
    the returned value is always the strict versioned contract.  Unknown
    legacy action kinds become ``tool_call``; their original payload is kept
    in ``raw_payload`` for audit and domain-specific interpretation.
    """

    if isinstance(value, PlanAction):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
    elif hasattr(value, "model_dump"):
        payload = dict(value.model_dump(mode="json"))
    else:
        payload = {
            key: getattr(value, key)
            for key in (
                "action_id",
                "id",
                "kind",
                "type",
                "action_type",
                "dependencies",
                "idempotency_key",
                "capability",
                "resource_class",
                "resource",
                "inputs",
                "input",
                "arguments",
                "reason",
                "token_estimate",
                "cost_units",
                "evidence_refs",
            )
            if hasattr(value, key)
        }
    action_id = str(payload.get("action_id") or payload.get("id") or f"{run_id}:r{round_index}:action:{position}")
    raw_kind = payload.get("kind") or payload.get("type") or payload.get("action_type")
    raw_kind = getattr(raw_kind, "value", raw_kind)
    normalized_kind = str(raw_kind or "tool_call").casefold()
    kind_aliases = {
        "cross_validate": PlanActionKind.VERIFY.value,
        "lookup": PlanActionKind.TOOL_CALL.value,
        "generic": PlanActionKind.TOOL_CALL.value,
        "tool": PlanActionKind.TOOL_CALL.value,
    }
    kind = kind_aliases.get(normalized_kind, normalized_kind)
    try:
        kind = PlanActionKind(kind)
    except ValueError:
        kind = PlanActionKind.TOOL_CALL
    capability = str(payload.get("capability") or payload.get("tool") or raw_kind or "generic")
    arguments = payload.get("arguments")
    if arguments is None:
        arguments = payload.get("inputs")
    if arguments is None:
        arguments = payload.get("input")
    if arguments is None:
        arguments = payload.get("input_contract")
    if arguments is None:
        policy_fields = {
            "schema_version",
            "raw_payload",
            "action_id",
            "id",
            "kind",
            "type",
            "action_type",
            "dependencies",
            "depends_on",
            "idempotency_key",
            "capability",
            "tool",
            "tool_name",
            "public_tool_name",
            "resource_class",
            "resource",
            "inputs",
            "input",
            "arguments",
            "input_contract",
            "question_ids",
            "question_refs",
            "hypothesis_ids",
            "hypothesis_refs",
            "reason",
            "rationale",
            "priority",
            "budget",
            "estimated_tokens",
            "estimated_cost_units",
            "estimated_tool_calls",
            "max_attempts",
            "token_estimate",
            "cost_units",
            "evidence_refs",
            "expected_observation_kinds",
        }
        arguments = {key: item for key, item in payload.items() if key not in policy_fields}
    if not isinstance(arguments, Mapping):
        raise ValueError("action arguments must be an object")

    budget = payload.get("budget")
    if not isinstance(budget, Mapping):
        budget = {}
    budget = {
        **dict(budget),
        "estimated_tokens": max(
            0,
            int(
                budget.get(
                    "estimated_tokens",
                    payload.get("token_estimate", payload.get("estimated_tokens", 0)),
                )
                or 0
            ),
        ),
        "estimated_cost_units": max(
            0.0,
            float(
                budget.get(
                    "estimated_cost_units",
                    payload.get("cost_units", payload.get("estimated_cost_units", 0.0)),
                )
                or 0.0
            ),
        ),
        "estimated_tool_calls": max(
            0,
            int(
                budget.get(
                    "estimated_tool_calls",
                    payload.get("estimated_tool_calls", 1),
                )
                or 0
            ),
        ),
    }
    canonical = {
        "action_id": action_id,
        "kind": kind,
        "capability": capability,
        "tool_name": payload.get("tool_name") or payload.get("public_tool_name"),
        "resource_class": payload.get("resource_class") or payload.get("resource") or capability,
        "arguments": dict(arguments),
        "depends_on": tuple(payload.get("depends_on") or payload.get("dependencies") or ()),
        "question_ids": tuple(payload.get("question_ids") or payload.get("question_refs") or ()),
        "hypothesis_ids": tuple(payload.get("hypothesis_ids") or payload.get("hypothesis_refs") or ()),
        "evidence_refs": tuple(payload.get("evidence_refs") or ()),
        "expected_observation_kinds": tuple(payload.get("expected_observation_kinds") or ()),
        "idempotency_key": str(payload.get("idempotency_key") or action_id),
        "priority": max(0, int(payload.get("priority") or 0)),
        "rationale": str(payload.get("rationale") or payload.get("reason") or ""),
        "budget": budget,
        "raw_payload": _json_safe_payload(payload),
    }
    return PlanAction.model_validate(canonical)


def _json_safe_payload(value: Any) -> Any:
    """Keep opaque model input JSON-compatible for the canonical contract."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe_payload(item) for item in value]
    return str(value)


def parse_model_response(value: Any) -> Any:
    """Extract structured JSON from supported model response envelopes.

    The helper accepts the project's ``ModelResponse`` shape, lightweight
    mapping/object fakes, JSON strings, and already-parsed mappings.  Tool
    calls are rejected at this boundary; only the planner/critic decision
    parsers may turn the result into semantic actions.
    """

    if isinstance(value, (PlannerDecision, ActionSpec, ResearchActionResult)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("model response is not valid UTF-8 structured JSON") from exc
    if isinstance(value, Mapping) and value.get("type") in {"text", "output_text"}:
        text = value.get("text", value.get("content"))
        if text is not None:
            return parse_model_response(text)
    # Some SDKs expose assistant content as a list of text parts.  Do not
    # treat an ordinary list of semantic actions as a content envelope; only
    # a list made entirely of typed text parts is joined here.
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and value
        and all(
            isinstance(item, Mapping)
            and item.get("type") in {"text", "output_text"}
            and item.get("text", item.get("content")) is not None
            for item in value
        )
    ):
        return parse_model_response(
            "".join(str(item.get("text", item.get("content"))) for item in value)
        )
    if isinstance(value, Mapping):
        tool_calls = value.get("tool_calls")
        if tool_calls:
            raise ValueError("model tool calls are not permitted in adaptive planning")
        # OpenAI-compatible response envelopes commonly put the actual
        # message under ``choices[0].message`` (or ``text``).  Treat this as
        # transport metadata rather than leaking it into the strict decision
        # model.
        choices = value.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
            if not choices:
                raise ValueError("model response contains no choices")
            return parse_model_response(choices[0])
        if "message" in value and value["message"] is not None and not any(
            key in value
            for key in (
                "actions",
                "append_actions",
                "additional_actions",
                "stop",
                "replan_required",
            )
        ):
            return parse_model_response(value["message"])
        if "text" in value and value["text"] is not None and not any(
            key in value
            for key in (
                "actions",
                "append_actions",
                "additional_actions",
                "stop",
                "replan_required",
            )
        ):
            return parse_model_response(value["text"])
        # ModelGateway responses are normally ModelResponse instances, but a
        # fake may return the wire mapping directly.
        for key in ("structured_output", "structured", "parsed"):
            if key in value and value[key] is not None:
                return parse_model_response(value[key])
        # A serialized ModelResponse carries transport metadata alongside its
        # JSON content.  The content is the model result, not a decision
        # wrapper, so parse it before handing the mapping to Pydantic.
        if "content" in value and value["content"] is not None and not any(
            key in value
            for key in (
                "actions",
                "append_actions",
                "additional_actions",
                "stop",
                "replan_required",
            )
        ):
            return parse_model_response(value["content"])
        if "output" in value and not any(
            key in value for key in ("actions", "append_actions", "stop", "replan_required")
        ):
            output = value["output"]
            if isinstance(output, (Mapping, Sequence)) and not isinstance(
                output, (str, bytes, bytearray)
            ):
                return parse_model_response(output)
            if isinstance(output, str):
                return parse_model_response(output)
        if set(value) == {"content"}:
            return parse_model_response(value["content"])
        return value

    tool_calls = getattr(value, "tool_calls", None)
    if tool_calls:
        raise ValueError("model tool calls are not permitted in adaptive planning")
    choices = getattr(value, "choices", None)
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes, bytearray)):
        if not choices:
            raise ValueError("model response contains no choices")
        return parse_model_response(choices[0])
    message = getattr(value, "message", None)
    if message is not None:
        return parse_model_response(message)
    structured = getattr(value, "structured_output", None)
    if structured is not None:
        return parse_model_response(structured)
    output = getattr(value, "output", None)
    if output is not None and not isinstance(output, str):
        return parse_model_response(output)
    content = getattr(value, "content", None)
    if content is not None:
        return parse_model_response(content)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
        except TypeError:
            dumped = value.model_dump()
        return parse_model_response(dumped)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()
            if text.startswith("json"):
                text = text[4:].lstrip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("model response is not valid structured JSON") from exc
    return value


def attach_model_usage(decision: Any, response: Any) -> Any:
    """Keep transport usage alongside a parsed decision for budget accounting.

    ``parse_model_response`` intentionally unwraps provider envelopes before
    validation.  The envelope's usage is still runtime-relevant, however:
    dropping it would make token/cost ceilings depend on which response shape
    a model adapter happened to return.  Store only the small usage mapping in
    the decision's audit payload; provider credentials and raw transport data
    never enter the model context.
    """

    usage = _response_usage(response)
    if usage is None or not hasattr(decision, "model_copy"):
        return decision
    existing = getattr(decision, "raw_output", None)
    payload = {
        "content": _json_safe_payload(existing),
        "usage": usage,
    }
    return decision.model_copy(update={"raw_output": payload})


def _response_usage(value: Any) -> dict[str, Any] | None:
    """Extract provider-neutral usage without retaining the response object."""

    if isinstance(value, Mapping):
        candidates: list[Any] = [value.get("usage"), value.get("token_usage"), value.get("billing")]
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping):
            candidates.extend(
                metadata.get(key) for key in ("usage", "token_usage", "billing")
            )
    else:
        candidates = [getattr(value, key, None) for key in ("usage", "token_usage", "billing")]
    for candidate in candidates:
        if candidate is None:
            continue
        if hasattr(candidate, "model_dump"):
            try:
                candidate = candidate.model_dump(mode="json")
            except TypeError:
                candidate = candidate.model_dump()
        if isinstance(candidate, Mapping) and candidate:
            return _json_safe_payload(candidate)
    return None


def parse_planner_decision(
    value: Any,
    *,
    run_id: str = "run",
    round_index: int = 0,
) -> PlannerDecision:
    """Validate one model result and normalize common additive field names."""

    payload = parse_model_response(value)
    if isinstance(payload, PlannerDecision):
        if payload.round_index == round_index:
            return payload
        return payload.model_copy(update={"round_index": round_index})
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        payload = {"actions": list(payload)}
    if not isinstance(payload, Mapping):
        raise ValueError("planner response must be an object or action list")
    data = dict(payload)
    for nested_key in ("plan", "decision", "next_plan"):
        nested = data.get(nested_key)
        if isinstance(nested, Mapping):
            merged = dict(nested)
            merged.update({key: item for key, item in data.items() if key not in {nested_key}})
            data = merged
            break
    if "actions_to_add" in data and "append_actions" not in data:
        data["append_actions"] = data["actions_to_add"]
    data.pop("actions_to_add", None)
    if "additional_actions" in data and "append_actions" not in data:
        data["append_actions"] = data["additional_actions"]
    data.pop("additional_actions", None)
    if "should_stop" in data and "stop" not in data:
        data["stop"] = data["should_stop"]
    data.pop("should_stop", None)
    if "replan_required" in data and "stop" not in data:
        # A replanning answer is not a stop answer.  The field is retained in
        # compatibility responses but should not terminate.
        data.setdefault("reason", "model requested replanning")
    data.pop("replan_required", None)
    if "rationale" in data and "reason" not in data:
        data["reason"] = data["rationale"]
    data.pop("rationale", None)
    # A canonical PlanProposal may be returned by a model gateway configured
    # with the versioned contract rather than this adapter's compact decision
    # shape.  Identity is runtime-owned, so ignore those authority fields
    # after retaining the actionable values above.
    if "plan_actions" in data and "actions" not in data:
        data["actions"] = data["plan_actions"]
    if "steps" in data and "actions" not in data:
        data["actions"] = data["steps"]
    canonical_proposal = data.get("schema_version") == "adaptive-plan/v1" or (
        "proposal_id" in data
        and "objective_id" in data
        and any(key in data for key in ("plan_actions", "steps", "status"))
    )
    for key in ("plan_actions", "steps"):
        data.pop(key, None)
    if canonical_proposal:
        for key in (
            "schema_version",
            "proposal_id",
            "status",
            "created_at",
            "budget",
            "raw_payload",
            "target_question_ids",
            "target_hypothesis_ids",
            "based_on_observation_ids",
            "evidence_refs",
        ):
            data.pop(key, None)
    raw = data.get("raw_output", payload)
    actions = [
        coerce_action(item, run_id=run_id, round_index=round_index, position=index)
        for index, item in enumerate(data.get("actions") or ())
    ]
    appended = [
        coerce_action(
            item,
            run_id=run_id,
            round_index=round_index,
            position=len(actions) + index,
        )
        for index, item in enumerate(data.get("append_actions") or ())
    ]
    data["actions"] = actions
    data["append_actions"] = appended
    data["round_index"] = round_index
    data["raw_output"] = raw
    return PlannerDecision.model_validate(data)


def build_model_request(
    *,
    run_id: str,
    role: str,
    instruction: str,
    context: Mapping[str, Any],
    output_schema: Mapping[str, Any] | None = None,
) -> ModelRequest:
    """Build the shared contract request used by planner and critic calls."""

    request_id = f"{run_id}:{role}:{uuid.uuid4().hex}"
    prepared_schema = prepare_output_schema(output_schema)
    schema_context = (
        f"\nOUTPUT_SCHEMA={stable_json(prepared_schema)}"
        if prepared_schema is not None
        else ""
    )
    # UUID makes request identity unique, while the semantic prompt and action
    # ids remain deterministic.  Request ids are transport/audit metadata.
    return ModelRequest(
        request_id=request_id,
        model_role=role,
        messages=(
            ModelMessage(
                role="system",
                content=(
                    "Return only one JSON object matching the supplied output schema. "
                    "You are one bounded research component; never call tools, emit "
                    "tool calls, or name executable MCP methods. Use only logical "
                    "capability identifiers from the context. Never output provider "
                    "credentials, account context, or raw provider payloads."
                ),
            ),
            ModelMessage(
                role="user",
                content=(
                    f"{instruction}{schema_context}\n"
                    f"CONTEXT={stable_json(context)}"
                ),
            ),
        ),
        # The model receives capability metadata as inert context.  Execution
        # remains exclusively in the injected scheduler/Gateway boundary.
        tools=(),
        output_schema=prepared_schema,
    )


async def invoke_model(
    model: ModelPort | Any,
    request: ModelRequest,
    *,
    prompt: str | None = None,
    output_model: Any = None,
) -> Any:
    """Call a compatible async model port without coupling to a provider SDK."""

    methods: list[Callable[..., Any]] = []
    for name in ("generate", "complete", "call", "invoke"):
        method = getattr(model, name, None)
        if method is not None:
            methods.append(method)
            break
    if not methods and callable(model):
        methods.append(model)
    if not methods:
        raise TypeError("model port must provide async generate/complete/call/invoke")
    method = methods[0]
    text_prompt = prompt or request.messages[-1].content
    try:
        signature = inspect.signature(method)
        params = list(signature.parameters.values())
    except (TypeError, ValueError):
        params = []
    named = {item.name: item for item in params}
    if "request" in named or "model_request" in named:
        argument_name = "request" if "request" in named else "model_request"
        kwargs: dict[str, Any] = {argument_name: request}
        if "response_model" in named:
            kwargs["response_model"] = output_model
        if "output_model" in named:
            kwargs["output_model"] = output_model
        value = method(**kwargs)
    elif any(name in named for name in ("prompt", "text", "instruction", "input", "payload", "context", "messages", "role", "model_role")):
        kwargs = {}
        if "prompt" in named:
            kwargs["prompt"] = text_prompt
        elif "text" in named:
            kwargs["text"] = text_prompt
        elif "instruction" in named:
            kwargs["instruction"] = text_prompt
        if "messages" in named:
            kwargs["messages"] = request.messages
        if "input" in named:
            kwargs["input"] = text_prompt
        if "payload" in named:
            kwargs["payload"] = text_prompt
        if "context" in named:
            kwargs["context"] = request.messages[-1].content
        if "role" in named:
            kwargs["role"] = request.model_role
        if "model_role" in named:
            kwargs["model_role"] = request.model_role
        for name in ("output_schema", "schema"):
            if name in named:
                kwargs[name] = request.output_schema
        for name in ("response_model", "output_model", "response_type"):
            if name in named:
                kwargs[name] = output_model
        value = method(**kwargs)
    elif len(params) == 0:
        value = method()
    elif params and params[0].annotation is str:
        value = method(text_prompt)
    else:
        value = method(request)
    if inspect.isawaitable(value):
        return await cast(Awaitable[Any], value)
    return value


class AdaptivePlanner:
    """Rolling-horizon planner backed by an injected async ``ModelPort``."""

    def __init__(
        self,
        model: ModelPort | Any,
        *,
        model_role: str = "research_planner",
        max_actions_per_round: int = 32,
        output_schema: Mapping[str, Any] | None = None,
    ) -> None:
        if model is None:
            raise ValueError("adaptive planner requires an async model port")
        if max_actions_per_round < 1:
            raise ValueError("max_actions_per_round must be positive")
        self.model = model
        self.model_role = model_role
        self.max_actions_per_round = max_actions_per_round
        self.output_schema = (
            prepare_output_schema(output_schema)
            if output_schema is not None
            else deepcopy(PLANNER_OUTPUT_SCHEMA)
        )

    async def plan(
        self,
        goal: str | Mapping[str, Any] | Any,
        *,
        state: Any = None,
        run_id: str = "run",
        round_index: int = 0,
        mode: str = "initial",
        critique: Any = None,
        tool_capabilities: Any = None,
        tool_snapshot_ref: str | None = None,
    ) -> PlannerDecision:
        context = build_model_context(
            goal,
            state,
            critique,
            tool_capabilities=tool_capabilities,
            tool_snapshot_ref=tool_snapshot_ref,
        )
        request = build_model_request(
            run_id=run_id,
            role=self.model_role,
            instruction=(
                "Create the next bounded research plan. "
                "Only emit semantic typed actions with dependencies and idempotency keys. "
                f"This is the {mode} rolling-horizon turn {round_index}."
            ),
            context=context,
            output_schema=self.output_schema,
        )
        raw = await invoke_model(self.model, request, output_model=PlannerDecision)
        decision = attach_model_usage(
            parse_planner_decision(raw, run_id=run_id, round_index=round_index),
            raw,
        )
        # The pinned reference is runtime-owned.  A model may omit it after
        # seeing it in context, but it must never be allowed to create or
        # switch the snapshot reference itself.
        effective_snapshot_ref = tool_snapshot_ref or _state_field(
            state,
            ("tool_snapshot_ref", "capability_snapshot_ref", "snapshot_ref", "snapshotRef"),
        )
        if decision.tool_snapshot_ref is None and effective_snapshot_ref:
            decision = decision.model_copy(update={"tool_snapshot_ref": str(effective_snapshot_ref)})
        actions = decision.all_actions
        if len(actions) > self.max_actions_per_round:
            gap = ResearchGap(
                source="adaptive",
                operation="planner",
                code="plan_action_limit",
                message="planner emitted more actions than the per-round limit",
                details={"limit": self.max_actions_per_round, "emitted": len(actions)},
            )
            return decision.model_copy(
                update={"actions": actions[: self.max_actions_per_round], "append_actions": (), "gaps": (*decision.gaps, gap)}
            )
        return decision

    async def initial_plan(self, goal: str | Mapping[str, Any] | Any, **kwargs: Any) -> PlannerDecision:
        kwargs.setdefault("mode", "initial")
        kwargs.setdefault("round_index", 0)
        return await self.plan(goal, **kwargs)

    async def replan(self, goal: str | Mapping[str, Any] | Any, **kwargs: Any) -> PlannerDecision:
        kwargs.setdefault("mode", "replan")
        return await self.plan(goal, **kwargs)

    # Short aliases are useful for dependency-injection code and fakes.
    initial = initial_plan
    next_plan = replan


Planner = AdaptivePlanner
ModelPlanner = AdaptivePlanner


_MODEL_OMIT = object()
_RAW_CONTEXT_KEYS = frozenset({
    "raw",
    "raw_output",
    "raw_payload",
    "raw_payloads",
    "raw_comments",
    "raw_provider_payloads",
    "raw_return",
    "raw_returns",
    "raw_result",
    "raw_results",
    "raw_tool_return",
    "raw_tool_returns",
    "raw_observation",
    "raw_observations",
    "raw_source_payload",
    "raw_source_payloads",
    "provider_payload",
    "provider_payloads",
    "provider_return",
    "provider_returns",
    "provider_content",
    "provider_contents",
    "raw_content",
    "raw_contents",
    "source_payload",
    "source_payloads",
    "provider_response",
    "provider_responses",
})
_SENSITIVE_CONTEXT_KEYS = frozenset({
    "access_token",
    "account_id",
    "account_ref",
    "api_key",
    "apikey",
    "authorization",
    "base_url",
    "client_secret",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "headers",
    "id_token",
    "mcp_url",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret",
    "service_url",
    "session_id",
    "session_token",
    "tenant_id",
    "tenant_ref",
    "token",
    # Common camel-case spellings normalize to these values below.
    "accesstoken",
    "clientsecret",
    "idtoken",
    "privatekey",
    "refreshtoken",
    "sessionid",
    "sessiontoken",
    "tenantid",
    "tenantref",
})
_BEARER_PATTERN = re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s,;]+")


def _context_key(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_")


def _is_sensitive_context_key(value: Any) -> bool:
    key = _context_key(value)
    return key in _SENSITIVE_CONTEXT_KEYS or key.endswith(
        (
            "_token",
            "_secret",
            "_password",
            "_credential",
            "_api_key",
            "token",
            "secret",
            "password",
            "credential",
            "apikey",
        )
    )


def _model_safe_value(value: Any, *, key: Any = None, schema: bool = False) -> Any:
    """Convert values to a credential-free, JSON-only model projection.

    Raw provider/model payloads are intentionally excluded.  Capability
    schemas are declarative data, so their property names (which may include a
    word such as ``token``) are retained while sensitive defaults/metadata are
    still scrubbed.
    """

    normalized_key = _context_key(key) if key is not None else ""
    if not schema and normalized_key in _RAW_CONTEXT_KEYS:
        return _MODEL_OMIT
    if not schema and _is_sensitive_context_key(key):
        return _MODEL_OMIT
    if schema and normalized_key in {"default", "example", "examples"}:
        return _MODEL_OMIT
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            return _BEARER_PATTERN.sub("[REDACTED]", value)
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except TypeError:
            value = value.model_dump()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_schema = schema or _context_key(child_key) in {"input_schema", "output_schema"}
            projected = _model_safe_value(child_value, key=child_key, schema=child_schema)
            if projected is not _MODEL_OMIT:
                result[str(child_key)] = projected
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result_list: list[Any] = []
        values = value
        if isinstance(value, (set, frozenset)):
            values = sorted(value, key=lambda item: str(item))
        for child_value in values:
            projected = _model_safe_value(child_value, schema=schema)
            if projected is not _MODEL_OMIT:
                result_list.append(projected)
        return result_list
    return _BEARER_PATTERN.sub("[REDACTED]", str(value))


def _model_dump_for_context(value: Any) -> Any:
    projected = _model_safe_value(value)
    return None if projected is _MODEL_OMIT else projected


def _state_field(state: Any, names: Sequence[str], default: Any = None) -> Any:
    if state is None:
        return default
    if isinstance(state, Mapping):
        for name in names:
            if name in state and state[name] is not None:
                return state[name]
        return default
    for name in names:
        value = getattr(state, name, _MODEL_OMIT)
        if value is not _MODEL_OMIT and value is not None:
            return value
    return default


def _context_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (Mapping, str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _capability_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        if "capabilities" in value and not any(
            key in value
            for key in (
                "name",
                "public_name",
                "tool_name",
                "capability",
                "capability_id",
                "input_schema",
                "inputSchema",
            )
        ):
            return _context_sequence(value["capabilities"])
        if any(
            key in value
            for key in (
                "name",
                "public_name",
                "tool_name",
                "capability",
                "capability_id",
                "input_schema",
                "inputSchema",
            )
        ):
            return (value,)
        # Accept a mapping keyed by logical capability, which is convenient
        # for catalog adapters while still projecting every descriptor through
        # the same redaction/normalization path.
        return tuple(
            {
                **(dict(item) if isinstance(item, Mapping) else {}),
                "name": str(name),
                "capability": str(
                    item.get("capability", name) if isinstance(item, Mapping) else name
                ),
            }
            for name, item in value.items()
        )
    snapshot_capabilities = _state_field(value, ("capabilities",), _MODEL_OMIT)
    if snapshot_capabilities is not _MODEL_OMIT and snapshot_capabilities is not value:
        return _context_sequence(snapshot_capabilities)
    return _context_sequence(value)


def _project_capability(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {
            "name": value,
            "capability": value,
            "description": "",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "gateway": "mcp_gateway",
        }
    projected = _model_dump_for_context(value)
    if not isinstance(projected, Mapping):
        return None
    name = projected.get("name") or projected.get("public_name") or projected.get("tool_name")
    capability = projected.get("capability") or projected.get("capability_id") or name
    input_schema = projected.get("input_schema") or projected.get("inputSchema")
    output_schema = projected.get("output_schema") or projected.get("outputSchema")
    if not name and not capability:
        return None
    # Normalize aliases so the model has one stable vocabulary irrespective
    # of whether a managed catalog or a test mapping supplied the descriptor.
    result: dict[str, Any] = {
        "name": str(name or capability),
        "capability": str(capability or name),
        "version": str(projected.get("version") or projected.get("capability_version") or "1.0"),
        "description": str(projected.get("description") or ""),
        "input_schema": input_schema or {"type": "object"},
        "output_schema": output_schema or {"type": "object"},
        "side_effect": projected.get("side_effect") or projected.get("sideEffect") or "read_only",
        "gateway": projected.get("gateway") or "mcp_gateway",
        "timeout_ms": projected.get("timeout_ms") or projected.get("timeoutMs") or 30_000,
        "cost_units": projected.get("cost_units") if projected.get("cost_units") is not None else 1.0,
        "produces_evidence": bool(
            projected.get("produces_evidence", projected.get("producesEvidence", False))
        ),
        "supports_pagination": bool(
            projected.get("supports_pagination", projected.get("supportsPagination", False))
        ),
    }
    if "metadata" in projected:
        result["metadata"] = projected["metadata"]
    return result


def _project_capabilities(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _capability_items(value):
        projected = _project_capability(item)
        if projected is None:
            continue
        name = str(projected["name"])
        if name in seen:
            continue
        seen.add(name)
        result.append(projected)
    return result


def _project_critique_for_model(value: Any) -> Any:
    """Normalize legacy and canonical critique records into one read model."""

    projected = _model_dump_for_context(value)
    if not isinstance(projected, Mapping):
        return projected
    result = dict(projected)
    if "decision" not in result:
        if result.get("stop"):
            result["decision"] = "terminate"
        elif result.get("replan_required"):
            result["decision"] = "replan"
        else:
            result["decision"] = "continue"
    if "rationale" not in result and result.get("reason"):
        result["rationale"] = result["reason"]
    return result


def _project_state_for_model(
    state: Any,
    *,
    tool_capabilities: Any = None,
    tool_snapshot_ref: str | None = None,
) -> dict[str, Any]:
    """Project the canonical state without exposing runtime-only payloads."""

    dumped = _model_dump_for_context(state)
    raw_state = dumped if isinstance(dumped, Mapping) else {}
    snapshot = tool_snapshot_ref or _state_field(
        state,
        ("tool_snapshot_ref", "capability_snapshot_ref", "snapshot_ref", "snapshotRef"),
    )
    source_capabilities = tool_capabilities
    if source_capabilities is None:
        source_capabilities = _state_field(
            state,
            ("tool_capabilities", "capabilities", "tool_capability_snapshot"),
            (),
        )
    snapshot_object_ref = _state_field(source_capabilities, ("snapshot_ref", "snapshotRef"), None)
    snapshot = snapshot or snapshot_object_ref
    capabilities = _project_capabilities(source_capabilities)

    current_plan = _model_dump_for_context(_state_field(state, ("plan", "current_plan")))
    plan_history = _model_dump_for_context(_state_field(state, ("plan_history", "plans"), ()))
    observations = _model_dump_for_context(
        _state_field(state, ("observations", "observation_history"), ())
    )
    latest_critique = _project_critique_for_model(
        _state_field(state, ("critique", "latest_critique", "last_critique"))
    )
    projection: dict[str, Any] = {
        "schema_version": raw_state.get("schema_version", "adaptive-investigation/v1"),
        "investigation_id": raw_state.get("investigation_id") or raw_state.get("run_id"),
        "revision": raw_state.get("revision", raw_state.get("state_revision", 0)),
        "status": raw_state.get("status", "planning"),
        "objective": _model_dump_for_context(_state_field(state, ("objective",))),
        "questions": _model_dump_for_context(_state_field(state, ("questions",), ())),
        "hypotheses": _model_dump_for_context(_state_field(state, ("hypotheses",), ())),
        "current_plan": current_plan,
        "plan_history": plan_history if plan_history is not None else [],
        "observations": observations if observations is not None else [],
        "latest_critique": latest_critique,
        "budget": _model_dump_for_context(_state_field(state, ("budget",))),
        "budget_usage": _model_dump_for_context(
            _state_field(state, ("budget_usage", "usage"), {})
        ),
        "tool_snapshot_ref": str(snapshot) if snapshot else None,
        "snapshot_ref": str(snapshot) if snapshot else None,
        "tool_capabilities": capabilities,
        "capabilities": capabilities,
        "evidence_refs": _model_dump_for_context(_state_field(state, ("evidence_refs",), ())),
        "findings": _model_dump_for_context(_state_field(state, ("findings",), ())),
        "controversies": _model_dump_for_context(_state_field(state, ("controversies",), ())),
        "gaps": _model_dump_for_context(_state_field(state, ("gaps",), ())),
        "continuation": _model_dump_for_context(_state_field(state, ("continuation",), {})),
    }
    projection["plan"] = current_plan
    projection["critique"] = latest_critique
    # Keep additive, non-sensitive state fields available to an adaptive model
    # without allowing raw provider values to bypass the projection above.
    for key, value in raw_state.items():
        projection.setdefault(str(key), value)
    return projection


def build_model_context(
    goal: Any,
    state: Any = None,
    critique: Any = None,
    *,
    observations: Sequence[Any] | None = None,
    tool_capabilities: Any = None,
    tool_snapshot_ref: str | None = None,
) -> dict[str, Any]:
    """Build the shared safe context sent to planner and critic model roles."""

    state_projection = _project_state_for_model(
        state,
        tool_capabilities=tool_capabilities,
        tool_snapshot_ref=tool_snapshot_ref,
    )
    previous_critique = _project_critique_for_model(
        critique
        if critique is not None
        else _state_field(state, ("critique", "latest_critique", "last_critique"))
    )
    history = state_projection.get("observations") or []
    # The canonical state carries the complete normalized observation data
    # exactly once. A planner turn does not need a second copy of the entire
    # history; a critic receives an index of only the newly completed wave.
    # Keep the same compact shape for integrations using the history alias.
    latest_values = [] if observations is None else [
        _model_dump_for_context(item) for item in observations
    ]
    latest = _observation_history_index(latest_values)
    history_index = _observation_history_index(history)
    canonical_state_ref = {
        "$ref": "state",
        "investigation_id": state_projection.get("investigation_id"),
        "revision": state_projection.get("revision"),
        "tool_snapshot_ref": state_projection.get("tool_snapshot_ref"),
        "tool_capabilities": state_projection.get("tool_capabilities", []),
    }
    context = {
        "goal": _model_dump_for_context(goal),
        "state": state_projection,
        # Keep an explicit compatibility alias without serializing the full
        # state a second time.  ``state`` is the canonical complete view.
        "canonical_state": canonical_state_ref,
        "current_plan": state_projection.get("current_plan"),
        "observations": latest,
        "latest_observations": latest,
        "observation_history": history_index,
        "previous_critique": previous_critique,
        "last_critique": previous_critique,
        "tool_snapshot_ref": state_projection.get("tool_snapshot_ref"),
        "snapshot_ref": state_projection.get("snapshot_ref"),
        "tool_capabilities": state_projection.get("tool_capabilities", []),
        "capabilities": state_projection.get("capabilities", []),
    }
    return context


def _observation_history_index(value: Any) -> list[dict[str, Any]]:
    """Build a compact audit index while state retains full observation data."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    fields = (
        "observation_id",
        "action_id",
        "kind",
        "outcome",
        "source",
        "capability",
        "evidence_refs",
        "cursor",
        "next_cursor",
        "has_more",
        "completeness",
        "continuation",
        "gap",
        "sequence",
    )
    result: list[dict[str, Any]] = []
    for item in value:
        projected = _model_dump_for_context(item)
        if not isinstance(projected, Mapping):
            continue
        result.append(
            {
                field: projected[field]
                for field in fields
                if field in projected
            }
        )
    return result


# Private compatibility spelling retained for callers that imported the
# prototype helper before the canonical context projection was introduced.
def _planning_context(goal: Any, state: Any, critique: Any) -> dict[str, Any]:
    return build_model_context(goal, state, critique)


class ScriptedModelPort:
    """Deterministic async model fake that records every contract request."""

    def __init__(self, responses: Sequence[Any] | Callable[[Any], Any]) -> None:
        self._responses = list(responses) if not callable(responses) else responses
        self.requests: list[Any] = []
        self.calls = 0

    async def generate(self, request: Any) -> Any:
        self.requests.append(request)
        self.calls += 1
        if callable(self._responses):
            value = self._responses(request)
        elif self._responses:
            value = self._responses.pop(0)
        else:
            value = {"actions": [], "stop": True, "reason": "script exhausted"}
        if inspect.isawaitable(value):
            return await cast(Awaitable[Any], value)
        return value


DeterministicFakeModel = ScriptedModelPort
FakeModelPort = ScriptedModelPort


__all__ = [
    "ActionKind",
    "ActionSpec",
    "AdaptiveAction",
    "AdaptivePlanner",
    "DeterministicFakeModel",
    "FakeModelPort",
    "InvestigationAction",
    "InvestigationPlan",
    "ModelPlanner",
    "ModelPort",
    "PLANNER_OUTPUT_SCHEMA",
    "PlanDecision",
    "Planner",
    "PlannerDecision",
    "prepare_output_schema",
    "parse_model_response",
    "ScriptedModelPort",
    "TypedAction",
    "build_model_context",
    "build_model_request",
    "coerce_action",
    "invoke_model",
    "parse_planner_decision",
    "strict_output_schema",
    "stable_json",
]
