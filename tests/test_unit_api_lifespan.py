"""Production Composition Root lifespan binding contracts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI


class _Runtime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.policy = object()
        self.task_store = object()
        self.projection_store = object()
        self.event_bus = self

    async def ensure_available(self) -> None:
        self.calls.append("redis-ping")

    async def aclose(self) -> None:
        self.calls.append("runtime-close")


class _Root:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.logical_bindings = {
            "research_task": object(),
            "reliable_task_lifecycle": object(),
            "reliable_projection_store": object(),
            "reliable_event_bus": object(),
        }
        self.closed = False

    async def resolve_logical(self, name: str) -> object:
        if name == "research_task":
            return "research-task-port"
        if name == "research_agent":
            return "comment-first-research-agent"
        if name == "reliable_projection_store":
            return self.runtime.projection_store
        if name == "reliable_event_bus":
            return self.runtime.event_bus
        raise AssertionError(name)

    async def close(self) -> None:
        self.closed = True


class _Dependency:
    def __init__(self, initialized: bool = False) -> None:
        self._initialized = initialized
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _ObservationPort:
    def __init__(
        self,
        events: list[object],
        *,
        start_error: bool = False,
        flush_delay: float = 0.0,
        flush_error: bool = False,
    ) -> None:
        self.events = events
        self.start_error = start_error
        self.flush_delay = flush_delay
        self.flush_error = flush_error

    def start(self) -> object:
        self.events.append("start")
        if self.start_error:
            raise RuntimeError("observation startup failed")

        async def finish_start() -> None:
            await asyncio.sleep(0)
            self.events.append("start-complete")

        return finish_start()

    async def flush(self, deadline_seconds: float | None = None) -> str:
        self.events.append(("flush", deadline_seconds))
        try:
            if self.flush_delay:
                await asyncio.sleep(self.flush_delay)
        except asyncio.CancelledError:
            self.events.append("flush-cancelled")
            raise
        if self.flush_error:
            raise RuntimeError("observation flush failed")
        return "flushed"

    def health(self) -> dict[str, object]:
        return {"status": "ready"}


class _EvaluationPort:
    def __init__(
        self,
        events: list[object],
        *,
        close_delay: float = 0.0,
        close_error: bool = False,
    ) -> None:
        self.events = events
        self.close_delay = close_delay
        self.close_error = close_error

    async def close(self) -> str:
        self.events.append("evaluation-close")
        try:
            if self.close_delay:
                await asyncio.sleep(self.close_delay)
        except asyncio.CancelledError:
            self.events.append("evaluation-close-cancelled")
            raise
        if self.close_error:
            raise RuntimeError("evaluation close failed")
        return "closed"

    async def submit_dataset(self, dataset: object) -> bool:
        del dataset
        return True

    async def submit_run(self, run: object) -> bool:
        del run
        return True

    def health(self) -> dict[str, object]:
        return {"status": "ready"}


class _ObservabilityRoot:
    def __init__(
        self,
        observation: _ObservationPort,
        evaluation: _EvaluationPort,
        events: list[object],
    ) -> None:
        self.observation = observation
        self.evaluation = evaluation
        self.events = events
        self.closed = False
        self.logical_bindings = {
            "observability.observation_port": object(),
            "observability.evaluation_port": object(),
            "research_agent": object(),
            "research_task": object(),
        }

    async def resolve_logical(self, name: str) -> object:
        if name == "observability.observation_port":
            return self.observation
        if name == "observability.evaluation_port":
            return self.evaluation
        if name == "research_agent":
            return "research-agent"
        if name == "research_task":
            return "research-task"
        raise AssertionError(name)

    async def close(self) -> None:
        self.events.append("root-close")
        self.closed = True


def _patch_standard_lifespan_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_settings: object,
    root: _ObservabilityRoot,
    storage: _Dependency,
    session: _Dependency,
    bus: object,
    events: list[object],
) -> None:
    import xhs_food.composition as composition
    import xhs_food.events.bus as event_bus_module
    import xhs_food.foundation as foundation
    import xhs_food.services as services_module
    import xhs_food.services.user_storage as storage_module

    def build_root(**kwargs: Any) -> _ObservabilityRoot:
        assert kwargs["target_settings"] is target_settings
        events.append("root-build")
        return root

    async def get_storage() -> _Dependency:
        return storage

    async def get_session() -> _Dependency:
        return session

    async def get_bus() -> object:
        return bus

    async def shutdown_bus() -> None:
        events.append("event-bus-shutdown")

    monkeypatch.setattr(foundation, "TargetSettings", lambda: target_settings)
    monkeypatch.setattr(composition, "build_composition_root", build_root)
    monkeypatch.setattr(storage_module, "get_user_storage_service", get_storage)
    monkeypatch.setattr(services_module, "get_session_manager", get_session)
    monkeypatch.setattr(event_bus_module, "get_event_bus", get_bus)
    monkeypatch.setattr(event_bus_module, "shutdown_event_bus", shutdown_bus)


@pytest.mark.unit
async def test_reliable_lifespan_binds_target_runtime_without_legacy_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.main as api_main
    import xhs_food.composition as composition
    import xhs_food.events.bus as event_bus_module
    import xhs_food.services as services_module
    import xhs_food.services.user_storage as storage_module

    calls: list[str] = []
    runtime = _Runtime(calls)
    root = _Root(runtime)
    storage = _Dependency()
    session = _Dependency()
    shutdown_calls: list[str] = []

    async def build_runtime(**_: Any) -> _Runtime:
        calls.append("runtime-build")
        return runtime

    def build_root(**kwargs: Any) -> _Root:
        target_settings = kwargs.pop("target_settings")
        assert target_settings.reliable_task_lifecycle is True
        assert kwargs == {
            "reliable_policy": runtime.policy,
            "reliable_task_store": runtime.task_store,
            "reliable_projection_store": runtime.projection_store,
            "reliable_event_bus": runtime.event_bus,
            "reliable_task_lifecycle": True,
        }
        calls.append("root-build")
        return root

    async def forbidden_legacy_bus(**_: Any) -> object:
        raise AssertionError("reliable lifespan must not initialize legacy EventBus")

    async def shutdown() -> None:
        shutdown_calls.append("event-bus-shutdown")

    monkeypatch.setenv("MODULAR_TARGET_ADAPTERS_ENABLED", "true")
    monkeypatch.setenv("MODULAR_RELIABLE_TASK_LIFECYCLE", "true")
    monkeypatch.setattr(composition, "build_reliable_runtime_bindings", build_runtime)
    monkeypatch.setattr(composition, "build_composition_root", build_root)
    async def get_storage() -> _Dependency:
        return storage

    async def get_session() -> _Dependency:
        return session

    monkeypatch.setattr(storage_module, "get_user_storage_service", get_storage)
    monkeypatch.setattr(services_module, "get_session_manager", get_session)
    monkeypatch.setattr(event_bus_module, "get_event_bus", forbidden_legacy_bus)
    monkeypatch.setattr(event_bus_module, "shutdown_event_bus", shutdown)

    application = FastAPI()
    async with api_main.lifespan(application):
        assert application.state.composition_root is root
        assert application.state.reliable_task_lifecycle is True
        assert application.state.reliable_event_bus is runtime.event_bus
        assert application.state.reliable_projection_store is runtime.projection_store
        assert application.state.research_task == "research-task-port"

    assert calls == ["runtime-build", "root-build", "redis-ping", "runtime-close"]
    assert root.closed is True
    assert storage.closed is False
    assert session.closed is True
    assert shutdown_calls == ["event-bus-shutdown"]


@pytest.mark.unit
async def test_lifespan_starts_async_observation_and_flushes_before_business_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.main as api_main
    from xhs_food.foundation.config import TargetSettings

    events: list[object] = []
    observation = _ObservationPort(events)
    evaluation = _EvaluationPort(events)
    root = _ObservabilityRoot(observation, evaluation, events)
    storage = _Dependency(initialized=True)
    session = _Dependency(initialized=True)
    target = TargetSettings(
        _env_file=None,
        otel_enabled=True,
        otel_exporter_endpoint="http://telemetry.invalid/v1/traces",
        otel_shutdown_flush_timeout_ms=100,
    )
    _patch_standard_lifespan_dependencies(
        monkeypatch,
        target_settings=target,
        root=root,
        storage=storage,
        session=session,
        bus=object(),
        events=events,
    )

    application = FastAPI()
    async with api_main.lifespan(application):
        assert application.state.observation_port is observation
        assert application.state.evaluation_port is evaluation
        assert "start" in events
        assert "start-complete" in events

    assert events.index("start-complete") > events.index("start")
    assert any(
        isinstance(item, tuple) and item[0] == "flush" and item[1] == 0.1
        for item in events
    )
    assert events.index("root-close") > events.index("event-bus-shutdown")
    assert storage.closed is True
    assert session.closed is True
    assert root.closed is True


@pytest.mark.unit
async def test_lifespan_observability_start_and_flush_failures_do_not_block_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.main as api_main
    from xhs_food.foundation.config import TargetSettings

    events: list[object] = []
    observation = _ObservationPort(events, start_error=True, flush_delay=0.2)
    evaluation = _EvaluationPort(events, close_delay=0.2)
    root = _ObservabilityRoot(observation, evaluation, events)
    storage = _Dependency(initialized=True)
    session = _Dependency(initialized=True)
    target = TargetSettings(
        _env_file=None,
        otel_enabled=True,
        otel_exporter_endpoint="http://telemetry.invalid/v1/traces",
        otel_shutdown_flush_timeout_ms=1,
    )
    _patch_standard_lifespan_dependencies(
        monkeypatch,
        target_settings=target,
        root=root,
        storage=storage,
        session=session,
        bus=object(),
        events=events,
    )

    application = FastAPI()
    async with api_main.lifespan(application):
        assert application.state.observation_port is observation
        assert application.state.evaluation_port is evaluation

    assert "start" in events
    assert "flush-cancelled" in events
    assert "evaluation-close-cancelled" in events
    assert "event-bus-shutdown" in events
    assert "root-close" in events
    assert storage.closed is True
    assert session.closed is True
    assert root.closed is True


@pytest.mark.unit
async def test_lifespan_exporter_failures_are_logged_and_business_shutdown_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.main as api_main
    from xhs_food.foundation.config import TargetSettings

    events: list[object] = []
    observation = _ObservationPort(events, flush_error=True)
    evaluation = _EvaluationPort(events, close_error=True)
    root = _ObservabilityRoot(observation, evaluation, events)
    storage = _Dependency(initialized=True)
    session = _Dependency(initialized=True)
    target = TargetSettings(
        _env_file=None,
        otel_enabled=True,
        otel_exporter_endpoint="http://telemetry.invalid/v1/traces",
        otel_shutdown_flush_timeout_ms=100,
    )
    _patch_standard_lifespan_dependencies(
        monkeypatch,
        target_settings=target,
        root=root,
        storage=storage,
        session=session,
        bus=object(),
        events=events,
    )

    application = FastAPI()
    async with api_main.lifespan(application):
        pass

    assert any(isinstance(item, tuple) and item[0] == "flush" for item in events)
    assert "evaluation-close" in events
    assert "event-bus-shutdown" in events
    assert "root-close" in events
    assert storage.closed is True
    assert session.closed is True
    assert root.closed is True
