"""Basic import and construction checks for the comment-first Agent."""

from __future__ import annotations

import sys

sys.path.insert(0, "src")


def test_imports() -> None:
    from xhs_food import XHSFoodOrchestrator, XHSFoodResponse, XHSFoodState
    from xhs_food.agents import AnalyzerAgent, IntentParserAgent
    from xhs_food.composition import build_composition_root
    from xhs_food.research import (
        CommentFirstResearchWorkflow,
        DianpingShopEnricher,
        XhsCommentLeadCollector,
    )
    from xhs_food.services import LLMService

    assert all(
        item is not None
        for item in (
            XHSFoodOrchestrator,
            XHSFoodState,
            XHSFoodResponse,
            AnalyzerAgent,
            IntentParserAgent,
            CommentFirstResearchWorkflow,
            XhsCommentLeadCollector,
            DianpingShopEnricher,
            LLMService,
            build_composition_root,
        )
    )


def test_schema_creation() -> None:
    from xhs_food.domain_packs.food.intent import FoodSearchIntent
    from xhs_food.schemas import ConversationContext, RestaurantRecommendation

    intent = FoodSearchIntent(
        location="成都",
        food_type="火锅",
        requirements=["本地人常去", "老店"],
        exclude_keywords=["网红"],
    )
    context = ConversationContext()
    context.add_user_message("成都火锅")
    recommendation = RestaurantRecommendation(
        name="测试老店",
        location="XX路XX号",
        features=["本地人推荐"],
        confidence=0.85,
    )

    assert intent.location == "成都"
    assert context.conversation_history[-1]["content"] == "成都火锅"
    assert recommendation.name == "测试老店"


def test_orchestrator_creation() -> None:
    from xhs_food import XHSFoodOrchestrator
    from xhs_food.research import CommentFirstResearchWorkflow

    orchestrator = XHSFoodOrchestrator(workflow=CommentFirstResearchWorkflow())

    assert isinstance(orchestrator.workflow, CommentFirstResearchWorkflow)
    assert orchestrator.context.turn_count == 0
