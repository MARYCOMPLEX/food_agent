"""Snapshots for the currently published Python and MCP compatibility surface."""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict
from importlib import import_module
from pathlib import Path

from xhs_food.di import get_xhs_tool_registry
from xhs_food.orchestrator import XHSFoodOrchestrator
from xhs_food.protocols import MCPToolRegistry, ToolResult


_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/characterization/python_public_contract.json").read_text(
        encoding="utf-8"
    )
)


def test_public_module_exports_match_snapshot() -> None:
    for module_name, expected in _FIXTURE["exports"].items():
        module = import_module(module_name)
        assert module.__all__ == expected
        assert all(hasattr(module, name) for name in expected)


def test_orchestrator_public_signatures_match_snapshot() -> None:
    assert list(inspect.signature(XHSFoodOrchestrator).parameters) == _FIXTURE[
        "orchestrator_constructor"
    ]
    for method_name, expected in _FIXTURE["orchestrator_methods"].items():
        assert list(inspect.signature(getattr(XHSFoodOrchestrator, method_name)).parameters) == expected
    assert isinstance(XHSFoodOrchestrator.context, property)


def test_orchestrator_constructor_preserves_caller_injection_points() -> None:
    dependencies = {name: object() for name in _FIXTURE["orchestrator_constructor"][:6]}
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=dependencies["xhs_registry"],
        llm_service=dependencies["llm_service"],
        intent_parser=dependencies["intent_parser"],
        analyzer=dependencies["analyzer"],
        follow_up_handler=dependencies["follow_up_handler"],
        search_executor=dependencies["search_executor"],
        deep_search=False,
        fast_mode_limit=7,
    )
    assert orchestrator._xhs_registry is dependencies["xhs_registry"]
    assert orchestrator._llm_service is dependencies["llm_service"]
    assert orchestrator._intent_parser is dependencies["intent_parser"]
    assert orchestrator._analyzer is dependencies["analyzer"]
    assert orchestrator._follow_up_handler is dependencies["follow_up_handler"]
    assert orchestrator._search_executor is dependencies["search_executor"]
    assert orchestrator._deep_search is False
    assert orchestrator._fast_mode_limit == 7


def test_default_mcp_registration_names_and_tool_result_envelopes() -> None:
    assert get_xhs_tool_registry().list_tools() == _FIXTURE["tools"]
    assert MCPToolRegistry().list_tools() == []

    ok = ToolResult.ok({"notes": [{"id": "n1"}]}, source="fixture")
    failed = ToolResult.fail("SOURCE_TIMEOUT", "source timed out", retryable=True)
    assert asdict(ok) == _FIXTURE["tool_result_ok"]
    assert asdict(failed) == _FIXTURE["tool_result_fail"]
