"""B0 rollback/rebind contracts for the legacy task policy."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

import pytest

from xhs_food.composition import build_legacy_composition_root
from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
from xhs_food.contracts import (
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    WorkflowRun,
)
from xhs_food.orchestrator import TemporalReliableResearchPolicy
from xhs_food.orchestrator.coordinator import ResearchCoordinator


class _LegacyPort:
    async def start_new(self, query: str) -> Any:
        raise AssertionError(query)

    async def refine(self, session_id: str, query: str) -> Any:
        raise AssertionError((session_id, query))

    async def recover(self, session_id: str) -> dict[str, Any]:
        return {"sessionId": session_id}

    async def status(self, session_id: str) -> dict[str, Any] | None:
        return None

    async def results(self, session_id: str) -> dict[str, Any] | None:
        return None


class _WorkflowHistory:
    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.runs: dict[str, WorkflowRun] = {}

    async def start(self, command: Any) -> WorkflowRun:
        self.starts.append(command)
        existing = self.runs.get(command.workflow_id)
        if existing is not None and existing.status not in {"completed", "failed", "cancelled"}:
            return existing
        run = WorkflowRun(
            workflow_id=command.workflow_id,
            run_id=f"run-{len(self.starts)}",
            status="running",
        )
        self.runs[command.workflow_id] = run
        return run

    async def signal(self, workflow_id: str, signal: str, payload: dict[str, Any]) -> None:
        del workflow_id, signal, payload

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        del workflow_id, reason

    async def describe(self, workflow_id: str) -> WorkflowRun | None:
        return self.runs.get(workflow_id)


def _request() -> ResearchRequest:
    return ResearchRequest(
        request_id="rollback-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="回切后仍保留历史",
        identity=RequestIdentity(session_ref="rollback-session"),
        policy=RequestPolicy(policy_version="research/v1", compatibility_version="http/v1"),
    )


@pytest.mark.unit
async def test_b0_rollback_rebinds_legacy_without_new_temporal_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _WorkflowHistory()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    assert task.workflow_id is not None
    history_before = dict(workflow.runs)
    starts_before = len(workflow.starts)

    # The gate only closes new reliable ingress. Existing history remains
    # queryable and is intentionally not cancelled, deleted, or rewritten.
    policy.disable_admission()

    monkeypatch.setenv("MODULAR_RELIABLE_TASK_LIFECYCLE", "false")
    monkeypatch.setenv("MODULAR_RESEARCH_CORE_VERSION", "legacy/v1")
    monkeypatch.setenv("MODULAR_TARGET_ADAPTERS_ENABLED", "false")
    root = build_legacy_composition_root()
    try:
        binding = root.registries["use_cases"].bindings["research_task"]
        assert binding.contract_version == "legacy/v1"
        assert "reliable_task_lifecycle" not in root.logical_bindings
        assert "reliable_task_store" not in root.logical_bindings
        assert "reliable_projection_store" not in root.logical_bindings
        assert all(
            not binding.enabled
            for binding in root.registries["target_foundation"].bindings.values()
        )

        legacy = await root.resolve_logical("modular_core")
        assert isinstance(legacy, LegacyResearchTaskFacade)
        assert callable(getattr(legacy, "start_new"))
        assert callable(getattr(legacy, "recover"))
        assert callable(getattr(legacy, "status"))
        assert callable(getattr(legacy, "results"))

        # The old run and its Temporal history survive the rebind unchanged.
        assert workflow.runs == history_before
        assert len(workflow.starts) == starts_before
    finally:
        await root.close()


@pytest.mark.unit
async def test_b0_rollback_legacy_facade_accepts_request_without_temporal_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the legacy admission path after the reliable flag is off."""

    workflow = _WorkflowHistory()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    await coordinator.submit(_request())
    starts_before = len(workflow.starts)

    class _Emitter:
        steps: list[dict[str, Any]] = []

        def reset(self) -> None:
            return None

        def init_steps(self, query: str) -> None:
            del query

    class _Manager:
        async def add_user_message(self, session_id: str, query: str) -> None:
            del session_id, query

    class _Storage:
        async def create_search_history(self, **kwargs: Any) -> None:
            del kwargs

    async def _noop_state(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def _get_emitter(session_id: str) -> _Emitter:
        del session_id
        return _Emitter()

    async def _get_manager() -> _Manager:
        return _Manager()

    async def _get_storage() -> _Storage:
        return _Storage()

    async def _run_stream(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    import xhs_food.composition.legacy_research_task as legacy_module

    monkeypatch.setattr(legacy_module.legacy_state, "update_state", _noop_state)
    monkeypatch.setattr(legacy_module, "get_emitter", _get_emitter)
    monkeypatch.setattr(legacy_module, "get_session_manager", _get_manager)
    monkeypatch.setattr(legacy_module, "get_user_storage_service", _get_storage)
    monkeypatch.setattr(legacy_module.legacy_tasks, "run_stream_search", _run_stream)
    monkeypatch.setenv("MODULAR_RELIABLE_TASK_LIFECYCLE", "false")
    monkeypatch.setenv("MODULAR_RESEARCH_CORE_VERSION", "legacy/v1")
    monkeypatch.setenv("MODULAR_TARGET_ADAPTERS_ENABLED", "false")

    root = build_legacy_composition_root()
    try:
        legacy = await root.resolve_logical("modular_core")
        assert isinstance(legacy, LegacyResearchTaskFacade)
        spawned: list[Coroutine[Any, Any, None]] = []

        def _capture(coroutine: Coroutine[Any, Any, None]) -> object:
            spawned.append(coroutine)
            coroutine.close()
            return object()

        legacy._task_spawner = _capture
        admission = await legacy.start_new("legacy request after rollback")
        assert admission.operation is ResearchOperation.QUERY
        assert admission.stream_ref.endswith(admission.session_id)
        assert len(workflow.starts) == starts_before
        assert len(spawned) == 1
    finally:
        await root.close()
