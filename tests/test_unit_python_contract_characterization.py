"""Public Python surface for the current Agent architecture."""

from __future__ import annotations

import inspect
from importlib import util

from xhs_food import __all__ as root_exports
from xhs_food.agents import __all__ as agent_exports
from xhs_food.orchestrator import XHSFoodOrchestrator
from xhs_food.research import __all__ as research_exports


def test_public_module_exports_match_current_surface() -> None:
    assert "SearchPhase" not in root_exports
    assert "FollowUpType" not in root_exports
    assert "POIEnricherAgent" not in agent_exports
    assert {"CommentFirstResearchWorkflow", "XhsCommentLeadCollector"} <= set(research_exports)


def test_orchestrator_has_one_workflow_injection_point() -> None:
    parameters = list(inspect.signature(XHSFoodOrchestrator).parameters)
    assert parameters[:3] == ["workflow", "llm_service", "_"]
    assert list(inspect.signature(XHSFoodOrchestrator.search_stream).parameters) == [
        "self",
        "user_input",
        "emitter",
        "tool_context",
    ]
    assert isinstance(XHSFoodOrchestrator.context, property)


def test_retired_implementation_modules_are_not_importable() -> None:
    for module_name in (
        "xhs_food.protocols.mcp",
        "xhs_food.providers.xhs_providers",
        "xhs_food.di.factories",
        "xhs_food.orchestrator.follow_up",
        "xhs_food.orchestrator.search_executor",
        "xhs_food.services.amap_api",
    ):
        assert util.find_spec(module_name) is None
