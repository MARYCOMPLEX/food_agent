"""Executable contracts for the comment-first research architecture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from xhs_food.contracts import (
    CommentEvidence,
    ResearchOutcome,
    ShopProfile,
    SourceCall,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research.evidence import CanonicalCommentEvidenceAdapter, EvidenceLedger
from xhs_food.research.profile_service import (
    ShopProfileRefreshPolicy,
    ShopProfileService,
)
from xhs_food.research.repository import (
    merge_profiles,
    profile_from_storage,
    profile_to_storage,
)
from xhs_food.research.sources import (
    AdaptiveQueryPlanner,
    DianpingShopEnricher,
    XhsCommentLeadCollector,
    _dedupe_comments,
    _normalise_comments,
)


def _comment(identifier: str, text: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "content": text,
        "like_count": 12,
        "sub_comment_count": 1,
        "user_info": {"user_id": f"user-{identifier}", "nickname": "本地食客"},
    }


class _FakeXhsSource:
    def __init__(self, *, unsupported_cursor: bool = False) -> None:
        self.unsupported_cursor = unsupported_cursor
        self.comment_arguments: list[dict[str, Any]] = []

    async def search_notes(self, **_: Any) -> SourceCall:
        first = _comment("c1", "这家老店的锅底很稳")
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={
                "notes": [
                    {
                        "note_id": "note-1",
                        "url": "https://www.xiaohongshu.com/explore/note-1",
                        "search_item": {
                            "note_card": {
                                "display_title": "本地人火锅",
                                "interact_info": {"comment_count": 2},
                            }
                        },
                        "comments": {
                            "items": [first],
                            "has_more": True,
                            "next_cursor": "cursor-1",
                            "pages": [{"items": [first]}],
                        },
                    }
                ]
            },
            raw_payload={"transport": "search-envelope", "opaque": {"keep": True}},
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.detail",
            success=True,
            data={"data": {"items": []}, "note_id": note_id},
            raw_payload={"transport": "detail-envelope"},
        )

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall:
        self.comment_arguments.append({"note_id": note_id, **arguments})
        second = _comment("c2", "但有人说周末服务很慢，建议错峰")
        metadata = {"dropped_arguments": ["cursor"]} if self.unsupported_cursor else {}
        return SourceCall(
            source="xhs",
            operation="comments.search",
            success=True,
            data={"items": [second], "has_more": False},
            metadata=metadata,
            raw_payload={"transport": "comments-envelope", "cursor": arguments.get("cursor")},
        )


@pytest.mark.asyncio
async def test_xhs_collector_keeps_embedded_and_cursor_pages_losslessly() -> None:
    source = _FakeXhsSource()
    collector = XhsCommentLeadCollector(
        source,
        planner=AdaptiveQueryPlanner(max_queries=1),
        max_notes=2,
        comment_page_size=10,
    )

    result = await collector.collect(FoodSearchIntent(location="成都", food_type="火锅"))

    assert len(result.notes) == 1
    note = result.notes[0]
    assert {item.comment_id for item in note.comments} == {"c1", "c2"}
    assert note.comment_completeness == "complete"
    assert note.comment_pages == 2
    assert note.raw_payload["search_envelopes"][0]["opaque"]["keep"] is True
    assert source.comment_arguments[0]["cursor"] == "cursor-1"


@pytest.mark.asyncio
async def test_xhs_collector_retains_successful_page_when_cursor_is_not_supported() -> None:
    source = _FakeXhsSource(unsupported_cursor=True)
    collector = XhsCommentLeadCollector(
        source,
        planner=AdaptiveQueryPlanner(max_queries=1),
        max_notes=1,
    )

    note = (await collector.collect(FoodSearchIntent(location="成都"))).notes[0]

    assert {item.comment_id for item in note.comments} == {"c1", "c2"}
    assert note.outcome is ResearchOutcome.PARTIAL
    assert note.comment_completeness == "partial"
    assert any(gap.code == "pagination_argument_unsupported" for gap in note.gaps)


class _CompleteEmbeddedXhsSource(_FakeXhsSource):
    async def search_notes(self, **_: Any) -> SourceCall:
        embedded = _comment("embedded", "搜索结果已经带回完整评论")
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={
                "notes": [
                    {
                        "note_id": "note-complete",
                        "title": "完整嵌入评论",
                        "comments": {
                            "items": [embedded],
                            "total": 1,
                            "has_more": False,
                        },
                    }
                ]
            },
            raw_payload={"transport": "embedded-search", "keep": True},
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.detail",
            success=True,
            data={"note_id": note_id, "comments": {"items": []}},
            raw_payload={"transport": "embedded-detail"},
        )


@pytest.mark.asyncio
async def test_xhs_skips_comments_search_when_embedded_comments_are_complete() -> None:
    source = _CompleteEmbeddedXhsSource()
    result = await XhsCommentLeadCollector(
        source,
        planner=AdaptiveQueryPlanner(max_queries=1),
        max_notes=1,
    ).collect(FoodSearchIntent(location="成都"))

    note = result.notes[0]
    assert [item.comment_id for item in note.comments] == ["embedded"]
    assert source.comment_arguments == []
    assert note.raw_payload["search_envelopes"][0]["keep"] is True
    assert note.raw_payload["embedded_comments"][0]["id"] == "embedded"


class _MalformedXhsSource(_FakeXhsSource):
    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.detail",
            success=True,
            data={"unexpected": "detail"},
            raw_payload={"detail_raw": {"opaque": True}},
        )

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall:
        self.comment_arguments.append({"note_id": note_id, **arguments})
        return SourceCall(
            source="xhs",
            operation="comments.search",
            success=True,
            data={"unexpected": "comments"},
            raw_payload={"comments_raw": {"opaque": True}},
        )


@pytest.mark.asyncio
async def test_xhs_malformed_successful_evidence_keeps_raw_and_is_partial() -> None:
    result = await XhsCommentLeadCollector(
        _MalformedXhsSource(),
        planner=AdaptiveQueryPlanner(max_queries=1),
        max_notes=1,
    ).collect(FoodSearchIntent(location="成都"))

    note = result.notes[0]
    assert note.outcome is ResearchOutcome.PARTIAL
    assert note.comment_completeness == "partial"
    assert [gap.code for gap in note.gaps].count("unsupported_response_shape") == 2
    assert note.raw_payload["detail"] == {"detail_raw": {"opaque": True}}
    assert note.raw_payload["comments"] == [{"comments_raw": {"opaque": True}}]


def test_xhs_comment_dedupe_uses_text_fingerprint_and_keeps_richer_occurrence() -> None:
    first = _normalise_comments(
        "note-1",
        [{"content": "同一 条评论", "like_count": 1}],
        operation="comments.search",
        page_cursor="cursor-1",
    )[0]
    second = _normalise_comments(
        "note-1",
        [
            {
                "content": " 同一  条评论 ",
                "like_count": 99,
                "user_info": {"nickname": "更丰富的用户"},
                "images": [{"url": "https://img.example/comment.jpg"}],
            }
        ],
        operation="comments.search",
        page_cursor="cursor-2",
    )[0]

    assert first.comment_id == second.comment_id
    merged = _dedupe_comments((first, second))
    assert len(merged) == 1
    assert merged[0].likes == 99
    assert merged[0].author == {"nickname": "更丰富的用户"}
    assert len(merged[0].provenance["occurrences"]) == 2
    assert len(merged[0].raw_payload["_duplicate_payloads"]) == 2


class _UnmarkedEmbeddedXhsSource(_CompleteEmbeddedXhsSource):
    async def search_notes(self, **_: Any) -> SourceCall:
        embedded = _comment("embedded", "搜索结果带回评论但没有完成标记")
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={
                "notes": [
                    {
                        "note_id": "note-unmarked",
                        "comments": {"items": [embedded], "total": 1},
                    }
                ]
            },
            raw_payload={"transport": "unmarked-embedded"},
        )


@pytest.mark.asyncio
async def test_xhs_unmarked_embedded_comments_do_not_skip_comment_search() -> None:
    source = _UnmarkedEmbeddedXhsSource()
    await XhsCommentLeadCollector(
        source,
        planner=AdaptiveQueryPlanner(max_queries=1),
        max_notes=1,
    ).collect(FoodSearchIntent(location="成都"))

    assert source.comment_arguments


class _FakeDianpingSource:
    def __init__(self, *, fail_second_review_page: bool = False) -> None:
        self.fail_second_review_page = fail_second_review_page
        self.review_offsets: list[int] = []
        self.detail_calls: list[str] = []

    async def search_places(self, **_: Any) -> SourceCall:
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data={
                "items": [
                    {
                        "shop_id": "dp-1",
                        "name": "老成都火锅",
                        "rating": 4.6,
                        "custom_provider_field": {"preserve": "yes"},
                    }
                ]
            },
            raw_payload={"transport": "places-search"},
        )

    async def place_detail(self, shop_id: str, **_: Any) -> SourceCall:
        self.detail_calls.append(shop_id)
        return SourceCall(
            source="dianping",
            operation="places.detail",
            success=True,
            data={
                "shop": {
                    "address": "成都市青羊区老街 1 号",
                    "city": "成都",
                    "photos": [{"url": "https://img.example/detail.jpg", "width": 800}],
                    "promotions": [{"title": "双人套餐", "price": 88}],
                    "recommended_dishes": ["毛肚"],
                    "latitude": 30.67,
                    "longitude": 104.06,
                }
            },
            raw_payload={"transport": "places-detail"},
        )

    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall:
        assert shop_id == "dp-1"
        offset = int(arguments.get("offset", 0))
        self.review_offsets.append(offset)
        if self.fail_second_review_page and offset > 0:
            return SourceCall(
                source="dianping",
                operation="reviews.search",
                success=False,
                error_code="provider_timeout",
                error_message="review page timed out",
                retryable=True,
                raw_payload={"transport": "reviews-timeout", "offset": offset},
            )
        item_id = "review-1" if offset == 0 else "review-2"
        item = {
            "review_id": item_id,
            "content": "毛肚很脆",
            "recommended_dishes": ["毛肚"],
            "images": [{"url": f"https://img.example/{item_id}.jpg"}],
            "promotions": [{"title": "点评券", "price": 9.9}],
        }
        data: dict[str, Any] = {"record_count": 2, "items": [item]}
        if offset > 0:
            data["completeness"] = {"corpus": {"status": "complete"}}
        return SourceCall(
            source="dianping",
            operation="reviews.search",
            success=True,
            data=data,
            raw_payload={"transport": "reviews-page", "offset": offset},
        )


class _PagedPlacesSource(_FakeDianpingSource):
    def __init__(self, *, fail_second_page: bool = False) -> None:
        super().__init__()
        self.fail_second_page = fail_second_page
        self.place_pages: list[int] = []

    async def search_places(self, **arguments: Any) -> SourceCall:
        page = int(arguments.get("page", 1))
        self.place_pages.append(page)
        if page == 2 and self.fail_second_page:
            return SourceCall(
                source="dianping",
                operation="places.search",
                success=False,
                error_code="provider_timeout",
                error_message="place page timed out",
                retryable=True,
                raw_payload={"transport": "places-timeout", "page": page},
            )
        if page == 1:
            item = {"shop_id": "dp-other", "name": "另一家", "address": "地址"}
        else:
            item = {
                "shop_id": "dp-target",
                "name": "目标店",
                "address": "地址",
                "location": "30,104",
                "recommended_dishes": ["招牌菜"],
                "images": ["https://img.example/target.jpg"],
            }
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data={
                "items": [item],
                "pagination": {"page": page, "has_next": page == 1, "next_page": 2}
                if page == 1
                else {"page": page, "has_next": False},
            },
            raw_payload={"transport": "places-page", "page": page},
        )


@pytest.mark.asyncio
async def test_dianping_places_search_follows_pages_and_keeps_every_raw_page() -> None:
    source = _PagedPlacesSource()
    result = await DianpingShopEnricher(source, max_profiles=1).enrich(
        ["目标店"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert source.place_pages == [1, 2]
    assert profile.provider_refs == {"dianping": "dp-target"}
    assert [page["page"] for page in profile.source_payload["search_raw"]] == [1, 2]
    assert profile.source_payload["search"]["pagination"]["pages_collected"] == 2


@pytest.mark.asyncio
async def test_dianping_places_later_page_failure_is_partial_and_auditable() -> None:
    source = _PagedPlacesSource(fail_second_page=True)
    result = await DianpingShopEnricher(source, max_profiles=1).enrich(
        ["目标店"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert source.place_pages == [1, 2]
    assert profile.outcome is ResearchOutcome.PARTIAL
    assert profile.source_payload[-1]["transport"] == "places-timeout"
    assert any(gap.code == "provider_timeout" for gap in profile.gaps)


class _AliasProfileSource:
    async def search_places(self, **_: Any) -> SourceCall:
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data={
                "items": [
                    {
                        "name": "无 id 档案",
                        "address": "成都东门 1 号",
                        "location": "30.67,104.06",
                        "imageList": [{"url": "https://img.example/alias.jpg"}],
                        "recommendedDishes": ["招牌菜"],
                        "promotionList": [{"title": "双人套餐"}],
                        "businessHours": "10:00-22:00",
                    }
                ],
                "pagination": {"has_next": False},
            },
            raw_payload={"transport": "alias-profile"},
        )

    async def place_detail(self, *_: Any, **__: Any) -> SourceCall:
        raise AssertionError("a complete no-id search profile should not require detail")

    async def search_reviews(self, *_: Any, **__: Any) -> SourceCall:
        raise AssertionError("a no-id profile has no review lookup identity")


@pytest.mark.asyncio
async def test_dianping_profile_maps_alias_fields_and_keeps_valid_no_id_profile() -> None:
    result = await DianpingShopEnricher(_AliasProfileSource(), max_profiles=1).enrich(
        ["无 id 档案"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert profile.provider_refs == {}
    assert profile.images[0]["url"] == "https://img.example/alias.jpg"
    assert profile.recommended_dishes == ("招牌菜",)
    assert profile.promotions[0]["title"] == "双人套餐"
    assert profile.opening_hours == "10:00-22:00"
    assert profile.outcome is ResearchOutcome.COMPLETE
    assert profile.source_payload["search"]["items"][0]["imageList"]


class _BranchOnlyPlacesSource:
    async def search_places(self, **_: Any) -> SourceCall:
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data={
                "items": [
                    {"shop_id": "dp-west", "name": "老店西门店"},
                    {"shop_id": "dp-east", "name": "老店东门店"},
                ]
            },
            raw_payload={"transport": "branch-only"},
        )

    async def place_detail(self, *_: Any, **__: Any) -> SourceCall:
        raise AssertionError("ambiguous branch names must not trigger detail")

    async def search_reviews(self, *_: Any, **__: Any) -> SourceCall:
        raise AssertionError("ambiguous branch names must not trigger reviews")


@pytest.mark.asyncio
async def test_dianping_place_matching_does_not_choose_a_branch_by_substring() -> None:
    result = await DianpingShopEnricher(_BranchOnlyPlacesSource(), max_profiles=1).enrich(
        ["老店"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert profile.provider_refs == {}
    assert any(gap.code == "shop_not_found" for gap in profile.gaps)
    assert profile.source_payload[0]["transport"] == "branch-only"


class _NestedReviewSource(_FakeDianpingSource):
    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall:
        assert shop_id == "dp-1"
        offset = int(arguments.get("offset", 0))
        self.review_offsets.append(offset)
        review = {
            "review_id": f"nested-review-{offset}",
            "recommendedDishes": ["嵌套菜"],
            "imageList": [{"url": f"https://img.example/nested-{offset}.jpg"}],
            "promotionList": [{"title": "嵌套券"}],
        }
        return SourceCall(
            source="dianping",
            operation="reviews.search",
            success=True,
            data={
                "response": {
                    "data": {
                        "items": [review],
                        "raw_responses": [
                            {"module": "reviewlist", "offset": offset}
                        ],
                        "pagination": {
                            "hasNext": offset == 0,
                            "nextOffset": 1,
                        },
                    }
                }
            },
            raw_payload={"transport": "nested-review", "offset": offset},
        )


@pytest.mark.asyncio
async def test_dianping_nested_review_pages_map_fields_and_keep_raw_pages() -> None:
    source = _NestedReviewSource()
    result = await DianpingShopEnricher(source, max_profiles=1, review_limit=10).enrich(
        ["老成都火锅"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert source.review_offsets == [0, 1]
    assert len(profile.source_payload["reviews_raw"]) == 2
    assert profile.source_payload["reviews_raw"][1]["offset"] == 1
    assert profile.review_completeness["complete"] is True
    assert "嵌套菜" in profile.recommended_dishes
    assert any(item["url"].endswith("nested-1.jpg") for item in profile.images)
    assert any(item["title"] == "嵌套券" for item in profile.promotions)
    assert profile.source_payload["reviews"]["raw_responses"] == [
        {"module": "reviewlist", "offset": 0},
        {"module": "reviewlist", "offset": 1},
    ]


class _MalformedReviewSource(_FakeDianpingSource):
    async def search_reviews(self, shop_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="dianping",
            operation="reviews.search",
            success=True,
            data={
                "items": [
                    {
                        "review_id": "review-good",
                        "content": "保留的有效行",
                        "raw": [],
                    },
                    None,
                    "malformed-row",
                ],
            },
            raw_payload={"transport": "reviews-malformed", "rows": [None, "malformed-row"]},
        )


@pytest.mark.asyncio
async def test_dianping_malformed_review_rows_keep_raw_and_emit_typed_gaps() -> None:
    result = await DianpingShopEnricher(_MalformedReviewSource(), max_profiles=1).enrich(
        ["老成都火锅"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    codes = {gap.code for gap in profile.gaps}
    assert "malformed_review_row" in codes
    assert "review_field_mapping_invalid" in codes
    assert profile.source_payload["reviews_raw"][0]["transport"] == "reviews-malformed"
    assert profile.source_payload["reviews_raw"][0]["rows"] == [None, "malformed-row"]


@pytest.mark.asyncio
async def test_dianping_enricher_merges_detail_review_media_and_unknown_fields() -> None:
    source = _FakeDianpingSource()
    enricher = DianpingShopEnricher(source, max_profiles=1, review_limit=10)

    result = await enricher.enrich(["老成都火锅"], FoodSearchIntent(location="成都"))

    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert profile.provider_refs == {"dianping": "dp-1"}
    assert profile.address == "成都市青羊区老街 1 号"
    assert profile.latitude == 30.67
    assert "毛肚" in profile.recommended_dishes
    assert any(isinstance(value, dict) and value.get("width") == 800 for value in profile.images)
    assert any(isinstance(value, dict) and value.get("title") == "双人套餐" for value in profile.promotions)
    assert profile.attributes["custom_provider_field"]["preserve"] == "yes"
    assert profile.source_payload["detail_raw"]["transport"] == "places-detail"
    assert profile.source_payload["reviews_raw"][0]["transport"] == "reviews-page"
    assert source.detail_calls == ["dp-1"]
    assert source.review_offsets == [0, 1]


@pytest.mark.asyncio
async def test_dianping_later_review_failure_is_partial_and_auditable() -> None:
    source = _FakeDianpingSource(fail_second_review_page=True)
    result = await DianpingShopEnricher(source, max_profiles=1, review_limit=10).enrich(
        ["老成都火锅"], FoodSearchIntent(location="成都")
    )

    profile = result.profiles[0]
    assert profile.outcome is ResearchOutcome.PARTIAL
    assert any(gap.code == "provider_timeout" for gap in profile.gaps)
    assert profile.source_payload["reviews_raw"][-1]["transport"] == "reviews-timeout"


@pytest.mark.asyncio
async def test_evidence_ledger_is_idempotent_and_canonical_projection_hides_identity() -> None:
    note = XhsNoteLead(
        note_id="note-1",
        title="成都老店",
        comments=(
            CommentEvidence(
                note_id="note-1",
                comment_id="comment-1",
                text="本地人说毛肚值得点",
                author={"user_id": "private-user", "nickname": "食客"},
                raw_payload={"provider": {"user_id": "private-user"}},
            ),
        ),
    )
    lifecycle = CanonicalCommentEvidenceAdapter()
    ledger = EvidenceLedger(lifecycle=lifecycle)

    first = await ledger.record(note)
    second = await ledger.record(note)

    assert first == second == ("xhs:note:note-1:comment:comment-1",)
    assert len(ledger.records) == 1
    assert len(lifecycle.batches) == 1
    assert lifecycle.batches[0].comments[0].attributes == {"likes": 0, "replies": 0}
    assert ledger.get(first[0]).raw_payload["provider"]["user_id"] == "private-user"


def test_shop_profile_merge_and_storage_identity_are_non_destructive() -> None:
    current = ShopProfile(
        provider_refs={"dianping": "dp-1"},
        name="老成都火锅",
        phone="028-111",
        address="老地址",
        images=("https://img.example/old.jpg",),
    )
    incoming = ShopProfile(
        provider_refs={"dianping": "dp-1"},
        name="老成都火锅",
        phone="028-222",
        images=({"url": "https://img.example/new.jpg"},),
    )

    merged = merge_profiles(current, incoming)
    first_storage = profile_to_storage(current)
    second_storage = profile_to_storage(merged)

    assert merged.address == "老地址"
    assert merged.phone == "028-222"
    assert len(merged.images) == 2
    assert first_storage["id"] == second_storage["id"]


def test_shop_profile_merge_keeps_legacy_fields_and_normalizes_provider_refs() -> None:
    current = ShopProfile(
        provider_refs={"Dianping": " dp-1 "},
        name="老店",
        attributes={
            "legacy_restaurant": {
                "must_try": "malformed-json",
                "pros": ["老字号"],
                "stats": {"likes": 3},
            }
        },
    )
    incoming = ShopProfile(
        provider_refs={"dianping": "  "},
        name="老店",
        attributes={"legacy_restaurant": {"pros": [], "stats": {}}},
    )

    merged = merge_profiles(current, incoming)
    assert merged.provider_refs == {"dianping": "dp-1"}
    assert merged.attributes["legacy_restaurant"] == {
        "must_try": "malformed-json",
        "pros": ["老字号"],
        "stats": {"likes": 3},
    }
    assert profile_to_storage(merged)["must_try"] == "malformed-json"


@pytest.mark.asyncio
async def test_shop_profile_service_reuses_fresh_profile_without_dianping_call() -> None:
    from xhs_food.research.repository import InMemoryShopProfileRepository

    now = datetime(2026, 9, 4, tzinfo=UTC)
    repository = InMemoryShopProfileRepository()
    await repository.upsert(
        ShopProfile(
            provider_refs={"dianping": "dp-fresh"},
            name="老成都火锅",
            address="老地址",
            fetched_at=now - timedelta(hours=2),
        )
    )

    service = ShopProfileService(
        repository,
        policy=ShopProfileRefreshPolicy(refresh_after=timedelta(days=7)),
        clock=lambda: now,
    )
    plan = await service.plan(["老成都火锅"])

    assert plan.refresh_candidates == ()
    assert plan.fresh_cache_hits == ("老成都火锅",)
    synced = await service.commit(plan, ())
    assert synced.profiles[0].address == "老地址"


@pytest.mark.asyncio
async def test_shop_profile_service_refreshes_stale_profile_and_keeps_it_on_failure() -> None:
    from xhs_food.research.repository import InMemoryShopProfileRepository

    now = datetime(2026, 9, 4, tzinfo=UTC)
    repository = InMemoryShopProfileRepository()
    old = ShopProfile(
        provider_refs={"dianping": "dp-stale"},
        name="老成都火锅",
        address="旧地址",
        fetched_at=now - timedelta(days=8),
    )
    await repository.upsert(old)
    service = ShopProfileService(repository, clock=lambda: now)
    plan = await service.plan(["老成都火锅"])

    assert plan.refresh_candidates == ("老成都火锅",)
    # A provider failure yields no replacement, but the durable old profile is
    # still available for the response rather than being erased.
    synced = await service.commit(plan, ())
    assert synced.profiles[0].address == "旧地址"


@pytest.mark.asyncio
async def test_shop_profile_commit_uses_provider_id_before_name_and_keeps_unidentified_profile() -> None:
    from xhs_food.research.repository import InMemoryShopProfileRepository

    repository = InMemoryShopProfileRepository()
    old = ShopProfile(
        provider_refs={"dianping": "dp-old"},
        name="同名店",
        address="旧地址",
    )
    await repository.upsert(old)
    service = ShopProfileService(repository)

    plan = await service.plan(["同名店", "无 id 店"])
    refreshed = (
        ShopProfile(provider_refs={"dianping": "dp-new"}, name="同名店", address="新地址"),
        ShopProfile(name="无 id 店", address="有效但无 provider id"),
    )
    synced = await service.commit(plan, refreshed)

    assert {profile.provider_refs.get("dianping") for profile in synced.profiles} == {
        "dp-old",
        "dp-new",
        None,
    }
    assert len(repository.profiles) == 3
    assert any(profile.name == "无 id 店" for profile in repository.profiles)


@pytest.mark.asyncio
async def test_shop_profile_name_fallback_does_not_merge_branch_by_substring() -> None:
    from xhs_food.research.profile_service import ShopProfileRefreshPlan
    from xhs_food.research.repository import InMemoryShopProfileRepository

    repository = InMemoryShopProfileRepository()
    service = ShopProfileService(repository)
    plan = ShopProfileRefreshPlan(
        candidates=("老店",),
        cached_profiles=(ShopProfile(name="老店春熙路店", address="春熙路"),),
        refresh_candidates=("老店",),
        fresh_cache_hits=(),
    )

    synced = await service.commit(plan, (ShopProfile(name="老店", address="总店"),))

    assert {profile.name for profile in synced.profiles} == {"老店", "老店春熙路店"}


@pytest.mark.asyncio
async def test_user_storage_profile_repository_prefers_provider_identity() -> None:
    from xhs_food.research.repository import UserStorageShopProfileRepository

    class _Storage:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []
            self.persisted: list[dict[str, Any]] = []

        async def get_cached_restaurant_by_provider_ref(
            self,
            provider: str,
            provider_ref: str,
        ) -> dict[str, Any] | None:
            self.calls.append(("provider", provider, provider_ref))
            return {
                "name": "老店春熙路店",
                "provider_refs": {"dianping": provider_ref},
                "address": "春熙路",
            }

        async def get_cached_restaurant_by_name(self, name: str) -> dict[str, Any] | None:
            self.calls.append(("name", name, ""))
            return {
                "name": name,
                "address": "错误的名称回退",
            }

        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            self.persisted.append(payload)

    storage = _Storage()
    repository = UserStorageShopProfileRepository(lambda: storage)
    merged = await repository.upsert(
        ShopProfile(
            provider_refs={"dianping": "dp-branch"},
            name="老店春熙路店",
            address="新地址",
        )
    )

    assert storage.calls == [("provider", "dianping", "dp-branch")]
    assert merged.address == "新地址"
    assert storage.persisted[0]["provider_refs"] == {"dianping": "dp-branch"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_failure", [False, True])
async def test_user_storage_provider_identity_never_falls_back_to_name(
    provider_failure: bool,
) -> None:
    from xhs_food.research.repository import UserStorageShopProfileRepository

    class _Storage:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []
            self.persisted: list[dict[str, Any]] = []

        async def get_cached_restaurant_by_provider_ref(
            self,
            provider: str,
            provider_ref: str,
        ) -> dict[str, Any] | None:
            self.calls.append(("provider", provider, provider_ref))
            if provider_failure:
                raise RuntimeError("provider lookup unavailable")
            return None

        async def get_cached_restaurant_by_name(self, name: str) -> dict[str, Any] | None:
            self.calls.append(("name", name, ""))
            raise AssertionError("provider identity must not use name fallback")

        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            self.persisted.append(payload)

    storage = _Storage()
    repository = UserStorageShopProfileRepository(lambda: storage)
    profile = await repository.upsert(
        ShopProfile(provider_refs={"dianping": " dp-branch "}, name="同名店")
    )

    assert profile.provider_refs == {"dianping": "dp-branch"}
    assert storage.calls == [("provider", "dianping", "dp-branch")]
    assert storage.persisted[0]["provider_refs"] == {"dianping": "dp-branch"}


@pytest.mark.asyncio
async def test_user_storage_profile_repository_reuses_existing_row_id() -> None:
    from xhs_food.research.repository import UserStorageShopProfileRepository

    class _Storage:
        def __init__(self) -> None:
            self.persisted: list[dict[str, Any]] = []

        async def get_cached_restaurant_by_provider_ref(
            self,
            provider: str,
            provider_ref: str,
        ) -> dict[str, Any] | None:
            assert (provider, provider_ref) == ("dianping", "dp-legacy")
            return {
                "id": "legacy-name-tel-id",
                "name": "旧店名",
                "provider_refs": {"dianping": "dp-legacy"},
                "must_try": [{"name": "毛肚", "reason": "脆"}],
                "pros": ["老字号"],
            }

        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            self.persisted.append(payload)

    storage = _Storage()
    repository = UserStorageShopProfileRepository(lambda: storage)
    await repository.upsert(
        ShopProfile(
            provider_refs={"dianping": " dp-legacy "},
            name="新店名",
            recommended_dishes=("毛肚",),
        )
    )

    assert storage.persisted[0]["id"] == "legacy-name-tel-id"
    assert storage.persisted[0]["must_try"] == [{"name": "毛肚", "reason": "脆"}]
    assert storage.persisted[0]["pros"] == ["老字号"]


@pytest.mark.asyncio
async def test_user_storage_reuses_legacy_row_id_when_provider_refs_are_not_backfilled() -> None:
    from xhs_food.research.repository import UserStorageShopProfileRepository

    class _Storage:
        def __init__(self) -> None:
            self.persisted: list[dict[str, Any]] = []

        async def get_cached_restaurant_by_provider_ref(
            self,
            provider: str,
            provider_ref: str,
        ) -> dict[str, Any] | None:
            assert (provider, provider_ref) == ("dianping", "dp-legacy")
            return {"id": "legacy-name-tel-id", "name": "旧店名"}

        async def upsert_restaurant(self, payload: dict[str, Any]) -> None:
            self.persisted.append(payload)

    storage = _Storage()
    repository = UserStorageShopProfileRepository(lambda: storage)
    await repository.upsert(
        ShopProfile(provider_refs={"dianping": " dp-legacy "}, name="新店名")
    )

    assert storage.persisted[0]["id"] == "legacy-name-tel-id"


def test_profile_storage_normalizes_name_identity_and_preserves_legacy_fields() -> None:
    spaced = profile_to_storage(ShopProfile(name="老 店"))
    compact = profile_to_storage(ShopProfile(name="老店"))
    assert spaced["id"] == compact["id"]

    profile = profile_from_storage(
        {
            "id": "legacy-id",
            "name": "老店",
            "provider_refs": '{"Dianping": " dp-1 "}',
            "must_try": '[{"name": "毛肚", "reason": "脆"}]',
            "pros": '["老字号"]',
            "cons": '["排队"]',
            "warning": "晚间拥挤",
            "trust_score": 4.2,
            "one_liner": "值得去",
            "black_list": '[{"name": "冰粉", "reason": "普通"}]',
            "stats": '{"likes": 12}',
            "source_notes": '["note-1"]',
        }
    )

    assert profile is not None
    assert profile.provider_refs == {"dianping": "dp-1"}
    legacy = profile.attributes["legacy_restaurant"]
    assert legacy == {
        "must_try": [{"name": "毛肚", "reason": "脆"}],
        "pros": ["老字号"],
        "cons": ["排队"],
        "warning": "晚间拥挤",
        "trust_score": 4.2,
        "one_liner": "值得去",
        "black_list": [{"name": "冰粉", "reason": "普通"}],
        "stats": {"likes": 12},
        "source_notes": ["note-1"],
    }
    persisted = profile_to_storage(profile, storage_id="legacy-id")
    assert persisted["must_try"] == legacy["must_try"]
    assert persisted["pros"] == legacy["pros"]
    assert persisted["cons"] == legacy["cons"]
    assert persisted["warning"] == legacy["warning"]
    assert persisted["stats"] == legacy["stats"]
    assert persisted["source_notes"] == legacy["source_notes"]


@pytest.mark.asyncio
async def test_user_storage_profile_repository_uses_only_exact_name_fallback() -> None:
    from xhs_food.research.repository import UserStorageShopProfileRepository

    class _Storage:
        async def get_cached_restaurant_by_name(self, name: str) -> dict[str, Any] | None:
            return {"name": name, "address": "精确名称"}

    repository = UserStorageShopProfileRepository(lambda: _Storage())
    profile = await repository.find_by_name("老店")

    assert profile is not None
    assert profile.name == "老店"
    assert profile.address == "精确名称"


def test_profile_from_storage_restores_refresh_metadata_and_unknown_payload() -> None:
    profile = profile_from_storage(
        {
            "name": "老成都火锅",
            "provider_refs": '{"dianping": "dp-1"}',
            "photos": '[{"url": "https://img.example/a.jpg"}]',
            "recommended_dishes": '["毛肚"]',
            "profile_metadata": '{"attributes": {"new_field": {"keep": true}}}',
            "source_payload": '{"future_provider_field": 42}',
            "profile_fetched_at": "2026-09-03T00:00:00+00:00",
            "profile_refresh_status": "complete",
        }
    )

    assert profile is not None
    assert profile.provider_refs["dianping"] == "dp-1"
    assert profile.images[0]["url"] == "https://img.example/a.jpg"
    assert profile.attributes["new_field"]["keep"] is True
    assert profile.source_payload["future_provider_field"] == 42
    assert profile.fetched_at == datetime(2026, 9, 3, tzinfo=UTC)
