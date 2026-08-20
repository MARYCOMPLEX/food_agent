"""Canonical source outcomes and the compatibility projection boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from xhs_food.contracts import (
    CanonicalSourceBatch,
    ContractError,
    ErrorCategory,
    ErrorScope,
    SourceAttemptMetadata,
    SourceAttemptOutcome,
    SourceCoverageMetadata,
)


class SourceOutcomeKind(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILURE = "failure"


class LegacySourceProjection(StrEnum):
    CONTINUE = "continue"
    TERMINAL_ERROR = "terminal_error"
    SUCCESS_WITH_BASIC_RESULT = "success_with_basic_result"


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    kind: SourceOutcomeKind
    item_count: int
    errors: tuple[ContractError, ...]


_RATE_LIMIT_CODES = frozenset({"RATE_LIMITED", "RATE_LIMIT", "HTTP_429"})
_TIMEOUT_CODES = frozenset({"SOURCE_TIMEOUT", "TIMEOUT"})
_MALFORMED_CODES = frozenset({"MALFORMED_RESPONSE", "INVALID_RESPONSE"})
_REMOTE_FAILURE_CODES = frozenset(
    {"SEARCH_FAILED", "NOTE_FETCH_FAILED", "BATCH_FAILED", "DEPENDENCY_UNAVAILABLE"}
)


def source_error(
    *,
    code: str,
    category: ErrorCategory,
    boundary_ref: str,
    scope: ErrorScope = ErrorScope.SOURCE,
    retryable: bool = False,
    message: str | None = None,
) -> ContractError:
    return ContractError(
        code=code,
        category=category,
        scope=scope,
        retryable=retryable,
        terminal=False,
        message=message,
        boundary_ref=boundary_ref,
    )


def error_from_exception(exc: BaseException, *, boundary_ref: str) -> ContractError:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return source_error(
            code="SOURCE_TIMEOUT",
            category=ErrorCategory.TIMEOUT,
            boundary_ref=boundary_ref,
            retryable=True,
        )
    if isinstance(exc, asyncio.CancelledError):
        return source_error(
            code="SOURCE_CANCELLED",
            category=ErrorCategory.CANCELLED,
            boundary_ref=boundary_ref,
            retryable=False,
        )
    return source_error(
        code="PROVIDER_INTERNAL",
        category=ErrorCategory.INTERNAL,
        scope=ErrorScope.PROVIDER,
        boundary_ref=boundary_ref,
        retryable=False,
        message=str(exc) or None,
    )


def error_from_provider_code(
    code: str | None,
    *,
    boundary_ref: str,
    message: str | None = None,
) -> ContractError:
    normalized = (code or "DEPENDENCY_UNAVAILABLE").upper()
    if normalized in _TIMEOUT_CODES:
        category, retryable = ErrorCategory.TIMEOUT, True
    elif normalized in _RATE_LIMIT_CODES:
        category, retryable = ErrorCategory.RATE_LIMITED, True
    elif normalized in _MALFORMED_CODES:
        category, retryable = ErrorCategory.MALFORMED_RESPONSE, False
    elif normalized in _REMOTE_FAILURE_CODES:
        category, retryable = ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    else:
        return source_error(
            code=normalized,
            category=ErrorCategory.INTERNAL,
            scope=ErrorScope.PROVIDER,
            boundary_ref=boundary_ref,
            retryable=False,
            message=message,
        )
    return source_error(
        code=normalized,
        category=category,
        boundary_ref=boundary_ref,
        retryable=retryable,
        message=message,
    )


def classify_batch(batch: CanonicalSourceBatch) -> SourceOutcome:
    item_count = sum(
        len(items) for items in (batch.documents, batch.comments, batch.authors, batch.media_refs)
    )
    if batch.errors:
        kind = SourceOutcomeKind.PARTIAL if item_count else SourceOutcomeKind.FAILURE
    else:
        kind = SourceOutcomeKind.SUCCESS if item_count else SourceOutcomeKind.EMPTY
    return SourceOutcome(kind=kind, item_count=item_count, errors=batch.errors)


def single_attempt_coverage(
    *,
    attempt_id: str,
    boundary_ref: str,
    item_count: int,
    watermark: str | None,
    errors: tuple[ContractError, ...],
) -> SourceCoverageMetadata:
    """Describe observed collection facts without deciding policy sufficiency."""

    outcome = (
        SourceAttemptOutcome.PARTIAL
        if item_count and errors
        else SourceAttemptOutcome.SUCCESS_NONEMPTY
        if item_count
        else SourceAttemptOutcome.FAILURE
        if errors
        else SourceAttemptOutcome.SUCCESS_EMPTY
    )
    return SourceCoverageMetadata(
        eligible_item_count=item_count,
        attempts=(
            SourceAttemptMetadata(
                attempt_id=attempt_id,
                boundary_ref=boundary_ref,
                outcome=outcome,
                item_count=item_count,
                watermark=watermark,
                error_indexes=tuple(range(len(errors))),
            ),
        ),
    )


def project_legacy_xhs(outcome: SourceOutcome) -> LegacySourceProjection:
    if outcome.item_count:
        return LegacySourceProjection.CONTINUE
    return LegacySourceProjection.TERMINAL_ERROR


def project_legacy_place(outcome: SourceOutcome) -> LegacySourceProjection:
    if outcome.kind in {SourceOutcomeKind.EMPTY, SourceOutcomeKind.FAILURE}:
        return LegacySourceProjection.SUCCESS_WITH_BASIC_RESULT
    return LegacySourceProjection.CONTINUE


__all__ = [
    "LegacySourceProjection",
    "SourceOutcome",
    "SourceOutcomeKind",
    "classify_batch",
    "error_from_exception",
    "error_from_provider_code",
    "project_legacy_place",
    "project_legacy_xhs",
    "single_attempt_coverage",
    "source_error",
]
