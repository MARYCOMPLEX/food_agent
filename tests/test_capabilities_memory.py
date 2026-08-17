"""Capability policy and layered memory tests."""

from __future__ import annotations

import pytest

from xhs_food.capabilities import (
    CapabilityCatalog,
    CapabilityGateway,
    CapabilityKind,
    CapabilityManifest,
    CapabilityPolicy,
    CapabilityPolicyError,
    LocalCapability,
    MCPToolSource,
    SideEffectLevel,
)
from xhs_food.memory import (
    InMemoryMemoryProvider,
    LayeredMemoryProvider,
    LazySessionManagerMemoryProvider,
    MemoryQuery,
    MemoryRecord,
)
from xhs_food.runtime.models import AgentRunContext, AgentRunResult, LoopPhase


@pytest.mark.asyncio
async def test_gateway_validates_schema_and_concurrency_metadata() -> None:
    seen = []

    async def handler(args, context):
        seen.append(args["query"])
        return {"items": [args["query"]]}

    capability = LocalCapability(
        CapabilityManifest(
            name="search",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        ),
        handler,
    )
    gateway = CapabilityGateway(CapabilityCatalog([capability]))
    context = AgentRunContext(run_id="r", session_id="s", user_input="q")

    assert await gateway.invoke("search", {"query": "火锅"}, context) == {"items": ["火锅"]}
    with pytest.raises(ValueError, match="missing"):
        await gateway.invoke("search", {}, context)
    assert seen == ["火锅"]


@pytest.mark.asyncio
async def test_gateway_blocks_untrusted_side_effect() -> None:
    capability = LocalCapability(
        CapabilityManifest(
            name="delete",
            trust="untrusted",
            side_effect=SideEffectLevel.DESTRUCTIVE,
        ),
        lambda args, context: None,
    )
    gateway = CapabilityGateway(
        CapabilityCatalog([capability]),
        policy=CapabilityPolicy(max_side_effect=SideEffectLevel.WRITE),
    )
    with pytest.raises(CapabilityPolicyError):
        await gateway.invoke(
            "delete",
            {},
            AgentRunContext(run_id="r", session_id="s", user_input="q"),
        )


@pytest.mark.asyncio
async def test_layered_memory_recall_is_traceable() -> None:
    provider = InMemoryMemoryProvider()
    memory = LayeredMemoryProvider(episodic=provider)
    await memory.put(
        MemoryRecord(
            namespace="session-1",
            scope="episodic",
            content="用户喜欢成都老火锅",
            metadata={"source": "test"},
        )
    )

    records = await memory.recall("成都火锅", "session-1")
    assert len(records) == 1
    assert records[0].metadata["source"] == "test"


@pytest.mark.asyncio
async def test_mcp_source_discovers_paginated_tools_and_preserves_remote_name() -> None:
    class FakeMCPClient:
        def __init__(self) -> None:
            self.calls = []

        async def list_tools(self, *, cursor=None):
            if cursor is None:
                return {
                    "tools": [
                        {
                            "name": "search",
                            "description": "Search evidence",
                            "inputSchema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {"query": {"type": "string"}},
                            },
                            "annotations": {"readOnlyHint": True},
                        }
                    ],
                    "nextCursor": "page-2",
                }
            return {
                "tools": [
                    {
                        "name": "publish",
                        "description": "Publish a result",
                        "inputSchema": {"type": "object"},
                        "annotations": {"idempotentHint": False},
                    }
                ]
            }

        async def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {"remote_name": name, **arguments}

    client = FakeMCPClient()
    catalog = CapabilityCatalog()
    manifests = await MCPToolSource(
        client,
        namespace="research",
        trust="local",
    ).load_into(catalog)

    assert [manifest.name for manifest in manifests] == [
        "research.search",
        "research.publish",
    ]
    assert manifests[0].kind == CapabilityKind.MCP
    assert manifests[0].side_effect == SideEffectLevel.READ_ONLY
    assert manifests[0].idempotent is True
    assert manifests[1].side_effect == SideEffectLevel.EXTERNAL
    assert manifests[1].idempotent is False

    gateway = CapabilityGateway(catalog)
    result = await gateway.invoke(
        "research.search",
        {"query": "成都火锅"},
        AgentRunContext(run_id="r", session_id="s", user_input="q"),
    )
    assert result == {"remote_name": "search", "query": "成都火锅"}
    assert client.calls == [("search", {"query": "成都火锅"})]


@pytest.mark.asyncio
async def test_lazy_session_memory_is_read_only_and_resolves_on_search(monkeypatch) -> None:
    class FakeSessionManager:
        def __init__(self) -> None:
            self.user_messages = []
            self.assistant_messages = []

        async def search_similar_context(self, query, *, session_id, limit):
            return [{"content": "偏好老火锅", "similarity": 0.91}]

        async def add_user_message(self, session_id, content):
            self.user_messages.append((session_id, content))

        async def add_assistant_message(self, session_id, content):
            self.assistant_messages.append((session_id, content))

    manager = FakeSessionManager()
    resolutions = 0

    async def get_manager():
        nonlocal resolutions
        resolutions += 1
        return manager

    monkeypatch.setattr(
        LazySessionManagerMemoryProvider,
        "_get_manager",
        staticmethod(get_manager),
    )
    provider = LazySessionManagerMemoryProvider(read_only=True)
    record = MemoryRecord(
        namespace="session-1",
        scope="episodic",
        content="成都火锅",
        metadata={"role": "user"},
    )
    context = AgentRunContext(
        run_id="run-1",
        session_id="session-1",
        user_input="成都火锅",
    )
    result = AgentRunResult(
        run_id="run-1",
        session_id="session-1",
        turn_id=1,
        status="completed",
        phase=LoopPhase.COMPLETE,
        answer="推荐老火锅",
    )

    assert await provider.put(record) is record
    await provider.commit_turn(context, result)
    assert await provider.delete(record.id, record.namespace) is False
    assert resolutions == 0

    memories = await provider.search(MemoryQuery(query="老火锅", namespace="session-1", limit=3))
    assert resolutions == 1
    assert memories[0].content["content"] == "偏好老火锅"
    assert memories[0].score == 0.91
    assert manager.user_messages == []
    assert manager.assistant_messages == []
