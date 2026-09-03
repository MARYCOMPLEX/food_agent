"""Regression gates for the retired generic place-provider boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.research import DianpingMcpSource, XhsMcpSource


@pytest.mark.unit
def test_only_explicit_platform_source_adapters_are_importable() -> None:
    assert XhsMcpSource.__name__ == "XhsMcpSource"
    assert DianpingMcpSource.__name__ == "DianpingMcpSource"


@pytest.mark.unit
def test_removed_generic_place_modules_are_not_present() -> None:
    root = Path(__file__).parents[1] / "src" / "xhs_food"
    assert not (root / "gateways" / "place.py").exists()
    assert not (root / "agents" / "poi_enricher.py").exists()
    assert not (root / "agents" / "poi_search.py").exists()
