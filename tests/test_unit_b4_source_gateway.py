"""B4 SourceGateway cursor, rate-limit, circuit, and outcome contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from xhs_food.contracts import (
    CanonicalSourceBatch,
    CanonicalSourceDocument,
    CollectRequest,
    ContractError,
    ErrorCategory,
    ErrorScope,
    IsolationCoordinates,
)
from xhs_food.gateways import InMemorySourceControl, SourceGateway


def _request() -> CollectRequest:
    return CollectRequest.model_construct(source_scope=("fixture",), cursor="cursor-7")


def _batch(*, items: bool = False, errors: tuple[ContractError, ...] = ()) -> CanonicalSourceBatch:
    return CanonicalSourceBatch.model_construct(
        source_id="fixture",
        connector_id="fixture-connector",
        connector_version="fixture/v1",
        normalizer_version="normalizer/v1",
        isolation=IsolationCoordinates(tenant_scope="public", language="zh", region="CN"),
        documents=(
            CanonicalSourceDocument(
                source_id="fixture",
                external_id="doc-1",
                canonical_url="https://fixture.invalid/doc-1",
                captured_at=datetime(2026, 8, 24, tzinfo=UTC),
            ),
        )
        if items
        else (),
        comments=(),
        authors=(),
        media_refs=(),
        watermark="watermark-7",
        next_cursor="cursor-8",
        errors=errors,
    )


class _Connector:
    source_id = "fixture"

    def __init__(self, result: Any) -> None:
        self.result = result
        self.cursors: list[str | None] = []

    async def search(self, request: Any) -> Any:
        self.cursors.append(request.cursor)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.mark.unit
async def test_source_gateway_preserves_cursor_and_empty_success() -> None:
    connector = _Connector(_batch())
    gateway = SourceGateway({"fixture": connector})

    outcome = (await gateway.collect(_request()))[0]

    assert connector.cursors == ["cursor-7"]
    assert outcome.outcome == "success_empty"
    assert outcome.error is None
    assert outcome.next_cursor == "cursor-8"


@pytest.mark.unit
async def test_source_gateway_distinguishes_partial_and_failure() -> None:
    error = ContractError(
        code="FIXTURE_RATE_LIMIT",
        category=ErrorCategory.RATE_LIMITED,
        scope=ErrorScope.SOURCE,
        retryable=True,
    )
    partial = SourceGateway({"fixture": _Connector(_batch(items=True, errors=(error,)))})
    partial_outcome = (await partial.collect(_request()))[0]
    assert partial_outcome.outcome == "partial"
    assert partial_outcome.batch is not None
    assert partial_outcome.error == error

    failed = SourceGateway({"fixture": _Connector(_batch(errors=(error,)))})
    failed_outcome = (await failed.collect(_request()))[0]
    assert failed_outcome.outcome == "failure"
    assert failed_outcome.batch is None
    assert failed_outcome.error == error


@pytest.mark.unit
async def test_source_gateway_rate_limit_and_circuit_are_bounded() -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    def clock() -> datetime:
        return now
    control = InMemorySourceControl(
        max_calls=1,
        window_seconds=60,
        failure_threshold=2,
        cooldown_seconds=30,
        clock=clock,
    )
    connector = _Connector(TimeoutError("fixture timeout"))
    gateway = SourceGateway({"fixture": connector}, control=control)

    first = (await gateway.collect(_request()))[0]
    second = (await gateway.collect(_request()))[0]
    assert first.error is not None and first.error.category is ErrorCategory.TIMEOUT
    assert second.error is not None and second.error.category is ErrorCategory.RATE_LIMITED

    now = now + timedelta(seconds=61)
    third = (await gateway.collect(_request()))[0]
    fourth = (await gateway.collect(_request()))[0]
    assert third.error is not None and third.error.category is ErrorCategory.TIMEOUT
    assert fourth.error is not None and fourth.error.code == "SOURCE_CIRCUIT_OPEN"
