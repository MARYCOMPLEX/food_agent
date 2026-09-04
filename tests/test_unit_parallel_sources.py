"""Bounded source parallelism and lossless pagination contracts."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest

from xhs_food.contracts import (
    PlatformChannel,
    ResearchOutcome,
    ResourceClass,
    SourceCall,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research.sources import (
    AdaptiveQueryPlanner,
    DianpingMcpSource,
    DianpingShopEnricher,
    XhsCommentLeadCollector,
    XhsMcpSource,
)


def _intent() -> FoodSearchIntent:
    return FoodSearchIntent(location="成都", food_type="火锅")


def _comment(comment_id: str) -> dict[str, Any]:
    return {"id": comment_id, "content": f"评论 {comment_id}", "like_count": 1}


class _StreamingXhsSource:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.comment_cursors: list[tuple[str, str | None]] = []
        self.raw_pages: list[dict[str, Any]] = []

    async def search_notes(self, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={
                "notes": [
                    {"note_id": "note-1", "title": "第一篇"},
                    {"note_id": "note-2", "title": "第二篇"},
                ]
            },
            raw_payload={"search_raw": True},
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.04 if note_id == "note-1" else 0.12)
            return SourceCall(
                source="xhs",
                operation="notes.detail",
                success=True,
                data={"title": note_id, "summary": "详情"},
                raw_payload={"detail_raw": note_id},
            )
        finally:
            self.active -= 1

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        cursor = arguments.get("cursor")
        self.comment_cursors.append((note_id, cursor))
        try:
            await asyncio.sleep(0.01)
            if note_id == "note-1" and cursor is None:
                data = {"items": [_comment("c1")], "has_more": True, "next_cursor": "c1"}
            elif note_id == "note-1" and cursor == "c1":
                data = {"items": [_comment("c2")], "has_more": False}
            else:
                data = {"items": [_comment(f"{note_id}-c1")], "has_more": False}
            raw = {"cursor": cursor, "opaque": f"page-{cursor or 'first'}"}
            self.raw_pages.append(raw)
            return SourceCall(
                source="xhs",
                operation="comments.search",
                success=True,
                data=data,
                raw_payload=raw,
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_xhs_iter_notes_yields_early_and_overlaps_detail_comments() -> None:
    source = _StreamingXhsSource()
    collector = XhsCommentLeadCollector(
        source,
        planner=AdaptiveQueryPlanner(1),
        max_notes=2,
        detail_concurrency=2,
        comments_concurrency=2,
    )

    yielded: list[str] = []
    async for note in collector.iter_notes(_intent()):
        yielded.append(note.note_id)
        if len(yielded) == 1:
            # note-1's first page and second cursor page are retained in order.
            assert [item.comment_id for item in note.comments] == ["c1", "c2"]
            assert note.raw_payload["comments"][0]["opaque"] == "page-first"
            assert note.raw_payload["comments"][1]["opaque"] == "page-c1"
            assert [
                cursor for note_id, cursor in source.comment_cursors if note_id == "note-1"
            ] == [None, "c1"]

    assert yielded == ["note-1", "note-2"]
    assert source.max_active >= 2


class _ParallelDianpingSource:
    def __init__(self, *, challenge_detail: bool = False) -> None:
        self.challenge_detail = challenge_detail
        self.detail_calls: list[str] = []
        self.review_calls: list[str] = []
        self.active: defaultdict[str, int] = defaultdict(int)
        self.max_active: defaultdict[str, int] = defaultdict(int)

    async def search_places(self, **arguments: Any) -> SourceCall:
        name = str(arguments["keyword"]).split()[-2]
        shop_id = {"甲店": "shop-a", "乙店": "shop-b"}[name]
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data={"items": [{"shop_id": shop_id, "name": name}]},
            raw_payload={"search_raw": name},
        )

    async def place_detail(self, shop_id: str, **_: Any) -> SourceCall:
        self.detail_calls.append(shop_id)
        self.active["detail"] += 1
        self.max_active["detail"] = max(self.max_active["detail"], self.active["detail"])
        try:
            await asyncio.sleep(0.03)
            if self.challenge_detail and shop_id == "shop-a":
                return SourceCall(
                    source="dianping",
                    operation="places.detail",
                    success=False,
                    error_code="challenge_required",
                    error_message="interactive verification required",
                    data={"shop": {"address": "挑战响应仍有地址"}},
                    raw_payload={"detail_raw": shop_id},
                )
            return SourceCall(
                source="dianping",
                operation="places.detail",
                success=True,
                data={"shop": {"address": f"地址 {shop_id}"}},
                raw_payload={"detail_raw": shop_id},
            )
        finally:
            self.active["detail"] -= 1

    async def search_reviews(self, shop_id: str, **_: Any) -> SourceCall:
        self.review_calls.append(shop_id)
        self.active["reviews"] += 1
        self.max_active["reviews"] = max(self.max_active["reviews"], self.active["reviews"])
        try:
            await asyncio.sleep(0.03)
            return SourceCall(
                source="dianping",
                operation="reviews.search",
                success=True,
                data={"items": [{"review_id": f"review-{shop_id}", "recommended_dishes": ["毛肚"]}]},
                raw_payload={"reviews_raw": shop_id},
            )
        finally:
            self.active["reviews"] -= 1


class _ProbeShapeDianpingSource:
    """Fixture matching the authenticated contract-probe response envelope."""

    def __init__(self) -> None:
        self.search_pages: list[int] = []
        self.review_offsets: list[int] = []

    async def search_places(self, **arguments: Any) -> SourceCall:
        page = int(arguments["page"])
        self.search_pages.append(page)
        item = {
            "shop_id": "probe-shop",
            "name": "探店火锅",
            "url": "https://www.dianping.com/shop/probe-shop",
            "image_url": "https://img.example/cover.jpg",
            "rating": 4.5,
            "review_count": 1234,
            "average_price": 88,
            "category": "四川火锅",
            "region": "静安寺商圈",
            "address": "上海市静安区示例路 1 号",
            "recommended_dishes": ["鲜毛肚"],
            "promotions": [],
        }
        if page == 2:
            item = {**item, "shop_id": "other-shop", "name": "第二页店"}
        data = {
            "items": [item],
            "result_count": 1,
            "pagination": {"current_page": page, "max_page": 2, "has_next": page == 1},
            "available_filters": {"categories": [{"id": 110, "name": "火锅"}]},
            "source_url": f"https://www.dianping.com/search?page={page}",
        }
        return SourceCall(
            source="dianping",
            operation="places.search",
            success=True,
            data=data,
            raw_payload={"page": page, "provider_marker": f"search-{page}"},
        )

    async def place_detail(self, shop_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="dianping",
            operation="places.detail",
            success=True,
            data={"shop": {"shop_id": shop_id, "phone": "021-12345678"}},
            raw_payload={"provider_marker": "detail"},
        )

    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall:
        offset = int(arguments["offset"])
        self.review_offsets.append(offset)
        data = {
            "shop": {"shop_id": shop_id, "name": "探店火锅"},
            "items": [
                {
                    "review_id": 1000 + offset,
                    "content": "锅底香，毛肚脆。",
                    "raw": {"reviewId": 1000 + offset},
                }
            ],
            "result_count": 1,
            "pagination": {"current_page": 1, "max_page": 1, "has_next": False},
            "raw_responses": [{"module": "reviewlist", "offset": offset}],
        }
        return SourceCall(
            source="dianping",
            operation="reviews.search",
            success=True,
            data=data,
            raw_payload={"offset": offset, "provider_marker": "reviews"},
        )


@pytest.mark.asyncio
async def test_dianping_probe_shapes_keep_pages_and_rich_profile_fields() -> None:
    source = _ProbeShapeDianpingSource()
    result = await DianpingShopEnricher(
        source,
        max_profiles=1,
        max_place_pages=3,
        review_limit=10,
    ).enrich(["探店火锅"], _intent())

    assert source.search_pages == [1, 2]
    assert source.review_offsets == [0]
    assert not any(gap.code == "unsupported_response_shape" for gap in result.gaps)
    profile = result.profiles[0]
    assert profile.provider_refs["dianping"] == "probe-shop"
    assert profile.image_url == "https://img.example/cover.jpg"
    assert profile.recommended_dishes == ("鲜毛肚",)
    assert profile.phone == "021-12345678"
    assert profile.attributes["review_pagination"]["max_page"] == 1
    search_payload = result.raw_payload["searches"]["探店火锅"]
    assert [page["page"] for page in search_payload] == [1, 2]


@pytest.mark.asyncio
async def test_dianping_candidate_and_capability_limits_are_independent() -> None:
    source = _ParallelDianpingSource()
    result = await DianpingShopEnricher(
        source,
        max_profiles=2,
        candidate_concurrency=2,
        detail_concurrency=1,
        reviews_concurrency=1,
    ).enrich(["甲店", "乙店"], _intent())

    assert [profile.name for profile in result.profiles] == ["甲店", "乙店"]
    assert source.max_active["detail"] == 1
    assert source.max_active["reviews"] == 1
    assert set(source.detail_calls) == {"shop-a", "shop-b"}
    assert set(source.review_calls) == {"shop-a", "shop-b"}


@pytest.mark.asyncio
async def test_dianping_detail_challenge_only_opens_detail_breaker() -> None:
    source = _ParallelDianpingSource(challenge_detail=True)
    result = await DianpingShopEnricher(
        source,
        max_profiles=2,
        candidate_concurrency=2,
        detail_concurrency=1,
        reviews_concurrency=1,
    ).enrich(["甲店", "乙店"], _intent())

    profiles = {profile.name: profile for profile in result.profiles}
    assert source.detail_calls == ["shop-a"]
    assert set(source.review_calls) == {"shop-a", "shop-b"}
    assert profiles["甲店"].address == "挑战响应仍有地址"
    assert profiles["甲店"].outcome is ResearchOutcome.PARTIAL
    assert any(
        gap.code == "detail_skipped_after_challenge"
        for profile in profiles.values()
        for gap in profile.gaps
    ) or any(gap.code == "detail_skipped_after_challenge" for gap in result.gaps)


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[PlatformChannel, str, dict[str, Any]]] = []

    async def call(
        self,
        platform: PlatformChannel,
        capability: str,
        arguments: dict[str, Any],
    ) -> SourceCall:
        self.calls.append((platform, capability, arguments))
        return SourceCall(
            source=platform.value,
            operation=capability,
            success=True,
            data={"items": []},
        )


class _RecordingResourceInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[ResourceClass, str]] = []

    async def execute(
        self,
        resource_class: ResourceClass,
        operation: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((ResourceClass(resource_class), str(args[1])))
        return await operation(*args, **kwargs)


@pytest.mark.asyncio
async def test_source_adapters_route_every_physical_call_through_resource_invoker() -> None:
    session = _RecordingSession()
    invoker = _RecordingResourceInvoker()
    xhs = XhsMcpSource(
        session,
        platform=PlatformChannel.XHS_PC,
        resource_executor=invoker,
    )
    dianping = DianpingMcpSource(session, resource_executor=invoker)

    await xhs.search_notes(query="火锅")
    await xhs.note_detail("note-1")
    await xhs.search_comments("note-1")
    await dianping.search_places(keyword="火锅")
    await dianping.place_detail("shop-1")
    await dianping.search_reviews("shop-1")

    assert invoker.calls == [
        (ResourceClass.XHS_SEARCH, "notes.search"),
        (ResourceClass.XHS_DETAIL, "notes.detail"),
        (ResourceClass.XHS_COMMENTS, "comments.search"),
        (ResourceClass.DIANPING_SEARCH, "places.search"),
        (ResourceClass.DIANPING_DETAIL, "places.detail"),
        (ResourceClass.DIANPING_REVIEWS, "reviews.search"),
    ]
    assert [capability for _, capability, _ in session.calls] == [
        "notes.search",
        "notes.detail",
        "comments.search",
        "places.search",
        "places.detail",
        "reviews.search",
    ]
