"""Connector-neutral cursor, rate, and circuit boundary for refresh work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

from xhs_food.contracts import (
    CanonicalSourceBatch,
    CollectRequest,
    ContractError,
    ErrorCategory,
    ErrorScope,
    SourceAdmissionDecision,
    SourceCollectionOutcome,
    SourceConnector,
    SourceControlPort,
)


class InMemorySourceControl:
    """Small injectable controller for unit tests and single-process probes."""

    def __init__(
        self,
        *,
        max_calls: int = 60,
        window_seconds: int = 60,
        failure_threshold: int = 3,
        cooldown_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if min(max_calls, window_seconds, failure_threshold, cooldown_seconds) < 1:
            raise ValueError("source control limits must be positive")
        self._max_calls = max_calls
        self._window = timedelta(seconds=window_seconds)
        self._failure_threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._calls: dict[str, list[datetime]] = {}
        self._failures: dict[str, int] = {}
        self._opened_until: dict[str, datetime] = {}

    async def admit(self, source_id: str) -> SourceAdmissionDecision:
        now = self._now()
        opened_until = self._opened_until.get(source_id)
        if opened_until is not None:
            if opened_until > now:
                return SourceAdmissionDecision(
                    allowed=False,
                    retry_after_seconds=max(1, ceil((opened_until - now).total_seconds())),
                    circuit_open=True,
                )
            self._opened_until.pop(source_id, None)
            self._failures[source_id] = 0
        calls = [
            value for value in self._calls.setdefault(source_id, []) if value > now - self._window
        ]
        self._calls[source_id] = calls
        if len(calls) >= self._max_calls:
            retry_after = max(1, ceil((calls[0] + self._window - now).total_seconds()))
            return SourceAdmissionDecision(allowed=False, retry_after_seconds=retry_after)
        calls.append(now)
        return SourceAdmissionDecision(allowed=True)

    async def record_success(self, source_id: str) -> None:
        self._failures[source_id] = 0

    async def record_failure(self, source_id: str, *, retryable: bool) -> None:
        if not retryable:
            return
        failures = self._failures.get(source_id, 0) + 1
        self._failures[source_id] = failures
        if failures >= self._failure_threshold:
            self._opened_until[source_id] = self._now() + self._cooldown

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source control clock must be timezone-aware")
        return value.astimezone(UTC)


class SourceGateway:
    """Route one collection command to registered connectors with safe outcomes."""

    def __init__(
        self,
        connectors: Mapping[str, SourceConnector],
        *,
        control: SourceControlPort | None = None,
    ) -> None:
        self._connectors = dict(connectors)
        self._control = control or InMemorySourceControl()

    async def collect(self, request: CollectRequest) -> tuple[SourceCollectionOutcome, ...]:
        return tuple(
            [await self.collect_one(request, source_id) for source_id in request.source_scope]
        )

    async def collect_one(self, request: CollectRequest, source_id: str) -> SourceCollectionOutcome:
        if source_id not in request.source_scope:
            raise ValueError("source_id is outside the CollectRequest source_scope")
        try:
            connector = self._connectors[source_id]
        except KeyError:
            return self._failure(
                source_id,
                code="SOURCE_NOT_REGISTERED",
                category=ErrorCategory.NOT_FOUND,
                retryable=False,
            )
        admission = await self._control.admit(source_id)
        if not admission.allowed:
            category = (
                ErrorCategory.DEPENDENCY_UNAVAILABLE
                if admission.circuit_open
                else ErrorCategory.RATE_LIMITED
            )
            return self._failure(
                source_id,
                code="SOURCE_CIRCUIT_OPEN" if admission.circuit_open else "SOURCE_RATE_LIMITED",
                category=category,
                retryable=True,
                details={"retryAfterSeconds": admission.retry_after_seconds},
            )
        try:
            batch = await connector.search(request)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._control.record_failure(source_id, retryable=True)
            return self._failure(
                source_id,
                code="SOURCE_TIMEOUT",
                category=ErrorCategory.TIMEOUT,
                retryable=True,
            )
        except Exception as exc:
            await self._control.record_failure(source_id, retryable=True)
            return self._failure(
                source_id,
                code="SOURCE_DEPENDENCY_UNAVAILABLE",
                category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
                retryable=True,
                message=str(exc),
            )
        if not isinstance(batch, CanonicalSourceBatch):
            await self._control.record_failure(source_id, retryable=False)
            return self._failure(
                source_id,
                code="SOURCE_MALFORMED_RESPONSE",
                category=ErrorCategory.MALFORMED_RESPONSE,
                retryable=False,
            )
        items = batch.documents or batch.comments or batch.authors or batch.media_refs
        if batch.errors:
            error = batch.errors[0]
            await self._control.record_failure(source_id, retryable=error.retryable)
            if items:
                return SourceCollectionOutcome(
                    source_id=source_id,
                    outcome="partial",
                    batch=batch,
                    error=error,
                )
            return SourceCollectionOutcome(source_id=source_id, outcome="failure", error=error)
        await self._control.record_success(source_id)
        return SourceCollectionOutcome(
            source_id=source_id,
            outcome="success_nonempty" if items else "success_empty",
            batch=batch,
        )

    @staticmethod
    def _failure(
        source_id: str,
        *,
        code: str,
        category: ErrorCategory,
        retryable: bool,
        message: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> SourceCollectionOutcome:
        return SourceCollectionOutcome(
            source_id=source_id,
            outcome="failure",
            error=ContractError(
                code=code,
                category=category,
                scope=ErrorScope.SOURCE,
                retryable=retryable,
                terminal=not retryable,
                message=message,
                boundary_ref=source_id,
                details=dict(details or {}),
            ),
        )


__all__ = ["InMemorySourceControl", "SourceGateway"]
