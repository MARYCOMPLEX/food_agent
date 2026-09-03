"""Offline consumer contracts for the S3 source and tool gateways."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from xhs_food.contracts import (
    JSON_SCHEMA_DIALECT,
    AllowedToolContract,
    CanonicalQuery,
    CollectRequest,
    ErrorCategory,
    ErrorScope,
    JsonSchema,
    SourceQueryProjection,
    ToolCall,
    canonical_schema_digest,
)
from xhs_food.gateways import (
    AmapPlaceSourceConnector,
    LegacySourceProjection,
    PlaceLookupToolAdapter,
    ProviderResult,
    SchemaToolGateway,
    SourceOutcomeKind,
    ToolRegistration,
    classify_batch,
    project_legacy_place,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


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
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("unreachable")


class FakeAmapClient:
    def __init__(self, result: object, *, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, str]] = []

    def search_poi(self, keywords: str, city: str = "", types: str = "050000") -> dict[str, Any]:
        self.calls.append({"keywords": keywords, "city": city, "types": types})
        if self.error is not None:
            raise self.error
        return cast(dict[str, Any], self.result)


def _collect_request(
    source_id: str = "xhs",
    *,
    source_text: str | None = None,
    source_locality: str = "",
) -> CollectRequest:
    query = CanonicalQuery.model_validate(
        {
            "schema_version": "canonical-query/v1",
            "normalizer_version": "canonical-normalizer/v1",
            "classifier_version": "food-constraint-classifier/v1",
            "isolation": {
                "tenant_scope": "public",
                "language": "zh-Hans",
                "region": "CN",
            },
            "query": {
                "domain": "food",
                "geo": {
                    "country_code": "CN",
                    "admin_path": ["cn.sc"],
                    "locality": "cn.sc.zigong",
                },
                "intent": {"kind": "recommend", "subject": "restaurant"},
                "audience": ["visitor"],
                "constraints": [],
                "time_range": {
                    "kind": "current",
                    "start": None,
                    "end": None,
                    "timezone": "Asia/Shanghai",
                },
                "freshness_policy": {
                    "policy_id": "food.default",
                    "policy_version": "food-freshness/v1",
                },
            },
        }
    )
    source_queries = (
        {
            source_id: SourceQueryProjection(
                source_id=source_id,
                text=source_text,
                language=query.isolation.language,
                renderer_id=f"food.{source_id}",
                renderer_version="source-query/v1",
                locality=source_locality,
            )
        }
        if source_text is not None
        else {}
    )
    return CollectRequest(
        query=query,
        source_scope=(source_id,),
        source_queries=source_queries,
        depth="standard",
    )


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
        (
            ProviderResult(
                success=True,
                data=cast(Any, {"result": b"not-json"}),
            ),
            "TOOL_OUTPUT_INVALID",
        ),
        (
            ProviderResult(
                success=True,
                data={"result": "ok"},
                metadata=cast(Any, {"captured_at": NOW}),
            ),
            "TOOL_METADATA_INVALID",
        ),
        (
            ProviderResult(
                success=False,
                error_code="DEPENDENCY_UNAVAILABLE",
                metadata=cast(Any, {"captured_at": NOW}),
            ),
            "TOOL_METADATA_INVALID",
        ),
    ],
)
async def test_tool_gateway_maps_non_json_values_to_stable_failures(
    provider_result: ProviderResult,
    expected_code: str,
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
    provider = FakeProvider(
        "echo", ProviderResult(success=True, data={"result": "hello"}), health=True
    )
    gateway = SchemaToolGateway(
        (ToolRegistration(_tool_contract(), provider, max_calls_per_task=1),)
    )

    first = await gateway.execute(_tool_call(call_id="call-1", task_id="same-task"))
    exhausted = await gateway.execute(_tool_call(call_id="call-2", task_id="same-task"))
    other_task = await gateway.execute(_tool_call(call_id="call-3", task_id="other-task"))

    assert first.success is True
    assert first.output == {"result": "hello"}
    assert exhausted.success is False
    assert exhausted.error is not None
    assert exhausted.error.code == "TOOL_BUDGET_EXHAUSTED"
    assert exhausted.error.category is ErrorCategory.BUDGET_EXHAUSTED
    assert other_task.success is True
    assert len(provider.calls) == 2
    assert await gateway.health("echo") is True

    unhealthy = FakeProvider(
        "echo",
        ProviderResult(success=True, data={"result": "hello"}),
        health=RuntimeError("health failed"),
    )
    unhealthy_gateway = SchemaToolGateway((ToolRegistration(_tool_contract(), unhealthy),))
    assert await unhealthy_gateway.health("echo") is False


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
        (
            ToolRegistration(
                _tool_contract(),
                FakeProvider("echo", ProviderResult(False, error_code="HTTP_429")),
            ),
        )
    ).execute(_tool_call())
    exploded = await SchemaToolGateway(
        (
            ToolRegistration(
                _tool_contract(),
                FakeProvider("echo", None, error=RuntimeError("fixture failure")),
            ),
        )
    ).execute(_tool_call(call_id="call-2"))

    assert rate_limited.error is not None
    assert rate_limited.error.category is ErrorCategory.RATE_LIMITED
    assert rate_limited.error.scope is ErrorScope.PROVIDER
    assert exploded.error is not None
    assert exploded.error.code == "PROVIDER_INTERNAL"
    assert exploded.error.scope is ErrorScope.PROVIDER


async def test_amap_success_and_empty_preserve_optional_source_semantics() -> None:
    success_client = FakeAmapClient(
        {
            "count": 1,
            "pois": [
                {
                    "poi_id": "poi-1",
                    "name": "Local restaurant",
                    "address": "Ziliujing district",
                }
            ],
        }
    )
    success_batch = await AmapPlaceSourceConnector(success_client, clock=lambda: NOW).search(
        _collect_request("amap")
    )

    assert classify_batch(success_batch).kind is SourceOutcomeKind.SUCCESS
    assert [item.external_id for item in success_batch.documents] == ["poi-1"]
    assert project_legacy_place(classify_batch(success_batch)) is LegacySourceProjection.CONTINUE
    assert success_client.calls == [
        {
            "keywords": "cn.sc.zigong restaurant",
            "city": "cn.sc.zigong",
            "types": "050000",
        }
    ]

    empty_batch = await AmapPlaceSourceConnector(
        FakeAmapClient({"count": 0, "pois": []}), clock=lambda: NOW
    ).search(_collect_request("amap"))
    empty_outcome = classify_batch(empty_batch)

    assert empty_outcome.kind is SourceOutcomeKind.EMPTY
    assert empty_batch.documents == ()
    assert empty_batch.errors == ()
    assert project_legacy_place(empty_outcome) is LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT


async def test_place_tool_preserves_empty_and_classifies_malformed_and_429() -> None:
    empty = await PlaceLookupToolAdapter(FakeAmapClient({"count": 0, "pois": []})).execute(
        keywords="restaurant", city="zigong"
    )
    malformed = await PlaceLookupToolAdapter(FakeAmapClient(["bad-envelope"])).execute(
        keywords="restaurant", city="zigong"
    )
    rate_limited = await PlaceLookupToolAdapter(
        FakeAmapClient({"error": "429 Client Error: Too Many Requests"})
    ).execute(keywords="restaurant", city="zigong")

    assert empty.success is True
    assert empty.data == {"count": 0, "pois": []}
    assert malformed.success is False
    assert malformed.error_code == "MALFORMED_RESPONSE"
    assert rate_limited.success is False
    assert rate_limited.error_code == "HTTP_429"


@pytest.mark.parametrize(
    ("raw", "expected_category", "expected_code", "retryable"),
    [
        (
            {"error": "429 Client Error: Too Many Requests"},
            ErrorCategory.RATE_LIMITED,
            "AMAP_RATE_LIMITED",
            True,
        ),
        (
            {"error": "upstream unavailable"},
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            "AMAP_DEPENDENCY_UNAVAILABLE",
            True,
        ),
        (
            {"count": 1, "pois": "not-a-list"},
            ErrorCategory.MALFORMED_RESPONSE,
            "AMAP_POIS_MALFORMED",
            False,
        ),
        (
            {"count": 1, "pois": [{"name": "missing id"}]},
            ErrorCategory.MALFORMED_RESPONSE,
            "AMAP_ITEM_MALFORMED",
            False,
        ),
    ],
)
async def test_amap_failure_taxonomy_projects_to_optional_basic_fallback(
    raw: object,
    expected_category: ErrorCategory,
    expected_code: str,
    retryable: bool,
) -> None:
    batch = await AmapPlaceSourceConnector(FakeAmapClient(raw), clock=lambda: NOW).search(
        _collect_request("amap")
    )
    outcome = classify_batch(batch)

    assert outcome.kind is SourceOutcomeKind.FAILURE
    assert len(outcome.errors) == 1
    assert outcome.errors[0].code == expected_code
    assert outcome.errors[0].category is expected_category
    assert outcome.errors[0].scope is ErrorScope.SOURCE
    assert outcome.errors[0].retryable is retryable
    assert project_legacy_place(outcome) is LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT


@pytest.mark.parametrize(
    ("error", "category", "scope", "retryable"),
    [
        (TimeoutError("timed out"), ErrorCategory.TIMEOUT, ErrorScope.SOURCE, True),
        (
            RuntimeError("adapter exploded"),
            ErrorCategory.INTERNAL,
            ErrorScope.PROVIDER,
            False,
        ),
    ],
)
async def test_amap_exceptions_remain_optional_source_failures(
    error: BaseException,
    category: ErrorCategory,
    scope: ErrorScope,
    retryable: bool,
) -> None:
    batch = await AmapPlaceSourceConnector(
        FakeAmapClient(result=None, error=error), clock=lambda: NOW
    ).search(_collect_request("amap"))
    outcome = classify_batch(batch)

    assert outcome.kind is SourceOutcomeKind.FAILURE
    assert outcome.errors[0].category is category
    assert outcome.errors[0].scope is scope
    assert outcome.errors[0].retryable is retryable
    assert project_legacy_place(outcome) is LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT
