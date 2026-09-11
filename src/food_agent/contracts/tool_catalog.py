"""Framework-neutral contracts for managed Agent tool discovery and execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from pydantic import Field, JsonValue, TypeAdapter, field_validator, model_validator

from .account_service import PlatformChannel
from .agent import AgentToolDefinition, AgentToolExecutionContext
from .base import ContractModel, NonEmptyStr, Timestamp
from .ports import ToolCall, ToolResult

HIDDEN_AGENT_TOOL_ARGUMENTS = frozenset(
    {"tenant_ref", "account_ref", "expected_session_version", "correlation_id"}
)
_JSON_VALUE = TypeAdapter(JsonValue)


class AgentToolPolicy(ContractModel):
    enabled: bool = False
    allowed_platforms: tuple[PlatformChannel, ...] = ()
    allowed_capabilities: tuple[NonEmptyStr, ...] = ()
    allowed_public_names: tuple[NonEmptyStr, ...] = ()
    max_retained_snapshots: int = Field(default=8, ge=1, le=128)

    @field_validator("allowed_platforms", "allowed_capabilities", "allowed_public_names")
    @classmethod
    def validate_unique(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Agent tool policy entries must be unique")
        return values

    @model_validator(mode="after")
    def validate_enabled_policy(self) -> AgentToolPolicy:
        if self.enabled and not self.allowed_platforms:
            raise ValueError("enabled Agent tool policy requires allowed platforms")
        if self.enabled and not (self.allowed_capabilities or self.allowed_public_names):
            raise ValueError("enabled Agent tool policy requires an explicit allow-list")
        return self

    def allows(self, *, platform: PlatformChannel, capability: str, public_name: str) -> bool:
        if not self.enabled or platform not in self.allowed_platforms:
            return False
        capability_allowed = any(
            capability == item or capability.startswith(item + ".")
            for item in self.allowed_capabilities
        )
        return capability_allowed or public_name in self.allowed_public_names


class AgentToolProjection(ContractModel):
    public_name: NonEmptyStr
    service_id: NonEmptyStr
    platform: PlatformChannel
    capability: NonEmptyStr
    capability_version: NonEmptyStr
    side_effect: Literal["read_only"] = "read_only"
    policy_state: Literal["allowed"] = "allowed"


class AgentToolRejection(ContractModel):
    service_id: NonEmptyStr
    platform: PlatformChannel
    remote_name: NonEmptyStr
    capability: NonEmptyStr
    code: Literal["policy-denied", "side-effect-denied", "schema-invalid", "name-collision"]


class AgentToolCatalogSnapshot(ContractModel):
    snapshot_ref: NonEmptyStr
    generation: int = Field(ge=1)
    created_at: Timestamp
    tools: tuple[AgentToolDefinition, ...] = ()
    projection: tuple[AgentToolProjection, ...] = ()
    rejections: tuple[AgentToolRejection, ...] = ()


@runtime_checkable
class AgentToolCatalogPort(Protocol):
    async def snapshot(self, context: AgentToolExecutionContext) -> AgentToolCatalogSnapshot: ...

    async def release(self, snapshot_ref: str) -> None: ...

    async def current_projection(self) -> AgentToolCatalogSnapshot: ...


@runtime_checkable
class ContextualToolExecutorPort(Protocol):
    async def execute(
        self,
        *,
        snapshot_ref: str,
        call: ToolCall,
        context: AgentToolExecutionContext,
    ) -> ToolResult: ...

    async def health(self, *, snapshot_ref: str, tool_name: str) -> bool: ...


def normalize_agent_tool_input_schema(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], frozenset[str]]:
    remote = _schema_copy(value)
    if not remote:
        remote = {"type": "object", "properties": {}}
    if remote.get("type", "object") != "object":
        raise ValueError("tool input schema must describe an object")
    Draft202012Validator.check_schema(remote)
    public = _schema_copy(remote)
    properties = public.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise ValueError("tool input properties must be an object")
    hidden = frozenset(HIDDEN_AGENT_TOOL_ARGUMENTS.intersection(properties))
    public["properties"] = {key: item for key, item in properties.items() if key not in hidden}
    required = public.get("required")
    if isinstance(required, list):
        public["required"] = [item for item in required if item not in hidden]
    Draft202012Validator.check_schema(public)
    return public, remote, hidden


def normalize_agent_tool_output_schema(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    schema = _schema_copy(value or {})
    Draft202012Validator.check_schema(schema)
    return schema


def validate_agent_tool_schema_value(schema: Mapping[str, Any], value: object) -> JsonValue:
    json_value = _JSON_VALUE.validate_python(value)
    Draft202012Validator(dict(schema)).validate(json_value)
    return json_value


def _schema_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value)))


__all__ = [
    "AgentToolCatalogPort",
    "AgentToolCatalogSnapshot",
    "AgentToolPolicy",
    "AgentToolProjection",
    "AgentToolRejection",
    "ContextualToolExecutorPort",
    "HIDDEN_AGENT_TOOL_ARGUMENTS",
    "normalize_agent_tool_input_schema",
    "normalize_agent_tool_output_schema",
    "validate_agent_tool_schema_value",
]
