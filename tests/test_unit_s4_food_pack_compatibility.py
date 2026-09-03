"""Food Pack contracts for the comment-first Agent."""

from __future__ import annotations

import pytest

from xhs_food.composition import build_composition_root
from xhs_food.domain_packs.food import create_food_pack, load_food_contract_resources
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.domain_packs.food.preprocessing import preprocess_comments
from xhs_food.schemas import RestaurantRecommendation


def test_food_pack_exposes_constraint_and_comment_evidence_policies() -> None:
    pack = create_food_pack()
    description = pack.describe()
    assert description.domain_id == "food"
    assert "争议" in pack.workflow.plan_queries(FoodSearchIntent(location="成都"))[-1]
    assert pack.classify_constraints({"constraints": []})["results"] == []


def test_comment_preprocessing_preserves_raw_evidence_and_bounded_text() -> None:
    comments = preprocess_comments(
        [{"id": "c1", "content": "锅底很香", "like_count": 8, "user_info": {"nickname": "食客"}}]
    )
    assert comments[0].id == "c1"
    assert comments[0].text == "锅底很香"
    assert comments[0].user_name == ""


def test_food_manifest_has_no_local_place_or_search_tool_compatibility() -> None:
    manifest, schema_bundle = load_food_contract_resources()
    assert manifest.allowed_tools == ()
    assert schema_bundle is not None
    assert {source.capability for source in manifest.domain_sources} == {
        "notes.search",
        "notes.detail",
        "comments.search",
        "places.search",
        "places.detail",
        "reviews.search",
    }


@pytest.mark.asyncio
async def test_composition_root_resolves_one_agent_workflow_and_task_facade() -> None:
    root = build_composition_root()
    try:
        workflow = await root.resolve_logical("research_agent")
        task = await root.resolve_logical("research_task")
        assert workflow is await root.resolve_logical("research_agent")
        assert hasattr(workflow, "execute")
        assert hasattr(task, "start_new")
        with pytest.raises(KeyError):
            await root.resolve_logical("modular_core")
    finally:
        await root.close()


def test_recommendation_wire_contract_uses_shop_profile_and_evidence() -> None:
    output = RestaurantRecommendation(name="老店").to_dict()
    assert "shopProfile" in output
    assert "evidenceRefs" in output
    assert "poi_details" not in output
