"""Production Composition Root lifespan binding contracts."""

from __future__ import annotations

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
