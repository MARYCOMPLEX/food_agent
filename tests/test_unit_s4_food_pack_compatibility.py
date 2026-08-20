"""S4 Food Pack extraction, differential, and rollback compatibility gates."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import xhs_food.domain_packs.food.preprocessing as food_preprocessing
import xhs_food.domain_packs.food.scoring as food_scoring
import xhs_food.services.preprocessing as legacy_preprocessing
import xhs_food.services.scoring as legacy_scoring
from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.composition import build_legacy_composition_root
from xhs_food.composition.adapters.food_output import LegacyFoodOutputAdapter
from xhs_food.composition.adapters.legacy_food import LegacyFoodPackAdapter
from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
from xhs_food.contracts import ContractError, ContractPayload, EvidenceBundle, EvidenceItem
from xhs_food.domain_packs.food import (
    FoodDecisionPolicy,
    FoodPlacePolicy,
    FoodSearchIntent,
    FoodWorkflowPolicy,
    create_food_pack,
    load_food_manifest,
    load_food_schema_bundle,
)
from xhs_food.domain_packs.food.prompts import COMMENT_ANALYSIS_SYSTEM_PROMPT
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.prompts import COMMENT_ANALYSIS_SYSTEM_PROMPT as LEGACY_COMMENT_PROMPT
from xhs_food.protocols.mcp import MCPToolRegistry
from xhs_food.schemas import (
    ConversationContext,
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)
from xhs_food.schemas import (
    FoodSearchIntent as LegacyFoodSearchIntent,
)

pytestmark = pytest.mark.unit

_SEARCH_FIXTURE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "characterization" / "food_search_behavior.json"
    ).read_text(encoding="utf-8")
)


def _intent() -> FoodSearchIntent:
    return FoodSearchIntent.from_dict(_SEARCH_FIXTURE["intent"])


def _recommendations() -> list[RestaurantRecommendation]:
    local = WanghongAnalysis(
        score=WanghongScore.LIKELY_LOCAL,
        confidence=0.9,
        reasons=["本地人口吻"],
        has_local_mentions=True,
    )
    wanghong = WanghongAnalysis(
        score=WanghongScore.LIKELY_WANGHONG,
        confidence=0.8,
        reasons=["排队营销", "拍照导向"],
    )
    return [
        RestaurantRecommendation(
            name="老 灶店",
            features=["老店"],
            source_notes=["n1"],
            confidence=0.8,
            wanghong_analysis=local,
        ),
        RestaurantRecommendation(
            name="老灶店",
            features=["夜宵"],
            source_notes=["n2", "n3"],
            confidence=0.9,
            wanghong_analysis=local,
        ),
        RestaurantRecommendation(
            name="打卡店",
            source_notes=["n4", "n5"],
            confidence=0.95,
            wanghong_analysis=wanghong,
        ),
        RestaurantRecommendation(name="未知"),
    ]


def test_food_owned_intent_prompt_preprocessing_and_scoring_keep_legacy_exports() -> None:
    assert LegacyFoodSearchIntent is FoodSearchIntent
    assert LEGACY_COMMENT_PROMPT is COMMENT_ANALYSIS_SYSTEM_PROMPT
    assert legacy_preprocessing.ProcessedComment is food_preprocessing.ProcessedComment
    assert legacy_preprocessing.preprocess_comments is food_preprocessing.preprocess_comments
    assert (
        legacy_preprocessing.format_comments_for_llm is food_preprocessing.format_comments_for_llm
    )
    assert legacy_scoring.ShopScore is food_scoring.ShopScore
    assert legacy_scoring.calculate_scores is food_scoring.calculate_scores
    assert legacy_scoring.get_top_shops is food_scoring.get_top_shops


def test_registered_and_legacy_workflow_policies_match_frozen_keyword_order() -> None:
    intent = _intent()
    policies = (create_food_pack().workflow, LegacyFoodPackAdapter().workflow)

    for policy in policies:
        assert policy.phase1_keywords(intent) == _SEARCH_FIXTURE["phase1_keywords"]
        assert policy.phase2_keywords(intent) == _SEARCH_FIXTURE["phase2_keywords"]
        assert policy.expand_keywords(intent) == _SEARCH_FIXTURE["expand_keywords"]
        assert policy.phase4_keywords(intent) == ["自贡 火锅 老店", "自贡 火锅 本地人"]
        assert policy.should_stop(15, deep_search=False, fast_limit=15) is True
        assert policy.should_stop(15, deep_search=True, fast_limit=15) is False

    assert isinstance(policies[0], FoodWorkflowPolicy)


def test_registered_and_legacy_decision_policies_are_differentially_exact() -> None:
    pack_policy = FoodDecisionPolicy()
    legacy_policy = LegacyFoodPackAdapter().decision
    pack_merged = pack_policy.merge_and_validate(deepcopy(_recommendations()))
    legacy_merged = legacy_policy.merge_and_validate(deepcopy(_recommendations()))

    pack_ranked, pack_filtered = pack_policy.rank_and_filter(pack_merged, ["不存在"])
    legacy_ranked, legacy_filtered = legacy_policy.rank_and_filter(
        legacy_merged,
        ["不存在"],
    )

    assert [item.to_dict() for item in pack_merged] == [item.to_dict() for item in legacy_merged]
    assert [item.to_dict() for item in pack_ranked] == [item.to_dict() for item in legacy_ranked]
    assert pack_filtered == legacy_filtered == 1
    assert [item.name for item in pack_ranked] == ["老 灶店"]


def test_food_place_policy_keeps_matching_projection_without_network_ownership() -> None:
    policy = FoodPlacePolicy()

    assert policy.search_variants("自贡盐帮馆（总店）", "自贡") == [
        ("自贡盐帮馆（总店）", "自贡", "exact_with_city"),
        ("盐帮馆（总店）", "自贡", "no_city_prefix"),
        ("自贡盐帮馆", "自贡", "no_branch_suffix"),
        ("盐帮馆", "自贡", "clean_name"),
        ("自贡盐帮馆（总店）", "", "no_city_limit"),
    ]
    assert policy.select_place({"pois": [{"name": "盐帮馆"}]}) == {"name": "盐帮馆"}
    assert policy.select_place({"error": "dependency_unavailable"}) is None
    assert (
        policy.build_address(
            {"pname": "四川省", "cityname": "自贡市", "adname": "自流井区", "address": "同兴路"}
        )
        == "四川省自贡市自流井区同兴路"
    )
    assert [policy.cost_band(value) for value in (29, 30, 79, 80)] == ["$", "$$", "$$", "$$$"]


def test_food_contract_methods_validate_against_every_pinned_output_schema() -> None:
    pack = create_food_pack()
    bundle = load_food_schema_bundle()
    documents = {item.schema_id: item for item in bundle.schemas}
    registry = Registry().with_resources(
        [
            (schema_id, Resource.from_contents(document.schema_document))
            for schema_id, document in documents.items()
        ]
    )

    for method_contract in pack.describe().method_schemas:
        method = method_contract.method.value
        example = cast(
            ContractPayload,
            documents[method_contract.input_schema_id].examples[0],
        )
        if method == "describe":
            output = pack.describe().model_dump(mode="json", by_alias=True)
        elif method == "classify_constraints":
            output = pack.classify_constraints(example)
        elif method == "validate_evidence":
            output = pack.validate_evidence(EvidenceItem.model_validate(example))
        elif method == "compute_features":
            output = pack.compute_features(
                EvidenceBundle.model_validate(cast(ContractPayload, example["bundle"])),
                tuple(
                    EvidenceItem.model_validate(item)
                    for item in cast(list[ContractPayload], example["evidence_items"])
                ),
            )
        elif method == "score_public":
            output = pack.score_public(example)
        elif method == "build_final_output":
            output = pack.build_final_output(example)
        else:
            output = pack.map_error(ContractError.model_validate(example)).model_dump(mode="json")

        validator = Draft202012Validator(
            documents[method_contract.output_schema_id].schema_document,
            registry=registry,
        )
        assert list(validator.iter_errors(output)) == [], method


def test_final_output_is_rejected_before_legacy_dto_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = LegacyFoodOutputAdapter()
    invalid = json.loads(json.dumps(load_food_manifest().final_output_example, ensure_ascii=False))
    invalid["recommendations"][0]["publicScore"] = 2
    mapped: list[object] = []

    def record_mapping(value: object) -> RestaurantRecommendation:
        mapped.append(value)
        return RestaurantRecommendation(name="unexpected")

    monkeypatch.setattr(
        LegacyFoodOutputAdapter,
        "_recommendation",
        staticmethod(record_mapping),
    )

    with pytest.raises(ValueError, match="maximum"):
        adapter.from_domain_output(invalid)

    assert mapped == []


async def test_search_executor_uses_active_validator_before_legacy_dto_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = LegacyFoodPackAdapter()
    validated: list[object] = []
    constructed: list[object] = []

    def reject_output(value: object) -> None:
        validated.append(value)
        raise ValueError("active Food Pack rejected output")

    def record_construction(**kwargs: object) -> object:
        constructed.append(kwargs)
        return object()

    monkeypatch.setattr(pack, "validate_final_output", reject_output)
    monkeypatch.setattr(LegacyFoodOutputAdapter, "_response", staticmethod(record_construction))
    executor = SearchExecutor(
        xhs_registry=MCPToolRegistry(),
        analyzer=cast(AnalyzerAgent, object()),
        context=ConversationContext(),
        food_pack=pack,
    )

    with pytest.raises(ValueError, match="active Food Pack rejected output"):
        await executor.handle_new_search(SimpleNamespace(intent=None))

    assert validated == [
        {
            "schemaVersion": "food-agent-final-output/v1",
            "summary": "",
            "recommendations": [],
        }
    ]
    assert constructed == []


def test_valid_domain_output_maps_to_exact_legacy_and_frontend_defaults() -> None:
    adapter = LegacyFoodOutputAdapter()
    response = adapter.from_domain_output(load_food_manifest().final_output_example)

    assert response.to_dict() == {
        "status": "ok",
        "recommendations": [
            RestaurantRecommendation(
                name="restaurant-001",
                confidence=0.91,
                source_notes=["evidence-001"],
            ).to_dict()
        ],
        "filtered_count": 0,
        "clarify_questions": [],
        "error_message": None,
        "summary": "找到 1 个公共候选。",
    }
    assert adapter.to_frontend(response) == response.to_dict()


async def test_pack_version_switch_rebinds_only_food_and_keeps_other_facades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODULAR_FOOD_PACK_VERSION", "legacy/v1")
    root = build_legacy_composition_root()
    try:
        food_binding = root.logical_bindings["food_pack"]
        assert (food_binding.registry_name, food_binding.binding_name) == (
            "domain_packs",
            "food_legacy",
        )
        assert isinstance(await root.resolve_logical("food_pack"), LegacyFoodPackAdapter)
        assert isinstance(
            await root.resolve_logical("modular_core"),
            LegacyResearchTaskFacade,
        )
        assert await root.resolve("tools", "food_tool_gateway") is not None
        assert await root.resolve("sources", "food_place_capability") is not None
        assert await root.resolve("sources", "food_reviews_capability") is not None
    finally:
        await root.close()
