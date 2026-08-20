"""Shared source consumer suite for legacy and target S3 adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import pytest

from xhs_food.agents.poi_enricher import POIEnricherAgent
from xhs_food.contracts import (
    CanonicalQuery,
    CanonicalSourceBatch,
    CollectRequest,
    ErrorCategory,
    ErrorScope,
    SourceAttemptMetadata,
    SourceAttemptOutcome,
    SourceCoverageMetadata,
)
from xhs_food.gateways import (
    AmapPlaceSourceConnector,
    LegacySourceProjection,
    ProviderResult,
    SourceOutcomeKind,
    XHSSourceConnector,
    classify_batch,
    project_legacy_place,
    project_legacy_xhs,
)
from xhs_food.orchestrator.search_executor import SearchExecutor
from xhs_food.protocols import MCPToolRegistry
from xhs_food.schemas import ConversationContext, RestaurantRecommendation

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
AdapterKind = Literal["legacy", "target"]


class _Provider:
    def __init__(
        self,
        name: str,
        result: object,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def health_check(self) -> bool:
        return True


class _HangingProvider(_Provider):
    def __init__(self) -> None:
        super().__init__("xhs_search", result=None)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("unreachable")


class _AmapClient:
    def __init__(
        self,
        result: object,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, str]] = []

    def search_poi(self, keywords: str, city: str = "", types: str = "050000") -> dict[str, Any]:
        self.calls.append({"keywords": keywords, "city": city, "types": types})
        if self.error is not None:
            raise self.error
        return cast(dict[str, Any], self.result)


def _collect_request(source_id: str = "xhs") -> CollectRequest:
    query = CanonicalQuery.model_validate(
        {
            "schema_version": "canonical-query/v1",
            "normalizer_version": "canonical-normalizer/v1",
            "classifier_version": "food-constraint-classifier/v1",
            "isolation": {
                "tenant_scope": "public",
                "language": "zh-Hans",
                "region": "CN",
            },
            "query": {
                "domain": "food",
                "geo": {
                    "country_code": "CN",
                    "admin_path": ["cn.sc"],
                    "locality": "cn.sc.zigong",
                },
                "intent": {"kind": "recommend", "subject": "restaurant"},
                "audience": ["visitor"],
                "constraints": [],
                "time_range": {
                    "kind": "current",
                    "start": None,
                    "end": None,
                    "timezone": "Asia/Shanghai",
                },
                "freshness_policy": {
                    "policy_id": "food.default",
                    "policy_version": "food-freshness/v1",
                },
            },
        }
    )
    return CollectRequest(query=query, source_scope=(source_id,), depth="standard")


def _xhs_connector(provider: _Provider) -> XHSSourceConnector:
    return XHSSourceConnector(
        search_provider=provider,
        note_provider=_Provider("xhs_note", ProviderResult(success=True, data={"notes": []})),
        batch_provider=_Provider("xhs_batch", ProviderResult(success=True, data={"results": {}})),
        clock=lambda: NOW,
    )


def _legacy_executor() -> SearchExecutor:
    return SearchExecutor(
        xhs_registry=MCPToolRegistry(),
        analyzer=cast(Any, object()),
        context=ConversationContext(),
    )


@dataclass(frozen=True, slots=True)
class _XHSCase:
    name: str
    result: object
    expected_ids: tuple[str, ...]
    expected_kind: SourceOutcomeKind
    expected_attempt: SourceAttemptOutcome
    category: ErrorCategory | None = None
    scope: ErrorScope | None = None
    retryable: bool | None = None
    error: BaseException | None = None


XHS_CASES = (
    _XHSCase(
        "success",
        ProviderResult(
            success=True,
            data={"notes": [{"id": "note-1", "title": "valid"}]},
        ),
        ("note-1",),
        SourceOutcomeKind.SUCCESS,
        SourceAttemptOutcome.SUCCESS_NONEMPTY,
    ),
    _XHSCase(
        "true-empty",
        ProviderResult(success=True, data={"notes": [], "watermark": "w-empty"}),
        (),
        SourceOutcomeKind.EMPTY,
        SourceAttemptOutcome.SUCCESS_EMPTY,
    ),
    _XHSCase(
        "timeout",
        None,
        (),
        SourceOutcomeKind.FAILURE,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.TIMEOUT,
        ErrorScope.SOURCE,
        True,
        TimeoutError("timed out"),
    ),
    _XHSCase(
        "rate-limit",
        ProviderResult(success=False, error_code="HTTP_429"),
        (),
        SourceOutcomeKind.FAILURE,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.RATE_LIMITED,
        ErrorScope.SOURCE,
        True,
    ),
    _XHSCase(
        "malformed",
        ProviderResult(success=True, data={"notes": "not-a-list"}),
        (),
        SourceOutcomeKind.FAILURE,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.MALFORMED_RESPONSE,
        ErrorScope.SOURCE,
        False,
    ),
    _XHSCase(
        "dependency-unavailable",
        ProviderResult(success=False, error_code="SEARCH_FAILED"),
        (),
        SourceOutcomeKind.FAILURE,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.DEPENDENCY_UNAVAILABLE,
        ErrorScope.SOURCE,
        True,
    ),
    _XHSCase(
        "exception",
        None,
        (),
        SourceOutcomeKind.FAILURE,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.INTERNAL,
        ErrorScope.PROVIDER,
        False,
        RuntimeError("provider exploded"),
    ),
    _XHSCase(
        "partial-item",
        ProviderResult(
            success=True,
            data={
                "notes": [
                    {"id": "note-1", "title": "valid"},
                    {"title": "missing id"},
                ]
            },
        ),
        ("note-1",),
        SourceOutcomeKind.PARTIAL,
        SourceAttemptOutcome.PARTIAL,
        ErrorCategory.MALFORMED_RESPONSE,
        ErrorScope.SOURCE,
        False,
    ),
)


@pytest.mark.parametrize("adapter_kind", ("legacy", "target"))
@pytest.mark.parametrize("case", XHS_CASES, ids=lambda case: case.name)
async def test_xhs_legacy_and_target_run_the_same_source_consumer_matrix(
    adapter_kind: AdapterKind,
    case: _XHSCase,
) -> None:
    provider = _Provider("xhs_search", case.result, error=case.error)

    if adapter_kind == "legacy":
        notes = await _legacy_executor().search_with_keyword(provider, "fixture", set())
        item_ids = tuple(str(note["id"]) for note in notes)
        projection = (
            LegacySourceProjection.CONTINUE if item_ids else LegacySourceProjection.TERMINAL_ERROR
        )
    else:
        batch = await _xhs_connector(provider).search(_collect_request())
        outcome = classify_batch(batch)
        item_ids = tuple(item.external_id for item in batch.documents)
        projection = project_legacy_xhs(outcome)

        assert outcome.kind is case.expected_kind
        assert batch.coverage is not None
        assert batch.coverage.eligible_item_count == len(item_ids)
        attempt = batch.coverage.attempts[0]
        assert attempt.outcome is case.expected_attempt
        assert attempt.item_count == len(item_ids)
        assert attempt.error_indexes == tuple(range(len(batch.errors)))
        if case.name == "true-empty":
            assert attempt.watermark == "w-empty"
        if case.category is None:
            assert batch.errors == ()
        else:
            assert len(batch.errors) == 1
            error = batch.errors[0]
            assert error.category is case.category
            assert error.scope is case.scope
            assert error.retryable is case.retryable

    assert item_ids == case.expected_ids
    assert projection is (
        LegacySourceProjection.CONTINUE
        if case.expected_ids
        else LegacySourceProjection.TERMINAL_ERROR
    )
    assert len(provider.calls) == 1


@dataclass(frozen=True, slots=True)
class _AggregateCase:
    name: str
    attempts: tuple[_XHSCase, ...]
    expected_ids: tuple[str, ...]
    expected_kind: SourceOutcomeKind


_CASE_BY_NAME = {case.name: case for case in XHS_CASES}
AGGREGATE_CASES = (
    _AggregateCase(
        "all-empty",
        (_CASE_BY_NAME["true-empty"], _CASE_BY_NAME["true-empty"]),
        (),
        SourceOutcomeKind.EMPTY,
    ),
    _AggregateCase(
        "all-failed",
        (_CASE_BY_NAME["timeout"], _CASE_BY_NAME["rate-limit"]),
        (),
        SourceOutcomeKind.FAILURE,
    ),
    _AggregateCase(
        "failed-empty-success",
        (
            _CASE_BY_NAME["dependency-unavailable"],
            _CASE_BY_NAME["true-empty"],
            _CASE_BY_NAME["success"],
        ),
        ("note-1",),
        SourceOutcomeKind.PARTIAL,
    ),
)


@pytest.mark.parametrize("adapter_kind", ("legacy", "target"))
@pytest.mark.parametrize("case", AGGREGATE_CASES, ids=lambda case: case.name)
async def test_xhs_attempt_aggregates_keep_legacy_projection_and_target_coverage(
    adapter_kind: AdapterKind,
    case: _AggregateCase,
) -> None:
    item_ids: list[str] = []
    target_batches: list[CanonicalSourceBatch] = []
    seen: set[str] = set()

    for fixture in case.attempts:
        provider = _Provider("xhs_search", fixture.result, error=fixture.error)
        if adapter_kind == "legacy":
            notes = await _legacy_executor().search_with_keyword(provider, "fixture", seen)
            item_ids.extend(str(note["id"]) for note in notes)
        else:
            batch = await _xhs_connector(provider).search(_collect_request())
            item_ids.extend(item.external_id for item in batch.documents)
            assert batch.coverage is not None
            target_batches.append(batch)

    projection = (
        LegacySourceProjection.CONTINUE if item_ids else LegacySourceProjection.TERMINAL_ERROR
    )
    assert tuple(item_ids) == case.expected_ids
    assert projection is (
        LegacySourceProjection.CONTINUE
        if case.expected_ids
        else LegacySourceProjection.TERMINAL_ERROR
    )

    if adapter_kind == "target":
        errors = tuple(error for batch in target_batches for error in batch.errors)
        documents = tuple(document for batch in target_batches for document in batch.documents)
        attempts: list[SourceAttemptMetadata] = []
        error_offset = 0
        for index, batch in enumerate(target_batches, 1):
            assert batch.coverage is not None
            attempt = batch.coverage.attempts[0]
            attempts.append(
                attempt.model_copy(
                    update={
                        "attempt_id": f"xhs_search-{index}",
                        "error_indexes": tuple(
                            error_offset + error_index for error_index in attempt.error_indexes
                        ),
                    }
                )
            )
            error_offset += len(batch.errors)

        first = target_batches[0]
        aggregate = CanonicalSourceBatch(
            isolation=first.isolation,
            source_id=first.source_id,
            connector_id=first.connector_id,
            connector_version=first.connector_version,
            normalizer_version=first.normalizer_version,
            documents=documents,
            watermark=None,
            errors=errors,
            coverage=SourceCoverageMetadata(
                eligible_item_count=len(documents),
                attempts=tuple(attempts),
            ),
        )
        outcome = classify_batch(aggregate)
        assert outcome.kind is case.expected_kind
        assert aggregate.errors == errors
        assert aggregate.coverage is not None
        assert [attempt.outcome for attempt in aggregate.coverage.attempts] == [
            fixture.expected_attempt for fixture in case.attempts
        ]
        assert project_legacy_xhs(outcome) is projection


@pytest.mark.parametrize("adapter_kind", ("legacy", "target"))
async def test_xhs_hanging_call_has_no_added_deadline_and_propagates_cancel(
    adapter_kind: AdapterKind,
) -> None:
    provider = _HangingProvider()
    if adapter_kind == "legacy":
        awaitable = _legacy_executor().search_with_keyword(provider, "fixture", set())
    else:
        awaitable = _xhs_connector(provider).search(_collect_request())
    task = asyncio.create_task(awaitable)

    await asyncio.wait_for(provider.started.wait(), timeout=0.2)
    await asyncio.sleep(0)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.cancelled.is_set()


@dataclass(frozen=True, slots=True)
class _PlaceCase:
    name: str
    result: object
    expected_attempt: SourceAttemptOutcome
    category: ErrorCategory | None = None
    scope: ErrorScope | None = None
    retryable: bool | None = None
    error: BaseException | None = None


PLACE_CASES = (
    _PlaceCase("true-empty", {"pois": []}, SourceAttemptOutcome.SUCCESS_EMPTY),
    _PlaceCase(
        "timeout",
        None,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.TIMEOUT,
        ErrorScope.SOURCE,
        True,
        TimeoutError("timed out"),
    ),
    _PlaceCase(
        "rate-limit",
        {"error": "429 Too Many Requests"},
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.RATE_LIMITED,
        ErrorScope.SOURCE,
        True,
    ),
    _PlaceCase(
        "malformed",
        ["not-an-object"],
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.MALFORMED_RESPONSE,
        ErrorScope.SOURCE,
        False,
    ),
    _PlaceCase(
        "dependency-unavailable",
        {"error": "upstream unavailable"},
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.DEPENDENCY_UNAVAILABLE,
        ErrorScope.SOURCE,
        True,
    ),
    _PlaceCase(
        "exception",
        None,
        SourceAttemptOutcome.FAILURE,
        ErrorCategory.INTERNAL,
        ErrorScope.PROVIDER,
        False,
        RuntimeError("provider exploded"),
    ),
)


@pytest.mark.parametrize("adapter_kind", ("legacy", "target"))
@pytest.mark.parametrize("case", PLACE_CASES, ids=lambda case: case.name)
async def test_optional_place_legacy_and_target_share_basic_fallback_contract(
    adapter_kind: AdapterKind,
    case: _PlaceCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _AmapClient(case.result, error=case.error)

    if adapter_kind == "legacy":
        recommendation = RestaurantRecommendation(
            name="Fixture Restaurant",
            location="Fixture District",
            features=["fixture"],
            source_notes=["note-1"],
            confidence=0.8,
        )
        enricher = POIEnricherAgent(amap_api=cast(Any, client))

        async def _cache_miss(_: str) -> None:
            return None

        monkeypatch.setattr(enricher, "_get_cached_poi", _cache_miss)
        result = (await enricher.enrich([recommendation]))[0]
        assert result.name == recommendation.name
        assert result.address == recommendation.location
        assert result.location is None
        assert result.tel is None
        projection = LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT
    else:
        batch = await AmapPlaceSourceConnector(client, clock=lambda: NOW).search(
            _collect_request("amap")
        )
        outcome = classify_batch(batch)
        projection = project_legacy_place(outcome)

        assert outcome.kind is (
            SourceOutcomeKind.EMPTY if case.category is None else SourceOutcomeKind.FAILURE
        )
        assert batch.coverage is not None
        attempt = batch.coverage.attempts[0]
        assert attempt.outcome is case.expected_attempt
        assert attempt.item_count == 0
        if case.category is None:
            assert batch.errors == ()
            assert attempt.error_indexes == ()
        else:
            assert len(batch.errors) == 1
            error = batch.errors[0]
            assert error.category is case.category
            assert error.scope is case.scope
            assert error.retryable is case.retryable
            assert attempt.error_indexes == (0,)

    assert projection is LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT
    assert len(client.calls) == 1
