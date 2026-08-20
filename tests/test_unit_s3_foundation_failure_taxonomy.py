"""Consumer tests for stable target Foundation failure translation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import IntegrityError
from temporalio.service import RPCError, RPCStatusCode

from xhs_food.contracts import (
    ErrorCategory,
    ErrorScope,
    EventEnvelope,
    ObjectRef,
    WorkflowStart,
)
from xhs_food.foundation import (
    Boto3ObjectStore,
    FoundationAdapterError,
    RedisEventBusAdapter,
    RedisStateStore,
    SQLAlchemyUnitOfWork,
    TemporalWorkflowAdapter,
    foundation_error_from_exception,
)

pytestmark = pytest.mark.unit


def _client_error(code: str, status: int, operation: str = "HeadObject") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "provider detail is private"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


@pytest.mark.parametrize(
    ("error", "scope", "category", "retryable"),
    [
        (TimeoutError("late"), ErrorScope.REPOSITORY, ErrorCategory.TIMEOUT, True),
        (
            IntegrityError("INSERT", {}, Exception("duplicate")),
            ErrorScope.REPOSITORY,
            ErrorCategory.CONFLICT,
            False,
        ),
        (
            RedisConnectionError("offline"),
            ErrorScope.CACHE,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            True,
        ),
        (
            RPCError("busy", RPCStatusCode.RESOURCE_EXHAUSTED, b""),
            ErrorScope.WORKFLOW,
            ErrorCategory.RATE_LIMITED,
            True,
        ),
        (
            _client_error("SlowDown", 503),
            ErrorScope.OBJECT_STORE,
            ErrorCategory.RATE_LIMITED,
            True,
        ),
        (
            json.JSONDecodeError("bad", "{", 0),
            ErrorScope.EVENT_BUS,
            ErrorCategory.MALFORMED_RESPONSE,
            False,
        ),
    ],
)
def test_foundation_taxonomy_is_stable_and_redacted(
    error: BaseException,
    scope: ErrorScope,
    category: ErrorCategory,
    retryable: bool,
) -> None:
    mapped = foundation_error_from_exception(
        error,
        scope=scope,
        operation=f"{scope.value}.fixture",
    )

    assert mapped.code == f"{scope.value.upper()}_{category.value.upper()}"
    assert mapped.scope is scope
    assert mapped.category is category
    assert mapped.retryable is retryable
    assert mapped.terminal is False
    assert mapped.boundary_ref == f"{scope.value}.fixture"
    assert mapped.message is None
    assert "provider detail is private" not in mapped.model_dump_json()


class _FailingSession:
    async def begin(self) -> None:
        raise TimeoutError("database did not answer")


class _FailingRedis:
    async def get(self, key: str) -> object:
        del key
        raise RedisConnectionError("redis is offline")

    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        del key, fields, maxlen, approximate
        raise RedisTimeoutError("redis timed out")


class _FailingTemporalClient:
    async def start_workflow(self, *args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise RPCError("temporal unavailable", RPCStatusCode.UNAVAILABLE, b"")


class _FailingS3Client:
    def head_object(self, *, Bucket: str, Key: str) -> object:
        del Bucket, Key
        raise _client_error("ServiceUnavailable", 503)


def _workflow_start() -> WorkflowStart:
    return WorkflowStart(
        workflow_id="workflow-1",
        workflow_type="research",
        task_queue="research",
        input={"query": "fixture"},
        idempotency_key="idem-1",
    )


def _object_ref() -> ObjectRef:
    return ObjectRef(
        object_id="object-1",
        key="fixture/object-1",
        content_hash="hash-1",
        size_bytes=1,
        content_type="text/plain",
    )


@pytest.mark.parametrize(
    ("invoke", "scope", "category", "retryable", "boundary_ref"),
    [
        (
            lambda: SQLAlchemyUnitOfWork(lambda: _FailingSession()).__aenter__(),
            ErrorScope.REPOSITORY,
            ErrorCategory.TIMEOUT,
            True,
            "repository.transaction.begin",
        ),
        (
            lambda: RedisStateStore(_FailingRedis()).get("fixture"),  # type: ignore[arg-type]
            ErrorScope.CACHE,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            True,
            "cache.state.get",
        ),
        (
            lambda: RedisEventBusAdapter(_FailingRedis()).publish(  # type: ignore[arg-type]
                EventEnvelope(
                    event_id="event-1",
                    topic="fixture",
                    payload={"status": "running"},
                    published_at=datetime(2026, 8, 21, tzinfo=UTC),
                )
            ),
            ErrorScope.EVENT_BUS,
            ErrorCategory.TIMEOUT,
            True,
            "event_bus.publish",
        ),
        (
            lambda: TemporalWorkflowAdapter(_FailingTemporalClient(), enabled=True).start(
                _workflow_start()
            ),
            ErrorScope.WORKFLOW,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            True,
            "workflow.start",
        ),
        (
            lambda: Boto3ObjectStore(bucket="fixture", client=_FailingS3Client()).stat(  # type: ignore[arg-type]
                _object_ref()
            ),
            ErrorScope.OBJECT_STORE,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            True,
            "object_store.stat",
        ),
    ],
)
async def test_target_adapters_raise_contract_backed_failures(
    invoke: Callable[[], Awaitable[object]],
    scope: ErrorScope,
    category: ErrorCategory,
    retryable: bool,
    boundary_ref: str,
) -> None:
    with pytest.raises(FoundationAdapterError) as caught:
        await invoke()

    mapped = caught.value.error
    assert mapped.scope is scope
    assert mapped.category is category
    assert mapped.retryable is retryable
    assert mapped.boundary_ref == boundary_ref
    assert caught.value.__cause__ is not None


class _CorruptRedis:
    async def get(self, key: str) -> object:
        del key
        return b"{not-json"


async def test_cache_corruption_maps_to_malformed_response() -> None:
    state = RedisStateStore(_CorruptRedis())  # type: ignore[arg-type]

    with pytest.raises(FoundationAdapterError) as caught:
        await state.get("fixture")

    assert caught.value.error.category is ErrorCategory.MALFORMED_RESPONSE
    assert caught.value.error.scope is ErrorScope.CACHE
    assert caught.value.error.retryable is False


class _CancelledSession:
    async def begin(self) -> None:
        raise asyncio.CancelledError


class _CancelledRedis:
    async def get(self, key: str) -> object:
        del key
        raise asyncio.CancelledError

    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        del key, fields, maxlen, approximate
        raise asyncio.CancelledError


class _CancelledTemporalClient:
    async def start_workflow(self, *args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise asyncio.CancelledError


class _CancelledS3Client:
    def head_object(self, *, Bucket: str, Key: str) -> object:
        del Bucket, Key
        raise asyncio.CancelledError


async def test_target_adapters_propagate_asyncio_cancellation() -> None:
    event = EventEnvelope(
        event_id="event-1",
        topic="fixture",
        payload={"status": "running"},
        published_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    operations: tuple[Callable[[], Awaitable[object]], ...] = (
        lambda: SQLAlchemyUnitOfWork(lambda: _CancelledSession()).__aenter__(),
        lambda: RedisStateStore(_CancelledRedis()).get("fixture"),  # type: ignore[arg-type]
        lambda: RedisEventBusAdapter(_CancelledRedis()).publish(event),  # type: ignore[arg-type]
        lambda: TemporalWorkflowAdapter(_CancelledTemporalClient(), enabled=True).start(
            _workflow_start()
        ),
        lambda: Boto3ObjectStore(bucket="fixture", client=_CancelledS3Client()).stat(  # type: ignore[arg-type]
            _object_ref()
        ),
    )

    for invoke in operations:
        with pytest.raises(asyncio.CancelledError):
            await invoke()
