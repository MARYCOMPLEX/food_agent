"""Snapshots for the currently published Python and MCP compatibility surface."""

from __future__ import annotations

import inspect
import json
from importlib import import_module, util
from pathlib import Path

from xhs_food.orchestrator import XHSFoodOrchestrator


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
        search_tool=dependencies["search_tool"],
        llm_service=dependencies["llm_service"],
        intent_parser=dependencies["intent_parser"],
        analyzer=dependencies["analyzer"],
        follow_up_handler=dependencies["follow_up_handler"],
        search_executor=dependencies["search_executor"],
        deep_search=False,
        fast_mode_limit=7,
    )
    assert orchestrator._llm_service is dependencies["llm_service"]
    assert orchestrator._intent_parser is dependencies["intent_parser"]
    assert orchestrator._analyzer is dependencies["analyzer"]
    assert orchestrator._follow_up_handler is dependencies["follow_up_handler"]
    assert orchestrator._search_executor is dependencies["search_executor"]
    assert orchestrator._deep_search is False
    assert orchestrator._fast_mode_limit == 7


def test_removed_legacy_mcp_modules_are_not_importable() -> None:
    assert util.find_spec("xhs_food.protocols.mcp") is None
    assert util.find_spec("xhs_food.providers.xhs_providers") is None
    assert util.find_spec("xhs_food.di.factories") is None
