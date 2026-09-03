"""Retirement gates for the removed compatibility route.

The former rollback suite tested the deleted legacy task facade.  The active
composition root now has one explicit Agent workflow and one transport task
entry point, so this file protects that boundary instead.
"""

from __future__ import annotations

import pytest

from xhs_food.composition import build_composition_root
from xhs_food.research import CommentFirstResearchWorkflow


@pytest.mark.unit
async def test_composition_root_exposes_named_research_boundaries_only() -> None:
    root = build_composition_root()
    try:
        assert "research_agent" in root.logical_bindings
        assert "research_task" in root.logical_bindings
        assert "modular_core" not in root.logical_bindings

        agent = await root.resolve_logical("research_agent")
        task = await root.resolve_logical("research_task")
        assert isinstance(agent, CommentFirstResearchWorkflow)
        assert hasattr(task, "start_new")
        assert hasattr(task, "refine")
    finally:
        await root.close()


@pytest.mark.unit
def test_removed_search_route_modules_are_absent() -> None:
    from pathlib import Path

    source_root = Path(__file__).parents[1] / "src" / "xhs_food"
    assert not (source_root / "orchestrator" / "follow_up.py").exists()
    assert not (source_root / "orchestrator" / "search_executor.py").exists()
    assert not (source_root / "services" / "amap_api.py").exists()
