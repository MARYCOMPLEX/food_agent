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
from xhs_food.research.repository import merge_profiles, profile_to_storage
from xhs_food.research.sources import (
    AdaptiveQueryPlanner,
    DianpingShopEnricher,
    XhsCommentLeadCollector,
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


def test_profile_from_storage_restores_refresh_metadata_and_unknown_payload() -> None:
    from xhs_food.research.repository import profile_from_storage

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
