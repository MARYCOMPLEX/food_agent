"""Typed source failures and early XHS streaming boundaries."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_food.contracts import SourceCall
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research.resource_limits import (
    BudgetExceededError,
    ResourceCallTimeoutError,
    ResourceCircuitOpenError,
)
from xhs_food.research.sources import DianpingShopEnricher, XhsCommentLeadCollector


def _intent() -> FoodSearchIntent:
    return FoodSearchIntent(location="成都", food_type="火锅")


class _RaisingSource:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def search_notes(self, **_: Any) -> SourceCall:
        raise self.error

    async def note_detail(self, *_: Any, **__: Any) -> SourceCall:
        raise self.error

    async def search_comments(self, *_: Any, **__: Any) -> SourceCall:
        raise self.error

    async def search_places(self, **_: Any) -> SourceCall:
        raise self.error

    async def place_detail(self, *_: Any, **__: Any) -> SourceCall:
        raise self.error

    async def search_reviews(self, *_: Any, **__: Any) -> SourceCall:
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    (
        (BudgetExceededError("calls exhausted", dimension="calls"), "budget_calls_exhausted", False),
        (ResourceCallTimeoutError("provider timed out"), "resource_timeout", True),
        (ResourceCircuitOpenError("xhs.search"), "circuit_open", True),
    ),
)
async def test_safe_source_calls_keep_runtime_failure_types(
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    source = _RaisingSource(error)
    collector = XhsCommentLeadCollector(source)
    enricher = DianpingShopEnricher(source)

    calls = (
        await collector._search("火锅"),
        await collector._safe_detail("note-1"),
        await collector._safe_comments("note-1", None),
        await enricher._safe_place_search("火锅店", _intent(), page=1),
        await enricher._safe_detail("shop-1"),
        await enricher._safe_reviews("shop-1"),
    )

    assert all(not call.success for call in calls)
    assert [call.error_code for call in calls] == [code] * len(calls)
    assert [call.retryable for call in calls] == [retryable] * len(calls)
    if code == "circuit_open":
        assert all(call.metadata["circuit_open"] is True for call in calls)
    if code.startswith("budget_"):
        assert all(call.metadata["budget_dimension"] == "calls" for call in calls)


@pytest.mark.asyncio
async def test_safe_source_calls_do_not_translate_cancellation_to_a_gap() -> None:
    source = _RaisingSource(asyncio.CancelledError())
    collector = XhsCommentLeadCollector(source)

    with pytest.raises(asyncio.CancelledError):
        await collector._safe_detail("note-1")


class _EarlyYieldSource:
    def __init__(self) -> None:
        self.slow_started = asyncio.Event()
        self.slow_release = asyncio.Event()
        self.slow_completed = asyncio.Event()
        self.slow_cancelled = asyncio.Event()

    async def search_notes(self, **arguments: Any) -> SourceCall:
        query = str(arguments["query"])
        if query == "慢搜索":
            self.slow_started.set()
            try:
                await self.slow_release.wait()
            except asyncio.CancelledError:
                self.slow_cancelled.set()
                raise
            self.slow_completed.set()
            raw = {"variant": "slow", "provider_unknown": {"kept": True}}
        else:
            await asyncio.sleep(0.01)
            raw = {"variant": "fast"}
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={"notes": [{"note_id": "note-1", "title": "火锅线索"}]},
            raw_payload=raw,
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        await asyncio.sleep(0.01)
        return SourceCall(
            source="xhs",
            operation="notes.detail",
            success=True,
            data={"title": note_id},
            raw_payload={"detail": note_id},
        )

    async def search_comments(self, note_id: str, **_: Any) -> SourceCall:
        await asyncio.sleep(0.01)
        return SourceCall(
            source="xhs",
            operation="comments.search",
            success=True,
            data={"items": [{"id": "comment-1", "content": "值得去"}]},
            raw_payload={"comment_page": note_id},
        )


class _PriorityCompensationSource:
    def __init__(self) -> None:
        self.high_started = asyncio.Event()
        self.high_release = asyncio.Event()

    async def search_notes(self, **arguments: Any) -> SourceCall:
        query = str(arguments["query"])
        if query == "高优先级":
            self.high_started.set()
            await self.high_release.wait()
            note_id = "high-note"
            marker = "high"
        else:
            await asyncio.sleep(0.01)
            note_id = "low-note"
            marker = "low"
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={"notes": [{"note_id": note_id, "title": note_id}]},
            raw_payload={"wave": marker},
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.detail",
            success=True,
            data={"note_id": note_id, "title": note_id},
            raw_payload={"detail": note_id},
        )

    async def search_comments(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="comments.search",
            success=True,
            data={"items": [{"id": f"comment-{note_id}", "content": note_id}], "has_more": False},
            raw_payload={"comment_page": note_id},
        )


@pytest.mark.asyncio
async def test_xhs_stream_compensates_for_a_late_higher_priority_candidate() -> None:
    source = _PriorityCompensationSource()
    collector = XhsCommentLeadCollector(source, max_notes=1, concurrency=2)
    stream = collector.iter_notes(_intent(), queries=("高优先级", "低优先级"))

    first = await asyncio.wait_for(anext(stream), timeout=0.5)
    assert first.note_id == "low-note"
    await asyncio.wait_for(source.high_started.wait(), timeout=0.5)

    source.high_release.set()
    replacement = await asyncio.wait_for(anext(stream), timeout=0.5)
    assert replacement.note_id == "high-note"
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.5)

    final = collector.last_stream_result
    assert final is not None
    assert [note.note_id for note in final.notes] == ["high-note"]
    assert [wave["wave"] for wave in final.raw_payload["search"]] == ["high", "low"]
    assert final.notes[0].metadata["collector_order"] == [0, 0, "high-note"]


@pytest.mark.asyncio
async def test_xhs_stream_yields_note_before_slow_search_and_reconciles_raw_snapshot() -> None:
    source = _EarlyYieldSource()
    collector = XhsCommentLeadCollector(source, max_notes=1, concurrency=2)
    stream = collector.iter_notes(_intent(), queries=("快速搜索", "慢搜索"))

    first = await asyncio.wait_for(anext(stream), timeout=0.5)
    assert first.note_id == "note-1"
    await asyncio.wait_for(source.slow_started.wait(), timeout=0.5)
    assert not source.slow_completed.is_set()
    assert [item["variant"] for item in first.raw_payload["search_envelopes"]] == ["fast"]

    source.slow_release.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.5)

    assert source.slow_completed.is_set()
    final = collector.last_stream_result
    assert final is not None
    assert [item["variant"] for item in final.notes[0].raw_payload["search_envelopes"]] == [
        "fast",
        "slow",
    ]
    assert final.notes[0].raw_payload["search_envelopes"][1]["provider_unknown"] == {
        "kept": True
    }


@pytest.mark.asyncio
async def test_xhs_stream_does_not_wait_for_a_slow_first_query() -> None:
    """A later fast query can feed the pipeline even when query zero stalls."""

    source = _EarlyYieldSource()
    collector = XhsCommentLeadCollector(source, max_notes=1, concurrency=2)
    stream = collector.iter_notes(_intent(), queries=("慢搜索", "快速搜索"))

    first = await asyncio.wait_for(anext(stream), timeout=0.5)
    assert first.note_id == "note-1"
    assert source.slow_started.is_set()
    assert not source.slow_completed.is_set()

    source.slow_release.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.5)
    assert source.slow_completed.is_set()


@pytest.mark.asyncio
async def test_xhs_stream_cancellation_cleans_pending_search_tasks() -> None:
    source = _EarlyYieldSource()
    collector = XhsCommentLeadCollector(source, max_notes=1, concurrency=2)
    stream = collector.iter_notes(_intent(), queries=("快速搜索", "慢搜索"))

    await asyncio.wait_for(anext(stream), timeout=0.5)
    await asyncio.wait_for(source.slow_started.wait(), timeout=0.5)
    await stream.aclose()

    await asyncio.wait_for(source.slow_cancelled.wait(), timeout=0.5)
    assert not source.slow_completed.is_set()
