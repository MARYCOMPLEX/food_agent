"""Project-owned contracts for the single research Agent runtime."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

from .account_service import PlatformChannel
from .base import ContractModel, ContractPayload, JsonValue, NonEmptyStr, VersionedContract
from .ports import ModelUsage, ToolCall, ToolResult
from .tasks import PlanBudget


class AgentDependencies(ContractModel):
    task_id: NonEmptyStr
    plan_id: NonEmptyStr
    domain: NonEmptyStr
    contract_versions: dict[str, str] = Field(default_factory=dict)
    allowed_step_ids: tuple[NonEmptyStr, ...] | None = None
    allowed_evidence_refs: tuple[NonEmptyStr, ...] | None = None

    @field_validator("allowed_step_ids", "allowed_evidence_refs")
    @classmethod
    def validate_allowed_refs(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("allowed Agent references must be unique")
        return values


class AgentToolDefinition(ContractModel):
    name: NonEmptyStr
    description: str = ""
    input_schema: ContractPayload
    output_schema: ContractPayload
    timeout_ms: int | None = Field(default=None, gt=0)
    cost_units: int = Field(default=1, ge=0)


class AgentToolExecutionContext(ContractModel):
    """Opaque request context available to tools but never declared to the model."""

    tenant_ref: NonEmptyStr
    platforms: tuple[PlatformChannel, ...] = Field(min_length=1)
    account_refs: dict[str, NonEmptyStr] = Field(default_factory=dict)
    expected_session_versions: dict[str, int] = Field(default_factory=dict)

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, values: tuple[PlatformChannel, ...]) -> tuple[PlatformChannel, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Agent tool platforms must be unique")
        return values

    @field_validator("account_refs", "expected_session_versions")
    @classmethod
    def validate_platform_keys(cls, values: dict[str, object]) -> dict[str, object]:
        for key in values:
            PlatformChannel(key)
        return values

    @model_validator(mode="after")
    def validate_platform_context(self) -> AgentToolExecutionContext:
        allowed_platforms = {platform.value for platform in self.platforms}
        context_platforms = set(self.account_refs) | set(self.expected_session_versions)
        if unknown_platforms := context_platforms - allowed_platforms:
            raise ValueError(
                "Agent tool context contains undeclared platforms: "
                + ", ".join(sorted(unknown_platforms))
            )
        if any(version < 1 for version in self.expected_session_versions.values()):
            raise ValueError("Agent tool session versions must be positive")
        return self


class AgentRunRequest(VersionedContract):
    request_id: NonEmptyStr
    prompt: str
    dependencies: AgentDependencies
    tools: tuple[AgentToolDefinition, ...] = ()
    output_schema: ContractPayload
    budget: PlanBudget = Field(default_factory=PlanBudget)
    tool_context: AgentToolExecutionContext | None = None


class AgentOutput(VersionedContract):
    summary: str = ""
    final_output: JsonValue = None
    proposed_step_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    replan_required: bool = False

    @field_validator("proposed_step_ids", "evidence_refs")
    @classmethod
    def validate_output_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("Agent output references must be non-empty")
        if len(values) != len(set(values)):
            raise ValueError("Agent output references must be unique")
        return values


class AgentRunResult(VersionedContract):
    request_id: NonEmptyStr
    output: AgentOutput
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    usage: ModelUsage = Field(default_factory=ModelUsage)
    provider_ref: str | None = None
    model_ref: str | None = None


class TemporalAgentBinding(ContractModel):
    """S5 registration metadata; B0 is the first phase allowed to enable it."""

    integration: Literal["pydantic-ai-temporal/v1"] = "pydantic-ai-temporal/v1"
    task_queue: NonEmptyStr = "research"
    enabled: Literal[False] = False


@runtime_checkable
class AgentRuntime(Protocol):
    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...


__all__ = [
    "AgentDependencies",
    "AgentOutput",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRuntime",
    "AgentToolDefinition",
    "AgentToolExecutionContext",
    "TemporalAgentBinding",
]
