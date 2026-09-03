"""Source consumer coverage for the optional place adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import pytest

from xhs_food.agents.poi_enricher import POIEnricherAgent
from xhs_food.contracts import (
    CanonicalQuery,
    CollectRequest,
    ErrorCategory,
    ErrorScope,
    SourceAttemptOutcome,
)
from xhs_food.gateways import (
    AmapPlaceSourceConnector,
    LegacySourceProjection,
    SourceOutcomeKind,
    classify_batch,
    project_legacy_place,
)
from xhs_food.schemas import RestaurantRecommendation

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
AdapterKind = Literal["legacy", "target"]


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
