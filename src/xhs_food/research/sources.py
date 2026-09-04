"""MCP-backed source adapters for comment-first food research."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from xhs_food.contracts import (
    CommentEvidence,
    DianpingSourcePort,
    PlatformChannel,
    ResearchGap,
    ResearchOutcome,
    ResourceClass,
    ShopProfile,
    SourceCall,
    XhsLeadSourcePort,
    XhsNoteLead,
)
from xhs_food.domain_packs.food.intent import FoodSearchIntent

from .mcp import ManagedMcpToolSession
from .repository import merge_profiles
from .resource_limits import (
    BudgetExceededError,
    ResourceCallTimeoutError,
    ResourceCircuitOpenError,
)

ResourceExecutor = Callable[..., Awaitable[Any]]


class XhsMcpSource:
    """Translate semantic XHS operations to the pinned MCP session."""

    def __init__(
        self,
        session: ManagedMcpToolSession,
        *,
        platform: PlatformChannel = PlatformChannel.XHS_PC,
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> None:
        self._session = session
        self._platform = platform
        self._resource_executor = resource_executor

    @property
    def session(self) -> ManagedMcpToolSession:
        """Expose the owned session for explicit lifecycle wiring."""

        return self._session

    async def open(self, context: Any) -> None:
        await self._session.open(context)

    async def close(self) -> None:
        await self._session.close()

    async def search_notes(self, **arguments: Any) -> SourceCall:
        return await self._call(ResourceClass.XHS_SEARCH, "notes.search", arguments)

    async def note_detail(self, note_id: str, **arguments: Any) -> SourceCall:
        return await self._call(
            ResourceClass.XHS_DETAIL,
            "notes.detail",
            {"note_id": note_id, **arguments},
        )

    async def search_comments(self, note_id: str, **arguments: Any) -> SourceCall:
        return await self._call(
            ResourceClass.XHS_COMMENTS,
            "comments.search",
            {"note_id": note_id, **arguments},
        )

    async def _call(
        self,
        resource_class: ResourceClass,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> SourceCall:
        operation = self._session.call
        executor = self._resource_executor
        if executor is None:
            return await operation(self._platform, capability, arguments)
        if hasattr(executor, "execute"):
            value = executor.execute(
                resource_class,
                operation,
                self._platform,
                capability,
                arguments,
            )
        else:
            value = executor(
                resource_class,
                operation,
                self._platform,
                capability,
                arguments,
            )
        if inspect.isawaitable(value):
            return await value
        return value


class DianpingMcpSource:
    """Translate semantic Dianping operations to the pinned MCP session."""

    def __init__(
        self,
        session: ManagedMcpToolSession,
        *,
        platform: PlatformChannel = PlatformChannel.DIANPING,
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> None:
        self._session = session
        self._platform = platform
        self._resource_executor = resource_executor

    @property
    def session(self) -> ManagedMcpToolSession:
        """Expose the owned session for explicit lifecycle wiring."""

        return self._session

    async def open(self, context: Any) -> None:
        await self._session.open(context)

    async def close(self) -> None:
        await self._session.close()

    async def search_places(self, **arguments: Any) -> SourceCall:
        return await self._call(ResourceClass.DIANPING_SEARCH, "places.search", arguments)

    async def place_detail(self, shop_id: str, **arguments: Any) -> SourceCall:
        return await self._call(
            ResourceClass.DIANPING_DETAIL,
            "places.detail",
            {"shop_id": shop_id, **arguments},
        )

    async def search_reviews(self, shop_id: str, **arguments: Any) -> SourceCall:
        return await self._call(
            ResourceClass.DIANPING_REVIEWS,
            "reviews.search",
            {"shop_id": shop_id, **arguments},
        )

    async def _call(
        self,
        resource_class: ResourceClass,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> SourceCall:
        operation = self._session.call
        executor = self._resource_executor
        if executor is None:
            return await operation(self._platform, capability, arguments)
        if hasattr(executor, "execute"):
            value = executor.execute(
                resource_class,
                operation,
                self._platform,
                capability,
                arguments,
            )
        else:
            value = executor(
                resource_class,
                operation,
                self._platform,
                capability,
                arguments,
            )
        if inspect.isawaitable(value):
            return await value
        return value


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


@dataclass(slots=True)
class _LeadCollectionState:
    queries: tuple[str, ...] = ()
    raw_search: list[Any] = field(default_factory=list)
    gaps: list[ResearchGap] = field(default_factory=list)
    candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    note_order: list[str] = field(default_factory=list)
    # The streaming path can complete a low-priority hit before a higher
    # priority search wave returns.  Keep the completed snapshots separately
    # so the final reducer can replace an early emission without losing the
    # ability to yield it promptly.
    completed_notes: dict[str, XhsNoteLead] = field(default_factory=dict)
    final_note_ids: tuple[str, ...] = ()
    stream_reconciled: bool = False


@dataclass(frozen=True, slots=True)
class _XhsCommentPages:
    comments: tuple[CommentEvidence, ...] = ()
    raw_payload: tuple[Any, ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    has_more: bool = False
    cursor: str | None = None
    pages: int = 0
    fingerprints: int = 0
    remaining_gap_recorded: bool = False


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
        search_concurrency: int | None = None,
        detail_concurrency: int | None = None,
        comments_concurrency: int | None = None,
        comment_concurrency: int | None = None,
    ) -> None:
        self._source = source
        self._planner = planner or AdaptiveQueryPlanner()
        self._max_notes = max(1, max_notes)
        self._comment_page_size = max(1, comment_page_size)
        self._max_comment_pages = max(1, max_comment_pages)
        pool_size = max(1, concurrency)
        self._search_semaphore = asyncio.Semaphore(
            max(1, search_concurrency if search_concurrency is not None else pool_size)
        )
        self._detail_semaphore = asyncio.Semaphore(
            max(1, detail_concurrency if detail_concurrency is not None else pool_size)
        )
        comments_size = (
            comments_concurrency
            if comments_concurrency is not None
            else comment_concurrency
            if comment_concurrency is not None
            else pool_size
        )
        self._comments_semaphore = asyncio.Semaphore(max(1, comments_size))
        self._last_stream_result: LeadCollectionResult | None = None

    @property
    def last_stream_result(self) -> LeadCollectionResult | None:
        """Return the aggregate snapshot for the most recent streamed run."""

        return self._last_stream_result

    async def collect(self, intent: FoodSearchIntent) -> LeadCollectionResult:
        state = _LeadCollectionState()
        await self._collect_searches(intent, state)
        selected = sorted(
            state.candidates.values(),
            key=_candidate_sort_key,
        )[: self._max_notes]
        notes = await asyncio.gather(
            *(self._note_worker(item) for item in selected), return_exceptions=True
        )
        output: list[XhsNoteLead] = []
        for value in notes:
            if isinstance(value, BaseException):
                state.gaps.append(_gap("xhs", "note.complete", "source_exception", value))
            else:
                output.append(cast(XhsNoteLead, value))
        output = [self._refresh_search_projection(note, state) for note in output]
        return LeadCollectionResult(
            notes=tuple(output),
            gaps=tuple(state.gaps),
            raw_payload={"queries": list(state.queries), "search": list(state.raw_search)},
        )

    async def iter_notes(
        self,
        intent: FoodSearchIntent,
        *,
        queries: Sequence[str] | None = None,
    ) -> AsyncIterator[XhsNoteLead]:
        """Yield each note as soon as its own evidence collection finishes."""

        state = _LeadCollectionState()
        notes: list[XhsNoteLead] = []
        self._last_stream_result = None
        try:
            async for note in self._iter_notes(intent, state, queries=queries):
                notes.append(note)
                yield note
        finally:
            # Streaming consumers receive the first complete snapshot for each
            # note as soon as its own evidence finishes.  Slower search
            # variants may still contribute duplicate hits afterwards; expose
            # a reconciled aggregate snapshot for callers that need the final
            # lossless projection (the emitted snapshot is intentionally not
            # mutated while analysis is in flight).
            if state.stream_reconciled:
                final_notes = tuple(
                    self._refresh_search_projection(state.completed_notes[note_id], state)
                    for note_id in state.final_note_ids
                    if note_id in state.completed_notes
                )
            else:
                final_notes = tuple(self._refresh_search_projection(note, state) for note in notes)
            self._last_stream_result = LeadCollectionResult(
                notes=final_notes,
                gaps=tuple(state.gaps),
                raw_payload={
                    "queries": list(state.queries),
                    "search": list(state.raw_search),
                },
            )

    async def stream_notes(
        self,
        intent: FoodSearchIntent,
        *,
        queries: Sequence[str] | None = None,
    ) -> AsyncIterator[XhsNoteLead]:
        """Compatibility alias for callers that use the streaming verb."""

        async for note in self.iter_notes(intent, queries=queries):
            yield note

    async def _iter_notes(
        self,
        intent: FoodSearchIntent,
        state: _LeadCollectionState,
        *,
        queries: Sequence[str] | None = None,
    ) -> AsyncIterator[XhsNoteLead]:
        queries = tuple(queries) if queries is not None else tuple(self._planner.plan(intent))
        queries = tuple(dict.fromkeys(str(query).strip() for query in queries if str(query).strip()))
        if not queries:
            queries = tuple(self._planner.plan(intent))
        state.queries = queries
        raw_search: list[Any] = [None] * len(queries)
        search_indices: dict[
            asyncio.Task[tuple[str, int, str, SourceCall | BaseException]], int
        ] = {
            asyncio.create_task(self._search_worker(index, query)): index
            for index, query in enumerate(queries)
        }
        pending: set[asyncio.Task[Any]] = set(search_indices)
        note_ids: set[str] = set()
        note_tasks: dict[asyncio.Task[Any], str] = {}
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                # Reduce each completed search immediately.  Waiting for a
                # contiguous planner-order prefix would let one slow query
                # hold back notes from every faster query, defeating the
                # streaming pipeline.  ``search_order`` is retained on each
                # candidate so the final projection remains deterministic for
                # the records that were accepted.
                for task in sorted(
                    (task for task in done if task in search_indices),
                    key=lambda task: search_indices[task],
                ):
                    value = task.result()
                    _, index, query, result = value
                    if isinstance(result, BaseException):
                        state.gaps.append(
                            _gap("xhs", "notes.search", "source_exception", result)
                        )
                        continue
                    raw_search[index] = (
                        result.raw_payload if result.raw_payload is not None else result.data
                    )
                    if not result.success:
                        state.gaps.append(_gap_from_call(result))
                        continue
                    for note_index, raw_note in enumerate(_note_entries(result.data)):
                        note_id = _note_id(raw_note)
                        if not note_id:
                            state.gaps.append(
                                ResearchGap(
                                    source="xhs",
                                    operation="notes.search",
                                    code="note_id_missing",
                                    message="provider note has no stable identifier",
                                )
                            )
                            continue
                        item = self._record_candidate(
                            state, note_id, raw_note, result, query, index, note_index
                        )
                        if note_id in note_ids or len(note_ids) >= self._max_notes:
                            continue
                        note_ids.add(note_id)
                        note_task = asyncio.create_task(
                            self._note_worker(item)
                        )
                        note_tasks[note_task] = note_id
                        pending.add(note_task)

                # Note completion may race with search completion.  Yielding
                # in stable candidate order for the same event-loop turn
                # avoids set iteration changing the stream transcript; the
                # final reducer also uses the explicit collector_order field.
                completed_note_tasks = sorted(
                    (task for task in done if task in note_tasks),
                    key=lambda task: _candidate_sort_key(
                        state.candidates.get(note_tasks[task], {})
                    ),
                )
                for task in completed_note_tasks:
                    note_id = note_tasks.pop(task)
                    value = task.result()
                    if isinstance(value, BaseException):
                        state.gaps.append(
                            _gap("xhs", "note.complete", "source_exception", value)
                        )
                    else:
                        note = cast(XhsNoteLead, value)
                        state.completed_notes[note_id] = note
                        yield note

            # All search waves have now been reduced.  A fast, lower-priority
            # wave may have already occupied the streaming slots while a
            # slower, higher-priority wave was still in flight.  Reconcile
            # against the complete candidate set and collect only the notes
            # that belong in the deterministic top-k projection.  The source
            # semaphores still bound detail/comment calls during this repair.
            selected = sorted(
                state.candidates.values(),
                key=_candidate_sort_key,
            )[: self._max_notes]
            missing = [
                item
                for item in selected
                if str(item["note_id"]) not in state.completed_notes
            ]
            if missing:
                compensated = await asyncio.gather(
                    *(self._note_worker(item) for item in missing),
                    return_exceptions=True,
                )
                compensation_notes: list[XhsNoteLead] = []
                for item, value in zip(missing, compensated, strict=False):
                    note_id = str(item["note_id"])
                    if isinstance(value, BaseException):
                        state.gaps.append(
                            _gap("xhs", "note.complete", "source_exception", value)
                        )
                        continue
                    note = cast(XhsNoteLead, value)
                    state.completed_notes[note_id] = note
                    compensation_notes.append(note)
                state.final_note_ids = tuple(
                    str(item["note_id"])
                    for item in selected
                    if str(item["note_id"]) in state.completed_notes
                )
                state.stream_reconciled = True
                # Make replacements visible to streaming consumers; the final
                # snapshot below removes superseded lower-priority emissions
                # from the aggregate result.  Set the final ids before yielding
                # so an early close after a replacement remains bounded.
                for note in compensation_notes:
                    yield note
            else:
                state.final_note_ids = tuple(
                    str(item["note_id"])
                    for item in selected
                    if str(item["note_id"]) in state.completed_notes
                )
                state.stream_reconciled = True
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            state.raw_search = [value for value in raw_search if value is not None]

    async def _collect_searches(
        self,
        intent: FoodSearchIntent,
        state: _LeadCollectionState,
    ) -> None:
        """Collect and reduce search waves in planner order for ``collect``."""

        queries = tuple(self._planner.plan(intent))
        state.queries = queries
        results = await asyncio.gather(
            *(self._search_worker(index, query) for index, query in enumerate(queries))
        )
        for _, index, query, result in sorted(results, key=lambda value: value[1]):
            if isinstance(result, BaseException):
                state.gaps.append(_gap("xhs", "notes.search", "source_exception", result))
                continue
            if not result.success:
                state.gaps.append(_gap_from_call(result))
                continue
            for note_index, raw_note in enumerate(_note_entries(result.data)):
                note_id = _note_id(raw_note)
                if not note_id:
                    state.gaps.append(
                        ResearchGap(
                            source="xhs",
                            operation="notes.search",
                            code="note_id_missing",
                            message="provider note has no stable identifier",
                        )
                    )
                    continue
                self._record_candidate(
                    state, note_id, raw_note, result, query, index, note_index
                )
        state.raw_search = []
        for result in sorted(results, key=lambda value: value[1]):
            call = result[3]
            if isinstance(call, BaseException):
                continue
            state.raw_search.append(
                call.raw_payload if call.raw_payload is not None else call.data
            )

    async def _search_worker(
        self,
        index: int,
        query: str,
    ) -> tuple[str, int, str, SourceCall | BaseException]:
        try:
            return "search", index, query, await self._search(query)
        except Exception as exc:
            return "search", index, query, _source_call_from_exception(
                "xhs", "notes.search", exc
            )

    async def _note_worker(
        self,
        item: dict[str, Any],
    ) -> XhsNoteLead | BaseException:
        try:
            return await self._complete_note(item)
        except Exception as exc:
            return exc

    def _record_candidate(
        self,
        state: _LeadCollectionState,
        note_id: str,
        raw_note: Mapping[str, Any],
        result: SourceCall,
        query: str,
        search_index: int,
        note_index: int,
    ) -> dict[str, Any]:
        item = state.candidates.get(note_id)
        if item is None:
            item = {
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
                "search_order": (search_index, note_index, note_id),
            }
            state.candidates[note_id] = item
            state.note_order.append(note_id)
        candidate_order = (search_index, note_index, note_id)
        item["search_order"] = min(_candidate_sort_key(item), candidate_order)
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
        return item

    def _refresh_search_projection(
        self,
        note: XhsNoteLead,
        state: _LeadCollectionState,
    ) -> XhsNoteLead:
        """Include duplicate search envelopes that arrived after streaming."""

        item = state.candidates.get(note.note_id)
        if item is None or not isinstance(note.raw_payload, Mapping):
            return note
        payload = dict(note.raw_payload)
        payload["search"] = list(item["raw"])
        payload["search_envelopes"] = list(item["search_payloads"])
        payload["embedded_comments"] = list(item.get("comments", ()))

        comments = _dedupe_comments(
            [
                *note.comments,
                *_normalise_comments(
                    note.note_id,
                    item.get("comments", ()),
                    operation="notes.search",
                    page_cursor=None,
                ),
            ]
        )
        gaps = list(note.gaps)
        # The note worker owns the actual cursor chain.  A search card often
        # advertises ``has_more`` for an embedded preview even after that
        # chain has been fully consumed; never regress a complete note based
        # on that stale card-level hint.
        has_more = bool(note.comment_has_more)
        cursor = note.comment_cursor
        item_expected = int(item.get("comment_count", 0))
        if item_expected > len(comments) and item_expected > note.comment_count:
            gaps.append(
                ResearchGap(
                    source="xhs",
                    operation="comments.search",
                    code="comment_count_mismatch",
                    message="late search hits advertise more comments than were collected",
                    retryable=True,
                    details={
                        "expected_count": item_expected,
                        "collected_count": len(comments),
                    },
                )
            )
        expected = max(
            note.comment_count,
            int(item.get("comment_count", 0)),
            len(comments),
        )
        completeness = note.comment_completeness
        if has_more or gaps:
            completeness = "partial"
        return note.model_copy(
            update={
                "comments": tuple(comments),
                "comment_count": expected,
                "comment_expected_count": max(
                    note.comment_expected_count or 0,
                    int(item.get("comment_expected_count", 0)),
                    expected,
                ),
                "comment_collected_count": len(comments),
                "comment_has_more": has_more,
                "comment_cursor": cursor if has_more else None,
                "comment_pages": max(
                    note.comment_pages,
                    int(item.get("comment_pages", 0)),
                ),
                "comment_completeness": completeness,
                "outcome": ResearchOutcome.PARTIAL if gaps else note.outcome,
                "gaps": tuple(_dedupe_gaps(gaps)),
                "queries": tuple(
                    dict.fromkeys(
                        (
                            *note.queries,
                            *(str(query) for query in item.get("queries", ()) if query),
                        )
                    )
                ),
                "raw_payload": payload,
            }
        )

    async def _search(self, query: str) -> SourceCall:
        try:
            async with self._search_semaphore:
                return await self._source.search_notes(
                    query=query,
                    keyword=query,
                    count=self._max_notes,
                    include_details=True,
                    include_comments=True,
                )
        except Exception as exc:
            return _source_call_from_exception("xhs", "notes.search", exc)

    async def _complete_note(
        self,
        item: dict[str, Any],
    ) -> XhsNoteLead:
        note_id = str(item["note_id"])
        raw_payload: dict[str, Any] = {
            "search": list(item["raw"]),
            "search_envelopes": list(item.get("search_payloads", ())),
            # Embedded comments are source evidence even when no additional
            # comments.search call is needed. Keep their raw row projection
            # explicit for consumers that do not inspect search envelopes.
            "embedded_comments": list(item.get("comments", ())),
        }
        gaps: list[ResearchGap] = list(item["gaps"])
        comments: list[CommentEvidence] = _normalise_comments(
            note_id, item["comments"], operation="notes.search", page_cursor=None
        )

        # Detail and the first comments page are independent requests.  Only
        # the cursor chain itself remains sequential, so page provenance stays
        # ordered while note-level work overlaps across candidates.
        detail_task = asyncio.create_task(self._safe_detail(note_id))
        comments_task: asyncio.Task[_XhsCommentPages] | None = None
        if not _embedded_comments_complete(item):
            comments_task = asyncio.create_task(self._collect_comment_pages(note_id, item))
        tasks: list[asyncio.Task[Any]] = [detail_task]
        if comments_task is not None:
            tasks.append(comments_task)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        detail = results[0]
        comment_pages: _XhsCommentPages | BaseException = (
            results[1] if comments_task is not None else _XhsCommentPages()
        )
        if isinstance(detail, BaseException):
            if isinstance(detail, asyncio.CancelledError):
                raise detail
            detail = _source_call_from_exception("xhs", "notes.detail", detail)
        if isinstance(comment_pages, BaseException):
            if isinstance(comment_pages, asyncio.CancelledError):
                raise comment_pages
            comment_error = _source_call_from_exception(
                "xhs", "comments.search", comment_pages
            )
            comment_pages = _XhsCommentPages(
                has_more=bool(item.get("comment_has_more")),
                cursor=item.get("comment_cursor"),
                gaps=(_gap_from_call(comment_error),),
                remaining_gap_recorded=True,
            )

        raw_payload["detail"] = (
            detail.raw_payload if detail.raw_payload is not None else detail.data
        )
        if detail.success:
            if _is_xhs_detail_shape(detail.data):
                comments.extend(
                    _normalise_comments(
                        note_id,
                        _extract_comments(detail.data),
                        operation="notes.detail",
                        page_cursor=None,
                    )
                )
            else:
                gaps.append(_unsupported_response_gap(detail))
        else:
            gaps.append(_gap_from_call(detail))
        comments.extend(comment_pages.comments)
        raw_payload["comments"] = list(comment_pages.raw_payload)
        gaps.extend(comment_pages.gaps)
        remaining = comment_pages.has_more
        continuation_cursor = comment_pages.cursor
        remaining_gap_recorded = comment_pages.remaining_gap_recorded

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
        detail_note = _detail_note_mapping(
            {"detail": detail.data} if isinstance(detail.data, Mapping) else {}
        )
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
            # reporting only the additional comments.search calls.
            comment_pages=max(
                int(item.get("comment_pages", 0)) + comment_pages.pages,
                comment_pages.fingerprints,
            ),
            comment_completeness=completeness,
            comments=tuple(deduped),
            queries=tuple(dict.fromkeys(item["queries"])),
            outcome=outcome,
            gaps=tuple(gaps),
            raw_payload=raw_payload,
            metadata={
                "collector_order": list(item["search_order"]),
            },
        )

    async def _collect_comment_pages(
        self,
        note_id: str,
        item: Mapping[str, Any],
    ) -> _XhsCommentPages:
        """Fetch one ordered cursor chain and retain every page envelope."""

        comments: list[CommentEvidence] = []
        raw_payload: list[Any] = []
        gaps: list[ResearchGap] = []
        continuation_cursor: str | None = item.get("comment_cursor")
        remaining = bool(item.get("comment_has_more"))
        remaining_gap_recorded = False
        pages = 0
        seen_page_fingerprints: set[str] = set()
        while pages < self._max_comment_pages:
            pages += 1
            request_cursor = continuation_cursor
            call = await self._safe_comments(note_id, request_cursor)
            raw_payload.append(call.raw_payload if call.raw_payload is not None else call.data)
            # A successful page is evidence even if its MCP metadata reports a
            # limitation.  Preserve it before recording the limitation gap.
            if call.success:
                if not _is_xhs_comments_shape(call.data):
                    remaining = remaining or bool(request_cursor)
                    continuation_cursor = request_cursor
                    remaining_gap_recorded = True
                    gaps.append(_unsupported_response_gap(call))
                    break
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
        return _XhsCommentPages(
            comments=tuple(comments),
            raw_payload=tuple(raw_payload),
            gaps=tuple(gaps),
            has_more=remaining,
            cursor=continuation_cursor if remaining else None,
            pages=pages,
            fingerprints=len(seen_page_fingerprints),
            remaining_gap_recorded=remaining_gap_recorded,
        )

    async def _safe_detail(self, note_id: str) -> SourceCall:
        try:
            async with self._detail_semaphore:
                return await self._source.note_detail(
                    note_id,
                    include_comments=True,
                    max_comments=self._comment_page_size,
                )
        except Exception as exc:
            return _source_call_from_exception("xhs", "notes.detail", exc)

    async def _safe_comments(self, note_id: str, cursor: str | None) -> SourceCall:
        try:
            async with self._comments_semaphore:
                return await self._source.search_comments(
                    note_id,
                    max_comments=self._comment_page_size,
                    cursor=cursor,
                    include_replies=True,
                )
        except Exception as exc:
            return _source_call_from_exception("xhs", "comments.search", exc)


class CapabilityCircuitBreaker:
    """Small run-scoped breaker for provider interactive verification."""

    def __init__(self, challenge_threshold: int = 1) -> None:
        self.challenge_threshold = max(1, challenge_threshold)
        self._challenge_count = 0
        self._open = False
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def challenge_count(self) -> int:
        return self._challenge_count

    async def allow(self) -> bool:
        async with self._lock:
            return not self._open

    async def record_challenge(self) -> None:
        async with self._lock:
            self._challenge_count += 1
            if self._challenge_count >= self.challenge_threshold:
                self._open = True


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


@dataclass(frozen=True, slots=True)
class _CandidateEnrichment:
    name: str
    profile: ShopProfile
    gaps: tuple[ResearchGap, ...] = ()
    raw_search: Any = None


@dataclass(frozen=True, slots=True)
class _PlaceSearchPages:
    """Ordered places.search pages and their normalized aggregate."""

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
        max_place_pages: int = 20,
        max_search_pages: int | None = None,
        review_limit: int = 50,
        detail_on_missing: bool = True,
        concurrency: int = 3,
        candidate_concurrency: int | None = None,
        search_concurrency: int | None = None,
        detail_concurrency: int | None = None,
        reviews_concurrency: int | None = None,
        review_concurrency: int | None = None,
        challenge_threshold: int = 1,
        circuit_breaker_threshold: int | None = None,
    ) -> None:
        self._source = source
        self._max_profiles = max(1, max_profiles)
        self._max_place_pages = max(
            1,
            max_search_pages if max_search_pages is not None else max_place_pages,
        )
        self._review_limit = max(1, review_limit)
        self._detail_on_missing = detail_on_missing
        pool_size = max(1, concurrency)
        self._candidate_semaphore = asyncio.Semaphore(
            max(1, candidate_concurrency if candidate_concurrency is not None else pool_size)
        )
        self._search_semaphore = asyncio.Semaphore(
            max(1, search_concurrency if search_concurrency is not None else pool_size)
        )
        self._detail_semaphore = asyncio.Semaphore(
            max(1, detail_concurrency if detail_concurrency is not None else pool_size)
        )
        reviews_size = (
            reviews_concurrency
            if reviews_concurrency is not None
            else review_concurrency
            if review_concurrency is not None
            else pool_size
        )
        self._reviews_semaphore = asyncio.Semaphore(max(1, reviews_size))
        breaker_threshold = (
            circuit_breaker_threshold
            if circuit_breaker_threshold is not None
            else challenge_threshold
        )
        self._detail_breaker = CapabilityCircuitBreaker(breaker_threshold)
        self._reviews_breaker = CapabilityCircuitBreaker(breaker_threshold)

    async def enrich(
        self,
        candidates: Sequence[str],
        intent: FoodSearchIntent,
    ) -> EnrichmentResult:
        selected = tuple(dict.fromkeys(str(name).strip() for name in candidates if str(name).strip()))[
            : self._max_profiles
        ]
        enriched = await asyncio.gather(
            *(self._enrich_candidate(name, intent) for name in selected),
            return_exceptions=True,
        )
        profiles: list[ShopProfile] = []
        gaps: list[ResearchGap] = []
        raw_searches: dict[str, Any] = {}
        for name, result in zip(selected, enriched, strict=False):
            if isinstance(result, BaseException):
                gap = _gap("dianping", "places.search", "source_exception", result)
                profiles.append(_placeholder_profile(name, gap))
                gaps.append(gap)
                continue
            raw_searches[name] = result.raw_search
            profiles.append(result.profile)
            gaps.extend(result.gaps)
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

    async def _enrich_candidate(
        self,
        name: str,
        intent: FoodSearchIntent,
    ) -> _CandidateEnrichment:
        async with self._candidate_semaphore:
            try:
                search_pages = await self._search_candidate(name, intent)
            except Exception as exc:
                call = _source_call_from_exception("dianping", "places.search", exc)
                gap = _gap_from_call(call)
                return _CandidateEnrichment(name, _placeholder_profile(name, gap), (gap,))

            search = search_pages.call
            raw_search = list(search_pages.raw_pages)
            search_gaps = list(search_pages.gaps)
            if not search.success:
                gap = _gap_from_call(search)
                search_gaps.append(gap)
                return _CandidateEnrichment(
                    name,
                    _placeholder_profile(name, gap, source_payload=raw_search),
                    tuple(search_gaps),
                    raw_search,
                )
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
                return _CandidateEnrichment(
                    name,
                    _placeholder_profile(
                        name,
                        gap,
                        source_payload=raw_search,
                        gaps=search_gaps,
                    ),
                    tuple((*search_gaps, gap)),
                    raw_search,
                )

            shop_id = _text(_first(item, "shop_id", "shopId", "id", "poi_id"))
            payload: dict[str, Any] = {
                # Keep the normalized response and the MCP envelope side by
                # side.  The former feeds field mapping; the latter is the
                # immutable audit copy used for replay/debugging.
                "search": search.data,
                "search_raw": list(raw_search),
                "search_pages": list(raw_search),
                "selected": item,
            }
            item_for_profile: Mapping[str, Any] = item
            item_gaps: list[ResearchGap] = list(search_gaps)
            missing = _missing_profile_fields(item)
            detail_task: asyncio.Task[SourceCall] | None = None
            if self._detail_on_missing and shop_id and missing:
                detail_task = asyncio.create_task(self._safe_detail(shop_id))
            reviews_task: asyncio.Task[ReviewCollectionResult] | None = None
            if shop_id:
                reviews_task = asyncio.create_task(self._collect_reviews(shop_id))

            detail: SourceCall | None = None
            review_collection: ReviewCollectionResult | None = None
            tasks: list[asyncio.Task[Any]] = [
                cast(asyncio.Task[Any], task)
                for task in (detail_task, reviews_task)
                if task is not None
            ]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                result_index = 0
                if detail_task is not None:
                    detail_value = results[result_index]
                    result_index += 1
                    if isinstance(detail_value, BaseException):
                        if isinstance(detail_value, asyncio.CancelledError):
                            raise detail_value
                        detail = _source_call_from_exception(
                            "dianping", "places.detail", detail_value
                        )
                    else:
                        detail = detail_value
                if reviews_task is not None:
                    reviews_value = results[result_index]
                    if isinstance(reviews_value, BaseException):
                        if isinstance(reviews_value, asyncio.CancelledError):
                            raise reviews_value
                        review_collection = ReviewCollectionResult(
                            call=_source_call_from_exception(
                                "dianping", "reviews.search", reviews_value
                            )
                        )
                    else:
                        review_collection = reviews_value

            if detail is not None:
                payload["detail"] = detail.data
                payload["detail_raw"] = (
                    detail.raw_payload if detail.raw_payload is not None else detail.data
                )
                # A challenged/error envelope may still contain useful
                # fields.  Merge them before recording its gap.
                if isinstance(detail.data, Mapping):
                    item_for_profile = _merge_maps(item, _detail_mapping(detail.data))
                if not detail.success and _is_circuit_open_call(detail):
                    item_gaps.append(_capability_skipped_gap("places.detail"))
                elif not detail.success:
                    item_gaps.append(_gap_from_call(detail))

            if review_collection is not None:
                reviews = review_collection.call
                payload["reviews"] = reviews.data
                payload["reviews_raw"] = (
                    list(review_collection.raw_pages)
                    if review_collection.raw_pages
                    else reviews.raw_payload
                )
                if isinstance(reviews.data, Mapping):
                    item_for_profile = _merge_review_fields(item_for_profile, reviews.data)
                if reviews.success:
                    item_gaps.extend(review_collection.gaps)
                elif _is_circuit_open_call(reviews):
                    item_gaps.extend(review_collection.gaps)
                    if not review_collection.gaps:
                        item_gaps.append(_capability_skipped_gap("reviews.search"))
                elif reviews.error_code not in {"MCP_CAPABILITY_UNAVAILABLE", "MCP_NOT_CONFIGURED"}:
                    item_gaps.extend(review_collection.gaps)
                    item_gaps.append(_gap_from_call(reviews))
                else:
                    item_gaps.extend(review_collection.gaps)
            profile = _profile_from_item(item_for_profile, payload, item_gaps)
            return _CandidateEnrichment(name, profile, tuple(item_gaps), raw_search)

    async def _search_candidate(
        self,
        name: str,
        intent: FoodSearchIntent,
    ) -> _PlaceSearchPages:
        """Fetch the ordered places.search page chain without lossy reduction."""

        pages: list[Any] = []
        calls: list[SourceCall] = []
        successful_payloads: list[Mapping[str, Any]] = []
        all_items: list[Mapping[str, Any]] = []
        seen_pages: set[int] = set()
        seen_fingerprints: set[str] = set()
        gaps: list[ResearchGap] = []
        page = 1
        has_next = False
        next_page: int | None = None

        while len(calls) < self._max_place_pages:
            if page in seen_pages:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="places.search",
                        code="repeated_page",
                        message="provider returned a non-advancing places page",
                        retryable=True,
                        details={"page": page},
                    )
                )
                has_next = True
                next_page = page
                break
            seen_pages.add(page)
            call = await self._safe_place_search(name, intent, page=page)
            calls.append(call)
            page_payload = call.raw_payload if call.raw_payload is not None else call.data
            pages.append(page_payload)

            if not call.success:
                if len(calls) > 1:
                    has_next = True
                    next_page = next_page or page
                    gaps.append(_gap_from_call(call))
                    break
                # The first failed envelope is returned intact to the caller,
                # which turns it into the candidate's typed source gap.
                return _PlaceSearchPages(call=call, raw_pages=tuple(pages))

            if not isinstance(call.data, (Mapping, list)):
                shape_gap = ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="unsupported_response_shape",
                    message="Dianping place response must be an object or list",
                    retryable=False,
                    details={"page": page, "type": type(call.data).__name__},
                )
                gaps.append(shape_gap)
                failed = _failed_call_with_gap(call, shape_gap)
                calls[-1] = failed
                if len(calls) == 1:
                    return _PlaceSearchPages(
                        call=failed,
                        gaps=tuple(gaps),
                        raw_pages=tuple(pages),
                    )
                has_next = True
                next_page = next_page or page
                break

            successful_payloads.append(call.data if isinstance(call.data, Mapping) else {})
            page_items = _place_entries(call.data)
            all_items.extend(page_items)
            if page > 1 and "page" in _metadata_names(
                call.metadata.get("dropped_arguments")
            ):
                gap = ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="pagination_argument_unsupported",
                    message="MCP contract does not expose the provider place page argument",
                    retryable=True,
                    details={"page": page},
                )
                gaps.append(gap)
                has_next = True
                next_page = page
                break
            fingerprint = _payload_fingerprint(
                tuple(
                    _place_item_id(item, index=index, page=page)
                    for index, item in enumerate(page_items)
                )
            )
            if fingerprint in seen_fingerprints and page_items:
                gap = ResearchGap(
                    source="dianping",
                    operation="places.search",
                    code="repeated_page",
                    message="provider returned a repeated places page",
                    retryable=True,
                    details={"page": page},
                )
                gaps.append(gap)
                has_next = True
                next_page = _place_next_page(call.data, page, len(page_items)) or page
                break
            seen_fingerprints.add(fingerprint)

            page_has_next = _place_has_next(call.data)
            candidate_next_page = _place_next_page(call.data, page, len(page_items))
            # An explicit next page is stronger than an omitted or stale
            # has_next flag; otherwise provider pages can be silently lost.
            if candidate_next_page is not None:
                page_has_next = True
            has_next = page_has_next
            next_page = candidate_next_page
            if not page_has_next:
                next_page = None
                break
            if next_page is None:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="places.search",
                        code="continuation_page_missing",
                        message="provider indicates more places but returned no usable page",
                        retryable=True,
                        details={"page": page},
                    )
                )
                break
            if next_page <= page:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="places.search",
                        code="repeated_page",
                        message="provider returned a non-advancing places page",
                        retryable=True,
                        details={"page": page, "next_page": next_page},
                    )
                )
                has_next = True
                break
            page = next_page
        else:
            # The loop only reaches this branch when the configured page
            # budget ended while the provider still advertised continuation.
            if has_next:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="places.search",
                        code="pagination_limit_reached",
                        message=f"place search pages exceeded {self._max_place_pages}",
                        retryable=True,
                        details={"next_page": next_page, "pages_collected": len(calls)},
                    )
                )

        first = next(
            (
                call
                for call in calls
                if call.success and isinstance(call.data, (Mapping, list))
            ),
            None,
        )
        if first is None:
            failed = calls[-1] if calls else SourceCall(
                source="dianping",
                operation="places.search",
                success=False,
                error_code="source_failed",
            )
            return _PlaceSearchPages(call=failed, gaps=tuple(gaps), raw_pages=tuple(pages))

        first_data = first.data if isinstance(first.data, Mapping) else {}
        aggregate = _aggregate_place_payload(
            first_data,
            successful_payloads,
            all_items,
            pages=len(calls),
            has_next=has_next,
            next_page=next_page,
            gaps=gaps,
        )
        metadata: dict[str, Any] = dict(first.metadata)
        metadata.update(
            {
                "place_pages": len(calls),
                "place_page_numbers": sorted(seen_pages),
                "place_result_count": len(all_items),
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
        return _PlaceSearchPages(
            call=aggregate_call,
            gaps=tuple(gaps),
            raw_pages=tuple(pages),
        )

    async def _safe_place_search(
        self,
        name: str,
        intent: FoodSearchIntent,
        *,
        page: int,
    ) -> SourceCall:
        try:
            async with self._search_semaphore:
                arguments: dict[str, Any] = {
                    "keyword": _search_query(name, intent),
                    "page": page,
                    "sort": "review_count",
                }
                city_id = getattr(intent, "city_id", None)
                if city_id is not None:
                    arguments["city_id"] = city_id
                return await self._source.search_places(**arguments)
        except Exception as exc:
            return _source_call_from_exception("dianping", "places.search", exc)

    async def _safe_detail(self, shop_id: str) -> SourceCall:
        try:
            async with self._detail_semaphore:
                if not await self._detail_breaker.allow():
                    return _circuit_open_call("places.detail")
                call = await self._source.place_detail(shop_id)
                if _is_interactive_call(call):
                    await self._detail_breaker.record_challenge()
                return call
        except Exception as exc:
            call = _source_call_from_exception("dianping", "places.detail", exc)
            if _is_interactive_call(call):
                await self._detail_breaker.record_challenge()
            return call

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
                    if _is_circuit_open_call(call):
                        gaps.append(_capability_skipped_gap("reviews.search"))
                    return ReviewCollectionResult(call=call, gaps=tuple(gaps), raw_pages=tuple(pages))
                # Keep successfully collected pages and make the uncollected
                # remainder explicit. A later-page failure must never be
                # mistaken for a complete corpus.
                has_next = True
                next_offset = next_offset or offset
                if _is_circuit_open_call(call):
                    gaps.append(_capability_skipped_gap("reviews.search"))
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
                calls[-1] = SourceCall(
                    source=call.source,
                    operation=call.operation,
                    success=False,
                    data=call.data,
                    error_code="unsupported_response_shape",
                    error_message="Dianping review response is not an object",
                    retryable=False,
                    metadata=dict(call.metadata),
                    raw_payload=call.raw_payload,
                )
                has_next = True
                next_offset = next_offset or offset
                break
            successful_payloads.append(call.data)

            raw_items = _review_items(call.data)
            if raw_items is None:
                gaps.append(
                    ResearchGap(
                        source="dianping",
                        operation="reviews.search",
                        code="unsupported_response_shape",
                        message="Dianping review response must contain an items list",
                        retryable=False,
                    )
                )
                calls[-1] = SourceCall(
                    source=call.source,
                    operation=call.operation,
                    success=False,
                    data=call.data,
                    error_code="unsupported_response_shape",
                    error_message="Dianping review response must contain an items list",
                    retryable=False,
                    metadata=dict(call.metadata),
                    raw_payload=call.raw_payload,
                )
                has_next = True
                next_offset = next_offset or offset
                break
            page_items: list[Mapping[str, Any]] = []
            page_item_indexes: list[int] = []
            for index, raw_item in enumerate(raw_items):
                row_gaps = _review_row_gaps(raw_item, index=index, offset=offset)
                gaps.extend(row_gaps)
                if isinstance(raw_item, Mapping):
                    page_items.append(raw_item)
                    page_item_indexes.append(index)
            for index, item in zip(page_item_indexes, page_items, strict=False):
                identifier = _review_item_id(item, index=index, offset=offset)
                # A provider page may contain more records than the requested
                # enrichment budget. Keep the complete raw page above, but
                # cap the normalized profile projection so one oversized page
                # cannot bypass ``review_limit``.
                if identifier not in unique_items and len(unique_items) >= self._review_limit:
                    continue
                unique_items.setdefault(identifier, item)

            fingerprint = _payload_fingerprint(
                tuple(
                    _review_item_id(item, index=index, offset=offset)
                    for index, item in zip(page_item_indexes, page_items, strict=False)
                )
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
            async with self._reviews_semaphore:
                # Dianping's review contract is offset based.  The provider
                # owns its page size; asking for a made-up ``limit`` silently
                # discarded evidence in the previous adapter.
                if not await self._reviews_breaker.allow():
                    return _circuit_open_call("reviews.search")
                call = await self._source.search_reviews(
                    shop_id,
                    offset=offset,
                    sort="default",
                    review_filter="all",
                )
                if _is_interactive_call(call):
                    await self._reviews_breaker.record_challenge()
                return call
        except Exception as exc:
            call = _source_call_from_exception("dianping", "reviews.search", exc)
            if _is_interactive_call(call):
                await self._reviews_breaker.record_challenge()
            return call


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
        for key in ("data", "result", "response", "payload", "body"):
            nested = payload.get(key)
            if isinstance(nested, (Mapping, list)):
                entries = _place_entries(nested)
                if entries:
                    return entries
    elif isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _place_item_id(value: Mapping[str, Any], *, index: int, page: int) -> str:
    """Build a deterministic page fingerprint key for a place row."""

    identifier = _text(_first(value, "shop_id", "shopId", "id", "poi_id"))
    if identifier:
        return identifier
    return f"generated-{page}-{index}-{_payload_fingerprint(value)}"


def _place_pagination_nodes(payload: Any) -> tuple[Mapping[str, Any], ...]:
    """Walk pagination envelopes without treating place rows as metadata."""

    if not isinstance(payload, Mapping):
        return ()
    nodes: list[Mapping[str, Any]] = []
    pending: list[Mapping[str, Any]] = [payload]
    seen: set[int] = set()
    while pending:
        node = pending.pop(0)
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        nodes.append(node)
        for key in (
            "pagination",
            "page_info",
            "pageInfo",
            "paging",
            "meta",
            "completeness",
            "continuation",
            "data",
            "result",
            "response",
            "payload",
            "body",
        ):
            child = node.get(key)
            if isinstance(child, Mapping):
                pending.append(child)
    return tuple(nodes)


def _place_first_mapping(payload: Any, key: str) -> Mapping[str, Any]:
    """Return a nested provider metadata mapping without dropping its fields."""

    for node in _place_pagination_nodes(payload):
        value = node.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _place_pagination_mapping(payload: Any) -> Mapping[str, Any]:
    """Resolve the provider pagination object from any response wrapper."""

    for node in _place_pagination_nodes(payload):
        for key in ("pagination", "page_info", "pageInfo", "paging"):
            value = node.get(key)
            if isinstance(value, Mapping):
                return value
    marker_keys = {
        "has_next",
        "hasNext",
        "has_more",
        "hasMore",
        "is_end",
        "isEnd",
        "complete",
        "status",
        "page",
        "current_page",
        "currentPage",
        "next_page",
        "nextPage",
        "total_pages",
        "totalPages",
        "page_count",
        "pageCount",
    }
    for node in _place_pagination_nodes(payload):
        if any(key in node for key in marker_keys):
            return node
    return {}


def _place_has_next(payload: Any) -> bool:
    """Read an explicit places continuation marker from provider metadata."""

    for node in _place_pagination_nodes(payload):
        for key in ("has_next", "hasNext", "has_more", "hasMore"):
            value = node.get(key)
            if isinstance(value, bool):
                return value
        for key in ("is_end", "isEnd"):
            value = node.get(key)
            if isinstance(value, bool):
                return not value
        complete = node.get("complete")
        if isinstance(complete, bool):
            return not complete
        status = _text(node.get("status")).casefold()
        if status in {"complete", "completed", "done", "end", "ended"}:
            return False
        if status in {"partial", "incomplete", "pending", "more"}:
            return True
    return False


def _place_next_page(payload: Any, page: int, item_count: int) -> int | None:
    """Resolve a provider page continuation, falling back to page + 1."""

    candidates: list[Any] = []
    current_values: list[int] = [page]
    total_pages: list[int] = []
    for node in _place_pagination_nodes(payload):
        candidates.extend(
            node.get(key)
            for key in (
                "next_page",
                "nextPage",
                "next_page_number",
                "nextPageNumber",
            )
        )
        for key in ("page", "current_page", "currentPage", "page_no", "pageNo"):
            parsed = _optional_int(node.get(key))
            if parsed is not None:
                current_values.append(parsed)
        for key in ("total_pages", "totalPages", "page_count", "pageCount"):
            parsed = _optional_int(node.get(key))
            if parsed is not None:
                total_pages.append(parsed)
    for value in candidates:
        if value in (None, ""):
            continue
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    if total_pages and max(current_values) < max(total_pages):
        return max(current_values) + 1
    if _place_has_next(payload):
        # A page-number API has a deterministic continuation even when the
        # provider omits next_page. ``item_count`` is intentionally unused:
        # an empty page with has_next=true is still a valid provider signal.
        _ = item_count
        return page + 1
    return None


def _aggregate_place_payload(
    first: Mapping[str, Any],
    pages_payloads: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    *,
    pages: int,
    has_next: bool,
    next_page: int | None,
    gaps: Sequence[ResearchGap],
) -> dict[str, Any]:
    """Expose all normalized place rows while retaining first-page metadata."""

    aggregate = dict(first)
    aggregate["items"] = [dict(item) for item in items]
    aggregate["result_count"] = len(items)
    pagination = _place_pagination_mapping(first)
    merged_pagination = dict(pagination) if isinstance(pagination, Mapping) else {}
    merged_pagination.update(
        {
            "pages_collected": pages,
            "collected_count": len(items),
            "has_next": has_next,
            "is_end": not has_next,
        }
    )
    if next_page is not None:
        merged_pagination["next_page"] = next_page
    aggregate["pagination"] = merged_pagination
    completeness = _place_first_mapping(first, "completeness")
    merged_completeness = dict(completeness) if isinstance(completeness, Mapping) else {}
    merged_completeness.update(
        {
            "status": "complete" if not has_next and not gaps else "partial",
            "complete": not has_next and not gaps,
            "pages_collected": pages,
            "collected_count": len(items),
            "next_page": next_page,
        }
    )
    if gaps:
        merged_completeness["gaps"] = [
            {
                "code": gap.code,
                "message": gap.message,
                "details": dict(gap.details),
            }
            for gap in gaps
        ]
    aggregate["completeness"] = merged_completeness
    # ``raw_pages`` lives in SourceCall.raw_payload as well as the profile's
    # search_raw projection. Keep provider-level nested raw response fields
    # visible in the normalized aggregate when they exist.
    provider_raw: list[Any] = []
    for page_payload in pages_payloads:
        provider_raw.extend(
            _provider_raw_responses(
                _place_pagination_nodes(page_payload),
            )
        )
    if provider_raw:
        aggregate["raw_responses"] = provider_raw
    return aggregate


def _candidate_sort_key(item: Mapping[str, Any]) -> tuple[int, int, str]:
    """Return the stable planner position used by every candidate reducer."""

    order = item.get("search_order")
    if isinstance(order, (tuple, list)) and len(order) >= 2:
        try:
            query_index = int(order[0])
            note_index = int(order[1])
        except (TypeError, ValueError):
            query_index = note_index = 10**9
        note_id = str(order[2]) if len(order) >= 3 else str(item.get("note_id", ""))
        return query_index, note_index, note_id
    return 10**9, 10**9, str(item.get("note_id", ""))


def _is_xhs_detail_shape(payload: Any) -> bool:
    """Recognise a detail envelope without pretending arbitrary JSON is valid."""

    if not isinstance(payload, Mapping):
        return False
    detail_fields = {
        "note_id",
        "noteId",
        "id",
        "title",
        "display_title",
        "displayTitle",
        "summary",
        "desc",
        "content",
        "full_desc",
        "url",
        "link",
        "comments",
        "comment_list",
        "commentList",
        "comment_items",
        "items",
    }
    for node in _mapping_nodes(payload):
        if any(key in node and node[key] not in (None, "") for key in detail_fields):
            return True
    return False


def _is_xhs_comments_shape(payload: Any) -> bool:
    """Recognise comment pages while rejecting successful opaque error JSON."""

    if isinstance(payload, list):
        return all(_comment_row_shape(value) for value in payload)
    if not isinstance(payload, Mapping):
        return False
    return any(_comment_envelope_shape(node) for node in _mapping_nodes(payload))


def _comment_envelope_shape(value: Mapping[str, Any], *, allow_marker: bool = False) -> bool:
    if _comment_row_shape(value):
        return True
    container_keys = ("comments", "comment_list", "commentList", "comment_items", "items")
    for key in container_keys:
        child = value.get(key)
        if isinstance(child, list):
            return all(_comment_row_shape(item) for item in child)
        if isinstance(child, Mapping) and _comment_envelope_shape(child, allow_marker=True):
            return True
    # An explicitly marked empty page is still a valid response shape.  The
    # marker is intentionally not treated as proof of completeness elsewhere.
    marker_keys = {
        "has_more",
        "has_next",
        "hasNext",
        "hasMore",
        "complete",
        "is_complete",
        "isComplete",
        "status",
        "total",
        "count",
        "next_cursor",
        "nextCursor",
    }
    return allow_marker and any(key in value for key in marker_keys)


def _comment_row_shape(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if _looks_like_comment(value):
        return True
    for key in ("comment_info", "commentInfo", "comment"):
        nested = value.get(key)
        if isinstance(nested, Mapping) and _looks_like_comment(nested):
            return True
    return False


def _unsupported_response_gap(call: SourceCall) -> ResearchGap:
    return ResearchGap(
        source=call.source,
        operation=call.operation,
        code="unsupported_response_shape",
        message=f"{call.source} returned an unsupported response shape",
        retryable=False,
        details={
            "type": type(call.data).__name__,
            "raw_present": call.raw_payload is not None,
        },
    )


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


def _embedded_comments_complete(item: Mapping[str, Any]) -> bool:
    """Return whether search already contains the complete comment set."""

    raw_comments = item.get("comments")
    if not isinstance(raw_comments, Sequence) or isinstance(
        raw_comments, (str, bytes, bytearray)
    ):
        return False
    if bool(item.get("comment_has_more")):
        return False

    # ``has_more`` being absent is not equivalent to ``has_more=false``.  A
    # search card may contain a preview list with no pagination metadata; it
    # must still go through comments.search so the preview cannot masquerade
    # as the full evidence corpus.
    markers = [
        _embedded_comment_completion_marker(value)
        for value in item.get("raw", ())
    ]
    if any(marker is False for marker in markers) or not any(marker is True for marker in markers):
        return False

    # Count distinct embedded rows using the provider id where available. The
    # fallback fingerprint keeps duplicate search hits from inflating the
    # count when a provider omits comment ids.
    identifiers: set[str] = set()
    for value in raw_comments:
        if not isinstance(value, Mapping):
            continue
        identifier = _text(_first(value, "comment_id", "commentId", "id"))
        if identifier:
            identifiers.add(identifier)
        else:
            text = _comment_text(value)
            identifiers.add(f"generated-{_comment_text_fingerprint(item.get('note_id', ''), text)}")
    expected = _int_value(item.get("comment_expected_count") or item.get("comment_count"))
    if expected > 0:
        return len(identifiers) >= expected
    return len(identifiers) == len(raw_comments)


def _embedded_comment_completion_marker(value: Any) -> bool | None:
    """Read completion markers from a note's embedded comment envelopes."""

    if not isinstance(value, Mapping):
        return None
    comments = value.get("comments")
    envelopes: list[Mapping[str, Any]] = []
    if isinstance(comments, Mapping):
        envelopes.append(comments)
    # Some adapters flatten the comment list but keep an explicit completion
    # marker beside it.  Inspect those markers only when a comments container
    # is present; a note/search-level ``has_more`` is otherwise ambiguous.
    if comments is not None:
        envelopes.append(value)
    for envelope in envelopes:
        for key in ("has_more", "has_next", "hasNext", "hasMore"):
            marker = envelope.get(key)
            if isinstance(marker, bool):
                return not marker
        for key in (
            "complete",
            "is_complete",
            "isComplete",
            "comments_complete",
            "commentsComplete",
        ):
            marker = envelope.get(key)
            if isinstance(marker, bool):
                return marker
        status = _text(envelope.get("status")).casefold()
        if status in {"complete", "completed", "done", "end", "ended"}:
            return True
        if status in {"partial", "incomplete", "pending", "more"}:
            return False
    return None


def _payload_fingerprint(value: Any) -> str:
    try:
        encoded = _stable_payload_json(value).encode("utf-8", errors="replace")
    except Exception:
        encoded = str(type(value)).encode()
    return hashlib.sha1(encoded).hexdigest()


def _stable_payload_json(value: Any) -> str:
    """Serialize provider payloads deterministically for deduplication only."""

    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): normalize(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if isinstance(item, (set, frozenset)):
            normalized = [normalize(child) for child in item]
            return sorted(
                normalized,
                key=lambda child: json.dumps(
                    child,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            )
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


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

    raw_identifier = _first(value, "review_id", "reviewId", "id")
    identifier = (
        _text(raw_identifier)
        if isinstance(raw_identifier, (str, int, float)) and not isinstance(raw_identifier, bool)
        else ""
    )
    if identifier:
        return identifier
    digest = hashlib.sha1(
        f"{offset}:{index}:{_payload_fingerprint(value)}".encode()
    ).hexdigest()[:24]
    return f"generated-{digest}"


def _review_row_gaps(
    value: Any,
    *,
    index: int,
    offset: int,
) -> tuple[ResearchGap, ...]:
    """Describe row/field mapping loss while leaving the original row intact."""

    if not isinstance(value, Mapping):
        return (
            ResearchGap(
                source="dianping",
                operation="reviews.search",
                code="malformed_review_row",
                message="Dianping review items must be objects",
                retryable=False,
                details={
                    "index": index,
                    "offset": offset,
                    "type": type(value).__name__,
                },
            ),
        )

    gaps: list[ResearchGap] = []
    identity_keys = ("review_id", "reviewId", "id")
    if not any(
        isinstance(value.get(key), (str, int, float))
        and not isinstance(value.get(key), bool)
        and _text(value.get(key))
        for key in identity_keys
        if key in value
    ):
        gaps.append(
            ResearchGap(
                source="dianping",
                operation="reviews.search",
                code="review_id_missing",
                message="Dianping review row has no usable review id",
                retryable=False,
                details={"index": index, "offset": offset},
            )
        )

    scalar_fields = (
        "review_id",
        "reviewId",
        "id",
        "content",
        "text",
        "summary",
    )
    for field_name in scalar_fields:
        if field_name not in value or value[field_name] in (None, ""):
            continue
        field_value = value[field_name]
        if isinstance(field_value, (str, int, float, bool)):
            continue
        gaps.append(
            _review_field_gap(
                index=index,
                offset=offset,
                field=field_name,
                expected="scalar",
                actual=type(field_value).__name__,
            )
        )

    mapping_fields = ("raw", "score_breakdown", "scoreBreakdown", "comment")
    for field_name in mapping_fields:
        if field_name not in value or value[field_name] in (None, ""):
            continue
        field_value = value[field_name]
        if isinstance(field_value, Mapping):
            continue
        gaps.append(
            _review_field_gap(
                index=index,
                offset=offset,
                field=field_name,
                expected="object",
                actual=type(field_value).__name__,
            )
        )

    collection_fields = (
        "recommended_dishes",
        "recommendedDishes",
        "dishes",
        "popular_dishes",
        "popularDishes",
        "signature_dishes",
        "signatureDishes",
        "must_try",
        "mustTry",
        "images",
        "image_list",
        "imageList",
        "photos",
        "photoList",
        "pictures",
        "pics",
        "promotions",
        "promotion",
        "promotion_list",
        "promotionList",
        "deals",
        "packages",
        "tags",
        "labels",
        "特征",
        "特徴",
        "features",
    )
    for field_name in collection_fields:
        if field_name not in value or value[field_name] in (None, ""):
            continue
        field_value = value[field_name]
        if isinstance(field_value, (str, int, float, Mapping, list, tuple)) and not isinstance(
            field_value, bool
        ):
            continue
        gaps.append(
            _review_field_gap(
                index=index,
                offset=offset,
                field=field_name,
                expected="scalar, object, or array",
                actual=type(field_value).__name__,
            )
        )
    return tuple(gaps)


def _review_field_gap(
    *,
    index: int,
    offset: int,
    field: str,
    expected: str,
    actual: str,
) -> ResearchGap:
    return ResearchGap(
        source="dianping",
        operation="reviews.search",
        code="review_field_mapping_invalid",
        message=f"Dianping review field {field} has an unsupported shape",
        retryable=False,
        details={
            "index": index,
            "offset": offset,
            "field": field,
            "expected": expected,
            "actual": actual,
        },
    )


def _review_envelope_nodes(payload: Any) -> tuple[Mapping[str, Any], ...]:
    """Walk review response wrappers while avoiding individual review rows."""

    if not isinstance(payload, Mapping):
        return ()
    nodes: list[Mapping[str, Any]] = []
    pending: list[Mapping[str, Any]] = [payload]
    seen: set[int] = set()
    while pending:
        node = pending.pop(0)
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        nodes.append(node)
        for key in (
            "data",
            "result",
            "response",
            "payload",
            "body",
            "reviews",
            "pagination",
            "page_info",
            "pageInfo",
            "paging",
            "meta",
            "completeness",
            "continuation",
            "corpus",
        ):
            child = node.get(key)
            if isinstance(child, Mapping):
                pending.append(child)
    return tuple(nodes)


def _review_items(payload: Any) -> list[Any] | None:
    """Read review rows from the common provider response wrappers."""

    for node in _review_envelope_nodes(payload):
        for key in (
            "items",
            "reviews",
            "review_items",
            "reviewItems",
            "review_list",
            "reviewList",
            "records",
        ):
            if key not in node:
                continue
            value = node.get(key)
            if isinstance(value, list):
                return value
    return None


def _review_first_mapping(payload: Any, key: str) -> Mapping[str, Any]:
    """Return the first nested review metadata mapping for a known field."""

    for node in _review_envelope_nodes(payload):
        value = node.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _review_pagination_mapping(payload: Any) -> Mapping[str, Any]:
    """Resolve pagination metadata from direct or wrapped review responses."""

    for node in _review_envelope_nodes(payload):
        for key in ("pagination", "page_info", "pageInfo", "paging"):
            value = node.get(key)
            if isinstance(value, Mapping):
                return value
    marker_keys = {
        "has_next",
        "hasNext",
        "has_more",
        "hasMore",
        "is_end",
        "isEnd",
        "complete",
        "status",
        "next_offset",
        "next_start_index",
        "nextOffset",
        "nextStartIndex",
    }
    for node in _review_envelope_nodes(payload):
        if any(key in node for key in marker_keys):
            return node
    return {}


def _review_next_offset(payload: Mapping[str, Any], offset: int, page_count: int) -> int | None:
    candidates: list[Any] = []
    for node in _review_envelope_nodes(payload):
        candidates.extend(
            node.get(key)
            for key in ("next_start_index", "next_offset", "nextStartIndex", "nextOffset")
        )
    for value in candidates:
        parsed = _optional_int(value)
        if parsed is not None and parsed > offset:
            return parsed
    if page_count > 0 and _review_has_next(payload):
        return offset + page_count
    return None


def _review_has_next(payload: Mapping[str, Any]) -> bool:
    for node in _review_envelope_nodes(payload):
        for key in ("has_next", "hasNext", "has_more", "hasMore"):
            value = node.get(key)
            if isinstance(value, bool):
                return value
        for key in ("is_end", "isEnd"):
            value = node.get(key)
            if isinstance(value, bool):
                return not value
        complete = node.get("complete")
        if isinstance(complete, bool):
            return not complete
        status = _text(node.get("status")).casefold()
        if status in {"complete", "completed", "done", "end", "ended"}:
            return False
        if status in {"partial", "incomplete", "pending", "more"}:
            return True
    return False


def _review_total_count(payload: Mapping[str, Any]) -> int | None:
    """Read a provider corpus count when pagination flags are incomplete."""

    for node in _review_envelope_nodes(payload):
        for key in ("record_count", "total_count", "total", "count"):
            value = _optional_int(node.get(key))
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
    pagination = _review_pagination_mapping(first)
    merged_pagination = dict(pagination)
    merged_pagination["pages_collected"] = pages
    merged_pagination["collected_count"] = len(items)
    merged_pagination["has_next"] = has_next
    merged_pagination["is_end"] = not has_next
    if next_offset is not None:
        merged_pagination["next_start_index"] = next_offset
    aggregate["pagination"] = merged_pagination

    completeness = _review_first_mapping(first, "completeness")
    if completeness:
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
        provider_raw.extend(
            _provider_raw_responses(
                _review_envelope_nodes(page),
            )
        )
    if provider_raw:
        aggregate["raw_responses"] = provider_raw
    return aggregate


def _provider_raw_responses(nodes: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Read one page's raw provider response list from any known envelope.

    A tool adapter may put this audit field beside ``items`` or inside a
    ``response/data`` wrapper.  The outer page ledger remains authoritative;
    this helper only exposes the provider's own raw-response projection on
    the normalized aggregate and intentionally keeps its order/duplicates.
    """

    for node in nodes:
        for key in ("raw_responses", "rawResponses"):
            value = node.get(key)
            if isinstance(value, list):
                return list(value)
        for key in ("raw_response", "rawResponse"):
            if key in node and node[key] is not None:
                return [node[key]]
    return []


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


def _comment_text(raw: Mapping[str, Any]) -> str:
    nested = _first_mapping(raw, "comment_info", "commentInfo", "comment")
    text = _text(_first(raw, "content", "text", "comment_text", "body"))
    return text or _text(_first(nested, "content", "text", "comment_text", "body"))


def _normalise_comment_text(value: str) -> str:
    # Whitespace and case differences are transport artefacts for anonymous
    # rows.  Keep punctuation/content intact so two distinct short comments
    # do not collapse accidentally.
    return re.sub(r"\s+", "", value.casefold()).strip()


def _comment_text_fingerprint(note_id: Any, text: str) -> str:
    identity = f"{note_id}\0{_normalise_comment_text(text)}"
    return hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()[:20]


def _normalise_comments(
    note_id: str,
    values: Sequence[Mapping[str, Any]],
    *,
    operation: str,
    page_cursor: str | None,
) -> list[CommentEvidence]:
    output: list[CommentEvidence] = []
    for raw in values:
        text = _comment_text(raw)
        identifier = _text(_first(raw, "comment_id", "commentId", "id"))
        generated = False
        if not identifier:
            identifier = f"generated-{_comment_text_fingerprint(note_id, text)}"
            generated = True
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
        provenance: dict[str, Any] = {"operation": operation, "source_id": identifier}
        if generated:
            provenance.update(
                {
                    "identity": "text_fingerprint",
                    "fingerprint": identifier.removeprefix("generated-"),
                }
            )
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
                provenance=provenance,
                metadata=metadata,
            )
        )
    return output


def _dedupe_comments(values: Sequence[CommentEvidence]) -> list[CommentEvidence]:
    indexes: dict[tuple[str, str, str], int] = {}
    output: list[CommentEvidence] = []
    for item in values:
        key = _comment_identity(item)
        previous_index = indexes.get(key)
        if previous_index is None:
            indexes[key] = len(output)
            output.append(item)
            continue
        output[previous_index] = _merge_duplicate_comments(output[previous_index], item)
    return output


def _comment_identity(item: CommentEvidence) -> tuple[str, str, str]:
    identifier = str(item.comment_id)
    provenance = item.provenance if isinstance(item.provenance, Mapping) else {}
    if provenance.get("identity") == "text_fingerprint":
        return item.note_id, "text", _normalise_comment_text(item.text)
    return item.note_id, "id", identifier


def _comment_richness(item: CommentEvidence) -> tuple[int, int, int, int, int, int, int, int]:
    metadata = item.metadata if isinstance(item.metadata, Mapping) else {}
    raw = item.raw_payload if isinstance(item.raw_payload, Mapping) else {}
    fields = (
        item.text.strip(),
        item.author,
        item.created_at,
        metadata.get("ip_location"),
        metadata.get("pictures"),
        metadata.get("tags"),
        raw,
    )
    populated = sum(value not in (None, "", (), [], {}) for value in fields)
    return (
        populated,
        len(item.text.strip()),
        len(item.author),
        len(metadata),
        len(raw),
        item.likes,
        item.replies,
        int(item.created_at is not None),
    )


def _merge_duplicate_comments(
    current: CommentEvidence,
    candidate: CommentEvidence,
) -> CommentEvidence:
    selected = candidate if _comment_richness(candidate) > _comment_richness(current) else current
    raw_occurrences: list[Any] = []
    for item in (current, candidate):
        payload = item.raw_payload
        if isinstance(payload, Mapping) and isinstance(payload.get("_duplicate_payloads"), list):
            raw_occurrences.extend(payload["_duplicate_payloads"])
        else:
            raw_occurrences.append(payload)
    selected_payload = selected.raw_payload
    if isinstance(selected_payload, Mapping):
        merged_payload: dict[str, Any] = dict(selected_payload)
    else:
        merged_payload = {"value": selected_payload}
    merged_payload["_duplicate_payloads"] = raw_occurrences

    occurrences: list[dict[str, Any]] = []
    for item in (current, candidate):
        provenance = dict(item.provenance) if isinstance(item.provenance, Mapping) else {}
        prior = provenance.pop("occurrences", None)
        if isinstance(prior, list):
            occurrences.extend(
                dict(value) if isinstance(value, Mapping) else {"value": value}
                for value in prior
            )
        else:
            occurrences.append(provenance)
    merged_provenance = (
        dict(selected.provenance) if isinstance(selected.provenance, Mapping) else {}
    )
    merged_provenance["occurrences"] = occurrences
    merged_metadata = dict(selected.metadata) if isinstance(selected.metadata, Mapping) else {}
    merged_metadata["occurrence_count"] = len(occurrences)
    return selected.model_copy(
        update={
            "raw_payload": merged_payload,
            "provenance": merged_provenance,
            "metadata": merged_metadata,
        }
    )


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
    images = _as_tuple(
        item.get("images")
        or item.get("image_list")
        or item.get("imageList")
        or item.get("photos")
        or item.get("photoList")
        or item.get("pictures")
        or item.get("pics")
    )
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
        or item.get("popularDishes")
        or item.get("signature_dishes")
        or item.get("signatureDishes")
        or item.get("must_try")
        or item.get("mustTry")
    )
    promotions = _as_tuple(
        item.get("promotions")
        or item.get("promotion")
        or item.get("promotion_list")
        or item.get("promotionList")
        or item.get("deals")
        or item.get("packages")
    )
    tags = _string_tuple(
        item.get("tags")
        or item.get("labels")
        or item.get("特徴")
        or item.get("features")
    )
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
            _first(
                item,
                "opening_hours",
                "openingHours",
                "business_hours",
                "businessHours",
                "open_time",
                "openTime",
                "hours",
            )
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
            or merged.get("popularDishes")
            or merged.get("signature_dishes")
            or merged.get("signatureDishes")
            or merged.get("must_try")
            or merged.get("mustTry")
        )
    )
    images: list[Any] = []
    for key in (
        "images",
        "image_list",
        "imageList",
        "photos",
        "photoList",
        "pictures",
        "pics",
    ):
        images.extend(_as_tuple(merged.get(key)))
    tags: list[str] = list(
        _string_tuple(
            merged.get("tags")
            or merged.get("labels")
            or merged.get("特徴")
            or merged.get("features")
        )
    )
    promotions: list[Any] = []
    extension_values: dict[str, list[Any]] = {}
    score_breakdowns: list[Any] = []
    media: list[Any] = []
    for key in (
        "promotions",
        "promotion",
        "promotion_list",
        "promotionList",
        "deals",
        "packages",
    ):
        promotions.extend(_as_tuple(merged.get(key)))
    if isinstance(review_items, list):
        for review in review_items:
            if not isinstance(review, Mapping):
                continue
            dishes.extend(
                _string_tuple(
                    review.get("recommended_dishes")
                    or review.get("recommendedDishes")
                    or review.get("dishes")
                    or review.get("popular_dishes")
                    or review.get("popularDishes")
                    or review.get("signature_dishes")
                    or review.get("signatureDishes")
                    or review.get("must_try")
                    or review.get("mustTry")
                )
            )
            for key in (
                "images",
                "image_list",
                "imageList",
                "photos",
                "photoList",
                "pictures",
                "pics",
                "videos",
            ):
                images.extend(_as_tuple(review.get(key)))
            tags.extend(
                _string_tuple(
                    review.get("tags")
                    or review.get("labels")
                    or review.get("特征")
                    or review.get("features")
                )
            )
            for key in (
                "promotions",
                "promotion",
                "promotion_list",
                "promotionList",
                "deals",
                "packages",
            ):
                promotions.extend(_as_tuple(review.get(key)))
            score_breakdown = review.get("score_breakdown")
            if isinstance(score_breakdown, Mapping):
                score_breakdowns.append(dict(score_breakdown))
            for key in (
                "images",
                "image_list",
                "imageList",
                "photos",
                "photoList",
                "pictures",
                "pics",
                "videos",
            ):
                media.extend(_as_tuple(review.get(key)))
            raw = review.get("raw")
            if isinstance(raw, Mapping):
                raw_pictures = raw.get("mixReviewPicList")
                if isinstance(raw_pictures, list):
                    media.extend(raw_pictures)
                raw_scores = raw.get("mixReviewScoreList")
                if isinstance(raw_scores, list):
                    score_breakdowns.extend(
                        dict(score)
                        for score in raw_scores
                        if isinstance(score, Mapping)
                    )
                extensions = raw.get("extInfoList")
                if isinstance(extensions, list):
                    for extension in extensions:
                        if not isinstance(extension, Mapping):
                            continue
                        title = _text(extension.get("title"))
                        values = extension.get("values")
                        if not title or not isinstance(values, list):
                            continue
                        extension_values.setdefault(title, []).extend(values)
                        normalized_title = title.casefold()
                        if any(
                            marker in normalized_title
                            for marker in ("喜欢的菜", "推荐菜", "必点", "招牌菜")
                        ):
                            dishes.extend(_string_tuple(values))
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
    merged["_review_extensions"] = {
        key: list(_unique_json_values(values)) for key, values in extension_values.items()
    }
    merged["_review_score_breakdowns"] = list(_unique_json_values(score_breakdowns))
    merged["_review_media"] = list(_unique_json_values(media))
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
        "dishes": (
            "recommended_dishes",
            "recommendedDishes",
            "dishes",
            "popular_dishes",
            "popularDishes",
            "signature_dishes",
            "signatureDishes",
            "must_try",
            "mustTry",
        ),
        "images": (
            "images",
            "image_list",
            "imageList",
            "photos",
            "photoList",
            "pictures",
            "pics",
            "image_url",
            "imageUrl",
        ),
    }
    return {name for name, keys in fields.items() if not any(item.get(key) for key in keys)}


def _best_place_match(name: str, items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    target = _normalise_name(name)
    if not target:
        return None
    exact = [
        item
        for item in items
        if _normalise_name(_text(_first(item, "name", "shop_name", "shopName"))) == target
    ]
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(exact):
        provider_ref = _text(_first(item, "shop_id", "shopId", "id", "poi_id"))
        identity = provider_ref or f"row:{_payload_fingerprint((index, item))}"
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
    return unique[0] if len(unique) == 1 else None


def _normalise_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def _placeholder_profile(
    name: str,
    gap: ResearchGap,
    *,
    source_payload: Any = None,
    gaps: Sequence[ResearchGap] = (),
) -> ShopProfile:
    """Represent a failed enrichment without discarding its source envelope."""

    return ShopProfile(
        name=name or "未命名店铺",
        outcome=ResearchOutcome.PARTIAL,
        gaps=tuple((*gaps, gap)),
        source_payload=source_payload,
    )


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
    text = f"{gap.code} {gap.message} {gap.details}".casefold()
    return any(token in text for token in ("verification", "captcha", "challenge", "interactive")) or "403" in text


def _is_interactive_call(call: SourceCall) -> bool:
    return not call.success and _is_interactive_gap(_gap_from_call(call))


def _source_call_from_exception(
    source: str,
    operation: str,
    error: BaseException,
) -> SourceCall:
    """Convert runtime failures to typed source results without provider calls.

    Resource failures are control-flow signals for the runtime.  Keeping their
    dimensions in ``SourceCall`` lets the collector preserve partial evidence
    while allowing its normal gap reducer to make the failure actionable.
    ``CancelledError`` is intentionally never passed here: callers let
    cancellation propagate so an aborted run cannot look like a source gap.
    """

    metadata: dict[str, Any] = {"exception_type": type(error).__name__}
    retryable = True
    if isinstance(error, BudgetExceededError):
        error_code = f"budget_{error.dimension}_exhausted"
        metadata["budget_dimension"] = error.dimension
        # A new attempt in this run cannot make a hard budget available again.
        retryable = False
    elif isinstance(error, ResourceCallTimeoutError):
        error_code = "resource_timeout"
        metadata["resource_timeout"] = True
    elif isinstance(error, ResourceCircuitOpenError):
        error_code = "circuit_open"
        metadata.update(
            {
                "circuit_open": True,
                "resource_class": str(error.resource_class),
            }
        )
    else:
        error_code = "source_exception"

    return SourceCall(
        source=source,
        operation=operation,
        success=False,
        error_code=error_code,
        error_message=str(error) or type(error).__name__,
        retryable=retryable,
        metadata=metadata,
    )


def _circuit_open_call(capability: str) -> SourceCall:
    source = "dianping"
    operation = capability
    return SourceCall(
        source=source,
        operation=operation,
        success=False,
        error_code="capability_circuit_open",
        error_message=f"{capability} stopped after provider interactive verification",
        retryable=True,
        metadata={"circuit_open": True, "capability": capability},
    )


def _is_circuit_open_call(call: SourceCall) -> bool:
    return bool(call.metadata.get("circuit_open")) or call.error_code == "capability_circuit_open"


def _capability_skipped_gap(capability: str) -> ResearchGap:
    operation = capability
    label = "detail" if capability == "places.detail" else "reviews"
    return ResearchGap(
        source="dianping",
        operation=operation,
        code=f"{label}_skipped_after_challenge",
        message=f"{capability} calls stopped after provider interactive verification",
        retryable=True,
        details={"capability": capability, "circuit_open": True},
    )


def _failed_call_with_gap(call: SourceCall, gap: ResearchGap) -> SourceCall:
    """Mark a malformed successful envelope as failed without dropping raw data."""

    metadata = dict(call.metadata)
    metadata["validation_gap"] = gap.code
    return SourceCall(
        source=call.source,
        operation=call.operation,
        success=False,
        data=call.data,
        error_code=gap.code,
        error_message=gap.message,
        retryable=gap.retryable,
        metadata=metadata,
        raw_payload=call.raw_payload,
    )


def _gap_from_call(call: SourceCall) -> ResearchGap:
    return ResearchGap(
        source=call.source,
        operation=call.operation,
        code=call.error_code or "source_failed",
        message=call.error_message or "provider call failed",
        retryable=call.retryable,
        details=dict(call.metadata),
    )


def _dedupe_gaps(values: Sequence[ResearchGap]) -> tuple[ResearchGap, ...]:
    """Keep one copy of each typed gap in a reconciled note snapshot."""

    unique: list[ResearchGap] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return tuple(unique)


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
    for key in ("shop", "place", "poi"):
        shop = value.get(key)
        if isinstance(shop, Mapping):
            return shop
    items = value.get("items")
    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    for key in ("data", "result", "response", "payload", "body"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            resolved = _detail_mapping(nested)
            if resolved:
                return resolved
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
    # ``setdefault`` would leave an empty outer field in place and would also
    # discard arrays from the nested response when both layers are present.
    # Use the same non-destructive merge rules as detail enrichment instead.
    return _merge_maps(value, shop)


def _profile_attributes(item: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    known = {
        "shop_id", "shopId", "id", "poi_id", "name", "shop_name", "shopName",
        "alias", "branch_name", "branchName", "url", "shop_url", "shopUrl",
        "image_url", "imageUrl", "cover", "cover_url", "coverUrl", "main_image",
        "images", "image_list", "imageList", "photos", "photoList", "pictures", "pics",
        "address", "addr", "city", "city_name", "cityName", "district", "area",
        "region", "region_name", "regionName", "business_area", "businessArea",
        "location", "coordinate", "coordinates", "latlng", "lat", "lng", "lon",
        "latitude", "longitude", "coordinate_system", "coordinateSystem", "coord_type", "coordType",
        "geo", "phone", "tel", "telephone", "rating", "score",
        "review_count", "reviewCount", "reviews", "average_price", "averagePrice",
        "cost", "avg_price", "category", "category_name", "categoryName",
        "opening_hours", "openingHours", "business_hours", "businessHours", "open_time", "openTime", "hours",
        "recommended_dishes", "recommendedDishes", "dishes", "popular_dishes", "popularDishes",
        "signature_dishes", "signatureDishes", "must_try", "mustTry",
        "promotions", "promotion", "promotion_list", "promotionList", "deals", "packages",
        "tags", "labels", "特征", "特徴", "features", "source_url", "sourceUrl",
        "branch_url", "branchUrl", "_review_completeness", "_review_protocol",
        "_review_available_filters", "_review_record_count", "_review_result_count",
        "_review_pagination", "_review_split_tips", "_review_shop",
        "_review_extensions", "_review_score_breakdowns", "_review_media",
    }
    attributes = {str(key): value for key, value in item.items() if key not in known}
    review_attribute_names = {
        "_review_protocol": "review_protocol",
        "_review_available_filters": "review_available_filters",
        "_review_record_count": "review_record_count",
        "_review_result_count": "review_result_count",
        "_review_pagination": "review_pagination",
        "_review_split_tips": "review_split_tips",
        "_review_shop": "review_shop",
        "_review_extensions": "review_extensions",
        "_review_score_breakdowns": "review_score_breakdowns",
        "_review_media": "review_media",
    }
    for key, attribute_name in review_attribute_names.items():
        if key in item:
            attributes[attribute_name] = item[key]
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

    # Search cards and detail responses commonly use different aliases for
    # the same repeated fields.  Keep the union under the canonical key so a
    # richer detail response cannot overwrite media, dishes, promotions, or
    # tags already discovered by search.
    collection_groups = (
        ("images", "image_list", "imageList", "photos", "photoList", "pictures", "pics"),
        (
            "recommended_dishes",
            "recommendedDishes",
            "dishes",
            "popular_dishes",
            "popularDishes",
            "signature_dishes",
            "signatureDishes",
            "must_try",
            "mustTry",
        ),
        ("promotions", "promotion", "promotion_list", "promotionList", "deals", "packages"),
        ("tags", "labels", "特征", "特徴", "features"),
    )
    string_groups = {"recommended_dishes", "tags"}
    for aliases in collection_groups:
        values: list[Any] = []
        for mapping in (left, right):
            for alias in aliases:
                values.extend(_as_tuple(mapping.get(alias)))
        if not values:
            continue
        canonical = aliases[0]
        if canonical in string_groups:
            merged[canonical] = tuple(
                dict.fromkeys(
                    text for value in values if (text := _text(value))
                )
            )
        else:
            merged[canonical] = _unique_json_values(values)
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
    "DianpingMcpSource",
    "DianpingShopEnricher",
    "EnrichmentResult",
    "LeadCollectionResult",
    "ReviewCollectionResult",
    "XhsCommentLeadCollector",
    "XhsMcpSource",
]
