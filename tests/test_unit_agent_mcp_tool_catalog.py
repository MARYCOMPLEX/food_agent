from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from api.deps import get_current_user_id
from api.platform import router as platform_router
from xhs_food.composition import build_composition_root
from xhs_food.composition.agent_tools import (
    AccountServiceAgentToolCatalog,
    build_agent_tool_policy,
)
from xhs_food.contracts import (
    AgentDependencies,
    AgentRunRequest,
    AgentToolCatalogSnapshot,
    AgentToolDefinition,
    AgentToolExecutionContext,
    AgentToolPolicy,
    McpToolCallResult,
    McpToolDescriptor,
    PlatformChannel,
    RemoteSideEffect,
    ToolCall,
    ToolResult,
)
from xhs_food.foundation import TargetSettings
from xhs_food.orchestrator.agent_runtime import PydanticAIAgentRuntime

pytestmark = pytest.mark.unit


def _search_descriptor(
    *,
    version: str = "1.0.0",
    output_schema: dict[str, Any] | None = None,
) -> McpToolDescriptor:
    return McpToolDescriptor(
        name="notes.search",
        description="Search public food notes.",
        capability="notes.search",
        capability_version=version,
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "tenant_ref": {"type": "string"},
                "account_ref": {"type": "string"},
            },
            "required": ["keyword", "tenant_ref", "account_ref"],
            "additionalProperties": False,
        },
        output_schema=output_schema
        or {
            "type": "object",
            "properties": {"notes": {"type": "array"}},
            "required": ["notes"],
            "additionalProperties": False,
        },
    )


class _Registry:
    def __init__(self) -> None:
        self.configs = (
            SimpleNamespace(service_id="xhs-account", timeout_seconds=2.0),
            SimpleNamespace(service_id="dianping-account", timeout_seconds=3.0),
        )
        self.descriptors: dict[PlatformChannel, tuple[McpToolDescriptor, ...]] = {
            PlatformChannel.XHS_PC: (
                _search_descriptor(),
                McpToolDescriptor(
                    name="account.login",
                    capability="account.login",
                    side_effect=RemoteSideEffect.ACCOUNT_LOGIN,
                ),
                McpToolDescriptor(
                    name="broken.schema",
                    capability="broken.schema",
                    input_schema={"type": "not-a-json-type"},
                ),
            ),
            PlatformChannel.DIANPING: (_search_descriptor(),),
        }
        self.outputs: dict[PlatformChannel, object] = {
            PlatformChannel.XHS_PC: {"notes": []},
            PlatformChannel.DIANPING: {"notes": []},
        }
        self.calls: list[tuple[PlatformChannel, McpToolDescriptor, dict[str, Any]]] = []

    def service_id_for(self, platform: PlatformChannel) -> str:
        return {
            PlatformChannel.XHS_PC: "xhs-account",
            PlatformChannel.DIANPING: "dianping-account",
        }[platform]

    def tools_for(self, platform: PlatformChannel) -> tuple[McpToolDescriptor, ...]:
        return self.descriptors[platform]

    async def call_pinned_tool(
        self,
        *,
        platform: PlatformChannel,
        descriptor: McpToolDescriptor,
        arguments: dict[str, Any],
    ) -> McpToolCallResult:
        self.calls.append((platform, descriptor, dict(arguments)))
        return McpToolCallResult(
            tool_name=descriptor.name,
            content=[{"type": "json", "json": self.outputs[platform]}],
        )


def _policy(**changes: Any) -> AgentToolPolicy:
    values: dict[str, Any] = {
        "enabled": True,
        "allowed_platforms": (PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        "allowed_capabilities": ("notes.search", "broken.schema", "account.login"),
    }
    values.update(changes)
    return AgentToolPolicy(**values)


def _context(*, include_xhs_account: bool = True) -> AgentToolExecutionContext:
    accounts = {PlatformChannel.DIANPING.value: "dp-primary"}
    if include_xhs_account:
        accounts[PlatformChannel.XHS_PC.value] = "xhs-primary"
    return AgentToolExecutionContext(
        tenant_ref="tenant-a",
        platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        account_refs=accounts,
    )


def test_policy_is_fail_closed_and_configuration_is_validated() -> None:
    assert build_agent_tool_policy(object()).enabled is False
    with pytest.raises(ValidationError, match="explicit allow-list"):
        AgentToolPolicy(enabled=True, allowed_platforms=(PlatformChannel.XHS_PC,))
    parsed = build_agent_tool_policy(
        SimpleNamespace(
            agent_mcp_tool_policy_json=(
                '{"enabled":true,"allowed_platforms":["xhs_pc"],'
                '"allowed_capabilities":["notes.search"]}'
            )
        )
    )
    assert parsed.allows(
        platform=PlatformChannel.XHS_PC,
        capability="notes.search",
        public_name="xhs_pc__notes_search",
    )

    with pytest.raises(ValidationError, match="undeclared platforms"):
        AgentToolExecutionContext(
            tenant_ref="tenant-a",
            platforms=(PlatformChannel.XHS_PC,),
            account_refs={PlatformChannel.DIANPING.value: "dp-primary"},
        )
    with pytest.raises(ValidationError, match="session versions must be positive"):
        AgentToolExecutionContext(
            tenant_ref="tenant-a",
            platforms=(PlatformChannel.XHS_PC,),
            expected_session_versions={PlatformChannel.XHS_PC.value: 0},
        )


@pytest.mark.asyncio
async def test_catalog_namespaces_filters_and_redacts_two_services() -> None:
    catalog = AccountServiceAgentToolCatalog(_Registry(), _policy())  # type: ignore[arg-type]
    snapshot = await catalog.snapshot(_context())

    assert [item.name for item in snapshot.tools] == [
        "dianping__notes_search",
        "xhs_pc__notes_search",
    ]
    xhs = next(item for item in snapshot.tools if item.name.startswith("xhs_pc"))
    assert set(xhs.input_schema["properties"]) == {"keyword"}
    assert xhs.input_schema["required"] == ["keyword"]
    assert {item.code for item in snapshot.rejections} == {
        "schema-invalid",
        "side-effect-denied",
    }
    projection = snapshot.model_dump(mode="json")
    assert "tenant-a" not in str(projection)
    assert "xhs-primary" not in str(projection)
    await catalog.release(snapshot.snapshot_ref)


@pytest.mark.asyncio
async def test_catalog_injects_context_and_rejects_override_or_missing_context() -> None:
    registry = _Registry()
    catalog = AccountServiceAgentToolCatalog(registry, _policy())  # type: ignore[arg-type]
    context = _context()
    snapshot = await catalog.snapshot(context)
    call = ToolCall(
        call_id="call-1",
        tool_name="xhs_pc__notes_search",
        arguments={"keyword": "自贡"},
        task_id="task-1",
    )

    result = await catalog.execute(
        snapshot_ref=snapshot.snapshot_ref,
        call=call,
        context=context,
    )
    assert result.success is True
    assert result.output == {"notes": []}
    assert registry.calls[-1][2] == {
        "keyword": "自贡",
        "tenant_ref": "tenant-a",
        "account_ref": "xhs-primary",
    }

    denied = await catalog.execute(
        snapshot_ref=snapshot.snapshot_ref,
        call=call.model_copy(update={"call_id": "call-2", "arguments": {"keyword": "x", "tenant_ref": "other"}}),
        context=context,
    )
    assert denied.success is False
    assert denied.error is not None and denied.error.code == "TOOL_CONTEXT_OVERRIDE_DENIED"

    missing = await catalog.execute(
        snapshot_ref=snapshot.snapshot_ref,
        call=call.model_copy(update={"call_id": "call-3"}),
        context=_context(include_xhs_account=False),
    )
    assert missing.success is False
    assert missing.error is not None and missing.error.code == "TOOL_CONTEXT_MISSING"
    assert len(registry.calls) == 1
    await catalog.release(snapshot.snapshot_ref)


@pytest.mark.asyncio
async def test_catalog_pins_refresh_and_rejects_malformed_output_or_unknown_snapshot() -> None:
    registry = _Registry()
    catalog = AccountServiceAgentToolCatalog(registry, _policy())  # type: ignore[arg-type]
    context = _context()
    first = await catalog.snapshot(context)
    registry.descriptors[PlatformChannel.XHS_PC] = (
        _search_descriptor(version="2.0.0"),
    )
    second = await catalog.snapshot(context)
    assert first.snapshot_ref != second.snapshot_ref

    call = ToolCall(
        call_id="refresh-1",
        tool_name="xhs_pc__notes_search",
        arguments={"keyword": "food"},
    )
    pinned = await catalog.execute(
        snapshot_ref=first.snapshot_ref,
        call=call,
        context=context,
    )
    assert pinned.success is True
    assert registry.calls[-1][1].capability_version == "1.0.0"

    registry.outputs[PlatformChannel.XHS_PC] = {"unexpected": True}
    malformed = await catalog.execute(
        snapshot_ref=second.snapshot_ref,
        call=call.model_copy(update={"call_id": "refresh-2"}),
        context=context,
    )
    assert malformed.success is False
    assert malformed.error is not None and malformed.error.code == "TOOL_OUTPUT_INVALID"

    unavailable = await catalog.execute(
        snapshot_ref="agent-tools-v1:missing",
        call=call.model_copy(update={"call_id": "refresh-3"}),
        context=context,
    )
    assert unavailable.success is False
    assert unavailable.error is not None and unavailable.error.code == "TOOL_SNAPSHOT_UNAVAILABLE"
    await catalog.release(first.snapshot_ref)
    await catalog.release(second.snapshot_ref)


@pytest.mark.asyncio
async def test_catalog_normalizes_standard_text_json_content() -> None:
    registry = _Registry()
    registry.outputs[PlatformChannel.XHS_PC] = '{"notes": []}'
    catalog = AccountServiceAgentToolCatalog(registry, _policy())  # type: ignore[arg-type]
    context = _context()
    snapshot = await catalog.snapshot(context)

    result = await catalog.execute(
        snapshot_ref=snapshot.snapshot_ref,
        call=ToolCall(
            call_id="text-json",
            tool_name="xhs_pc__notes_search",
            arguments={"keyword": "自贡"},
        ),
        context=context,
    )

    assert result.success is True
    assert result.output == {"notes": []}
    await catalog.release(snapshot.snapshot_ref)


class _StaticGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call.tool_name)
        return ToolResult(call_id=call.call_id, success=True, output={})

    async def health(self, tool_name: str) -> bool:
        return bool(tool_name)


class _ManagedCatalog:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.released: list[str] = []

    async def snapshot(self, context: AgentToolExecutionContext) -> AgentToolCatalogSnapshot:
        assert context.tenant_ref == "tenant-a"
        return AgentToolCatalogSnapshot(
            snapshot_ref="agent-tools-v1:runtime",
            generation=1,
            created_at="2026-09-02T00:00:00Z",
            tools=(
                AgentToolDefinition(
                    name="xhs_pc__notes_search",
                    description="Search notes",
                    input_schema={"type": "object", "properties": {}},
                    output_schema={"type": "object"},
                ),
            ),
        )

    async def release(self, snapshot_ref: str) -> None:
        self.released.append(snapshot_ref)

    async def current_projection(self) -> AgentToolCatalogSnapshot:
        return await self.snapshot(_context())

    async def execute(
        self,
        *,
        snapshot_ref: str,
        call: ToolCall,
        context: AgentToolExecutionContext,
    ) -> ToolResult:
        assert snapshot_ref == "agent-tools-v1:runtime"
        assert context.tenant_ref == "tenant-a"
        self.calls.append(call.tool_name)
        return ToolResult(call_id=call.call_id, success=True, output={"notes": []})

    async def health(self, *, snapshot_ref: str, tool_name: str) -> bool:
        return bool(snapshot_ref and tool_name)


@pytest.mark.asyncio
async def test_runtime_exposes_and_routes_native_managed_tool() -> None:
    static = _StaticGateway()
    managed = _ManagedCatalog()
    runtime = PydanticAIAgentRuntime(
        tool_gateway=static,
        managed_tool_catalog=managed,
        managed_tool_executor=managed,
        model=TestModel(
            call_tools=["xhs_pc__notes_search"],
            custom_output_args={"summary": "ok", "final_output": {"ok": True}},
        ),
        enabled=True,
    )
    result = await runtime.run(
        AgentRunRequest(
            request_id="managed-run",
            prompt="search",
            dependencies=AgentDependencies(task_id="task", plan_id="plan", domain="food"),
            output_schema={"type": "object", "required": ["ok"]},
            tool_context=AgentToolExecutionContext(
                tenant_ref="tenant-a",
                platforms=(PlatformChannel.XHS_PC,),
                account_refs={PlatformChannel.XHS_PC.value: "primary"},
            ),
        )
    )
    assert [item.tool_name for item in result.tool_calls] == ["xhs_pc__notes_search"]
    assert managed.calls == ["xhs_pc__notes_search"]
    assert static.calls == []
    assert managed.released == ["agent-tools-v1:runtime"]


@pytest.mark.asyncio
async def test_composition_binds_catalog_only_for_explicit_policy() -> None:
    disabled = build_composition_root(target_settings=TargetSettings(_env_file=None))
    assert "agent_tool_catalog" not in disabled.logical_bindings
    await disabled.close()

    settings = TargetSettings(
        _env_file=None,
        account_services_json=(
            '[{"service_id":"xhs-account","base_url":"http://xhs.test",'
            '"mcp_url":"http://xhs.test/mcp","protocol":"http+mcp",'
            '"channels":["xhs_pc"],"capabilities":["notes.search"]}]'
        ),
        agent_mcp_tool_policy_json=(
            '{"enabled":true,"allowed_platforms":["xhs_pc"],'
            '"allowed_capabilities":["notes.search"]}'
        ),
    )
    root = build_composition_root(target_settings=settings)
    assert "agent_tool_catalog" in root.logical_bindings
    resolved = await root.resolve_logical("agent_tool_catalog")
    assert isinstance(resolved, AccountServiceAgentToolCatalog)
    await root.close()


def test_agent_tool_catalog_api_returns_redacted_projection() -> None:
    class _ProjectionCatalog:
        async def current_projection(self) -> AgentToolCatalogSnapshot:
            return AgentToolCatalogSnapshot(
                snapshot_ref="agent-tools-v1:projection",
                generation=1,
                created_at="2026-09-02T00:00:00Z",
                projection=(
                    {
                        "public_name": "xhs_pc__notes_search",
                        "service_id": "xhs-account",
                        "platform": "xhs_pc",
                        "capability": "notes.search",
                        "capability_version": "1.0.0",
                    },
                ),
            )

    application = FastAPI()
    application.state.agent_tool_catalog = _ProjectionCatalog()
    application.include_router(platform_router)
    application.dependency_overrides[get_current_user_id] = lambda: "tenant-secret"
    with TestClient(application) as client:
        response = client.get("/v1/platform/agent-tools/catalog")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["tools"][0]["public_name"] == "xhs_pc__notes_search"
    assert "tenant-secret" not in response.text
