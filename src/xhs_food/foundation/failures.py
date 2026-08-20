"""Stable failure translation for target infrastructure adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager

from botocore import exceptions as boto_errors
from pydantic import ValidationError
from redis import exceptions as redis_errors
from sqlalchemy import exc as sqlalchemy_errors
from temporalio import exceptions as temporal_errors
from temporalio.service import RPCError, RPCStatusCode

from xhs_food.contracts import ContractError, ErrorCategory, ErrorScope

_FOUNDATION_SCOPES = frozenset(
    {
        ErrorScope.REPOSITORY,
        ErrorScope.WORKFLOW,
        ErrorScope.CACHE,
        ErrorScope.EVENT_BUS,
        ErrorScope.OBJECT_STORE,
    }
)

_S3_RATE_LIMIT_CODES = frozenset(
    {
        "bandwidthlimitexceeded",
        "limitexceeded",
        "provisionedthroughputexceededexception",
        "requestlimitexceeded",
        "slowdown",
        "throttledexception",
        "throttling",
        "throttlingexception",
        "toomanyrequestsexception",
    }
)
_S3_TIMEOUT_CODES = frozenset({"requestexpired", "requesttimeout", "requesttimeoutexception"})
_S3_NOT_FOUND_CODES = frozenset({"404", "nosuchkey", "nosuchobject", "notfound"})
_POSTGRES_RETRYABLE_CONFLICTS = frozenset({"40001", "40P01"})


class FoundationAdapterError(RuntimeError):
    """Exception carrier for a serializable infrastructure ``ContractError``."""

    def __init__(self, error: ContractError) -> None:
        super().__init__(error.code)
        self.error = error


def foundation_error_from_exception(
    exc: BaseException,
    *,
    scope: ErrorScope,
    operation: str,
) -> ContractError:
    """Translate a driver exception without leaking provider-specific details."""

    if scope not in _FOUNDATION_SCOPES:
        raise ValueError(f"unsupported Foundation failure scope: {scope}")
    if not operation:
        raise ValueError("Foundation failure operation must not be empty")
    if isinstance(exc, asyncio.CancelledError):
        raise exc
    if isinstance(exc, FoundationAdapterError):
        return exc.error

    category, retryable = _classify_exception(exc)
    return ContractError(
        code=f"{scope.value.upper()}_{category.value.upper()}",
        category=category,
        scope=scope,
        retryable=retryable,
        terminal=False,
        boundary_ref=operation,
    )


@contextmanager
def foundation_failure_boundary(*, scope: ErrorScope, operation: str) -> Iterator[None]:
    """Raise one stable adapter exception while preserving task cancellation."""

    try:
        yield
    except asyncio.CancelledError:
        raise
    except FoundationAdapterError:
        raise
    except Exception as exc:
        raise FoundationAdapterError(
            foundation_error_from_exception(exc, scope=scope, operation=operation)
        ) from exc


def _classify_exception(exc: BaseException) -> tuple[ErrorCategory, bool]:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, redis_errors.TimeoutError)):
        return ErrorCategory.TIMEOUT, True
    if isinstance(exc, sqlalchemy_errors.TimeoutError):
        return ErrorCategory.TIMEOUT, True
    if isinstance(exc, (boto_errors.ConnectTimeoutError, boto_errors.ReadTimeoutError)):
        return ErrorCategory.TIMEOUT, True
    if isinstance(exc, temporal_errors.WorkflowAlreadyStartedError):
        return ErrorCategory.CONFLICT, False
    if isinstance(exc, temporal_errors.CancelledError):
        return ErrorCategory.CANCELLED, False
    if isinstance(exc, RPCError):
        return _classify_temporal_rpc(exc.status)
    if isinstance(exc, boto_errors.ClientError):
        return _classify_s3_client_error(exc)
    if isinstance(
        exc,
        (
            redis_errors.AuthenticationError,
            redis_errors.AuthorizationError,
            redis_errors.NoPermissionError,
            PermissionError,
        ),
    ):
        return ErrorCategory.POLICY_DENIED, False
    if isinstance(
        exc,
        (
            redis_errors.MaxConnectionsError,
            redis_errors.OutOfMemoryError,
            redis_errors.TryAgainError,
        ),
    ):
        return ErrorCategory.RATE_LIMITED, True
    if isinstance(
        exc,
        (
            redis_errors.ConnectionError,
            redis_errors.BusyLoadingError,
            redis_errors.ClusterDownError,
            redis_errors.MasterDownError,
            boto_errors.EndpointConnectionError,
            boto_errors.ConnectionClosedError,
            ConnectionError,
        ),
    ):
        return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if isinstance(exc, FileNotFoundError):
        return ErrorCategory.NOT_FOUND, False
    if isinstance(
        exc,
        (redis_errors.InvalidResponse, json.JSONDecodeError, UnicodeError, ValidationError),
    ):
        return ErrorCategory.MALFORMED_RESPONSE, False
    if isinstance(exc, sqlalchemy_errors.IntegrityError):
        return ErrorCategory.CONFLICT, False
    if isinstance(
        exc,
        (
            sqlalchemy_errors.OperationalError,
            sqlalchemy_errors.InterfaceError,
            sqlalchemy_errors.DBAPIError,
        ),
    ):
        sqlstate = _sqlstate(exc)
        if sqlstate in _POSTGRES_RETRYABLE_CONFLICTS:
            return ErrorCategory.CONFLICT, True
        if getattr(exc, "connection_invalidated", False) or isinstance(
            exc,
            (sqlalchemy_errors.OperationalError, sqlalchemy_errors.InterfaceError),
        ):
            return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if isinstance(exc, sqlalchemy_errors.DataError):
        return ErrorCategory.VALIDATION, False
    if isinstance(exc, boto_errors.BotoCoreError):
        return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if isinstance(exc, OSError):
        return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if isinstance(exc, (KeyError, TypeError)):
        return ErrorCategory.MALFORMED_RESPONSE, False
    return ErrorCategory.INTERNAL, False


def _classify_temporal_rpc(status: RPCStatusCode) -> tuple[ErrorCategory, bool]:
    if status is RPCStatusCode.DEADLINE_EXCEEDED:
        return ErrorCategory.TIMEOUT, True
    if status is RPCStatusCode.RESOURCE_EXHAUSTED:
        return ErrorCategory.RATE_LIMITED, True
    if status is RPCStatusCode.UNAVAILABLE:
        return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if status is RPCStatusCode.ABORTED:
        return ErrorCategory.CONFLICT, True
    if status is RPCStatusCode.ALREADY_EXISTS:
        return ErrorCategory.CONFLICT, False
    if status is RPCStatusCode.NOT_FOUND:
        return ErrorCategory.NOT_FOUND, False
    if status in {RPCStatusCode.PERMISSION_DENIED, RPCStatusCode.UNAUTHENTICATED}:
        return ErrorCategory.POLICY_DENIED, False
    if status in {
        RPCStatusCode.INVALID_ARGUMENT,
        RPCStatusCode.FAILED_PRECONDITION,
        RPCStatusCode.OUT_OF_RANGE,
    }:
        return ErrorCategory.VALIDATION, False
    if status is RPCStatusCode.CANCELLED:
        return ErrorCategory.CANCELLED, False
    if status is RPCStatusCode.DATA_LOSS:
        return ErrorCategory.MALFORMED_RESPONSE, False
    return ErrorCategory.INTERNAL, False


def _classify_s3_client_error(
    exc: boto_errors.ClientError,
) -> tuple[ErrorCategory, bool]:
    response = exc.response
    code = str(response.get("Error", {}).get("Code", "")).casefold()
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code in _S3_TIMEOUT_CODES or status == 408:
        return ErrorCategory.TIMEOUT, True
    if code in _S3_RATE_LIMIT_CODES or status == 429:
        return ErrorCategory.RATE_LIMITED, True
    if code in _S3_NOT_FOUND_CODES or status == 404:
        return ErrorCategory.NOT_FOUND, False
    if status == 409:
        return ErrorCategory.CONFLICT, False
    if status in {401, 403}:
        return ErrorCategory.POLICY_DENIED, False
    if isinstance(status, int) and status >= 500:
        return ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    if isinstance(status, int) and 400 <= status < 500:
        return ErrorCategory.VALIDATION, False
    return ErrorCategory.INTERNAL, False


def _sqlstate(exc: sqlalchemy_errors.DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    value = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return str(value).upper() if value else None


__all__ = [
    "FoundationAdapterError",
    "foundation_error_from_exception",
    "foundation_failure_boundary",
]
