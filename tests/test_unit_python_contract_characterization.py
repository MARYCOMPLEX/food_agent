"""Public Python surface for the current Agent architecture."""

from __future__ import annotations

import inspect
from importlib import util

from food_agent import __all__ as root_exports
from food_agent.agents import __all__ as agent_exports
from food_agent.orchestrator import XHSFoodOrchestrator
from food_agent.research import __all__ as research_exports


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
        "food_agent.protocols.mcp",
        "food_agent.providers.xhs_providers",
        "food_agent.di.factories",
        "food_agent.orchestrator.follow_up",
        "food_agent.orchestrator.search_executor",
        "food_agent.services.amap_api",
    ):
        try:
            spec = util.find_spec(module_name)
        except ModuleNotFoundError:
            spec = None
        assert spec is None
