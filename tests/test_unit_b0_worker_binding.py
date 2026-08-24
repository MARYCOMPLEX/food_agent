"""B0 Research worker queue and quota binding contracts."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.composition import build_reliable_research_worker
from xhs_food.foundation import TemporalTaskQueues, build_temporal_worker
from xhs_food.orchestrator import ReliableTaskConfig


class _WorkerFixture:
    def __init__(self, client: Any, **kwargs: Any) -> None:
        self.client = client
        self.kwargs = kwargs


class _Activities:
    def activities(self) -> tuple[str, ...]:
        return ("activity",)


class _Plugin:
    pass


@pytest.mark.unit
def test_temporal_worker_uses_queue_quota_and_rejects_disabled_workloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import temporalio.worker

    monkeypatch.setattr(temporalio.worker, "Worker", _WorkerFixture)
    queues = TemporalTaskQueues(research="research", refresh="refresh", media="media")
    worker = build_temporal_worker(
        object(),
        task_queues=queues,
        queue="research",
        workflows=(str,),
        activities=(lambda: None,),
    )

    assert worker.kwargs["task_queue"] == "research"
    assert worker.kwargs["max_concurrent_activities"] == 8
    assert worker.kwargs["max_concurrent_workflow_tasks"] == 8
    with pytest.raises(ValueError, match="disabled"):
        build_temporal_worker(
            object(),
            task_queues=queues,
            queue="refresh",
            workflows=(),
            activities=(),
        )


@pytest.mark.unit
def test_reliable_research_worker_registers_workflow_activities_and_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_worker(client: Any, **kwargs: Any) -> object:
        captured.update(kwargs)
        captured["client"] = client
        return object()

    monkeypatch.setattr(
        "xhs_food.foundation.build_temporal_worker",
        fake_worker,
    )
    monkeypatch.setattr(
        "xhs_food.orchestrator.reliable_task.pydantic_ai_worker_plugin",
        lambda: _Plugin(),
    )

    worker = build_reliable_research_worker(
        object(),
        _Activities(),  # type: ignore[arg-type]
        config=ReliableTaskConfig(task_queue="research"),
    )

    assert worker is not None
    assert captured["queue"] == "research"
    assert captured["activities"] == ("activity",)
    assert captured["plugins"] and isinstance(captured["plugins"][0], _Plugin)
    assert captured["workflows"]
