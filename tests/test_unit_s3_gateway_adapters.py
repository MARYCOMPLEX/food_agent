"""Offline contracts for the managed tool gateway.

Source-specific extraction is tested in ``test_unit_comment_first_research``;
this suite keeps the generic policy, schema, budget, timeout, and provider
failure guarantees independent of any retired place adapter.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_food.contracts import (
    JSON_SCHEMA_DIALECT,
    AllowedToolContract,
    ErrorCategory,
    ErrorScope,
    JsonSchema,
    ToolCall,
    canonical_schema_digest,
)
from xhs_food.gateways import ProviderResult, SchemaToolGateway, ToolRegistration

pytestmark = pytest.mark.unit


class FakeProvider:
    def __init__(
        self,
        name: str,
        result: object,
        *,
        error: BaseException | None = None,
        health: bool | BaseException = True,
    ) -> None:
        self.name = name
        self.result = result
        self.error = error
        self.health_result = health
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def health_check(self) -> bool:
        if isinstance(self.health_result, BaseException):
            raise self.health_result
        return self.health_result


class HangingProvider(FakeProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name, result=None)
        self.cancelled = asyncio.Event()

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("unreachable")


def _tool_contract(tool_id: str = "echo") -> AllowedToolContract:
    input_schema: JsonSchema = {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"urn:food-agent:tool:{tool_id}:input:v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1}},
    }
    output_schema: JsonSchema = {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"urn:food-agent:tool:{tool_id}:output:v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["result"],
        "properties": {"result": {"type": "string", "minLength": 1}},
    }
    return AllowedToolContract(
        tool_id=tool_id,
        tool_version="1.0.0",
        permission="test.execute",
        timeout_ms=100,
        error_codes=("provider_error",),
        input_schema_digest=canonical_schema_digest(input_schema),
        output_schema_digest=canonical_schema_digest(output_schema),
        input_schema=input_schema,
        input_example={"query": "hello"},
        output_schema=output_schema,
        output_example={"result": "hello"},
    )


def _tool_call(
    *,
    call_id: str = "call-1",
    tool_name: str = "echo",
    task_id: str = "task-1",
    arguments: dict[str, Any] | None = None,
    timeout_ms: int | None = None,
) -> ToolCall:
    return ToolCall(
        call_id=call_id,
        tool_name=tool_name,
        task_id=task_id,
        arguments=arguments if arguments is not None else {"query": "hello"},
        timeout_ms=timeout_ms,
    )


async def test_tool_gateway_enforces_registration_allow_list_before_provider() -> None:
    provider = FakeProvider("echo", ProviderResult(success=True, data={"result": "hello"}))
    gateway = SchemaToolGateway(
        (ToolRegistration(_tool_contract(), provider),), allowed_tools=frozenset()
    )

    denied = await gateway.execute(_tool_call())
    missing = await gateway.execute(_tool_call(tool_name="missing"))

    assert denied.success is False
    assert denied.error is not None
    assert denied.error.code == "TOOL_POLICY_DENIED"
    assert denied.error.category is ErrorCategory.POLICY_DENIED
    assert missing.success is False
    assert missing.error is not None
    assert missing.error.code == "TOOL_NOT_FOUND"
    assert missing.error.category is ErrorCategory.NOT_FOUND
    assert provider.calls == []
    assert await gateway.health("echo") is False
    assert await gateway.health("missing") is False


async def test_tool_gateway_validates_input_and_output_schema() -> None:
    provider = FakeProvider("echo", ProviderResult(success=True, data={"unexpected": "value"}))
    gateway = SchemaToolGateway((ToolRegistration(_tool_contract(), provider),))

    invalid_input = await gateway.execute(_tool_call(arguments={"unknown": "value"}))
    assert invalid_input.success is False
    assert invalid_input.error is not None
    assert invalid_input.error.code == "TOOL_INPUT_INVALID"
    assert invalid_input.error.category is ErrorCategory.VALIDATION
    assert provider.calls == []

    invalid_output = await gateway.execute(_tool_call(call_id="call-2"))
    assert invalid_output.success is False
    assert invalid_output.error is not None
    assert invalid_output.error.code == "TOOL_OUTPUT_INVALID"
    assert invalid_output.error.category is ErrorCategory.MALFORMED_RESPONSE
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("provider_result", "expected_code"),
    [
        (ProviderResult(success=True, data={"result": b"not-json"}), "TOOL_OUTPUT_INVALID"),
        (
            ProviderResult(success=True, data={"result": "ok"}, metadata={"captured_at": object()}),
            "TOOL_METADATA_INVALID",
        ),
        (
            ProviderResult(success=False, error_code="DEPENDENCY_UNAVAILABLE", metadata={"captured_at": object()}),
            "TOOL_METADATA_INVALID",
        ),
    ],
)
async def test_tool_gateway_maps_non_json_values_to_stable_failures(
    provider_result: ProviderResult, expected_code: str
) -> None:
    provider = FakeProvider("echo", provider_result)
    result = await SchemaToolGateway((ToolRegistration(_tool_contract(), provider),)).execute(
        _tool_call()
    )
    assert result.success is False
    assert result.error is not None
    assert result.error.code == expected_code
    assert result.error.scope is ErrorScope.TOOL


async def test_tool_gateway_budget_is_task_scoped_and_health_isolated() -> None:
    provider = FakeProvider("echo", ProviderResult(success=True, data={"result": "hello"}))
    gateway = SchemaToolGateway(
        (ToolRegistration(_tool_contract(), provider, max_calls_per_task=1),)
    )
    first = await gateway.execute(_tool_call(call_id="call-1", task_id="same-task"))
    exhausted = await gateway.execute(_tool_call(call_id="call-2", task_id="same-task"))
    other_task = await gateway.execute(_tool_call(call_id="call-3", task_id="other-task"))
    assert first.success is True
    assert exhausted.error is not None and exhausted.error.code == "TOOL_BUDGET_EXHAUSTED"
    assert other_task.success is True
    assert len(provider.calls) == 2
    assert await gateway.health("echo") is True


async def test_tool_gateway_timeout_is_classified_and_cancels_provider() -> None:
    provider = HangingProvider("echo")
    gateway = SchemaToolGateway((ToolRegistration(_tool_contract(), provider),))
    result = await gateway.execute(_tool_call(timeout_ms=10))
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_TIMEOUT"
    assert result.error.category is ErrorCategory.TIMEOUT
    assert result.error.scope is ErrorScope.TOOL
    assert result.error.retryable is True
    assert provider.cancelled.is_set()


async def test_tool_gateway_keeps_provider_failures_out_of_source_scope() -> None:
    rate_limited = await SchemaToolGateway(
        (ToolRegistration(_tool_contract(), FakeProvider("echo", ProviderResult(False, error_code="HTTP_429"))),)
    ).execute(_tool_call())
    exploded = await SchemaToolGateway(
        (ToolRegistration(_tool_contract(), FakeProvider("echo", None, error=RuntimeError("fixture failure"))),)
    ).execute(_tool_call(call_id="call-2"))
    assert rate_limited.error is not None
    assert rate_limited.error.category is ErrorCategory.RATE_LIMITED
    assert rate_limited.error.scope is ErrorScope.PROVIDER
    assert exploded.error is not None
    assert exploded.error.code == "PROVIDER_INTERNAL"
    assert exploded.error.scope is ErrorScope.PROVIDER
