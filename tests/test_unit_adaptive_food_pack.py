"""Unit contracts for the observation-driven Food Domain Pack adapter."""

from __future__ import annotations

from xhs_food.contracts import SourceEnvelope
from xhs_food.domain_packs.food.adaptive_pack import (
    FoodAdaptivePack,
    FoodClaimType,
    FoodEvidenceType,
    ObservationEnvelope,
)


def _comment(
    comment_id: str,
    sentiment: str,
    *,
    text: str = "成都本地人推荐这家店",
    shop: str = "老店",
    payload_ref: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": comment_id,
        "note_id": "note-1",
        "content": text,
        "sentiment": sentiment,
        "mentioned_shops": [shop],
        "mentioned_dishes": ["毛肚"],
    }
    if payload_ref:
        item["provider_payload_ref"] = payload_ref
    return item


def test_declaration_exposes_food_goal_ontology_source_order_and_depth_policy() -> None:
    pack = FoodAdaptivePack()

    assert pack.goal.goal_id == "food.restaurant-recommendation"
    assert FoodEvidenceType.XHS_COMMENT.value in pack.evidence_types
    assert FoodEvidenceType.DIANPING_PROFILE.value in pack.evidence_types
    assert pack.source_priorities["comments.search"] > pack.source_priorities["places.detail"]
    assert pack.source_priority[0].role == "primary"
    assert pack.source_priority[1].role == "secondary"
    assert pack.comment_deep_fetch.include_replies is True
    assert pack.comment_deep_fetch.max_pages > 1
    assert "address" in pack.shop_fields
    assert "average_price" in pack.shop_fields
    assert "opening_hours" in pack.shop_fields


def test_comment_observation_becomes_standard_claims_and_candidate_entities_losslessly() -> None:
    raw_comment = _comment("comment-1", "positive", payload_ref="blob://comment-1")
    envelope = ObservationEnvelope(
        source="xhs",
        operation="comments.search",
        items=(raw_comment,),
        raw_payload={"provider_page": 1, "opaque": True},
        provider_payload_ref="payload://page-1",
        completeness="complete",
        expected_count=1,
    )

    result = FoodAdaptivePack().adapt_observation(envelope)

    assert len(result.claims) == 1
    assert result.claims[0].attributes["claim_type"] == FoodClaimType.EXPERIENCE.value
    assert result.claims[0].evidence_refs == ("xhs:note:note-1:comment:comment-1",)
    shop = next(entity for entity in result.entities if entity["entity_type"] == "shop")
    assert shop["entity_id"] == "shop:老店"
    assert shop["raw_comment_refs"] == ["xhs:note:note-1:comment:comment-1"]
    assert result.raw_comments == (raw_comment,)
    assert result.provider_payload_refs == ("payload://page-1",)
    assert result.raw_provider_payloads == ({"provider_page": 1, "opaque": True},)


def test_model_findings_become_cited_candidates_without_replacing_raw_comments() -> None:
    pack = FoodAdaptivePack()
    adaptation = pack.adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=({"id": "comment-1", "note_id": "note-1", "content": "值得排队"},),
            raw_payload={"provider": "untouched"},
            completeness="complete",
            expected_count=1,
        )
    )

    reduced = pack.reduce_findings(
        adaptation,
        findings=(
            {
                "entity_name": "隐藏老火锅",
                "claim": "评论集中认可锅底和性价比",
                "sentiment": "positive",
                "dish_names": ["毛肚"],
                "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
            },
        ),
    )

    shop = next(item for item in reduced.entities if item["entity_id"] == "shop:隐藏老火锅")
    assert shop["candidate"] is True
    assert shop["dishes"] == ["毛肚"]
    assert any(
        claim.attributes["source"] == "model_critic" for claim in reduced.claims
    )
    assert reduced.raw_comments[0]["content"] == "值得排队"
    assert reduced.raw_provider_payloads[0] == {"provider": "untouched"}


def test_uncited_model_finding_is_a_gap_and_not_a_fabricated_claim() -> None:
    pack = FoodAdaptivePack()
    adaptation = pack.adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(_comment("comment-1", "positive"),),
            completeness="complete",
            expected_count=1,
        )
    )

    reduced = pack.merge_model_findings(
        adaptation,
        findings=({"entity_name": "未引用的店"},),
    )

    assert not any(item.get("name") == "未引用的店" for item in reduced.entities)
    assert any(gap.code == "uncited_model_finding" for gap in reduced.gaps)


def test_model_finding_accepts_shop_and_string_entity_aliases() -> None:
    pack = FoodAdaptivePack()
    adaptation = pack.adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(_comment("comment-1", "positive"),),
            completeness="complete",
            expected_count=1,
        )
    )

    reduced = pack.merge_model_findings(
        adaptation,
        findings=(
            {"shop": "店铺甲", "claim": "值得专程去", "evidence_refs": ["ref:a"]},
            {"entity": "店铺乙", "claim": "需要核实", "evidence_refs": ["ref:b"]},
            {
                "shop": {"name": "店铺丙"},
                "claim": "环境安静",
                "evidence_refs": ["ref:c"],
            },
        ),
    )

    assert {item["name"] for item in reduced.entities if item.get("candidate")} >= {
        "店铺甲",
        "店铺乙",
        "店铺丙",
    }


def test_explicit_claims_and_controversies_keep_provider_and_comment_references() -> None:
    item = _comment("comment-1", "negative", text="有人说不值，避雷")
    item["claims"] = [{"claim_id": "claim-explicit", "type": "complaint", "text": "不值"}]
    item["unresolved_controversies"] = [
        {"kind": "price_disagreement", "entity": "老店", "description": "价格是否合理"}
    ]
    result = FoodAdaptivePack().adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(item,),
            provider_payload_ref="payload://page-1",
            completeness="complete",
            expected_count=1,
        )
    )

    assert result.claims[0].claim_id == "claim-explicit"
    assert result.controversies[0]["status"] == "unresolved"
    assert "xhs:note:note-1:comment:comment-1" in result.controversies[0]["evidence_refs"]
    assert "payload://page-1" in result.controversies[0]["provider_payload_refs"]


def test_mixed_sentiment_and_candidate_entity_emit_dynamic_capability_actions() -> None:
    pack = FoodAdaptivePack()
    result = pack.adapt_observation(
        [
            ObservationEnvelope(
                source="xhs",
                operation="comments.search",
                items=(_comment("positive", "positive"), _comment("negative", "negative")),
                completeness="complete",
                expected_count=2,
            )
        ]
    )

    actions = pack.next_actions(result, run_id="run-1")
    capabilities = {action.capability for action in actions}
    assert "comments.search" in capabilities
    assert "places.search" in capabilities
    assert "places.detail" not in capabilities
    assert all(action.action_id.startswith("run-1:food:") for action in actions)
    controversy_action = next(action for action in actions if action.capability == "comments.search")
    assert controversy_action.metadata["trigger"] == "unresolved_controversy"
    assert set(controversy_action.arguments) == {
        "note_id",
        "max_comments",
        "include_replies",
    }
    assert controversy_action.arguments["note_id"] in {"note-1"}
    assert controversy_action.arguments["max_comments"] <= 100
    assert controversy_action.arguments["include_replies"] is True
    assert controversy_action.metadata["context"]["depth"] == "targeted"
    assert controversy_action.metadata["context"]["query"] == "老店 真实评价 争议 避雷"
    lookup_action = next(action for action in actions if action.capability == "places.search")
    assert lookup_action.source == "dianping"
    assert lookup_action.metadata["trigger"] == "candidate_entity_lookup"
    assert lookup_action.arguments["keyword"] == "老店"
    assert set(lookup_action.arguments) == {"keyword"}
    assert set(lookup_action.evidence_refs) == {
        "xhs:note:note-1:comment:positive",
        "xhs:note:note-1:comment:negative",
    }


def test_unresolved_controversy_without_note_id_uses_schema_valid_note_search() -> None:
    item = {
        "id": "comment-without-note",
        "content": "需要核实",
        "sentiment": "negative",
        "mentioned_shops": ["老店"],
        "unresolved_controversies": [
            {"entity": "老店", "description": "价格是否合理"}
        ],
    }
    result = FoodAdaptivePack().adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(item,),
            completeness="complete",
            expected_count=1,
        )
    )

    actions = FoodAdaptivePack().next_actions(result)
    note_search = next(action for action in actions if action.capability == "notes.search")
    assert not any(action.capability == "comments.search" for action in actions)
    assert set(note_search.arguments) == {
        "query",
        "count",
        "sort_type",
        "include_details",
        "include_comments",
        "max_comments",
    }
    assert note_search.arguments["query"] == "老店 真实评价 争议 避雷"
    assert note_search.arguments["count"] == 3
    assert note_search.arguments["sort_type"] == "most_comments"
    assert note_search.arguments["include_details"] is True
    assert note_search.arguments["include_comments"] is True
    assert note_search.arguments["max_comments"] <= 60
    assert note_search.metadata["context"]["entity_id"] == "shop:老店"


def test_provider_id_candidate_emits_detail_with_provider_identity() -> None:
    pack = FoodAdaptivePack()
    adaptation = pack.adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(_comment("comment-1", "positive"),),
            completeness="complete",
            expected_count=1,
        )
    )
    reduced = pack.merge_model_findings(
        adaptation,
        findings=(
            {
                "shop": {"name": "老店", "shop_id": "dp-1"},
                "claim": "评论支持毛肚",
                "evidence_refs": ["xhs:note:note-1:comment:comment-1"],
            },
        ),
    )

    actions = pack.next_actions(reduced)
    detail = next(action for action in actions if action.capability == "places.detail")
    assert not any(action.capability == "places.search" for action in actions)
    assert detail.arguments["shop_id"] == "dp-1"
    assert set(detail.arguments) == {"shop_id"}
    assert "xhs:note:note-1:comment:comment-1" in detail.evidence_refs


def test_secondary_profile_enriches_the_comment_candidate_without_repeating_profile_action() -> None:
    pack = FoodAdaptivePack()
    result = pack.adapt_observation(
        [
            ObservationEnvelope(
                source="xhs",
                operation="comments.search",
                items=(_comment("comment-1", "positive"),),
                completeness="complete",
                expected_count=1,
            ),
            ObservationEnvelope(
                source="dianping",
                operation="places.detail",
                items=({"id": "dp-1", "name": "老店", "address": "成都"},),
                raw_payload={"shop": "dp-1"},
                provider_payload_ref="payload://shop-1",
                completeness="complete",
            ),
        ]
    )

    shop = next(entity for entity in result.entities if entity["entity_id"] == "shop:老店")
    assert shop["status"] == "enriched"
    assert result.profiles[0]["provider_id"] == "dp-1"
    assert result.profiles[0]["stage"] == "detail"
    assert result.profiles[0]["profile_stage"] == "detail"
    assert result.profiles[0]["address"] == "成都"
    assert pack.next_actions(result) == ()


def test_partial_observation_creates_retryable_gap_and_deep_fetch_action() -> None:
    pack = FoodAdaptivePack()
    result = pack.adapt_observation(
        ObservationEnvelope(
            source="xhs",
            operation="comments.search",
            items=(_comment("comment-1", "positive"),),
            next_cursor="cursor-2",
            has_more=True,
            completeness="partial",
            expected_count=5,
        )
    )

    assert result.coverage.dimensions["comments"] == 0.2
    assert any(gap.code == "partial_observation" and gap.retryable for gap in result.gaps)
    actions = pack.next_actions(result)
    assert any(
        action.capability == "comments.search" and action.metadata["trigger"] == "retryable_gap"
        for action in actions
    )
    retry = next(action for action in actions if action.metadata["trigger"] == "retryable_gap")
    assert set(retry.arguments) == {"note_id", "max_comments", "include_replies"}
    assert retry.arguments["note_id"] == "note-1"
    assert retry.metadata["context"]["next_cursor"] == "cursor-2"
    assert pack.evaluate_stop(result).stop is False


def test_missing_provider_cursor_is_not_fabricated_or_retried() -> None:
    observation = ObservationEnvelope(
        source="dianping",
        operation="places.search",
        data={"items": [{"name": "老店"}], "has_more": True},
    )

    assert observation.next_cursor is None
    assert observation.has_more is False
    assert observation.continuation["has_more_without_cursor"] is True
    result = FoodAdaptivePack().adapt_observation(observation)
    assert any(gap.code == "continuation_missing_cursor" and not gap.retryable for gap in result.gaps)


def test_dianping_search_is_identity_stage_and_does_not_block_detail_for_same_name_candidate() -> None:
    pack = FoodAdaptivePack()
    search = ObservationEnvelope(
        source="dianping",
        operation="places.search",
        items=({"id": "dp-1", "name": "老店", "rating": 4.5},),
        completeness="complete",
    )

    search_result = pack.adapt_observation(search)
    assert search_result.profiles == ()
    identified = search_result.entities[0]
    assert identified["status"] == "identified"
    assert identified["candidate"] is False
    assert identified["provider_id"] == "dp-1"

    candidate = ObservationEnvelope(
        source="xhs",
        operation="comments.search",
        items=(_comment("comment-1", "positive"),),
        completeness="complete",
        expected_count=1,
    )
    combined = pack.adapt_observation((candidate, search))
    entity = next(item for item in combined.entities if item["entity_id"] == "shop:老店")
    assert entity["status"] == "candidate"
    detail = next(action for action in pack.next_actions(combined) if action.capability == "places.detail")
    assert detail.arguments == {"shop_id": "dp-1"}
    assert detail.entity_id == "shop:老店"


def test_dianping_search_retry_carries_next_page_without_repeating_page_one() -> None:
    result = FoodAdaptivePack().adapt_observation(
        ObservationEnvelope(
            source="dianping",
            operation="places.search",
            data={
                "items": [{"id": "dp-1", "name": "老店"}],
                "pagination": {"has_next": True, "next_page": 2},
            },
            metadata={"action": {"arguments": {"keyword": "老店"}}},
        )
    )

    retry = next(
        action
        for action in FoodAdaptivePack().next_actions(result)
        if action.capability == "places.search"
        and action.metadata.get("trigger") == "retryable_gap"
    )
    assert retry.arguments == {"keyword": "老店", "page": 2}


def test_existing_source_envelope_is_an_accepted_observation_input() -> None:
    source = SourceEnvelope(
        source="xhs",
        operation="comments.search",
        normalized_items=(_comment("comment-1", "positive"),),
        raw_payload={"raw": "kept"},
        provenance={"provider_payload_ref": "payload://source-envelope"},
    )

    result = FoodAdaptivePack().adapt_observation(source)

    assert result.observations[0].source == "xhs"
    assert result.raw_provider_payloads == ({"raw": "kept"},)
    assert "payload://source-envelope" in result.provider_payload_refs


def test_to_dict_preserves_complete_observation_metadata_and_raw_payload() -> None:
    observation = ObservationEnvelope(
        observation_id="observation-1",
        investigation_id="run-1",
        source="xhs",
        operation="comments.search",
        items=(_comment("comment-1", "positive"),),
        cursor="cursor-1",
        next_cursor="cursor-2",
        has_more=True,
        completeness="partial",
        provider_payload_ref="payload://page-1",
        metadata={"query": "成都 毛肚", "entity_id": "shop:老店"},
        provenance={"account": "xhs-account", "request_id": "request-1"},
        raw_payload={"opaque": {"provider_field": "kept"}},
    )

    payload = FoodAdaptivePack().adapt_observation(observation).to_dict()
    serialized = payload["observations"][0]

    assert serialized["observation_id"] == "observation-1"
    assert serialized["cursor"] == "cursor-1"
    assert serialized["next_cursor"] == "cursor-2"
    assert serialized["metadata"]["entity_id"] == "shop:老店"
    assert serialized["provenance"]["request_id"] == "request-1"
    assert serialized["raw_payload"] == {"opaque": {"provider_field": "kept"}}


def test_profile_merge_does_not_erase_non_empty_fields_with_empty_refresh_values() -> None:
    profile = FoodAdaptivePack().adapt_observation(
        [
            ObservationEnvelope(
                source="dianping",
                operation="places.detail",
                items=({"id": "dp-1", "name": "老店", "address": "成都", "images": ["a.jpg"]},),
                completeness="complete",
            ),
            ObservationEnvelope(
                source="dianping",
                operation="places.detail",
                items=({"id": "dp-1", "name": "老店", "address": "", "images": []},),
                completeness="complete",
            ),
        ]
    ).profiles[0]

    assert profile["address"] == "成都"
    assert profile["images"] == ["a.jpg"]


def test_xhs_note_search_embedded_comments_are_reduced_without_note_cards_as_comments() -> None:
    comment = _comment("embedded-comment", "positive")
    raw_mcp = {
        "content": [
            {
                "type": "json",
                "json": {
                    "status": "success",
                    "search_items": [{"id": "note-card-1", "model_type": "note"}],
                    "notes": [
                        {"note_id": "note-without-comments", "comments": {"items": []}},
                        {
                            "note_id": "note-1",
                            "comments": {
                                "items": [comment],
                                "has_more": True,
                                "next_cursor": "comment-cursor-2",
                            },
                        }
                    ],
                },
            }
        ],
        "isError": False,
    }

    observation = ObservationEnvelope(
        source="xhs",
        operation="notes.search",
        data=raw_mcp,
    )
    result = FoodAdaptivePack().adapt_observation(observation)

    assert observation.items[0]["id"] == "note-card-1"
    assert [item["id"] for item in result.comments] == ["embedded-comment"]
    assert observation.raw_payload == raw_mcp
    assert observation.next_cursor == "comment-cursor-2"
    assert observation.has_more is True
    assert observation.completeness == "partial"


def test_dianping_review_search_uses_shop_profile_and_keeps_review_items_as_auxiliary_payload() -> None:
    provider = {
        "shop": {"shop_id": "dp-1", "name": "老店", "type": "restaurant"},
        "items": [{"review_id": "review-1", "content": "值得"}],
        "pagination": {"start_index": 0, "next_start_index": 5, "has_next": True},
        "completeness": {
            "status": "partial",
            "complete": False,
            "continuation": {"next_offset": 5},
        },
    }
    raw_mcp = {"content": [{"type": "json", "json": provider}], "isError": False}

    observation = ObservationEnvelope(
        source="dianping",
        operation="reviews.search",
        data=raw_mcp,
    )
    result = FoodAdaptivePack().adapt_observation(observation)

    assert len(observation.items) == 1
    assert result.profiles[0]["provider_id"] == "dp-1"
    assert result.profiles[0]["stage"] == "reviews"
    assert result.profiles[0]["profile_stage"] == "reviews"
    assert result.profiles[0]["review_completeness"]["status"] == "partial"
    assert result.profiles[0]["source_payload"]["review_items"][0]["review_id"] == "review-1"
    assert observation.next_cursor == "5"
    assert observation.completeness == "partial"

    follow_ups = FoodAdaptivePack().next_actions(result)
    review_retry = next(
        action
        for action in follow_ups
        if action.capability == "reviews.search"
        and action.metadata.get("trigger") == "retryable_gap"
    )
    assert review_retry.arguments["shop_id"] == "dp-1"
    assert review_retry.arguments["offset"] == 5
    assert review_retry.arguments["sort"] == "default"
    assert review_retry.arguments["review_filter"] == "all"
