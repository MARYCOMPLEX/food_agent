"""Versioned contracts used by the canonical adaptive investigation loop.

The contracts keep objectives, plans, observations, budgets, capability
snapshots, evidence references, and termination state strict and serializable.
Execution remains in ``research.adaptive``; MCP routing, Food reduction, and
evidence/profile persistence stay behind their owning adapters and ports.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from .base import (
    ContractPayload,
    JsonValue,
    NonEmptyStr,
    Timestamp,
    VersionedContract,
)
from .research import ResearchGap, ResearchOutcome

ADAPTIVE_INVESTIGATION_SCHEMA_VERSION = "adaptive-investigation/v1"
OBJECTIVE_SCHEMA_VERSION = "adaptive-objective/v1"
QUESTION_SCHEMA_VERSION = "adaptive-question/v1"
HYPOTHESIS_SCHEMA_VERSION = "adaptive-hypothesis/v1"
INVESTIGATION_BUDGET_SCHEMA_VERSION = "adaptive-budget/v1"
BUDGET_USAGE_SCHEMA_VERSION = "adaptive-budget-usage/v1"
TOOL_CAPABILITY_SCHEMA_VERSION = "adaptive-tool-capability/v1"
TOOL_CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "adaptive-tool-snapshot/v1"
PLAN_ACTION_SCHEMA_VERSION = "adaptive-plan-action/v1"
PLAN_PROPOSAL_SCHEMA_VERSION = "adaptive-plan/v1"
OBSERVATION_SCHEMA_VERSION = "adaptive-observation/v1"
CRITIQUE_SCHEMA_VERSION = "adaptive-critique/v1"
TERMINATION_SCHEMA_VERSION = "adaptive-termination/v1"


_IDENTIFIER = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[^\s\x00-\x1f\x7f]+$",
    ),
]


def _unique_nonempty(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    """Reject duplicate or opaque-reference-shaped values at the boundary."""

    if any(not value or any(ord(char) < 32 for char in value) for value in values):
        raise ValueError(f"{field_name} must contain non-empty printable values")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _validate_json_value(value: object, path: str) -> None:
    """Reject non-JSON values and non-finite numbers in opaque payload fields."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} must not contain NaN or Infinity")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string JSON key")
            _validate_json_value(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    raise ValueError(f"{path} must contain JSON-compatible values")


def _validate_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is not None and value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC RFC 3339 time")
    return value


class _AdaptiveContract(VersionedContract):
    """Immutable, strict object boundary shared by adaptive contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    _json_fields: ClassVar[tuple[str, ...]] = (
        "arguments",
        "attributes",
        "constraints",
        "continuation",
        "data",
        "input_schema",
        "metadata",
        "output_schema",
        "provenance",
        "raw_payload",
    )
    _numeric_fields: ClassVar[tuple[str, ...]] = (
        "confidence",
        "cost_units",
        "elapsed_seconds",
        "estimated_cost_units",
        "max_cost_units",
        "max_wall_time_seconds",
    )

    @model_validator(mode="after")
    def validate_opaque_json(self) -> Self:
        for field_name in self._json_fields:
            value = getattr(self, field_name, None)
            if value is not None:
                _validate_json_value(value, field_name)
        for field_name in self._numeric_fields:
            value = getattr(self, field_name, None)
            if isinstance(value, float) and not isfinite(value):
                raise ValueError(f"{field_name} must not be NaN or Infinity")
        return self


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class HypothesisStatus(StrEnum):
    UNTESTED = "untested"
    TESTING = "testing"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class PlanActionKind(StrEnum):
    TOOL_CALL = "tool_call"
    SEARCH = "search"
    FETCH = "fetch"
    ANALYZE = "analyze"
    VERIFY = "verify"
    CROSS_VALIDATE = "cross_validate"
    CRITIQUE = "critique"
    SYNTHESIZE = "synthesize"
    STOP = "stop"


class PlanProposalStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ObservationKind(StrEnum):
    TOOL_RESULT = "tool_result"
    SOURCE = "source"
    EVIDENCE = "evidence"
    ANALYSIS = "analysis"
    CRITIQUE = "critique"
    ERROR = "error"
    PROGRESS = "progress"


class ObservationOutcome(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ObservationCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class CritiqueDisposition(StrEnum):
    CONTINUE = "continue"
    REPLAN = "replan"
    REQUEST_EVIDENCE = "request_evidence"
    SYNTHESIZE = "synthesize"
    TERMINATE = "terminate"


class TerminationReason(StrEnum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    NO_PROGRESS = "no_progress"
    USER_REQUESTED = "user_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    POLICY_DENIED = "policy_denied"


class InvestigationStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    EMPTY = "empty"
    COMPLETED = "completed"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Kept as a terminal wire value for callers that distinguish an explicit
    # planner/critic stop from a naturally completed run.
    STOPPED = "stopped"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.COMPLETE,
            self.EMPTY,
            self.PARTIAL,
            self.FAILED,
            self.CANCELLED,
            self.STOPPED,
        }


class ToolSideEffect(StrEnum):
    READ_ONLY = "read_only"
    ACCOUNT_LOGIN = "account_login"
    ACCOUNT_MUTATION = "account_mutation"
    PUBLISH = "publish"
    UPLOAD = "upload"
    SHELL = "shell"
    CREDENTIAL_EXPORT = "credential_export"


class Objective(_AdaptiveContract):
    """Stable investigation objective supplied by the user/use case."""

    schema_version: Literal["adaptive-objective/v1"] = OBJECTIVE_SCHEMA_VERSION
    objective_id: _IDENTIFIER = Field(validation_alias=AliasChoices("objective_id", "id"))
    statement: NonEmptyStr = Field(
        validation_alias=AliasChoices("statement", "description", "text", "goal")
    )
    success_criteria: tuple[NonEmptyStr, ...] = ()
    constraints: ContractPayload = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0)
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    raw_payload: JsonValue | None = None

    @field_validator("success_criteria", "evidence_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @property
    def id(self) -> str:
        return self.objective_id

    @property
    def description(self) -> str:
        return self.statement

    @property
    def goal(self) -> str:
        return self.statement


class Question(_AdaptiveContract):
    """A bounded question that the investigation must answer or explain."""

    schema_version: Literal["adaptive-question/v1"] = QUESTION_SCHEMA_VERSION
    question_id: _IDENTIFIER = Field(validation_alias=AliasChoices("question_id", "id"))
    text: NonEmptyStr = Field(
        validation_alias=AliasChoices("text", "question", "prompt", "query")
    )
    objective_id: _IDENTIFIER | None = None
    status: QuestionStatus = QuestionStatus.OPEN
    priority: int = Field(default=0, ge=0)
    question_type: Literal["primary", "follow_up", "verification", "clarification"] = "primary"
    answer: JsonValue | None = None
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    raw_payload: JsonValue | None = None

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "evidence_refs")

    @property
    def id(self) -> str:
        return self.question_id

    @property
    def prompt(self) -> str:
        return self.text


class Hypothesis(_AdaptiveContract):
    """A falsifiable working hypothesis updated from observations."""

    schema_version: Literal["adaptive-hypothesis/v1"] = HYPOTHESIS_SCHEMA_VERSION
    hypothesis_id: _IDENTIFIER = Field(validation_alias=AliasChoices("hypothesis_id", "id"))
    statement: NonEmptyStr = Field(validation_alias=AliasChoices("statement", "text", "claim"))
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    question_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("question_ids", "question_refs")
    )
    assumptions: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    raw_payload: JsonValue | None = None

    @field_validator("question_ids", "assumptions", "evidence_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @model_validator(mode="after")
    def validate_supported_hypothesis(self) -> Self:
        if self.status in {HypothesisStatus.SUPPORTED, HypothesisStatus.REFUTED} and not self.evidence_refs:
            raise ValueError("supported or refuted hypotheses require evidence_refs")
        return self

    @property
    def id(self) -> str:
        return self.hypothesis_id

    @property
    def text(self) -> str:
        return self.statement


class InvestigationBudget(_AdaptiveContract):
    """Hard ceilings for one investigation; at least one ceiling is required."""

    schema_version: Literal["adaptive-budget/v1"] = (
        INVESTIGATION_BUDGET_SCHEMA_VERSION
    )
    max_iterations: int | None = Field(
        default=10,
        ge=0,
        validation_alias=AliasChoices("max_iterations", "max_rounds"),
    )
    max_actions: int | None = Field(default=40, ge=0)
    max_tool_calls: int | None = Field(
        default=40,
        ge=0,
        validation_alias=AliasChoices("max_tool_calls", "max_calls"),
    )
    max_cost_units: float | None = Field(default=100.0, ge=0.0)
    max_tokens: int | None = Field(
        default=100_000,
        ge=0,
        validation_alias=AliasChoices("max_tokens", "max_model_tokens", "max_llm_tokens"),
    )
    max_observations: int | None = Field(default=200, ge=0)
    max_wall_time_seconds: float | None = Field(default=900.0, ge=0.0)
    deadline_at: Timestamp | None = None

    @field_validator("deadline_at")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return _validate_utc(value, "deadline_at")

    @model_validator(mode="after")
    def validate_bounded(self) -> Self:
        ceilings = (
            self.max_iterations,
            self.max_actions,
            self.max_tool_calls,
            self.max_cost_units,
            self.max_tokens,
            self.max_observations,
            self.max_wall_time_seconds,
            self.deadline_at,
        )
        if all(value is None for value in ceilings):
            raise ValueError("an investigation budget requires at least one finite ceiling")
        return self

    def exhausted_dimensions(self, usage: BudgetUsage) -> tuple[str, ...]:
        """Return dimensions at or above their configured ceiling."""

        dimensions: list[str] = []
        checks = (
            ("iterations", self.max_iterations, usage.iterations),
            ("actions", self.max_actions, usage.actions),
            ("tool_calls", self.max_tool_calls, usage.tool_calls),
            ("cost_units", self.max_cost_units, usage.cost_units),
            ("tokens", self.max_tokens, usage.tokens),
            ("observations", self.max_observations, usage.observations),
            ("wall_time_seconds", self.max_wall_time_seconds, usage.elapsed_seconds),
        )
        for name, limit, consumed in checks:
            if limit is not None and consumed >= limit:
                dimensions.append(name)
        if self.deadline_at is not None and datetime.now(UTC) >= self.deadline_at:
            dimensions.append("deadline")
        return tuple(dimensions)

    def is_exhausted(self, usage: BudgetUsage) -> bool:
        return bool(self.exhausted_dimensions(usage))

    @property
    def max_rounds(self) -> int | None:
        """Compatibility projection for scheduler terminology."""

        return self.max_iterations

    @property
    def max_calls(self) -> int | None:
        """Compatibility projection for scheduler terminology."""

        return self.max_tool_calls


class BudgetUsage(_AdaptiveContract):
    """Observed consumption; values may exceed a ceiling to record overshoot."""

    schema_version: Literal["adaptive-budget-usage/v1"] = BUDGET_USAGE_SCHEMA_VERSION
    iterations: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("iterations", "rounds"),
    )
    actions: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    cost_units: float = Field(default=0.0, ge=0.0)
    tokens: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("tokens", "model_tokens", "llm_tokens"),
    )
    observations: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)

    @property
    def model_tokens(self) -> int:
        return self.tokens

    @property
    def rounds(self) -> int:
        """Compatibility projection for scheduler terminology."""

        return self.iterations

    @property
    def calls(self) -> int:
        """Compatibility projection for scheduler terminology."""

        return self.tool_calls


class BudgetSnapshot(_AdaptiveContract):
    """Serializable limit/usage pair used in state and termination metadata."""

    schema_version: Literal["adaptive-budget-snapshot/v1"] = "adaptive-budget-snapshot/v1"
    budget: InvestigationBudget
    usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @property
    def exhausted(self) -> bool:
        return self.budget.is_exhausted(self.usage)

    @property
    def exhausted_dimensions(self) -> tuple[str, ...]:
        return self.budget.exhausted_dimensions(self.usage)


class ToolCapabilityMetadata(_AdaptiveContract):
    """Model-visible metadata for a capability exposed through the MCP Gateway."""

    schema_version: Literal["adaptive-tool-capability/v1"] = TOOL_CAPABILITY_SCHEMA_VERSION
    name: _IDENTIFIER = Field(validation_alias=AliasChoices("name", "public_name", "tool_name"))
    capability: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("capability", "capability_id"),
    )
    version: _IDENTIFIER = Field(
        default="1.0",
        validation_alias=AliasChoices("version", "capability_version"),
    )
    description: str = ""
    input_schema: ContractPayload = Field(default_factory=lambda: {"type": "object"})
    output_schema: ContractPayload = Field(default_factory=lambda: {"type": "object"})
    side_effect: ToolSideEffect = ToolSideEffect.READ_ONLY
    gateway: Literal["mcp_gateway"] = "mcp_gateway"
    timeout_ms: int = Field(default=30_000, gt=0)
    cost_units: float = Field(default=1.0, ge=0.0)
    produces_evidence: bool = False
    supports_pagination: bool = False
    metadata: ContractPayload = Field(default_factory=dict)
    raw_payload: JsonValue | None = None

    @model_validator(mode="after")
    def validate_capability_metadata(self) -> Self:
        if self.capability is None:
            object.__setattr__(self, "capability", self.name)
        for schema_name in ("input_schema", "output_schema"):
            schema = getattr(self, schema_name)
            schema_type = schema.get("type")
            if schema_type is not None and schema_type != "object":
                raise ValueError(f"{schema_name} must describe an object boundary")
        if len(self.description) > 2_000:
            raise ValueError("tool capability description is too long")
        return self

    @property
    def public_name(self) -> str:
        return self.name

    @property
    def capability_version(self) -> str:
        return self.version


class ToolCapabilitySnapshot(_AdaptiveContract):
    """Immutable per-run capability metadata snapshot."""

    schema_version: Literal["adaptive-tool-snapshot/v1"] = (
        TOOL_CAPABILITY_SNAPSHOT_SCHEMA_VERSION
    )
    snapshot_ref: _IDENTIFIER = Field(
        validation_alias=AliasChoices("snapshot_ref", "capability_snapshot_ref")
    )
    capabilities: tuple[ToolCapabilityMetadata, ...] = ()
    captured_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    gateway: Literal["mcp_gateway"] = "mcp_gateway"
    raw_payload: JsonValue | None = None

    @field_validator("captured_at")
    @classmethod
    def validate_capture_time(cls, value: datetime) -> datetime:
        return _validate_utc(value, "captured_at")  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        names = tuple(capability.name for capability in self.capabilities)
        if len(names) != len(set(names)):
            raise ValueError("tool capability names must be unique in a snapshot")
        return self


class ActionBudget(_AdaptiveContract):
    """Optional estimate and retry ceiling attached to one planned action."""

    schema_version: Literal["adaptive-action-budget/v1"] = "adaptive-action-budget/v1"
    max_attempts: int = Field(default=1, ge=1)
    estimated_tool_calls: int = Field(default=0, ge=0)
    estimated_cost_units: float = Field(default=0.0, ge=0.0)
    estimated_tokens: int = Field(default=0, ge=0)


class PlanAction(_AdaptiveContract):
    """One model-proposed semantic action, never a raw provider invocation."""

    schema_version: Literal["adaptive-plan-action/v1"] = PLAN_ACTION_SCHEMA_VERSION
    action_id: _IDENTIFIER = Field(validation_alias=AliasChoices("action_id", "id"))
    kind: PlanActionKind = Field(
        default=PlanActionKind.TOOL_CALL,
        validation_alias=AliasChoices("kind", "action_kind", "type"),
    )
    capability: _IDENTIFIER = Field(
        validation_alias=AliasChoices("capability", "tool_capability", "capability_id")
    )
    tool_name: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_name", "public_tool_name"),
    )
    resource_class: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_class", "resource"),
    )
    arguments: ContractPayload = Field(
        default_factory=dict,
        validation_alias=AliasChoices("arguments", "inputs", "input"),
    )
    depends_on: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("depends_on", "dependencies")
    )
    question_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("question_ids", "question_refs")
    )
    hypothesis_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("hypothesis_ids", "hypothesis_refs")
    )
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    expected_observation_kinds: tuple[ObservationKind, ...] = ()
    idempotency_key: _IDENTIFIER | None = None
    priority: int = Field(default=0, ge=0)
    rationale: str = ""
    budget: ActionBudget = Field(default_factory=ActionBudget)
    raw_payload: JsonValue | None = None

    @field_validator("depends_on", "question_ids", "hypothesis_ids", "evidence_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action_id in self.depends_on:
            raise ValueError("an action cannot depend on itself")
        if self.idempotency_key is None:
            object.__setattr__(self, "idempotency_key", self.action_id)
        return self

    @property
    def id(self) -> str:
        return self.action_id

    @property
    def tool_capability(self) -> str:
        return self.capability

    @property
    def inputs(self) -> ContractPayload:
        """Compatibility projection for the pre-canonical scheduler API."""

        return self.arguments

    @property
    def dependencies(self) -> tuple[str, ...]:
        """Compatibility projection for the pre-canonical scheduler API."""

        return self.depends_on

    @property
    def resource(self) -> str:
        return self.resource_class or self.capability

    @property
    def token_estimate(self) -> int:
        return self.budget.estimated_tokens

    @property
    def cost_units(self) -> float:
        return self.budget.estimated_cost_units


class PlanProposal(_AdaptiveContract):
    """A complete rolling-plan proposal pinned to an investigation revision."""

    schema_version: Literal["adaptive-plan/v1"] = PLAN_PROPOSAL_SCHEMA_VERSION
    proposal_id: _IDENTIFIER = Field(validation_alias=AliasChoices("proposal_id", "id"))
    investigation_id: _IDENTIFIER = Field(
        validation_alias=AliasChoices("investigation_id", "run_id")
    )
    objective_id: _IDENTIFIER
    revision: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("revision", "iteration", "plan_revision"),
    )
    base_revision: int = Field(default=0, ge=0)
    status: PlanProposalStatus = PlanProposalStatus.PROPOSED
    actions: tuple[PlanAction, ...] = Field(
        default=(), validation_alias=AliasChoices("actions", "plan_actions", "steps")
    )
    rationale: NonEmptyStr = "model proposed next evidence actions"
    created_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    target_question_ids: tuple[_IDENTIFIER, ...] = ()
    target_hypothesis_ids: tuple[_IDENTIFIER, ...] = ()
    based_on_observation_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("based_on_observation_ids", "observation_ids")
    )
    tool_snapshot_ref: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_snapshot_ref", "capability_snapshot_ref"),
    )
    budget: InvestigationBudget | None = None
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    raw_payload: JsonValue | None = None

    @field_validator(
        "target_question_ids",
        "target_hypothesis_ids",
        "based_on_observation_ids",
        "evidence_refs",
    )
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @field_validator("created_at")
    @classmethod
    def validate_creation_time(cls, value: datetime) -> datetime:
        return _validate_utc(value, "created_at")  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_action_graph(self) -> Self:
        if self.base_revision > self.revision:
            raise ValueError("base_revision cannot exceed revision")
        action_ids = tuple(action.action_id for action in self.actions)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("plan action_id values must be unique")
        known = set(action_ids)
        for action in self.actions:
            unknown = set(action.depends_on) - known
            if unknown:
                raise ValueError(
                    f"action {action.action_id!r} has unknown dependencies: {sorted(unknown)!r}"
                )
        _reject_dependency_cycles(self.actions)
        return self

    @property
    def id(self) -> str:
        return self.proposal_id

    @property
    def plan_actions(self) -> tuple[PlanAction, ...]:
        return self.actions

    @property
    def iteration(self) -> int:
        return self.revision


def _reject_dependency_cycles(actions: tuple[PlanAction, ...]) -> None:
    """Reject cycles with an iterative topological walk."""

    remaining = {action.action_id: len(action.depends_on) for action in actions}
    dependents: dict[str, list[str]] = {action.action_id: [] for action in actions}
    for action in actions:
        for dependency in action.depends_on:
            dependents[dependency].append(action.action_id)
    ready = [action_id for action_id, count in remaining.items() if count == 0]
    visited = 0
    while ready:
        action_id = ready.pop()
        visited += 1
        for dependent in dependents[action_id]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    if visited != len(actions):
        cyclic = sorted(action_id for action_id, count in remaining.items() if count > 0)
        raise ValueError(f"plan dependency cycle detected among {cyclic!r}")


class ObservationEnvelope(_AdaptiveContract):
    """Append-only normalized observation with its untouched provider payload."""

    schema_version: Literal["adaptive-observation/v1"] = OBSERVATION_SCHEMA_VERSION
    observation_id: _IDENTIFIER = Field(validation_alias=AliasChoices("observation_id", "id"))
    investigation_id: _IDENTIFIER = Field(
        validation_alias=AliasChoices("investigation_id", "run_id")
    )
    action_id: _IDENTIFIER | None = None
    kind: ObservationKind = Field(
        default=ObservationKind.TOOL_RESULT,
        validation_alias=AliasChoices("kind", "observation_kind", "type"),
    )
    outcome: ObservationOutcome = ObservationOutcome.SUCCESS
    observed_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    sequence: int | None = Field(default=None, ge=1)
    source: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("source", "source_id", "provider"),
    )
    capability: _IDENTIFIER | None = None
    data: JsonValue | None = Field(
        default=None,
        validation_alias=AliasChoices("data", "normalized", "payload", "value"),
    )
    raw_payload: JsonValue | None = Field(
        default=None,
        validation_alias=AliasChoices("raw_payload", "raw", "provider_payload"),
    )
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    cursor: NonEmptyStr | None = None
    next_cursor: NonEmptyStr | None = None
    has_more: bool = False
    completeness: ObservationCompleteness = ObservationCompleteness.UNKNOWN
    continuation: ContractPayload = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: ContractPayload = Field(default_factory=dict)
    metadata: ContractPayload = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def validate_observation_time(cls, value: datetime) -> datetime:
        return _validate_utc(value, "observed_at")  # type: ignore[return-value]

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "evidence_refs")

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            self.data is not None
            and self.kind
            in {
                ObservationKind.TOOL_RESULT,
                ObservationKind.SOURCE,
                ObservationKind.EVIDENCE,
            }
            and self.raw_payload is None
        ):
            raise ValueError("source/tool observation data requires raw_payload")
        if self.has_more and not self.next_cursor:
            raise ValueError("an observation with has_more requires next_cursor")
        if self.completeness is ObservationCompleteness.COMPLETE and self.has_more:
            raise ValueError("a complete observation cannot have more pages")
        if (
            self.outcome is not ObservationOutcome.SUCCESS
            and self.completeness is ObservationCompleteness.COMPLETE
        ):
            raise ValueError("a non-success observation cannot be complete")
        return self

    @property
    def id(self) -> str:
        return self.observation_id

    @property
    def payload(self) -> JsonValue | None:
        return self.data

    @property
    def raw_return(self) -> JsonValue | None:
        """Compatibility projection for execution observations."""

        return self.raw_payload

    @property
    def raw_result(self) -> JsonValue | None:
        return self.raw_payload

    @property
    def result(self) -> JsonValue | None:
        return self.data

    @property
    def success(self) -> bool:
        return self.outcome in {
            ObservationOutcome.SUCCESS,
            ObservationOutcome.PARTIAL,
        }

    @property
    def operation(self) -> str:
        return self.capability or self.kind.value

    @property
    def gap(self) -> ResearchGap | None:
        """Compatibility projection for execution-layer failure details.

        The canonical envelope keeps failure details inside its strict
        metadata map so provider fields remain lossless.  Execution callers
        can still inspect a typed gap without maintaining a second envelope
        model.
        """

        value = self.metadata.get("gap")
        if isinstance(value, ResearchGap):
            return value
        if isinstance(value, Mapping):
            try:
                return ResearchGap.model_validate(value)
            except Exception:
                return None
        return None

    @property
    def status(self) -> str:
        """Execution status projection derived from the canonical outcome."""

        return {
            ObservationOutcome.SUCCESS: "completed",
            ObservationOutcome.PARTIAL: "completed",
            ObservationOutcome.FAILURE: "failed",
            ObservationOutcome.REJECTED: "rejected",
            ObservationOutcome.SKIPPED: "skipped",
        }[self.outcome]


class CritiqueDecision(_AdaptiveContract):
    """Evidence-aware model decision that controls the next rolling plan."""

    schema_version: Literal["adaptive-critique/v1"] = CRITIQUE_SCHEMA_VERSION
    decision_id: _IDENTIFIER = Field(validation_alias=AliasChoices("decision_id", "id"))
    investigation_id: _IDENTIFIER = Field(
        validation_alias=AliasChoices("investigation_id", "run_id")
    )
    decision: CritiqueDisposition = Field(
        default=CritiqueDisposition.CONTINUE,
        validation_alias=AliasChoices("decision", "disposition", "action"),
    )
    rationale: NonEmptyStr = "continue gathering evidence"
    plan_revision: int = Field(default=0, ge=0)
    observation_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("observation_ids", "observation_refs")
    )
    question_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("question_ids", "question_refs")
    )
    hypothesis_ids: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("hypothesis_ids", "hypothesis_refs")
    )
    requested_capabilities: tuple[_IDENTIFIER, ...] = Field(
        default=(), validation_alias=AliasChoices("requested_capabilities", "capability_refs")
    )
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    budget_usage: BudgetUsage | None = None
    raw_payload: JsonValue | None = None

    @field_validator(
        "observation_ids",
        "question_ids",
        "hypothesis_ids",
        "requested_capabilities",
        "evidence_refs",
    )
    @classmethod
    def validate_references(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _unique_nonempty(values, str(info.field_name))

    @property
    def disposition(self) -> CritiqueDisposition:
        return self.decision


class Termination(_AdaptiveContract):
    """Terminal decision with an explicit reason and optional continuation."""

    schema_version: Literal["adaptive-termination/v1"] = TERMINATION_SCHEMA_VERSION
    termination_id: _IDENTIFIER = Field(
        default="termination-1", validation_alias=AliasChoices("termination_id", "id")
    )
    investigation_id: _IDENTIFIER = Field(
        validation_alias=AliasChoices("investigation_id", "run_id")
    )
    reason: TerminationReason = Field(
        validation_alias=AliasChoices("reason", "termination_reason", "code")
    )
    summary: NonEmptyStr = "investigation terminated"
    occurred_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    continuation: ContractPayload = Field(default_factory=dict)
    resumable: bool = False
    raw_payload: JsonValue | None = None

    @field_validator("occurred_at")
    @classmethod
    def validate_termination_time(cls, value: datetime) -> datetime:
        return _validate_utc(value, "occurred_at")  # type: ignore[return-value]

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "evidence_refs")

    @model_validator(mode="after")
    def validate_continuation(self) -> Self:
        if self.resumable and not self.continuation:
            raise ValueError("a resumable termination requires continuation metadata")
        return self

    @property
    def terminal(self) -> Literal[True]:
        return True


class InvestigationState(_AdaptiveContract):
    """Immutable state snapshot for one rolling evidence-feedback loop."""

    schema_version: Literal["adaptive-investigation/v1"] = (
        ADAPTIVE_INVESTIGATION_SCHEMA_VERSION
    )
    investigation_id: _IDENTIFIER = Field(
        validation_alias=AliasChoices("investigation_id", "run_id", "state_id")
    )
    revision: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("revision", "state_revision"),
    )
    status: InvestigationStatus = InvestigationStatus.PLANNING
    objective: Objective
    questions: tuple[Question, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    plan: PlanProposal | None = Field(
        default=None, validation_alias=AliasChoices("plan", "current_plan")
    )
    plan_history: tuple[PlanProposal, ...] = ()
    observations: tuple[ObservationEnvelope, ...] = Field(
        default=(), validation_alias=AliasChoices("observations", "observation_history")
    )
    critique: CritiqueDecision | None = None
    termination: Termination | None = None
    # These projections keep the audit state useful to the transport/domain
    # adapters without reintroducing a second runtime state contract.
    outcome: ResearchOutcome = ResearchOutcome.EMPTY
    rounds: tuple[Any, ...] = ()
    findings: tuple[JsonValue, ...] = ()
    controversies: tuple[JsonValue, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    continuation: ContractPayload = Field(default_factory=dict)
    stop_reason: str = ""
    created_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    budget: InvestigationBudget = Field(default_factory=InvestigationBudget)
    budget_usage: BudgetUsage = Field(
        default_factory=BudgetUsage,
        validation_alias=AliasChoices("budget_usage", "usage"),
    )
    tool_capabilities: tuple[ToolCapabilityMetadata, ...] = Field(
        default=(), validation_alias=AliasChoices("tool_capabilities", "capabilities")
    )
    tool_snapshot_ref: _IDENTIFIER | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_snapshot_ref", "capability_snapshot_ref"),
    )
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    metadata: ContractPayload = Field(default_factory=dict)
    raw_payload: JsonValue | None = None

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_nonempty(values, "evidence_refs")

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_state_times(cls, value: datetime) -> datetime:
        return _validate_utc(value, "state timestamps")  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_state_references(self) -> Self:
        question_ids = tuple(question.question_id for question in self.questions)
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question_id values must be unique")
        question_id_set = set(question_ids)
        for question in self.questions:
            if question.objective_id is not None and question.objective_id != self.objective.objective_id:
                raise ValueError("question objective_id must match state objective")
        hypothesis_ids = tuple(hypothesis.hypothesis_id for hypothesis in self.hypotheses)
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError("hypothesis_id values must be unique")
        hypothesis_id_set = set(hypothesis_ids)
        for hypothesis in self.hypotheses:
            unknown_questions = set(hypothesis.question_ids) - question_id_set
            if unknown_questions:
                raise ValueError(
                    f"hypothesis references unknown questions: {sorted(unknown_questions)!r}"
                )
        observation_ids = tuple(observation.observation_id for observation in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation_id values must be unique")
        observation_id_set = set(observation_ids)
        proposal_ids = tuple(proposal.proposal_id for proposal in self.plan_history)
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("plan_history proposal_id values must be unique")
        history_revisions = tuple(proposal.revision for proposal in self.plan_history)
        if any(
            current_revision <= previous_revision
            for previous_revision, current_revision in zip(
                history_revisions, history_revisions[1:], strict=False
            )
        ):
            raise ValueError("plan_history revisions must be strictly increasing")

        if self.plan is not None:
            self._validate_proposal_identity(self.plan)
        for proposal in self.plan_history:
            self._validate_proposal_identity(proposal)
        proposals = tuple(proposal for proposal in (self.plan, *self.plan_history) if proposal is not None)
        for proposal in proposals:
            if proposal.revision > self.revision:
                raise ValueError("plan revision cannot exceed state revision")
            if proposal.tool_snapshot_ref != self.tool_snapshot_ref:
                raise ValueError("plan tool_snapshot_ref must match state tool_snapshot_ref")
        if self.plan is not None and self.plan_history:
            latest_history = self.plan_history[-1]
            if self.plan.revision < latest_history.revision:
                raise ValueError("current plan revision cannot precede plan history")
            if (
                self.plan.revision == latest_history.revision
                and self.plan.proposal_id != latest_history.proposal_id
            ):
                raise ValueError("current plan conflicts with latest plan history revision")
        for proposal in proposals:
            unknown_observations = set(proposal.based_on_observation_ids) - observation_id_set
            if unknown_observations:
                raise ValueError(
                    f"plan references unknown observations: {sorted(unknown_observations)!r}"
                )
            for action in proposal.actions:
                unknown_questions = set(action.question_ids) - question_id_set
                if unknown_questions:
                    raise ValueError(
                        f"action references unknown questions: {sorted(unknown_questions)!r}"
                    )
                unknown_hypotheses = set(action.hypothesis_ids) - hypothesis_id_set
                if unknown_hypotheses:
                    raise ValueError(
                        f"action references unknown hypotheses: {sorted(unknown_hypotheses)!r}"
                    )
        if self.critique is not None and self.critique.investigation_id != self.investigation_id:
            raise ValueError("critique investigation_id must match state")
        if self.critique is not None:
            if self.critique.plan_revision > self.revision:
                raise ValueError("critique plan_revision cannot exceed state revision")
            if self.plan is not None and self.critique.plan_revision != self.plan.revision:
                raise ValueError("critique plan_revision must match current plan revision")
            unknown_observations = set(self.critique.observation_ids) - observation_id_set
            if unknown_observations:
                raise ValueError(
                    f"critique references unknown observations: {sorted(unknown_observations)!r}"
                )
            unknown_questions = set(self.critique.question_ids) - question_id_set
            if unknown_questions:
                raise ValueError(
                    f"critique references unknown questions: {sorted(unknown_questions)!r}"
                )
            unknown_hypotheses = set(self.critique.hypothesis_ids) - hypothesis_id_set
            if unknown_hypotheses:
                raise ValueError(
                    f"critique references unknown hypotheses: {sorted(unknown_hypotheses)!r}"
                )
        if self.termination is not None:
            if self.termination.investigation_id != self.investigation_id:
                raise ValueError("termination investigation_id must match state")
            if not self.status.is_terminal:
                raise ValueError("termination requires a terminal investigation status")
        elif self.status.is_terminal:
            raise ValueError("terminal investigation status requires termination")
        for observation in self.observations:
            if observation.investigation_id != self.investigation_id:
                raise ValueError("observation investigation_id must match state")

        refs = list(self.evidence_refs)
        for item in (*self.questions, *self.hypotheses, *self.observations):
            refs.extend(item.evidence_refs)
        if self.objective.evidence_refs:
            refs.extend(self.objective.evidence_refs)
        for proposal in proposals:
            refs.extend(proposal.evidence_refs)
            for action in proposal.actions:
                refs.extend(action.evidence_refs)
        if self.critique is not None:
            refs.extend(self.critique.evidence_refs)
        if self.termination is not None:
            refs.extend(self.termination.evidence_refs)
        merged_refs = tuple(dict.fromkeys(refs))
        if merged_refs != self.evidence_refs:
            object.__setattr__(self, "evidence_refs", merged_refs)
        return self

    def _validate_proposal_identity(self, proposal: PlanProposal) -> None:
        if proposal.investigation_id != self.investigation_id:
            raise ValueError("plan investigation_id must match state")
        if proposal.objective_id != self.objective.objective_id:
            raise ValueError("plan objective_id must match state objective")
        unknown_questions = set(proposal.target_question_ids) - {
            question.question_id for question in self.questions
        }
        if unknown_questions:
            raise ValueError(f"plan references unknown questions: {sorted(unknown_questions)!r}")
        unknown_hypotheses = set(proposal.target_hypothesis_ids) - {
            hypothesis.hypothesis_id for hypothesis in self.hypotheses
        }
        if unknown_hypotheses:
            raise ValueError(
                f"plan references unknown hypotheses: {sorted(unknown_hypotheses)!r}"
            )

    @property
    def run_id(self) -> str:
        return self.investigation_id

    @property
    def usage(self) -> BudgetUsage:
        return self.budget_usage

    @property
    def current_plan(self) -> PlanProposal | None:
        return self.plan

    @property
    def observation_history(self) -> tuple[ObservationEnvelope, ...]:
        return self.observations

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    @property
    def budget_exhausted(self) -> bool:
        return self.budget.is_exhausted(self.budget_usage)

    @property
    def goal(self) -> str:
        """Compatibility projection of the canonical objective statement."""

        return self.objective.statement

    @property
    def raw_tool_returns(self) -> tuple[JsonValue | None, ...]:
        return tuple(observation.raw_payload for observation in self.observations)

    @property
    def raw_returns(self) -> tuple[JsonValue | None, ...]:
        return self.raw_tool_returns

    @property
    def status_value(self) -> str:
        return self.status.value


# Readable aliases for callers migrating from generic planner terminology.
AdaptiveInvestigationState = InvestigationState
Budget = InvestigationBudget
BudgetLimits = InvestigationBudget
BudgetMetadata = InvestigationBudget
ToolCapability = ToolCapabilityMetadata
ToolCapabilityDescriptor = ToolCapabilityMetadata
Plan = PlanProposal
Observation = ObservationEnvelope
Critique = CritiqueDecision


__all__ = [
    "ADAPTIVE_INVESTIGATION_SCHEMA_VERSION",
    "OBJECTIVE_SCHEMA_VERSION",
    "QUESTION_SCHEMA_VERSION",
    "HYPOTHESIS_SCHEMA_VERSION",
    "INVESTIGATION_BUDGET_SCHEMA_VERSION",
    "BUDGET_USAGE_SCHEMA_VERSION",
    "TOOL_CAPABILITY_SCHEMA_VERSION",
    "TOOL_CAPABILITY_SNAPSHOT_SCHEMA_VERSION",
    "PLAN_ACTION_SCHEMA_VERSION",
    "PLAN_PROPOSAL_SCHEMA_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "CRITIQUE_SCHEMA_VERSION",
    "TERMINATION_SCHEMA_VERSION",
    "ActionBudget",
    "AdaptiveInvestigationState",
    "Budget",
    "BudgetLimits",
    "BudgetMetadata",
    "BudgetSnapshot",
    "BudgetUsage",
    "Critique",
    "CritiqueDecision",
    "CritiqueDisposition",
    "Hypothesis",
    "HypothesisStatus",
    "InvestigationBudget",
    "InvestigationState",
    "InvestigationStatus",
    "Objective",
    "Observation",
    "ObservationCompleteness",
    "ObservationEnvelope",
    "ObservationKind",
    "ObservationOutcome",
    "Plan",
    "PlanAction",
    "PlanActionKind",
    "PlanProposal",
    "PlanProposalStatus",
    "Question",
    "QuestionStatus",
    "Termination",
    "TerminationReason",
    "ToolCapability",
    "ToolCapabilityDescriptor",
    "ToolCapabilityMetadata",
    "ToolCapabilitySnapshot",
    "ToolSideEffect",
]
