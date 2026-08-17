"""Hermetic integration test for the search adapter and Agent Loop."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from xhs_food import XHSFoodOrchestrator
from xhs_food.agents.intent_parser import IntentParseResult
from xhs_food.schemas import FoodSearchIntent, RestaurantRecommendation


class _Parser:
    async def parse(self, user_input, context=None):
        return IntentParseResult(
            success=True,
            intent=FoodSearchIntent(location="成都", food_type="火锅"),
        )

    def detect_follow_up_type(self, user_input, context=None):
        return (None, None)


class _Executor:
    def reset_cache(self):
        return None

    async def execute_4_stage_search(self, intent):
        return [{"id": "note-1", "title": "本地老店", "desc": "老火锅", "likes": 10}]

    async def analyze_notes_concurrent(self, notes, intent):
        return [RestaurantRecommendation(name="老店A", source_notes=["note-1"], confidence=0.9)]

    def merge_and_validate(self, restaurants):
        return restaurants


@dataclass
class _Enriched:
    name: str

    def to_dict(self):
        return {"name": self.name, "address": "成都"}


class _Poi:
    async def enrich_stream(self, recommendations, city):
        for rec in recommendations:
            yield _Enriched(rec.name)


class _Registry:
    def get(self, name):
        return None


@pytest.mark.asyncio
async def test_orchestrator_process_uses_agent_loop(monkeypatch):
    import xhs_food.agents as agents_module

    monkeypatch.setattr(agents_module, "get_poi_enricher", lambda: _Poi())
    orchestrator = XHSFoodOrchestrator(
        xhs_registry=_Registry(),
        llm_service=object(),
        intent_parser=_Parser(),
        analyzer=object(),
        search_executor=_Executor(),
        use_agent_loop=True,
    )

    response = await orchestrator.process("成都本地火锅")

    assert response.status == "ok"
    assert response.recommendations[0].name == "老店A"
    assert orchestrator.last_run is not None
    assert orchestrator.last_run.status == "completed"
    assert orchestrator.last_run.evidence[0].source_id == "note-1"
