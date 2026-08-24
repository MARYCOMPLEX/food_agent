"""Offline S3 contract tests for target Foundation adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from xhs_food.contracts import ActivityCall, ActivityPort, EventEnvelope, WorkflowStart
from xhs_food.foundation import (
    FoundationAdapterError,
    ObservabilityBootstrap,
    RedisEventBusAdapter,
    RedisHotStateContract,
    RedisSessionWindow,
    RedisStateStore,
    SQLAlchemyDatabase,
    SQLAlchemyUnitOfWork,
    TargetAdapterDisabled,
    TemporalActivityAdapter,
    TemporalTaskQueues,
    TemporalWorkerQuota,
    TemporalWorkflowAdapter,
    correlation_attributes,
    deterministic_workflow_input,
    prometheus_labels,
)


class FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def begin(self) -> None:
        self.calls.append("begin")

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")

    async def close(self) -> None:
        self.calls.append("close")


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.values: dict[str, object] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> object:
        self.calls.append(("get", (key,), {}))
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> object:
        self.calls.append(("set", (key, value), {"ex": ex, "nx": nx}))
        self.values[key] = value
        return True

    async def eval(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append(("eval", args, kwargs))
        raise NotImplementedError

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete", keys, {}))
        return sum(self.values.pop(key, None) is not None for key in keys)

    async def rpush(self, key: str, value: str) -> int:
        self.calls.append(("rpush", (key, value), {}))
        return len(self.lists.setdefault(key, [])) + 1

    async def ltrim(self, key: str, start: int, end: int) -> object:
        self.calls.append(("ltrim", (key, start, end), {}))
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[object]:
        self.calls.append(("lrange", (key, start, end), {}))
        return list(self.lists.get(key, [])[start : end + 1])

    async def expire(self, key: str, ttl: int) -> object:
        self.calls.append(("expire", (key, ttl), {}))
        return True

    async def xadd(
        self,
        key: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        self.calls.append(
            (
                "xadd",
                (key, dict(fields)),
                {"maxlen": maxlen, "approximate": approximate},
            )
        )
        return "1-0"

    async def xread(self, *args: Any, **kwargs: Any) -> list[object]:
        self.calls.append(("xread", args, kwargs))
        return []


def _workflow_start() -> WorkflowStart:
    return WorkflowStart(
        workflow_id="workflow-1",
        workflow_type="research",
        task_queue="research",
        input={"z": 1, "a": {"y": 2, "x": 1}},
        idempotency_key="idem-1",
    )


@pytest.mark.unit
async def test_sqlalchemy_uow_owns_one_session_and_commits_or_rolls_back() -> None:
    sessions: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession([])
        sessions.append(session)
        return session

    committed = SQLAlchemyUnitOfWork(factory)
    with pytest.raises(RuntimeError, match="not active"):
        committed.session_for_adapter()
    async with committed:
        owned_session = committed.session_for_adapter()
        assert owned_session is sessions[0]
        await committed.commit()
        with pytest.raises(RuntimeError, match="already finished"):
            await committed.commit()
    assert sessions[0].calls == ["begin", "commit", "close"]

    rolled_back = SQLAlchemyUnitOfWork(factory)
    with pytest.raises(RuntimeError, match="fixture failure"):
        async with rolled_back:
            raise RuntimeError("fixture failure")
    assert sessions[1].calls == ["begin", "rollback", "close"]


@pytest.mark.unit
async def test_sqlalchemy_uow_closes_session_when_begin_fails() -> None:
    calls: list[str] = []

    class BeginFailureSession(FakeSession):
        async def begin(self) -> None:
            self.calls.append("begin")
            raise TimeoutError("fixture begin timeout")

    unit_of_work = SQLAlchemyUnitOfWork(lambda: BeginFailureSession(calls))

    with pytest.raises(FoundationAdapterError) as caught:
        await unit_of_work.__aenter__()

    assert caught.value.error.boundary_ref == "repository.transaction.begin"
    assert calls == ["begin", "close"]
    with pytest.raises(RuntimeError, match="not active"):
        unit_of_work.session_for_adapter()


@pytest.mark.unit
def test_sqlalchemy_target_does_not_create_an_engine_while_disabled() -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def engine_factory(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return object()

    database = SQLAlchemyDatabase(
        "postgresql://fixture/database", enabled=False, engine_factory=engine_factory
    )
    with pytest.raises(TargetAdapterDisabled, match="sqlalchemy"):
        database.start()
    assert calls == []
    with pytest.raises(RuntimeError, match="not been started"):
        database.unit_of_work()


@pytest.mark.unit
async def test_redis_hot_state_enforces_ttl_stream_boundaries_and_has_no_lock_surface() -> None:
    client = FakeRedis()
    contract = RedisHotStateContract()
    state = RedisStateStore(client)
    sessions = RedisSessionWindow(client, contract)
    events = RedisEventBusAdapter(client, contract)

    await state.set("result", {"status": "ok"}, 60)
    assert await state.get("result") == {"status": "ok"}
    await sessions.append("session-1", {"role": "user", "content": "hello"}, 86_400)
    entry_id = await events.publish(
        EventEnvelope(
            event_id="event-1",
            topic="search",
            payload={"status": "running"},
            published_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
    )

    assert entry_id == "1-0"
    assert (
        "set",
        ("state:result", '{"status":"ok"}'),
        {"ex": 60, "nx": False},
    ) in client.calls
    assert ("ltrim", ("session:session-1:window", -20, -1), {}) in client.calls
    assert ("expire", ("session:session-1:window", 86_400), {}) in client.calls
    assert (
        "xadd",
        ("events:search:stream", {"payload": client.calls[-2][1][1]["payload"]}),
        {"maxlen": 1_000, "approximate": True},
    ) in client.calls
    assert ("expire", ("events:search:stream", 3_600), {}) in client.calls
    for adapter in (RedisStateStore, RedisSessionWindow, RedisEventBusAdapter):
        public = {name for name in dir(adapter) if not name.startswith("_")}
        assert not {name for name in public if "lock" in name or "lease" in name}

    with pytest.raises(ValueError, match="TTL"):
        await sessions.append("session-1", {}, 30)
    with pytest.raises(ValueError, match="read exceeds"):
        await sessions.recent("session-1", 21)


@pytest.mark.unit
async def test_temporal_is_disabled_by_default_and_payloads_are_deterministic() -> None:
    start = _workflow_start()
    payload = deterministic_workflow_input(start)
    assert list(payload) == sorted(payload)
    assert list(payload["input"]) == ["a", "z"]
    queues = TemporalTaskQueues(research="research", refresh="refresh", media="media")
    assert queues.allowed == frozenset({"research", "refresh", "media"})
    assert queues.active == frozenset({"research"})
    assert queues.quota_for("research").max_concurrent_workflows == 8
    with pytest.raises(ValueError, match="disabled"):
        queues.assert_enabled("refresh")
    with pytest.raises(ValueError, match="concurrency"):
        TemporalWorkerQuota("research", 0, 1, 100)
    with pytest.raises(ValueError, match="distinct"):
        TemporalTaskQueues(research="same", refresh="same", media="media")

    calls: list[str] = []

    class Client:
        async def start_workflow(self, *args: Any, **kwargs: Any) -> object:
            calls.append("start")
            return object()

    adapter = TemporalWorkflowAdapter(Client(), task_queues=queues, enabled=False)
    with pytest.raises(TargetAdapterDisabled, match="temporal"):
        await adapter.start(start)
    assert calls == []

    activity_calls: list[dict[str, Any]] = []

    async def activity_handler(payload: dict[str, Any]) -> dict[str, Any]:
        activity_calls.append(payload)
        return {"z": 2, "a": 1}

    activity = TemporalActivityAdapter(
        {"source.collect": activity_handler},
        task_queues=queues,
        enabled=False,
    )
    assert isinstance(activity, ActivityPort)
    call = ActivityCall(
        activity_id="activity-1",
        activity_type="source.collect",
        task_queue="research",
        input={"z": 1, "a": 2},
        idempotency_key="activity-idem-1",
    )
    with pytest.raises(TargetAdapterDisabled, match="temporal-activity"):
        await activity.execute(call)
    assert activity_calls == []

    enabled_activity = TemporalActivityAdapter(
        {"source.collect": activity_handler},
        task_queues=queues,
        enabled=True,
    )
    result = await enabled_activity.execute(call)
    assert activity_calls == [{"a": 2, "z": 1}]
    assert result.output == {"a": 1, "z": 2}

    async def forbidden_connect(*args: Any, **kwargs: Any) -> object:
        calls.append("connect")
        return object()

    with pytest.raises(TargetAdapterDisabled, match="temporal"):
        await TemporalWorkflowAdapter.connect(
            address="temporal.test:7233",
            namespace="default",
            enabled=False,
            client_factory=forbidden_connect,
        )
    assert calls == []


@pytest.mark.unit
def test_observability_redacts_attributes_and_instruments_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attributes = correlation_attributes(
        {
            "task_id": "task-private-id",
            "bundle_version": 3,
            "provider": "provider-a",
            "query": "private user query",
            "connector_id": "connector-private-id",
        }
    )
    task_id = attributes["task_id"]
    connector_id = attributes["connector_id"]
    assert isinstance(task_id, str) and task_id.startswith("sha256:")
    assert isinstance(connector_id, str) and connector_id.startswith("sha256:")
    assert attributes["bundle_version"] == 3
    assert attributes["provider"] == "provider-a"
    assert "query" not in attributes
    assert prometheus_labels({"operation": "search", "outcome": "ok"}) == {
        "operation": "search",
        "outcome": "ok",
    }
    with pytest.raises(ValueError, match="unapproved"):
        prometheus_labels({"task_id": "high-cardinality"})
    with pytest.raises(ValueError, match="unregistered"):
        prometheus_labels({"operation": "user-controlled-operation"})

    calls: list[tuple[str, Any]] = []

    class FastAPIInstrumentorFake:
        @staticmethod
        def instrument_app(application: object, **kwargs: Any) -> None:
            calls.append(("fastapi", (application, kwargs)))

    class HTTPXInstrumentorFake:
        def instrument(self) -> None:
            calls.append(("httpx", None))

    class RedisInstrumentorFake:
        def instrument(self) -> None:
            calls.append(("redis", None))

    class SQLAlchemyInstrumentorFake:
        def instrument(self, *, engine: object) -> None:
            calls.append(("sqlalchemy", engine))

    monkeypatch.setattr(
        "xhs_food.foundation.observability.FastAPIInstrumentor", FastAPIInstrumentorFake
    )
    monkeypatch.setattr(
        "xhs_food.foundation.observability.HTTPXClientInstrumentor", HTTPXInstrumentorFake
    )
    monkeypatch.setattr(
        "xhs_food.foundation.observability.RedisInstrumentor", RedisInstrumentorFake
    )
    monkeypatch.setattr(
        "xhs_food.foundation.observability.SQLAlchemyInstrumentor", SQLAlchemyInstrumentorFake
    )

    bootstrap = ObservabilityBootstrap(enabled=True)
    application = object()
    engine = type("Engine", (), {"sync_engine": "sync-engine"})()
    bootstrap.instrument_fastapi(application)
    bootstrap.instrument_fastapi(application)
    bootstrap.instrument_default_clients()
    bootstrap.instrument_default_clients()
    bootstrap.instrument_sqlalchemy(engine)
    bootstrap.instrument_sqlalchemy(engine)
    assert calls == [
        ("fastapi", (application, {"excluded_urls": "health,metrics"})),
        ("httpx", None),
        ("redis", None),
        ("sqlalchemy", "sync-engine"),
    ]
