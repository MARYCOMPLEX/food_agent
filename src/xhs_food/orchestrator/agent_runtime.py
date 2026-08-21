"""Pydantic AI V2 adapter for the single shared research Agent runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from xhs_food.contracts import (
    AgentDependencies,
    AgentOutput,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
    AgentToolDefinition,
    ContractError,
    ContractPayload,
    ErrorCategory,
    ErrorScope,
    ModelUsage,
    TemporalAgentBinding,
    ToolCall,
    ToolGateway,
    ToolResult,
)


class GatewayToolRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    arguments: ContractPayload = Field(default_factory=dict)


class GatewayToolResponse(BaseModel):
    success: bool
    output: Any = None
    error: ContractPayload | None = None


@dataclass(slots=True)
class _RunState:
    request: AgentRunRequest
    tools: dict[str, AgentToolDefinition]
    calls: list[ToolCall] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    cost_units: int = 0


_ACTIVE_RUN: ContextVar[_RunState | None] = ContextVar("research_agent_run", default=None)


class AgentRuntimeFailure(RuntimeError):
    def __init__(self, error: ContractError) -> None:
        super().__init__(error.message or error.code)
        self.error = error


class AgentRuntimeDisabledError(AgentRuntimeFailure):
    pass


class AgentBudgetExceededError(AgentRuntimeFailure):
    pass


class AgentOutputValidationError(AgentRuntimeFailure):
    pass


class AgentToolPolicyError(AgentRuntimeFailure):
    pass


class AgentToolValidationError(AgentRuntimeFailure):
    pass


class AgentProviderError(AgentRuntimeFailure):
    pass


class PydanticAIAgentRuntime:
    """One typed Agent whose only tool crosses the project Tool Gateway.

    The adapter is registered in S5 but disabled by default. Temporal metadata
    is descriptive only; B0 enables the official durable execution binding.
    """

    def __init__(
        self,
        *,
        tool_gateway: ToolGateway,
        model: Any = None,
        agent: Any = None,
        enabled: bool = False,
        temporal_binding: TemporalAgentBinding | None = None,
    ) -> None:
        self._tool_gateway = tool_gateway
        self._enabled = enabled
        self._temporal_binding = temporal_binding or TemporalAgentBinding()
        self._agent = agent or Agent(
            model=model,
            output_type=AgentOutput,
            deps_type=AgentDependencies,
            name="shared-research-agent",
            tools=(
                Tool(
                    self._execute_gateway_tool,
                    takes_ctx=True,
                    name="gateway_execute",
                    description="Execute one declared capability through the typed Tool Gateway.",
                ),
            ),
            defer_model_check=model is None,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def temporal_binding(self) -> TemporalAgentBinding:
        return self._temporal_binding

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        if not self._enabled:
            raise AgentRuntimeDisabledError(
                _error(
                    code="AGENT_RUNTIME_DISABLED",
                    category=ErrorCategory.POLICY_DENIED,
                    scope=ErrorScope.PLAN,
                    message="the S5 Agent runtime binding is disabled",
                )
            )
        if (
            request.budget.deadline_at is not None
            and datetime.now(UTC) >= request.budget.deadline_at
        ):
            raise _budget_failure("agent deadline has already elapsed")
        if request.budget.max_steps == 0:
            raise _budget_failure("agent request budget permits no model steps")

        try:
            tools = _index_tools(request.tools)
            _validate_request_schemas(request, tools)
        except AgentRuntimeFailure:
            raise
        except ValueError as exc:
            raise AgentToolValidationError(
                _error(
                    code="TOOL_SCHEMA_INVALID",
                    category=ErrorCategory.VALIDATION,
                    scope=ErrorScope.TOOL,
                    message=str(exc),
                )
            ) from exc
        state = _RunState(request=request, tools=tools)
        token = _ACTIVE_RUN.set(state)
        try:
            timeout = _deadline_seconds(request.budget.deadline_at)
            run = self._agent.run(
                request.prompt,
                deps=request.dependencies,
                usage_limits=UsageLimits(
                    request_limit=request.budget.max_steps,
                    tool_calls_limit=request.budget.max_tool_calls,
                ),
            )
            try:
                result = await asyncio.wait_for(run, timeout=timeout)
            except TimeoutError as exc:
                raise _budget_failure("agent deadline elapsed during execution") from exc
            try:
                output = (
                    result.output
                    if isinstance(result.output, AgentOutput)
                    else AgentOutput.model_validate(result.output)
                )
                _validate_value(request.output_schema, output.final_output, "agent final output")
            except AgentRuntimeFailure:
                raise
            except (ValueError, TypeError) as exc:
                raise AgentOutputValidationError(
                    _error(
                        code="AGENT_OUTPUT_INVALID",
                        category=ErrorCategory.MALFORMED_RESPONSE,
                        scope=ErrorScope.PLAN,
                        message=str(exc),
                    )
                ) from exc
            _validate_agent_output_scope(output, request.dependencies)
            raw_usage = result.usage
            usage = raw_usage() if callable(raw_usage) else raw_usage
            return AgentRunResult(
                request_id=request.request_id,
                output=output,
                tool_calls=tuple(state.calls),
                tool_results=tuple(state.results),
                usage=ModelUsage(
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                ),
                provider_ref=_optional_text(getattr(usage, "provider", None)),
                model_ref=_optional_text(getattr(usage, "model", None)),
            )
        except AgentRuntimeFailure:
            raise
        except UsageLimitExceeded as exc:
            raise _budget_failure(str(exc)) from exc
        except UnexpectedModelBehavior as exc:
            raise AgentOutputValidationError(
                _error(
                    code="AGENT_OUTPUT_INVALID",
                    category=ErrorCategory.MALFORMED_RESPONSE,
                    scope=ErrorScope.PLAN,
                    message=str(exc),
                )
            ) from exc
        except (ValueError, TypeError) as exc:
            raise AgentProviderError(
                _error(
                    code="AGENT_PROVIDER_FAILURE",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    scope=ErrorScope.PROVIDER,
                    message=str(exc),
                    retryable=True,
                )
            ) from exc
        except Exception as exc:
            raise AgentProviderError(
                _error(
                    code="AGENT_PROVIDER_FAILURE",
                    category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    scope=ErrorScope.PROVIDER,
                    message=str(exc),
                    retryable=True,
                )
            ) from exc
        finally:
            _ACTIVE_RUN.reset(token)

    async def _execute_gateway_tool(
        self,
        ctx: RunContext[AgentDependencies],
        request: GatewayToolRequest,
    ) -> GatewayToolResponse:
        state = _ACTIVE_RUN.get()
        if state is None or ctx.deps.task_id != state.request.dependencies.task_id:
            raise RuntimeError("gateway tool called outside its owning Agent run")
        try:
            definition = state.tools[request.tool_name]
        except KeyError as exc:
            raise AgentToolPolicyError(
                _error(
                    code="TOOL_POLICY_DENIED",
                    category=ErrorCategory.POLICY_DENIED,
                    scope=ErrorScope.TOOL,
                    message=f"undeclared Agent tool: {request.tool_name}",
                )
            ) from exc

        next_count = len(state.calls) + 1
        if (
            state.request.budget.max_tool_calls is not None
            and next_count > state.request.budget.max_tool_calls
        ):
            raise _budget_failure("Agent tool-call budget exhausted")
        next_cost = state.cost_units + definition.cost_units
        if (
            state.request.budget.max_cost_units is not None
            and next_cost > state.request.budget.max_cost_units
        ):
            raise _budget_failure("Agent cost-unit budget exhausted")

        try:
            _validate_value(definition.input_schema, request.arguments, "Agent tool input")
        except ValueError as exc:
            raise AgentToolValidationError(
                _error(
                    code="TOOL_INPUT_INVALID",
                    category=ErrorCategory.VALIDATION,
                    scope=ErrorScope.TOOL,
                    message=str(exc),
                )
            ) from exc
        call = ToolCall(
            call_id=f"{state.request.request_id}:tool:{next_count}",
            tool_name=definition.name,
            arguments=request.arguments,
            task_id=state.request.dependencies.task_id,
            timeout_ms=definition.timeout_ms,
        )
        state.calls.append(call)
        state.cost_units = next_cost
        result = await self._tool_gateway.execute(call)
        state.results.append(result)
        if not result.success:
            return GatewayToolResponse(
                success=False,
                error=result.error.model_dump(mode="json") if result.error else None,
            )
        try:
            _validate_value(definition.output_schema, result.output, "Agent tool output")
        except ValueError as exc:
            raise AgentToolValidationError(
                _error(
                    code="TOOL_OUTPUT_INVALID",
                    category=ErrorCategory.MALFORMED_RESPONSE,
                    scope=ErrorScope.TOOL,
                    message=str(exc),
                )
            ) from exc
        return GatewayToolResponse(success=True, output=result.output)


class ScriptedAgentRuntime:
    """Deterministic provider/model fake for offline contract tests."""

    def __init__(self, responses: Iterable[AgentRunResult | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("scripted Agent runtime has no response")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response.request_id != request.request_id:
            raise ValueError("scripted Agent response request_id mismatch")
        _validate_value(request.output_schema, response.output.final_output, "agent final output")
        _validate_agent_output_scope(response.output, request.dependencies)
        return response


def _index_tools(tools: tuple[AgentToolDefinition, ...]) -> dict[str, AgentToolDefinition]:
    indexed = {tool.name: tool for tool in tools}
    if len(indexed) != len(tools):
        raise AgentToolPolicyError(
            _error(
                code="TOOL_POLICY_DENIED",
                category=ErrorCategory.POLICY_DENIED,
                scope=ErrorScope.TOOL,
                message="Agent tool names must be unique",
            )
        )
    return indexed


def _validate_request_schemas(
    request: AgentRunRequest,
    tools: dict[str, AgentToolDefinition],
) -> None:
    try:
        Draft202012Validator.check_schema(request.output_schema)
    except Exception as exc:
        raise AgentOutputValidationError(
            _error(
                code="AGENT_OUTPUT_SCHEMA_INVALID",
                category=ErrorCategory.VALIDATION,
                scope=ErrorScope.PLAN,
                message=str(exc),
            )
        ) from exc
    for definition in tools.values():
        try:
            Draft202012Validator.check_schema(definition.input_schema)
            Draft202012Validator.check_schema(definition.output_schema)
        except Exception as exc:
            raise AgentToolValidationError(
                _error(
                    code="TOOL_SCHEMA_INVALID",
                    category=ErrorCategory.VALIDATION,
                    scope=ErrorScope.TOOL,
                    message=str(exc),
                )
            ) from exc


def _deadline_seconds(deadline_at: datetime | None) -> float | None:
    if deadline_at is None:
        return None
    remaining = (deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise _budget_failure("agent deadline has already elapsed")
    return remaining


def _validate_value(schema: ContractPayload, value: Any, boundary: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except Exception as exc:
        raise ValueError(f"{boundary} failed schema validation: {exc}") from exc


def _validate_agent_output_scope(output: AgentOutput, dependencies: AgentDependencies) -> None:
    if dependencies.allowed_step_ids is not None:
        unknown_steps = sorted(set(output.proposed_step_ids) - set(dependencies.allowed_step_ids))
        if unknown_steps:
            raise AgentOutputValidationError(
                _error(
                    code="AGENT_PLAN_OUTPUT_INVALID",
                    category=ErrorCategory.VALIDATION,
                    scope=ErrorScope.PLAN,
                    message=f"Agent proposed step IDs outside the allowed plan scope: {unknown_steps}",
                )
            )
    if dependencies.allowed_evidence_refs is not None:
        unknown_refs = sorted(set(output.evidence_refs) - set(dependencies.allowed_evidence_refs))
        if unknown_refs:
            raise AgentOutputValidationError(
                _error(
                    code="AGENT_EVIDENCE_OUTPUT_INVALID",
                    category=ErrorCategory.VALIDATION,
                    scope=ErrorScope.PLAN,
                    message=f"Agent proposed evidence refs outside the allowed plan scope: {unknown_refs}",
                )
            )


def _budget_failure(message: str) -> AgentBudgetExceededError:
    return AgentBudgetExceededError(
        _error(
            code="AGENT_BUDGET_EXHAUSTED",
            category=ErrorCategory.BUDGET_EXHAUSTED,
            scope=ErrorScope.PLAN,
            message=message,
        )
    )


def _error(
    *,
    code: str,
    category: ErrorCategory,
    scope: ErrorScope,
    message: str,
    retryable: bool = False,
) -> ContractError:
    return ContractError(
        code=code,
        category=category,
        scope=scope,
        retryable=retryable,
        message=message,
    )


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None


assert isinstance(ScriptedAgentRuntime(()), AgentRuntime)


__all__ = [
    "AgentBudgetExceededError",
    "AgentOutputValidationError",
    "AgentProviderError",
    "AgentToolPolicyError",
    "AgentToolValidationError",
    "AgentRuntimeDisabledError",
    "AgentRuntimeFailure",
    "GatewayToolRequest",
    "GatewayToolResponse",
    "PydanticAIAgentRuntime",
    "ScriptedAgentRuntime",
]
