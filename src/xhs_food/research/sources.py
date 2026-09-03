"""MCP-backed source adapters for comment-first food research."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from xhs_food.contracts import (
    CommentEvidence,
    DianpingSourcePort,
    PlatformChannel,
    ResearchGap,
    ResearchOutcome,
    ShopProfile,
    SourceCall,
    XhsLeadSourcePort,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent

from .mcp import ManagedMcpToolSession
from .repository import merge_profiles


class XhsMcpSource:
    """Translate semantic XHS operations to the pinned MCP session."""

    def __init__(
        self,
        session: ManagedMcpToolSession,
        *,
        platform: PlatformChannel = PlatformChannel.XHS_PC,
    ) -> None:
        self._session = session
        self._platform = platform

    @property
    def session(self) -> ManagedMcpToolSession:
        """Expose the owned session for explicit lifecycle wiring."""

        return self._session

    async def open(self, context: Any) -> None:
        await self._session.open(context)

    async def close(self) -> None:
        await self._session.close()

    async def search_notes(self, **arguments: Any) -> SourceCall:
        return await self._session.call(self._platform, "notes.search", arguments)

    async def note_detail(self, note_id: str, **arguments: Any) -> SourceCall:
        return await self._session.call(
            self._platform,
            "notes.detail",
            {"note_id": note_id, **arguments},
        )

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall:
        return await self._session.call(
            self._platform,
            "comments.search",
            {"note_id": note_id, **arguments},
        )


class DianpingMcpSource:
    """Translate semantic Dianping operations to the pinned MCP session."""

    def __init__(
        self,
        session: ManagedMcpToolSession,
        *,
        platform: PlatformChannel = PlatformChannel.DIANPING,
    ) -> None:
        self._session = session
        self._platform = platform

    @property
    def session(self) -> ManagedMcpToolSession:
        """Expose the owned session for explicit lifecycle wiring."""

        return self._session

    async def open(self, context: Any) -> None:
        await self._session.open(context)

    async def close(self) -> None:
        await self._session.close()

    async def search_places(self, **arguments: Any) -> SourceCall:
        return await self._session.call(self._platform, "places.search", arguments)

    async def place_detail(self, shop_id: str, **arguments: Any) -> SourceCall:
        return await self._session.call(
            self._platform,
            "places.detail",
            {"shop_id": shop_id, **arguments},
        )

    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall:
        return await self._session.call(
            self._platform,
            "reviews.search",
            {"shop_id": shop_id, **arguments},
        )


class XhsSourceAdapterFactory:
    """Composition-root factory for a context-bound XHS source adapter."""

    def __init__(
        self,
        session_factory: Callable[[], ManagedMcpToolSession],
        *,
        platform: PlatformChannel = PlatformChannel.XHS_PC,
    ) -> None:
        self._session_factory = session_factory
        self._platform = platform

    def __call__(self) -> XhsMcpSource:
        return XhsMcpSource(self._session_factory(), platform=self._platform)


class DianpingSourceAdapterFactory:
    """Composition-root factory for a context-bound Dianping source adapter."""

    def __init__(self, session_factory: Callable[[], ManagedMcpToolSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> DianpingMcpSource:
        return DianpingMcpSource(self._session_factory())


class AdaptiveQueryPlanner:
    """Generate a small set of high-information queries.

    Variants are chosen once from the conversation intent and let the source
    return a full comment corpus; additional calls are driven by observed
    gaps, not by a hard-coded phase ladder.
    """

    def __init__(self, max_queries: int = 3) -> None:
        self.max_queries = max(1, max_queries)

    def plan(self, intent: FoodSearchIntent) -> tuple[str, ...]:
        base = " ".join(item for item in (intent.location, intent.food_type) if item).strip()
        if not base:
            base = intent.location.strip()
        variants = [base]
        if intent.requirements:
            variants.append(f"{base} {' '.join(intent.requirements[:2])}".strip())
        # A controversy-oriented query is useful for the Agent's core insight:
        # disagreements and corrections in the comment section.
        variants.append(f"{base} 争议 避雷".strip())
        unique = list(dict.fromkeys(item for item in variants if item))
        return tuple(unique[: self.max_queries])


@dataclass(frozen=True, slots=True)
class LeadCollectionResult:
    notes: tuple[XhsNoteLead, ...]
    gaps: tuple[ResearchGap, ...] = ()
    raw_payload: Any = None


class XhsCommentLeadCollector:
    """Collect notes and all available comments while preserving raw envelopes."""

    def __init__(
        self,
        source: XhsLeadSourcePort,
        *,
        planner: AdaptiveQueryPlanner | None = None,
        max_notes: int = 30,
        comment_page_size: int = 100,
        max_comment_pages: int = 20,
        concurrency: int = 3,
    ) -> None:
        self._source = source
        self._planner = planner or AdaptiveQueryPlanner()
        self._max_notes = max(1, max_notes)
        self._comment_page_size = max(1, comment_page_size)
        self._max_comment_pages = max(1, max_comment_pages)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    async def collect(self, intent: FoodSearchIntent) -> LeadCollectionResult:
        queries = self._planner.plan(intent)
        search_results = await asyncio.gather(
            *(self._search(query) for query in queries), return_exceptions=True
        )
        candidates: dict[str, dict[str, Any]] = {}
        global_gaps: list[ResearchGap] = []
        raw_search: list[Any] = []
        for query, result in zip(queries, search_results, strict=False):
            if isinstance(result, BaseException):
                global_gaps.append(_gap("xhs", "notes.search", "source_exception", result))
                continue
            if not result.success:
                global_gaps.append(_gap_from_call(result))
                raw_search.append(result.raw_payload)
                continue
            raw_search.append(result.raw_payload if result.raw_payload is not None else result.data)
            for raw_note in _note_entries(result.data):
                note_id = _note_id(raw_note)
                if not note_id:
                    global_gaps.append(
                        ResearchGap(
                            source="xhs",
                            operation="notes.search",
                            code="note_id_missing",
                            message="provider note has no stable identifier",
                        )
                    )
                    continue
                item = candidates.setdefault(
                    note_id,
                    {
                        "note_id": note_id,
                        "raw": [],
                        "search_payloads": [],
                        "queries": [],
                        "comments": [],
                        "gaps": [],
                        "comment_count": 0,
                        "comment_expected_count": 0,
                        "comment_has_more": False,
                        "comment_cursor": None,
                        "comment_pages": 0,
                    },
                )
                item["raw"].append(raw_note)
                item["search_payloads"].append(
                    result.raw_payload if result.raw_payload is not None else result.data
                )
                item["queries"].append(query)
                expected, has_more, cursor, page_count = _comment_envelope_stats(raw_note)
                item["comment_count"] = max(item["comment_count"], expected)
                item["comment_expected_count"] = max(item["comment_expected_count"], expected)
                item["comment_has_more"] = bool(item["comment_has_more"] or has_more)
                item["comment_cursor"] = item["comment_cursor"] or cursor
                item["comment_pages"] = max(item["comment_pages"], page_count)
                item["comments"].extend(_extract_comments(raw_note))

        selected = list(candidates.values())[: self._max_notes]
        notes = await asyncio.gather(
            *(self._complete_note(item) for item in selected), return_exceptions=True
        )
        output: list[XhsNoteLead] = []
        for value in notes:
            if isinstance(value, BaseException):
                global_gaps.append(_gap("xhs", "note.complete", "source_exception", value))
            else:
                output.append(value)
        return LeadCollectionResult(
            notes=tuple(output),
            gaps=tuple(global_gaps),
            raw_payload={"queries": list(queries), "search": raw_search},
        )

    async def _search(self, query: str) -> SourceCall:
        async with self._semaphore:
            return await self._source.search_notes(
                query=query,
                keyword=query,
                count=self._max_notes,
                include_details=True,
                include_comments=True,
            )

    async def _complete_note(self, item: dict[str, Any]) -> XhsNoteLead:
        note_id = str(item["note_id"])
        raw_payload: dict[str, Any] = {
            "search": list(item["raw"]),
            "search_envelopes": list(item.get("search_payloads", ())),
        }
        gaps: list[ResearchGap] = list(item["gaps"])
        comments: list[CommentEvidence] = _normalise_comments(
            note_id, item["comments"], operation="notes.search", page_cursor=None
        )

        # Detail provides the note body and may include an initial comment
        # window.  It is best-effort: embedded search data is never discarded.
        detail = await self._safe_detail(note_id)
        if detail is not None:
            raw_payload["detail"] = detail.raw_payload if detail.raw_payload is not None else detail.data
            if detail.success:
                comments.extend(
                    _normalise_comments(
                        note_id,
                        _extract_comments(detail.data),
                        operation="notes.detail",
                        page_cursor=None,
                    )
                )
            else:
                gaps.append(_gap_from_call(detail))

        # Always ask the comment endpoint at least once.  If it exposes a
        # cursor, continue until exhausted (bounded only by a provider safety
        # limit, with an explicit gap when the bound is reached).
        cursor: str | None = item.get("comment_cursor")
        embedded_has_more = bool(item.get("comment_has_more"))
        # ``notes.search`` can embed a first comment window and expose a
        # continuation cursor.  The endpoint response is authoritative for
        # whether that continuation is still open; never let the embedded
        # flag force a false partial result after the cursor is exhausted.
        remaining = embedded_has_more
        continuation_cursor = cursor
        remaining_gap_recorded = False
        pages = 0
        seen_page_fingerprints: set[str] = set()
        while pages < self._max_comment_pages:
            pages += 1
            request_cursor = continuation_cursor
            call = await self._safe_comments(note_id, request_cursor)
            raw_payload.setdefault("comments", []).append(
                call.raw_payload if call.raw_payload is not None else call.data
            )
            # Consume a successful response before inspecting transport
            # metadata.  A provider may return useful comments even when the
            # current MCP descriptor cannot expose the continuation cursor;
            # dropping that page would make the adapter lose evidence it has
            # already fetched.
            if call.success:
                comments.extend(
                    _normalise_comments(
                        note_id,
                        _extract_comments(call.data),
                        operation="comments.search",
                        page_cursor=request_cursor,
                    )
                )
            if request_cursor and "cursor" in _metadata_names(
                call.metadata.get("dropped_arguments")
            ):
                remaining = True
                continuation_cursor = request_cursor
                remaining_gap_recorded = True
                gaps.append(
                    ResearchGap(
                        source="xhs",
                        operation="comments.search",
                        code="pagination_argument_unsupported",
                        message="MCP contract does not expose the provider cursor argument",
                        retryable=True,
                        details={"cursor": request_cursor},
                    )
                )
                break
            if not call.success:
                remaining = remaining or bool(request_cursor)
                continuation_cursor = request_cursor
                gaps.append(_gap_from_call(call))
                break
            next_cursor = _next_cursor(call.data)
            call_has_more = _has_more(call.data)
            page_fingerprint = _payload_fingerprint(call.data)
            if page_fingerprint in seen_page_fingerprints:
                remaining = True
                continuation_cursor = next_cursor or request_cursor
                remaining_gap_recorded = True
                gaps.append(
                    ResearchGap(
                        source="xhs",
                        operation="comments.search",
                        code="repeated_page",
                        message="provider returned a repeated comment page",
                        retryable=True,
                    )
                )
                break
            seen_page_fingerprints.add(page_fingerprint)

            # A cursor is sufficient evidence of another page even when an
            # older provider omits ``has_more``.  Conversely, a terminal
            # response clears the embedded ``has_more`` flag.
            if next_cursor and next_cursor != request_cursor:
                remaining = True
                continuation_cursor = next_cursor
                continue
            if call_has_more is True:
                remaining = True
                continuation_cursor = request_cursor
                remaining_gap_recorded = True
                gaps.append(
                    ResearchGap(
                        source="xhs",
                        operation="comments.search",
                        code="continuation_cursor_missing",
                        message="provider indicates more comments but returned no usable cursor",
                        retryable=True,
                    )
                )
                break
            remaining = False
            continuation_cursor = None
            break
        else:
            remaining = True
            remaining_gap_recorded = True
            gaps.append(
                ResearchGap(
                    source="xhs",
                    operation="comments.search",
                    code="pagination_limit_reached",
                    message=f"comment pages exceeded {self._max_comment_pages}",
                    retryable=True,
                )
            )

        deduped = _dedupe_comments(comments)
        expected = max(item["comment_count"], len(deduped))
        has_more = remaining
        final_cursor = continuation_cursor if has_more else None
        completeness = "complete"
        if has_more:
            completeness = "partial"
            if not remaining_gap_recorded:
                gaps.append(
                    ResearchGap(
                        source="xhs",
                        operation="comments.search",
                        code="comments_remaining",
                        message="provider indicates additional comment pages",
                        retryable=True,
                        details={"next_cursor": final_cursor, "expected_count": expected},
                    )
                )
        elif item["comment_count"] and len(deduped) < item["comment_count"]:
            completeness = "partial"
            gaps.append(
                ResearchGap(
                    source="xhs",
                    operation="comments.search",
                    code="comment_count_mismatch",
                    message="collected comments are fewer than provider count",
                    retryable=True,
                    details={
                        "expected_count": item["comment_count"],
                        "collected_count": len(deduped),
                    },
                )
            )
        outcome = ResearchOutcome.COMPLETE if not gaps else ResearchOutcome.PARTIAL
        if not deduped and gaps:
            outcome = ResearchOutcome.PARTIAL
        raw = item["raw"][0] if item["raw"] else {}
        search_item = _first_mapping(raw, "search_item")
        note_card = _first_mapping(raw, "note_card") or _first_mapping(search_item, "note_card")
        detail_note = _detail_note_mapping(raw)
        title = (
            _text(_first(raw, "title", "display_title"))
            or _text(_first(note_card, "display_title", "title"))
            or _text(_first(detail_note, "title", "display_title"))
        )
        summary = (
            _text(_first(raw, "summary", "desc", "content", "full_desc"))
            or _text(_first(detail_note, "desc", "summary", "content", "full_desc"))
        )
        url = (
            _text(_first(raw, "url", "link"))
            or _text(_first(search_item, "url", "link"))
            or _text(_first(note_card, "url", "link"))
        )
        return XhsNoteLead(
            note_id=note_id,
            title=title,
            summary=summary,
            url=url or None,
            comment_count=expected,
            comment_expected_count=item.get("comment_expected_count") or expected,
            comment_collected_count=len(deduped),
            comment_has_more=has_more,
            comment_cursor=final_cursor,
            # Search responses may already contain one or more embedded
            # comment pages.  Keep those pages in the audit count instead of
            # reporting only the follow-up comments.search calls.
            comment_pages=max(int(item.get("comment_pages", 0)) + pages, len(seen_page_fingerprints)),
            comment_completeness=completeness,
            comments=tuple(deduped),
            queries=tuple(dict.fromkeys(item["queries"])),
            outcome=outcome,
            gaps=tuple(gaps),
            raw_payload=raw_payload,
        )

    async def _safe_detail(self, note_id: str) -> SourceCall | None:
        try:
            async with self._semaphore:
                return await self._source.note_detail(
                    note_id,
                    include_comments=True,
                    max_comments=self._comment_page_size,
                )
        except Exception as exc:
            return SourceCall(
                source="xhs",
                operation="notes.detail",
                success=False,
                error_code="source_exception",
                error_message=type(exc).__name__,
                retryable=True,
            )

    async def _safe_comments(self, note_id: str, cursor: str | None) -> SourceCall:
        try:
            async with self._semaphore:
                return await self._source.search_comments(
                    note_id,
                    max_comments=self._comment_page_size,
                    cursor=cursor,
                    include_replies=True,
                )
        except Exception as exc:
            return SourceCall(
                source="xhs",
                operation="comments.search",
                success=False,
                error_code="source_exception",
                error_message=type(exc).__name__,
                retryable=True,
            )


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    profiles: tuple[ShopProfile, ...]
    gaps: tuple[ResearchGap, ...] = ()
    raw_payload: Any = None


@dataclass(frozen=True, slots=True)
class ReviewCollectionResult:
    """Bounded Dianping review collection with an auditable page ledger."""

    call: SourceCall
    gaps: tuple[ResearchGap, ...] = ()
    raw_pages: tuple[Any, ...] = ()


class DianpingShopEnricher:
    """Add structured shop data without making it a prerequisite for evidence."""

    def __init__(
        self,
        source: DianpingSourcePort,
        *,
        max_profiles: int = 10,
        review_limit: int = 50,
        detail_on_missing: bool = True,
        concurrency: int = 3,
    ) -> None:
        self._source = source
        self._max_profiles = max(1, max_profiles)
        self._review_limit = max(1, review_limit)
        self._detail_on_missing = detail_on_missing
        self._semaphore = asyncio.Semaphore(max(1, concurrency))

    async def enrich(
        self,
        candidates: Sequence[str],
        intent: FoodSearchIntent,
    ) -> EnrichmentResult:
        selected = tuple(dict.fromkeys(str(name).strip() for name in candidates if str(name).strip()))[
            : self._max_profiles
        ]
        searches = await asyncio.gather(
            *(self._search_candidate(name, intent) for name in selected),
            return_exceptions=True,
        )
        profiles: list[ShopProfile] = []
        gaps: list[ResearchGap] = []
        raw_searches: dict[str, Any] = {}
        detail_blocked = False
        for name, result in zip(selected, searches, strict=False):
            if isinstance(result, BaseException):
                gap = _gap("dianping", "places.search", "source_exception", result)
                profiles.append(_placeholder_profile(name, gap))
                gaps.append(gap)
                continue
            search = result
            raw_searches[name] = search.raw_payload if search.raw_payload is not None else search.data
            if not search.success:
                gap = _gap_from_call(search)
                profiles.append(_placeholder_profile(name, gap))
                gaps.append(gap)
                continue
            items = _place_entries(search.data)
            item = _best_place_match(name, items)
            if item is None:
                gap = ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="shop_not_found",
                    message=f"no Dianping result matched {name}",
                    details={"query": _search_query(name, intent)},
                )
                profiles.append(_placeholder_profile(name, gap))
                gaps.append(gap)
                continue

            shop_id = _text(_first(item, "shop_id", "shopId", "id", "poi_id"))
            payload: dict[str, Any] = {
                # Keep the normalized response and the MCP envelope side by
                # side.  The former feeds field mapping; the latter is the
                # immutable audit copy used for replay/debugging.
                "search": search.data,
                "search_raw": search.raw_payload,
                "selected": item,
            }
            item_for_profile: Mapping[str, Any] = item
            item_gaps: list[ResearchGap] = []
            missing = _missing_profile_fields(item)
            if self._detail_on_missing and shop_id and missing:
                if detail_blocked:
                    item_gaps.append(
                        ResearchGap(
                            source="dianping",
                            operation="places.detail",
                            code="detail_skipped_after_challenge",
                            message="detail calls stopped after provider interactive verification",
                            retryable=True,
                        )
                    )
                else:
                    detail = await self._safe_detail(shop_id)
                    payload["detail"] = detail.data
                    payload["detail_raw"] = detail.raw_payload
                    if detail.success and isinstance(detail.data, Mapping):
                        item_for_profile = _merge_maps(item, _detail_mapping(detail.data))
                    elif not detail.success:
                        gap = _gap_from_call(detail)
                        item_gaps.append(gap)
                        if _is_interactive_gap(gap):
                            detail_blocked = True
            if shop_id:
                review_collection = await self._collect_reviews(shop_id)
                reviews = review_collection.call
                payload["reviews"] = reviews.data
                payload["reviews_raw"] = (
                    list(review_collection.raw_pages)
                    if review_collection.raw_pages
                    else reviews.raw_payload
                )
                if reviews.success:
                    item_for_profile = _merge_review_fields(item_for_profile, reviews.data)
                    item_gaps.extend(review_collection.gaps)
                elif reviews.error_code not in {"MCP_CAPABILITY_UNAVAILABLE", "MCP_NOT_CONFIGURED"}:
                    item_gaps.append(_gap_from_call(reviews))
            profile = _profile_from_item(item_for_profile, payload, item_gaps)
            profiles.append(profile)
            gaps.extend(item_gaps)
        profiles = _dedupe_profiles(profiles)
        return EnrichmentResult(
            profiles=tuple(profiles),
            gaps=tuple(gaps),
            raw_payload={
                "searches": raw_searches,
                "profiles": {
                    profile.provider_refs.get("dianping") or profile.name: profile.source_payload
                    for profile in profiles
                },
            },
        )

    async def _search_candidate(self, name: str, intent: FoodSearchIntent) -> SourceCall:
        async with self._semaphore:
            arguments: dict[str, Any] = {
                "keyword": _search_query(name, intent),
                "page": 1,
                "sort": "review_count",
            }
            city_id = getattr(intent, "city_id", None)
            if city_id is not None:
                arguments["city_id"] = city_id
            return await self._source.search_places(**arguments)

    async def _safe_detail(self, shop_id: str) -> SourceCall:
        try:
            async with self._semaphore:
                return await self._source.place_detail(shop_id)
        except Exception as exc:
            return SourceCall(
                source="dianping",
                operation="places.detail",
                success=False,
                error_code="source_exception",
                error_message=type(exc).__name__,
                retryable=True,
            )

    async def _collect_reviews(self, shop_id: str) -> ReviewCollectionResult:
        """Collect review pages up to the configured budget without lossy reads.

        Dianping exposes an offset continuation and a provider-wide corpus
        count.  The Agent only needs a bounded sample for shop enrichment,
        but every page it did fetch is retained and a budget/continuation gap
        makes the uncollected remainder explicit.  Comment evidence remains
        owned by the XHS evidence ledger; these reviews are profile clues.
        """

        pages: list[Any] = []
        calls: list[SourceCall] = []
        successful_payloads: list[Mapping[str, Any]] = []
        unique_items: dict[str, Mapping[str, Any]] = {}
        seen_fingerprints: set[str] = set()
        seen_offsets: set[int] = set()
        offset = 0
        next_offset: int | None = None
        has_next = False
        gaps: list[ResearchGap] = []

        while True:
            if offset in seen_offsets:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="repeated_offset",
                        message="provider returned a non-advancing review offset",
                        retryable=True,
                        details={"offset": offset},
                    )
                )
                break
            seen_offsets.add(offset)
            call = await self._safe_reviews(shop_id, offset=offset)
            calls.append(call)
            page_payload = call.raw_payload if call.raw_payload is not None else call.data
            pages.append(page_payload)
            if not call.success:
                if len(calls) == 1:
                    return ReviewCollectionResult(call=call, gaps=tuple(gaps), raw_pages=tuple(pages))
                # Keep successfully collected pages and make the uncollected
                # remainder explicit. A later-page failure must never be
                # mistaken for a complete corpus.
                has_next = True
                next_offset = next_offset or offset
                gaps.append(_gap_from_call(call))
                break
            if not isinstance(call.data, Mapping):
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="unsupported_response_shape",
                        message="Dianping review response is not an object",
                        retryable=False,
                    )
                )
                has_next = True
                next_offset = next_offset or offset
                break
            successful_payloads.append(call.data)

            raw_items = call.data.get("items")
            page_items = (
                [item for item in raw_items if isinstance(item, Mapping)]
                if isinstance(raw_items, list)
                else []
            )
            for index, item in enumerate(page_items):
                identifier = _review_item_id(item, index=index, offset=offset)
                unique_items.setdefault(identifier, item)

            fingerprint = _payload_fingerprint(
                tuple(_review_item_id(item, index=index, offset=offset) for index, item in enumerate(page_items))
            )
            if fingerprint in seen_fingerprints:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="repeated_page",
                        message="provider returned a repeated review page",
                        retryable=True,
                        details={"offset": offset},
                    )
                )
                has_next = True
                next_offset = _review_next_offset(call.data, offset, len(page_items))
                break
            seen_fingerprints.add(fingerprint)

            if offset and "offset" in _metadata_names(call.metadata.get("dropped_arguments")):
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="pagination_argument_unsupported",
                        message="MCP contract does not expose the provider review offset",
                        retryable=True,
                        details={"offset": offset},
                    )
                )
                has_next = True
                next_offset = offset
                break

            has_next = _review_has_next(call.data)
            next_offset = _review_next_offset(call.data, offset, len(page_items))
            provider_total = _review_total_count(call.data)
            if provider_total is not None and provider_total > len(unique_items):
                # Some provider versions omit pagination.has_next but expose
                # a corpus count. Treat that count as authoritative.
                has_next = True
                if next_offset is None and page_items:
                    next_offset = offset + len(page_items)
            if len(unique_items) >= self._review_limit:
                if has_next or next_offset is not None:
                    gaps.append(
                        ResearchGap(
                            source="dianping",
                            operation="reviews.search",
                            code="review_budget_reached",
                            message=f"review enrichment budget reached ({self._review_limit})",
                            retryable=True,
                            details={"next_offset": next_offset, "collected_count": len(unique_items)},
                        )
                    )
                break
            if not has_next:
                next_offset = None
                break
            if next_offset is None:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="continuation_offset_missing",
                        message="provider indicates more reviews but returned no usable offset",
                        retryable=True,
                    )
                )
                break
            if next_offset <= offset:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="repeated_offset",
                        message="provider returned a non-advancing review offset",
                        retryable=True,
                        details={"offset": offset, "next_offset": next_offset},
                    )
                )
                break
            offset = next_offset

        first = next((call for call in calls if call.success and isinstance(call.data, Mapping)), None)
        if first is None:
            failed = calls[-1] if calls else SourceCall(
                source="dianping",
                operation="reviews.search",
                success=False,
                error_code="source_failed",
            )
            return ReviewCollectionResult(call=failed, gaps=tuple(gaps), raw_pages=tuple(pages))

        first_data = first.data if isinstance(first.data, Mapping) else {}
        aggregate = _aggregate_review_payload(
            first_data,
            tuple(successful_payloads),
            tuple(unique_items.values()),
            pages=len(calls),
            has_next=has_next,
            next_offset=next_offset,
            gaps=gaps,
        )
        metadata: dict[str, Any] = dict(first.metadata)
        metadata.update(
            {
                "review_pages": len(calls),
                "review_offsets": sorted(seen_offsets),
                "review_unique_count": len(unique_items),
            }
        )
        aggregate_call = SourceCall(
            source=first.source,
            operation=first.operation,
            success=True,
            data=aggregate,
            metadata=metadata,
            raw_payload={"pages": pages},
        )
        return ReviewCollectionResult(
            call=aggregate_call,
            gaps=tuple(gaps),
            raw_pages=tuple(pages),
        )

    async def _safe_reviews(self, shop_id: str, *, offset: int = 0) -> SourceCall:
        try:
            async with self._semaphore:
                # Dianping's review contract is offset based.  The provider
                # owns its page size; asking for a made-up ``limit`` silently
                # discarded evidence in the previous adapter.
                return await self._source.search_reviews(
                    shop_id,
                    offset=offset,
                    sort="default",
                    review_filter="all",
                )
        except Exception as exc:
            return SourceCall(
                source="dianping",
                operation="reviews.search",
                success=False,
                error_code="source_exception",
                error_message=type(exc).__name__,
                retryable=True,
            )


def _note_entries(payload: Any) -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    if isinstance(payload, Mapping):
        for key in ("notes", "search_items", "items", "results"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                entries.extend(item for item in value if isinstance(item, Mapping))
        data = payload.get("data")
        if isinstance(data, (Mapping, list)):
            entries.extend(_note_entries(data))
    elif isinstance(payload, list):
        entries.extend(item for item in payload if isinstance(item, Mapping))
    return entries


def _place_entries(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("items", "results", "shops", "pois"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, Mapping)]
        shop = payload.get("shop")
        if isinstance(shop, Mapping):
            return [shop]
        data = payload.get("data")
        if isinstance(data, (Mapping, list)):
            return _place_entries(data)
    elif isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _comment_envelope_stats(value: Mapping[str, Any]) -> tuple[int, bool, str | None, int]:
    """Read the XHS comments envelope without assuming one response layer."""

    expected = _int_value(
        _first(value, "comment_count", "comments_count", "commentCount")
    )
    has_more = False
    cursor: str | None = None
    page_count = 0
    envelopes: list[Mapping[str, Any]] = []
    comments = value.get("comments")
    if isinstance(comments, Mapping):
        envelopes.append(comments)
    for envelope in envelopes:
        has_more = bool(envelope.get("has_more", envelope.get("hasNext", False)))
        cursor = _text(_first(envelope, "next_cursor", "nextCursor", "cursor")) or None
        pages = envelope.get("pages")
        page_count = max(page_count, len(pages) if isinstance(pages, list) else 0)
        if not expected:
            expected = _int_value(
                _first(envelope, "comment_count", "comments_count", "total", "record_count")
            )
    search_item = _first_mapping(value, "search_item")
    note_card = _first_mapping(value, "note_card") or _first_mapping(search_item, "note_card")
    interact = _first_mapping(note_card, "interact_info", "interactInfo")
    expected = max(expected, _int_value(_first(interact, "comment_count", "comments_count")))
    return expected, has_more, cursor, page_count


def _payload_fingerprint(value: Any) -> str:
    try:
        encoded = repr(value).encode("utf-8", errors="replace")
    except Exception:
        encoded = str(type(value)).encode()
    return hashlib.sha1(encoded).hexdigest()


def _metadata_names(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item) for item in value}
    return set()


def _review_item_id(
    value: Mapping[str, Any],
    *,
    index: int,
    offset: int,
) -> str:
    """Return a stable review key even for a malformed provider row."""

    identifier = _text(_first(value, "review_id", "reviewId", "id"))
    if identifier:
        return identifier
    digest = hashlib.sha1(
        f"{offset}:{index}:{_payload_fingerprint(value)}".encode()
    ).hexdigest()[:24]
    return f"generated-{digest}"


def _review_next_offset(payload: Mapping[str, Any], offset: int, page_count: int) -> int | None:
    candidates: list[Any] = []
    pagination = payload.get("pagination")
    if isinstance(pagination, Mapping):
        candidates.extend(
            pagination.get(key)
            for key in ("next_start_index", "next_offset", "nextStartIndex", "nextOffset")
        )
    completeness = payload.get("completeness")
    if isinstance(completeness, Mapping):
        continuation = completeness.get("continuation")
        if isinstance(continuation, Mapping):
            candidates.extend(
                continuation.get(key)
                for key in ("next_offset", "next_start_index", "nextOffset", "nextStartIndex")
            )
    for value in candidates:
        parsed = _optional_int(value)
        if parsed is not None and parsed > offset:
            return parsed
    if page_count > 0 and _review_has_next(payload):
        return offset + page_count
    return None


def _review_has_next(payload: Mapping[str, Any]) -> bool:
    pagination = payload.get("pagination")
    if isinstance(pagination, Mapping):
        if isinstance(pagination.get("has_next"), bool):
            return bool(pagination["has_next"])
        if isinstance(pagination.get("hasNext"), bool):
            return bool(pagination["hasNext"])
        if isinstance(pagination.get("is_end"), bool):
            return not bool(pagination["is_end"])
    completeness = payload.get("completeness")
    if isinstance(completeness, Mapping):
        continuation = completeness.get("continuation")
        if isinstance(continuation, Mapping) and any(
            continuation.get(key) not in (None, "")
            for key in ("next_offset", "next_start_index", "nextOffset", "nextStartIndex")
        ):
            return True
        corpus = completeness.get("corpus")
        if isinstance(corpus, Mapping) and corpus.get("status") == "complete":
            return False
        if completeness.get("complete") is False:
            return True
    return False


def _review_total_count(payload: Mapping[str, Any]) -> int | None:
    """Read a provider corpus count when pagination flags are incomplete."""

    for key in ("record_count", "total_count", "total", "count"):
        value = _optional_int(payload.get(key))
        if value is not None:
            return value
    completeness = payload.get("completeness")
    if isinstance(completeness, Mapping):
        for key in ("total_count", "record_count", "total"):
            value = _optional_int(completeness.get(key))
            if value is not None:
                return value
        corpus = completeness.get("corpus")
        if isinstance(corpus, Mapping):
            for key in ("total_count", "record_count", "total"):
                value = _optional_int(corpus.get(key))
                if value is not None:
                    return value
    return None


def _aggregate_review_payload(
    first: Mapping[str, Any],
    pages_payloads: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    *,
    pages: int,
    has_next: bool,
    next_offset: int | None,
    gaps: Sequence[ResearchGap],
) -> dict[str, Any]:
    """Merge pages while retaining provider metadata and unknown fields."""

    aggregate = dict(first)
    aggregate["items"] = [dict(item) for item in items]
    aggregate["result_count"] = len(items)
    pagination = first.get("pagination")
    if isinstance(pagination, Mapping):
        merged_pagination = dict(pagination)
        merged_pagination["pages_collected"] = pages
        merged_pagination["collected_count"] = len(items)
        merged_pagination["has_next"] = has_next
        merged_pagination["is_end"] = not has_next
        if next_offset is not None:
            merged_pagination["next_start_index"] = next_offset
        aggregate["pagination"] = merged_pagination

    completeness = first.get("completeness")
    if isinstance(completeness, Mapping):
        merged_completeness = dict(completeness)
        merged_completeness["complete"] = not has_next and not gaps
        merged_completeness["status"] = "complete" if not has_next and not gaps else "partial"
        corpus = completeness.get("corpus")
        if isinstance(corpus, Mapping):
            merged_corpus = dict(corpus)
            merged_corpus["collected_count"] = len(items)
            merged_corpus["status"] = "complete" if not has_next and not gaps else "partial"
            merged_completeness["corpus"] = merged_corpus
        continuation = completeness.get("continuation")
        if isinstance(continuation, Mapping):
            merged_continuation = dict(continuation)
            merged_continuation["next_offset"] = next_offset
            merged_completeness["continuation"] = merged_continuation
        existing_gaps = completeness.get("gaps")
        provider_gaps = list(existing_gaps) if isinstance(existing_gaps, list) else []
        provider_gaps.extend(
            {"code": gap.code, "message": gap.message, "details": dict(gap.details)}
            for gap in gaps
        )
        if provider_gaps:
            merged_completeness["gaps"] = provider_gaps
        aggregate["completeness"] = merged_completeness
    else:
        aggregate["completeness"] = {
            "contract_version": "agent-review-completeness/v1",
            "status": "complete" if not has_next and not gaps else "partial",
            "complete": not has_next and not gaps,
            "pages_collected": pages,
            "collected_count": len(items),
            "next_offset": next_offset,
            "gaps": [
                {"code": gap.code, "message": gap.message, "details": dict(gap.details)}
                for gap in gaps
            ],
        }
    # A page-level raw envelope is retained under the provider's own field,
    # while callers also receive the outer MCP payload through SourceCall.
    provider_raw: list[Any] = []
    for page in pages_payloads:
        raw_responses = page.get("raw_responses")
        if isinstance(raw_responses, list):
            provider_raw.extend(raw_responses)
        elif page.get("raw_response") is not None:
            provider_raw.append(page.get("raw_response"))
    if provider_raw:
        aggregate["raw_responses"] = provider_raw
    return aggregate


def _detail_note_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    detail = value.get("detail")
    if not isinstance(detail, Mapping):
        return {}
    return _detail_mapping(detail)


def _note_id(value: Mapping[str, Any]) -> str:
    nested = _first_mapping(value, "note_card", "search_item", "note")
    search_item = _first_mapping(value, "search_item")
    note_card = _first_mapping(nested, "note_card") or _first_mapping(search_item, "note_card")
    raw = (
        _first(value, "note_id", "noteId", "id")
        or _first(nested, "note_id", "noteId", "id")
        or _first(note_card, "note_id", "noteId", "id")
    )
    return _text(raw)


def _extract_comments(value: Any, *, _depth: int = 0) -> list[Mapping[str, Any]]:
    if _depth > 5:
        return []
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        for key in ("comments", "comment_list", "commentList", "comment_items", "items"):
            items = value.get(key)
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    if _looks_like_comment(item):
                        found.append(item)
                    # Replies are commonly nested below a comment object and
                    # are not represented in the parent list. Recurse into
                    # each item so they remain evidence too.
                    found.extend(_extract_comments(item, _depth=_depth + 1))
        comment_keys = {
            "comments",
            "comment_list",
            "commentList",
            "comment_items",
            "items",
        }
        for key, child in value.items():
            # The first group is consumed above.  Page and reply containers
            # must still be traversed: they often contain comments that are
            # absent from the flattened ``items`` list.
            if key in comment_keys and isinstance(child, list):
                continue
            if isinstance(child, (Mapping, list)):
                found.extend(_extract_comments(child, _depth=_depth + 1))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, Mapping):
                # A list of comments can be recognised by a text-like field.
                if _looks_like_comment(child):
                    found.append(child)
                found.extend(_extract_comments(child, _depth=_depth + 1))
    return found


def _looks_like_comment(value: Mapping[str, Any]) -> bool:
    """Reject note metadata (for example ``corner_tag_info``) as comments."""

    has_text = any(key in value for key in ("content", "text", "comment_text", "body"))
    has_identity = _first(
        value,
        "id",
        "comment_id",
        "commentId",
        "user_info",
        "user",
        "author",
        "like_count",
        "sub_comment_count",
    ) is not None
    return has_text and has_identity


def _normalise_comments(
    note_id: str,
    values: Sequence[Mapping[str, Any]],
    *,
    operation: str,
    page_cursor: str | None,
) -> list[CommentEvidence]:
    output: list[CommentEvidence] = []
    for index, raw in enumerate(values):
        nested = _first_mapping(raw, "comment_info", "commentInfo", "comment")
        text = _text(_first(raw, "content", "text", "comment_text", "body"))
        if not text:
            text = _text(_first(nested, "content", "text", "comment_text", "body"))
        identifier = _text(_first(raw, "comment_id", "commentId", "id"))
        if not identifier:
            digest = hashlib.sha1(f"{note_id}\0{text}\0{index}".encode()).hexdigest()[:20]
            identifier = f"generated-{digest}"
        likes = _int_value(_first(raw, "likes", "like_count", "likeCount", "liked_count"))
        replies = _int_value(_first(raw, "replies", "reply_count", "replyCount", "sub_comment_count"))
        author = _first_mapping(raw, "user", "author", "user_info", "userInfo") or {}
        parent = _first_mapping(raw, "target_comment", "parent_comment", "parentComment")
        parent_id = _text(_first(raw, "parent_comment_id", "parentCommentId")) or _text(
            _first(parent, "id", "comment_id", "commentId")
        )
        metadata: dict[str, Any] = {
            "ip_location": _text(_first(raw, "ip_location", "ipLocation")) or None,
            "pictures": list(_as_tuple(raw.get("pictures") or raw.get("images"))),
            "tags": list(_as_tuple(raw.get("show_tags") or raw.get("tags"))),
            "is_reply": bool(parent_id),
        }
        if page_cursor is not None:
            metadata["page_cursor"] = page_cursor
        if parent_id:
            metadata["parent_comment_id"] = parent_id
        output.append(
            CommentEvidence(
                note_id=note_id,
                comment_id=identifier,
                text=text,
                author=dict(author),
                likes=max(0, likes),
                replies=max(0, replies),
                created_at=_datetime(_first(raw, "created_at", "createdAt", "create_time", "time")),
                raw_payload=dict(raw),
                provenance={"operation": operation, "source_id": identifier},
                metadata=metadata,
            )
        )
    return output


def _dedupe_comments(values: Sequence[CommentEvidence]) -> list[CommentEvidence]:
    seen: set[tuple[str, str]] = set()
    output: list[CommentEvidence] = []
    for item in values:
        key = (item.note_id, item.comment_id)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _next_cursor(payload: Any) -> str | None:
    for source in _mapping_nodes(payload):
        value = _first(source, "next_cursor", "nextCursor", "cursor")
        has_next = _first(source, "has_more", "has_next", "hasNext")
        if value and has_next is not False:
            return _text(value) or None
    return None


def _has_more(payload: Any) -> bool | None:
    for source in _mapping_nodes(payload):
        for key in ("has_more", "has_next", "hasNext"):
            if key in source and isinstance(source[key], bool):
                return source[key]
    return None


def _profile_from_item(
    item: Mapping[str, Any],
    payload: Mapping[str, Any],
    gaps: Sequence[ResearchGap],
) -> ShopProfile:
    item = _flatten_shop_item(item)
    shop_id = _text(_first(item, "shop_id", "shopId", "id", "poi_id"))
    images = _as_tuple(item.get("images") or item.get("image_list") or item.get("photos"))
    image_url = _media_url(
        _first(item, "image_url", "imageUrl", "cover", "cover_url", "coverUrl", "main_image")
    )
    if image_url and not any(_media_url(value) == image_url for value in images):
        images = (image_url, *images)
    dishes = _string_tuple(
        item.get("recommended_dishes")
        or item.get("recommendedDishes")
        or item.get("dishes")
        or item.get("popular_dishes")
    )
    promotions = _as_tuple(item.get("promotions") or item.get("promotion"))
    tags = _string_tuple(item.get("tags") or item.get("labels") or item.get("特徴"))
    name = _text(_first(item, "name", "shop_name", "shopName")) or "未命名店铺"
    outcome = ResearchOutcome.COMPLETE if not gaps else ResearchOutcome.PARTIAL
    geo = _geo_mapping(item)
    latitude = _float_value(_first(item, "latitude", "lat"))
    longitude = _float_value(_first(item, "longitude", "lng", "lon"))
    if latitude is None:
        latitude = _float_value(_first(geo, "latitude", "lat"))
    if longitude is None:
        longitude = _float_value(_first(geo, "longitude", "lng", "lon"))
    source_url = _text(
        _first(item, "source_url", "sourceUrl")
        or _first(payload, "source_url", "sourceUrl")
        or _first(payload.get("detail") if isinstance(payload.get("detail"), Mapping) else {}, "source_url", "sourceUrl")
        or _first(payload.get("search") if isinstance(payload.get("search"), Mapping) else {}, "source_url", "sourceUrl")
    ) or None
    return ShopProfile(
        provider_refs={"dianping": shop_id} if shop_id else {},
        name=name,
        alias=_text(_first(item, "alias", "branch_name", "branchName")) or None,
        url=_text(_first(item, "url", "shop_url", "shopUrl")) or None,
        image_url=image_url,
        images=_unique_json_values(images),
        address=_text(_first(item, "address", "addr")) or None,
        city=_text(_first(item, "city", "city_name", "cityName")) or None,
        district=_text(_first(item, "district", "area")) or None,
        region=_text(_first(item, "region", "region_name", "regionName")) or None,
        business_area=_text(_first(item, "business_area", "businessArea")) or None,
        location=_location(item),
        latitude=latitude,
        longitude=longitude,
        coordinate_system=_text(
            _first(item, "coordinate_system", "coordinateSystem", "coord_type", "coordType")
        ) or None,
        geo=geo,
        phone=_text(_first(item, "phone", "tel", "telephone")) or None,
        rating=_float_value(_first(item, "rating", "score")),
        review_count=_optional_int(_first(item, "review_count", "reviewCount", "reviews")),
        average_price=_float_value(_first(item, "average_price", "averagePrice", "cost", "avg_price")),
        category=_text(_first(item, "category", "category_name", "categoryName")) or None,
        opening_hours=_string_or_json(
            _first(item, "opening_hours", "business_hours", "open_time", "openTime", "hours")
        ),
        source_url=source_url,
        recommended_dishes=dishes,
        promotions=_unique_json_values(promotions),
        tags=tags,
        attributes=_profile_attributes(item, payload),
        review_completeness=_review_completeness(payload),
        source_payload=dict(payload),
        source_updated_at=_latest_fetched_at(payload),
        fetched_at=datetime.now(UTC),
        outcome=outcome,
        gaps=tuple(gaps),
    )


def _merge_review_fields(item: Mapping[str, Any], reviews: Any) -> Mapping[str, Any]:
    if not isinstance(reviews, Mapping):
        return item
    merged = dict(item)
    review_items = reviews.get("items")
    dishes: list[str] = list(
        _string_tuple(
            merged.get("recommended_dishes")
            or merged.get("recommendedDishes")
            or merged.get("dishes")
            or merged.get("popular_dishes")
        )
    )
    images: list[Any] = []
    for key in ("images", "image_list", "imageList", "photos"):
        images.extend(_as_tuple(merged.get(key)))
    tags: list[str] = list(_string_tuple(merged.get("tags") or merged.get("labels")))
    promotions: list[Any] = []
    for key in ("promotions", "promotion", "promotion_list", "promotionList"):
        promotions.extend(_as_tuple(merged.get(key)))
    if isinstance(review_items, list):
        for review in review_items:
            if not isinstance(review, Mapping):
                continue
            dishes.extend(_string_tuple(review.get("recommended_dishes") or review.get("dishes")))
            for key in ("images", "image_list", "imageList", "photos", "videos"):
                images.extend(_as_tuple(review.get(key)))
            tags.extend(_string_tuple(review.get("tags") or review.get("labels")))
            for key in ("promotions", "promotion", "promotion_list", "promotionList"):
                promotions.extend(_as_tuple(review.get(key)))
    merged["recommended_dishes"] = tuple(dict.fromkeys(dishes))
    # Keep provider media/promotion objects intact.  They often contain the
    # URL plus dimensions, labels, or deal metadata used by downstream UI.
    merged["images"] = _unique_json_values(images)
    merged["tags"] = tuple(dict.fromkeys(tags))
    merged["promotions"] = _unique_json_values(promotions)
    merged["_review_completeness"] = reviews.get("completeness")
    merged["_review_protocol"] = reviews.get("protocol")
    merged["_review_available_filters"] = reviews.get("available_filters")
    merged["_review_record_count"] = reviews.get("record_count")
    merged["_review_result_count"] = reviews.get("result_count")
    merged["_review_pagination"] = reviews.get("pagination")
    merged["_review_split_tips"] = reviews.get("split_tips")
    merged["_review_shop"] = reviews.get("shop")
    review_shop = reviews.get("shop")
    if isinstance(review_shop, Mapping):
        for key, value in review_shop.items():
            if merged.get(key) in (None, "", [], {}, ()) and value not in (None, "", [], {}, ()):
                merged[key] = value
    review_geo = _review_geo(reviews)
    if review_geo:
        merged.setdefault("geo", review_geo)
        merged.setdefault("latitude", review_geo.get("latitude"))
        merged.setdefault("longitude", review_geo.get("longitude"))
        merged.setdefault("coordinate_system", review_geo.get("coordinate_system"))
    return merged


def _missing_profile_fields(item: Mapping[str, Any]) -> set[str]:
    fields = {
        "address": ("address", "addr"),
        "location": ("location", "lat", "lng", "latitude", "longitude"),
        "dishes": ("recommended_dishes", "recommendedDishes", "dishes"),
        "images": ("images", "photos", "image_url", "imageUrl"),
    }
    return {name for name, keys in fields.items() if not any(item.get(key) for key in keys)}


def _best_place_match(name: str, items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    target = _normalise_name(name)
    if not target:
        return None
    exact = [item for item in items if _normalise_name(_text(_first(item, "name", "shop_name", "shopName"))) == target]
    if exact:
        return exact[0]
    for item in items:
        candidate = _normalise_name(_text(_first(item, "name", "shop_name", "shopName")))
        if candidate and (candidate in target or target in candidate):
            return item
    return None


def _normalise_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def _placeholder_profile(name: str, gap: ResearchGap) -> ShopProfile:
    return ShopProfile(name=name or "未命名店铺", outcome=ResearchOutcome.PARTIAL, gaps=(gap,))


def _dedupe_profiles(values: Sequence[ShopProfile]) -> list[ShopProfile]:
    """Collapse repeated provider hits without losing richer later fields."""

    indexed: dict[str, ShopProfile] = {}
    for profile in values:
        provider_ref = profile.provider_refs.get("dianping")
        key = f"dianping:{provider_ref}" if provider_ref else f"name:{_normalise_name(profile.name)}"
        existing = indexed.get(key)
        indexed[key] = profile if existing is None else merge_profiles(existing, profile)
    return list(indexed.values())


def _is_interactive_gap(gap: ResearchGap) -> bool:
    text = f"{gap.code} {gap.message}".casefold()
    return any(token in text for token in ("verification", "captcha", "challenge", "interactive")) or "403" in text


def _gap_from_call(call: SourceCall) -> ResearchGap:
    return ResearchGap(
        source=call.source,
        operation=call.operation,
        code=call.error_code or "source_failed",
        message=call.error_message or "provider call failed",
        retryable=call.retryable,
        details=dict(call.metadata),
    )


def _gap(source: str, operation: str, code: str, exc: BaseException) -> ResearchGap:
    return ResearchGap(
        source=source,
        operation=operation,
        code=code,
        message=type(exc).__name__,
        retryable=True,
    )


def _first(value: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    return None


def _first_mapping(value: Mapping[str, Any] | None, *keys: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    for key in keys:
        child = value.get(key)
        if isinstance(child, Mapping):
            return child
    return {}


def _detail_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    shop = value.get("shop")
    if isinstance(shop, Mapping):
        return shop
    data = value.get("data")
    if isinstance(data, Mapping):
        shop = data.get("shop")
        if isinstance(shop, Mapping):
            return shop
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], Mapping):
            return items[0]
        return data
    items = value.get("items")
    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    return value


def _mapping_nodes(value: Any, *, _depth: int = 0) -> tuple[Mapping[str, Any], ...]:
    """Return bounded mapping nodes for nested provider envelopes."""

    if _depth > 5:
        return ()
    if isinstance(value, Mapping):
        nodes: list[Mapping[str, Any]] = [value]
        for child in value.values():
            if isinstance(child, (Mapping, list)):
                nodes.extend(_mapping_nodes(child, _depth=_depth + 1))
        return tuple(nodes)
    if isinstance(value, list):
        nodes: list[Mapping[str, Any]] = []
        for child in value:
            if isinstance(child, (Mapping, list)):
                nodes.extend(_mapping_nodes(child, _depth=_depth + 1))
        return tuple(nodes)
    return ()


def _flatten_shop_item(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Overlay a nested ``shop`` object while retaining provider extensions."""

    shop = value.get("shop")
    if not isinstance(shop, Mapping):
        return value
    merged = dict(value)
    for key, child in shop.items():
        if child not in (None, "", [], {}, ()):
            merged.setdefault(key, child)
    return merged


def _profile_attributes(item: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    known = {
        "shop_id", "shopId", "id", "poi_id", "name", "shop_name", "shopName",
        "alias", "branch_name", "branchName", "url", "shop_url", "shopUrl",
        "image_url", "imageUrl", "cover", "images", "image_list", "photos",
        "address", "addr", "city", "city_name", "cityName", "district", "area",
        "region", "region_name", "regionName", "business_area", "businessArea",
        "location", "coordinate", "coordinates", "latlng", "lat", "lng", "lon",
        "latitude", "longitude", "coordinate_system", "coordinateSystem", "coord_type", "coordType",
        "geo", "phone", "tel", "telephone", "rating", "score",
        "review_count", "reviewCount", "reviews", "average_price", "averagePrice",
        "cost", "avg_price", "category", "category_name", "categoryName",
        "opening_hours", "business_hours", "open_time", "openTime", "hours",
        "recommended_dishes", "recommendedDishes", "dishes", "popular_dishes",
        "promotions", "promotion", "tags", "labels", "特徴", "source_url", "sourceUrl",
        "branch_url", "branchUrl", "_review_completeness", "_review_protocol",
        "_review_available_filters", "_review_record_count", "_review_result_count",
        "_review_pagination", "_review_split_tips", "_review_shop",
    }
    attributes = {str(key): value for key, value in item.items() if key not in known}
    for key in (
        "_review_protocol",
        "_review_available_filters",
        "_review_record_count",
        "_review_result_count",
        "_review_pagination",
        "_review_split_tips",
        "_review_shop",
    ):
        if key in item:
            attributes[key.removeprefix("_review_")] = item[key]
    if isinstance(payload.get("search"), Mapping):
        search = payload["search"]
        for key in ("query", "source_url", "fetched_at", "available_filters"):
            if key in search and key not in attributes:
                attributes[f"search_{key}"] = search[key]
    if isinstance(payload.get("detail"), Mapping):
        detail = payload["detail"]
        for key in ("source_url", "fetched_at", "raw_response"):
            if key in detail and key not in attributes:
                attributes[f"detail_{key}"] = detail[key]
    if isinstance(payload.get("reviews"), Mapping):
        reviews = payload["reviews"]
        for key in (
            "protocol",
            "pagination",
            "completeness",
            "available_filters",
            "split_tips",
            "record_count",
            "result_count",
            "raw_responses",
        ):
            if key in reviews and key not in attributes:
                attributes[f"reviews_{key}"] = reviews[key]
    return attributes


def _review_completeness(payload: Mapping[str, Any]) -> dict[str, Any]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, Mapping):
        return {}
    value = reviews.get("completeness")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _latest_fetched_at(payload: Mapping[str, Any]) -> datetime | None:
    values: list[datetime] = []
    for key in ("search", "detail", "reviews"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            parsed = _datetime(value.get("fetched_at"))
            if parsed is not None:
                values.append(parsed)
    return max(values) if values else None


def _review_geo(reviews: Mapping[str, Any]) -> dict[str, Any]:
    """Extract coordinates exposed in Dianping review extension metadata."""

    raw_items = reviews.get("items")
    if not isinstance(raw_items, list):
        return {}
    for review in raw_items:
        if not isinstance(review, Mapping):
            continue
        raw = review.get("raw")
        if not isinstance(raw, Mapping):
            continue
        extensions = raw.get("extInfoList")
        if not isinstance(extensions, list):
            continue
        values: dict[str, Any] = {}
        for extension in extensions:
            if not isinstance(extension, Mapping):
                continue
            title = _text(extension.get("title")).casefold()
            extension_values = extension.get("values")
            if not isinstance(extension_values, list) or not extension_values:
                continue
            if title == "fslat":
                values["latitude"] = _float_value(extension_values[0])
            elif title == "fslng":
                values["longitude"] = _float_value(extension_values[0])
        if values.get("latitude") is not None and values.get("longitude") is not None:
            values["coordinate_system"] = "provider"
            return values
    return {}


def _search_query(name: str, intent: FoodSearchIntent) -> str:
    parts = [intent.location.strip(), name.strip()]
    if intent.food_type and intent.food_type not in name:
        parts.append(intent.food_type.strip())
    return " ".join(part for part in parts if part)


def _nested(value: Mapping[str, Any] | None, *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _merge_maps(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if value not in (None, "", [], {}, ()):
            merged[key] = value
    return merged


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _string_or_json(value: Any) -> str | None:
    if value in (None, "", [], {}, ()):
        return None
    if isinstance(value, str):
        return value.strip() or None
    try:
        import json

        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return _text(value) or None


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    try:
        return max(0, int(float(str(value).replace(",", ""))))
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    return _int_value(value) if value is not None else None


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _location(item: Mapping[str, Any]) -> str | None:
    raw_location = _first(item, "location")
    if isinstance(raw_location, str) and raw_location.strip():
        return raw_location.strip()
    value = _geo_mapping(item)
    if value:
        lat = _first(value, "lat", "latitude")
        lng = _first(value, "lng", "lon", "longitude")
        if lat is not None and lng is not None:
            return f"{lat},{lng}"
    if value:
        label = _first(value, "address", "name", "label")
        if label is not None:
            return _text(label) or None
    lat = _first(item, "lat", "latitude")
    lng = _first(item, "lng", "lon", "longitude")
    return f"{lat},{lng}" if lat is not None and lng is not None else None


def _geo_mapping(item: Mapping[str, Any]) -> dict[str, Any]:
    value = _first(item, "geo", "location", "coordinate", "coordinates", "latlng")
    if isinstance(value, Mapping):
        return dict(value)
    lat = _first(item, "lat", "latitude")
    lng = _first(item, "lng", "lon", "longitude")
    if lat is None or lng is None:
        return {}
    return {"latitude": lat, "longitude": lng}


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _unique_json_values(values: Sequence[Any]) -> tuple[Any, ...]:
    """Deduplicate JSON values without flattening structured provider data."""

    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, "", [], {}, ()):
            continue
        try:
            marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            marker = repr(value)
        if marker not in seen:
            seen.add(marker)
            output.append(value)
    return tuple(output)


def _media_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        candidate = _first(
            value,
            "url",
            "image_url",
            "imageUrl",
            "src",
            "origin_url",
            "original_url",
            "large_url",
            "thumb_url",
        )
        return _text(candidate) or None
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    output: list[str] = []
    for item in _as_tuple(value):
        if isinstance(item, Mapping):
            item = _first(item, "name", "dish_name", "dishName", "title", "label")
        text = _text(item)
        if text and text not in output:
            output.append(text)
    return tuple(output)


__all__ = [
    "AdaptiveQueryPlanner",
    "DianpingSourceAdapterFactory",
    "DianpingMcpSource",
    "DianpingShopEnricher",
    "EnrichmentResult",
    "LeadCollectionResult",
    "ReviewCollectionResult",
    "XhsCommentLeadCollector",
    "XhsSourceAdapterFactory",
    "XhsMcpSource",
]
