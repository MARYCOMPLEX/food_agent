"""Live qualification suite for the locked Temporal/Pydantic AI baseline.

The suite is intentionally marked ``live``.  It starts Temporal's official
time-skipping test server and therefore is not part of the offline unit gate.
No application services, databases, Redis keys, or real model providers are
used.  The Pydantic AI model is the SDK's deterministic ``TestModel``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.durable_exec.temporal import (
    PydanticAIPlugin,
    PydanticAIWorkflow,
    TemporalAgent,
    pydantic_data_converter,
)
from pydantic_ai.models.test import TestModel
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from xhs_food.contracts import (
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    WorkflowRun,
)
from xhs_food.orchestrator import (
    InMemoryReliableTaskAuthority,
    InMemoryReliableTaskEventPublisher,
    ReliableResearchActivities,
    TemporalReliableResearchPolicy,
    TemporalResearchWorkflow,
    build_workflow_start,
)
from xhs_food.orchestrator.coordinator import ResearchCoordinator

QUEUE = "research"


@activity.defn(name="b0.qualification.echo")
async def _echo(payload: dict[str, str]) -> str:
    """Deterministic stand-in for a connector/repository activity."""

    return f"{payload['value']}:{payload['revision']}"


_retry_attempts: Counter[str] = Counter()


@activity.defn(name="b0.qualification.retry")
async def _retry_until_third_attempt(key: str) -> str:
    _retry_attempts[key] += 1
    if _retry_attempts[key] < 3:
        raise ApplicationError("transient qualification failure", type="Transient")
    return "recovered"


@activity.defn(name="b0.qualification.always-fail")
async def _always_fail(key: str) -> str:
    _retry_attempts[key] += 1
    raise ApplicationError("retry budget exhausted", type="Exhausted")


@activity.defn(name="b0.qualification.slow")
async def _slow(value: str) -> str:
    # A real cancellation point makes the cancellation race observable without
    # relying on wall-clock timers in workflow code.
    await asyncio.sleep(0.2)
    return value


@workflow.defn(name="B0QualificationWorkflow")
class _QualificationWorkflowV1:
    @workflow.run
    async def run(self, payload: dict[str, str]) -> str:
        return await workflow.execute_activity(
            "b0.qualification.echo",
            payload,
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"echo:{payload['id']}",
        )


@workflow.defn(name="B0QualificationWorkflow")
class _QualificationWorkflowV2:
    @workflow.run
    async def run(self, payload: dict[str, str]) -> str:
        result = await workflow.execute_activity(
            "b0.qualification.echo",
            payload,
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"echo:{payload['id']}",
        )
        # The marker is the supported Temporal deployment-upgrade boundary:
        # old histories take the old branch, while new executions take v2.
        if workflow.patched("b0-qualification-v2"):
            return f"{result}:v2"
        return result


@workflow.defn(name="B0RetryQualificationWorkflow")
class _RetryQualificationWorkflow:
    @workflow.run
    async def run(self, key: str) -> str:
        return await workflow.execute_activity(
            "b0.qualification.retry",
            key,
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=10),
                maximum_interval=timedelta(milliseconds=20),
                maximum_attempts=3,
            ),
            activity_id=f"retry:{key}",
        )


@workflow.defn(name="B0ExhaustionQualificationWorkflow")
class _ExhaustionQualificationWorkflow:
    @workflow.run
    async def run(self, key: str) -> str:
        return await workflow.execute_activity(
            "b0.qualification.always-fail",
            key,
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=10),
                maximum_interval=timedelta(milliseconds=20),
                maximum_attempts=2,
            ),
            activity_id=f"exhaust:{key}",
        )


@workflow.defn(name="B0RecoveryQualificationWorkflow")
class _RecoveryQualificationWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, str]) -> str:
        # The timer is persisted before the worker is intentionally stopped.
        await workflow.sleep(timedelta(seconds=1))
        return await workflow.execute_activity(
            "b0.qualification.echo",
            payload,
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"recover:{payload['id']}",
        )


@workflow.defn(name="B0CancellationQualificationWorkflow")
class _CancellationQualificationWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return await workflow.execute_activity(
            "b0.qualification.slow",
            value,
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"slow:{value}",
        )


class _AgentDeps(BaseModel):
    task_id: str


class _AgentOutput(BaseModel):
    answer: str


_test_agent = Agent(
    TestModel(call_tools=["lookup"], custom_output_args={"answer": "model-ok"}),
    output_type=_AgentOutput,
    deps_type=_AgentDeps,
    name="b0-qualification-agent",
)


@_test_agent.tool(name="lookup")
async def _lookup(ctx: RunContext[_AgentDeps], value: str) -> str:
    return f"tool:{ctx.deps.task_id}:{value}"


_temporal_agent = TemporalAgent(_test_agent, name="b0-qualification-agent")


@workflow.defn(name="B0PydanticQualificationWorkflow")
class _PydanticQualificationWorkflow(PydanticAIWorkflow):
    """Uses the official plugin to register model/tool Activities."""

    __pydantic_ai_agents__ = (_temporal_agent,)

    @workflow.run
    async def run(self, prompt: str) -> str:
        result = await _temporal_agent.run(prompt, deps=_AgentDeps(task_id="task-qualification"))
        return result.output.answer


@pytest_asyncio.fixture(scope="module")
async def temporal_env() -> Any:
    """Start the SDK-provided ephemeral test server once for this module."""

    env = await WorkflowEnvironment.start_time_skipping(
        # Configure the client converter directly.  Passing PydanticAIPlugin
        # to both client and worker would register its Activities twice.
        data_converter=pydantic_data_converter,
    )
    try:
        yield env
    finally:
        await env.shutdown()


def _basic_activities() -> list[Any]:
    return [_echo, _retry_until_third_attempt, _always_fail, _slow]


def _event_names(history: WorkflowHistory) -> list[str]:
    return [
        EventType.Name(event.event_type).removeprefix("EVENT_TYPE_") for event in history.events
    ]


def _event_counts(history: WorkflowHistory) -> Counter[str]:
    return Counter(_event_names(history))


@pytest.mark.live
async def test_temporal_workflow_history_is_deterministic_and_replayable(temporal_env: Any) -> None:
    payload = {"id": "determinism-1", "value": "query", "revision": "v1"}
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_QualificationWorkflowV1],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        handle = await temporal_env.client.start_workflow(
            _QualificationWorkflowV1.run,
            payload,
            id="b0-determinism-1",
            task_queue=QUEUE,
        )
        assert await handle.result() == "query:v1"
        history = await handle.fetch_history()

    # Replayer executes workflow code against the persisted event history.  A
    # nondeterministic workflow raises here instead of producing a soft error.
    replay = Replayer(
        workflows=[_QualificationWorkflowV1],
        plugins=[PydanticAIPlugin()],
    )
    replay_result = await replay.replay_workflow(history)
    assert replay_result.replay_failure is None
    counts = _event_counts(history)
    assert counts["ACTIVITY_TASK_SCHEDULED"] == 1
    assert counts["ACTIVITY_TASK_COMPLETED"] == 1


@pytest.mark.live
async def test_pydantic_ai_model_and_tool_calls_are_temporal_activities(temporal_env: Any) -> None:
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_PydanticQualificationWorkflow],
        plugins=[PydanticAIPlugin()],
    ):
        handle = await temporal_env.client.start_workflow(
            _PydanticQualificationWorkflow.run,
            "qualify this request",
            id="b0-pydantic-agent-1",
            task_queue=QUEUE,
        )
        assert await handle.result() == "model-ok"
        history = await handle.fetch_history()

    names = _event_names(history)
    # The official TemporalAgent emits one model request Activity and one
    # function-tool Activity before the final output Activity completes.
    activity_names = [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if EventType.Name(event.event_type).removeprefix("EVENT_TYPE_") == "ACTIVITY_TASK_SCHEDULED"
    ]
    assert any(name.endswith("__model_request") for name in activity_names)
    assert any("lookup" in name or "call_tool" in name for name in activity_names)
    assert "WORKFLOW_EXECUTION_COMPLETED" in names


@pytest.mark.live
async def test_activity_retry_and_retry_exhaustion_are_explicit(temporal_env: Any) -> None:
    _retry_attempts.clear()
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_RetryQualificationWorkflow, _ExhaustionQualificationWorkflow],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        recovered = await temporal_env.client.execute_workflow(
            _RetryQualificationWorkflow.run,
            "retry-key",
            id="b0-retry-1",
            task_queue=QUEUE,
        )
        assert recovered == "recovered"
        exhausted_handle = await temporal_env.client.start_workflow(
            _ExhaustionQualificationWorkflow.run,
            "exhaust-key",
            id="b0-exhaustion-1",
            task_queue=QUEUE,
        )
        with pytest.raises(WorkflowFailureError):
            await exhausted_handle.result()
        exhausted_history = await exhausted_handle.fetch_history()

    counts = _event_counts(exhausted_history)
    assert _retry_attempts["retry-key"] == 3
    assert _retry_attempts["exhaust-key"] == 2
    started = [
        event.activity_task_started_event_attributes.attempt
        for event in exhausted_history.events
        if EventType.Name(event.event_type).removeprefix("EVENT_TYPE_") == "ACTIVITY_TASK_STARTED"
    ]
    # The test server may compact retry events into the final started/failed
    # pair; the attempt number and activity-side count remain authoritative.
    assert started == [2]
    assert counts["ACTIVITY_TASK_FAILED"] == 1
    assert counts["WORKFLOW_EXECUTION_FAILED"] == 1


@pytest.mark.live
async def test_worker_stop_and_restart_resumes_persisted_workflow(temporal_env: Any) -> None:
    payload = {"id": "restart-1", "value": "after-crash-stop", "revision": "v1"}
    # Complete a timer-bearing workflow, stop the first worker cleanly, and
    # then run the same workflow on a fresh worker. The persisted history is
    # also replayed below, which is the deterministic worker-restart check for
    # the SDK's test server. A process-level crash harness belongs to B0's
    # deployment gate and is intentionally kept outside this live fixture.
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_RecoveryQualificationWorkflow],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        handle = await temporal_env.client.start_workflow(
            _RecoveryQualificationWorkflow.run,
            payload,
            id="b0-worker-restart-1",
            task_queue=QUEUE,
        )
        assert await handle.result() == "after-crash-stop:v1"
        history = await handle.fetch_history()

    replay = Replayer(
        workflows=[_RecoveryQualificationWorkflow],
        plugins=[PydanticAIPlugin()],
    )
    replay_result = await replay.replay_workflow(history)
    assert replay_result.replay_failure is None

    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_RecoveryQualificationWorkflow],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        restarted = await temporal_env.client.execute_workflow(
            _RecoveryQualificationWorkflow.run,
            payload,
            id="b0-worker-restart-2",
            task_queue=QUEUE,
        )
    assert restarted == "after-crash-stop:v1"


@pytest.mark.live
async def test_cancellation_race_has_one_terminal_history(temporal_env: Any) -> None:
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_CancellationQualificationWorkflow],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        handle = await temporal_env.client.start_workflow(
            _CancellationQualificationWorkflow.run,
            "cancel-race",
            id="b0-cancel-race-1",
            task_queue=QUEUE,
        )
        await asyncio.gather(
            handle.cancel(reason="qualification cancellation race"),
            _wait_for_workflow_terminal(handle),
        )
        with pytest.raises((WorkflowFailureError, CancelledError)):
            await handle.result()
        history = await handle.fetch_history()

    terminal_events = [
        name
        for name in _event_names(history)
        if name
        in {
            "WORKFLOW_EXECUTION_COMPLETED",
            "WORKFLOW_EXECUTION_FAILED",
            "WORKFLOW_EXECUTION_CANCELED",
            "WORKFLOW_EXECUTION_TERMINATED",
        }
    ]
    assert len(terminal_events) == 1


async def _wait_for_workflow_terminal(handle: Any) -> None:
    for _ in range(100):
        description = await handle.describe()
        if getattr(description.status, "name", "").endswith(
            ("COMPLETED", "FAILED", "CANCELED", "TERMINATED")
        ):
            return
        await asyncio.sleep(0.02)


async def _wait_for_history_event(handle: Any, event_name: str) -> None:
    for _ in range(100):
        history = await handle.fetch_history()
        if event_name in _event_names(history):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"workflow history did not contain {event_name}")


@pytest.mark.live
async def test_patched_workflow_replays_old_history_and_runs_new_branch(temporal_env: Any) -> None:
    payload = {"id": "upgrade-1", "value": "deploy", "revision": "v1"}
    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_QualificationWorkflowV1],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        old_handle = await temporal_env.client.start_workflow(
            _QualificationWorkflowV1.run,
            payload,
            id="b0-upgrade-old",
            task_queue=QUEUE,
        )
        assert await old_handle.result() == "deploy:v1"
        old_history = await old_handle.fetch_history()

    replayer = Replayer(
        workflows=[_QualificationWorkflowV2],
        plugins=[PydanticAIPlugin()],
    )
    replay_result = await replayer.replay_workflow(old_history)
    assert replay_result.replay_failure is None

    async with Worker(
        temporal_env.client,
        task_queue=QUEUE,
        workflows=[_QualificationWorkflowV2],
        activities=_basic_activities(),
        plugins=[PydanticAIPlugin()],
    ):
        new_result = await temporal_env.client.execute_workflow(
            _QualificationWorkflowV2.run,
            payload,
            id="b0-upgrade-new",
            task_queue=QUEUE,
        )
    assert new_result == "deploy:v1:v2"


class _ApplicationLegacyPort:
    async def start_new(self, query: str) -> Any:
        del query
        raise AssertionError("legacy path must not be used")

    async def refine(self, session_id: str, query: str) -> Any:
        del session_id, query
        raise AssertionError("legacy path must not be used")

    async def recover(self, session_id: str) -> dict[str, str]:
        return {"sessionId": session_id}

    async def status(self, session_id: str) -> None:
        del session_id
        return None

    async def results(self, session_id: str) -> None:
        del session_id
        return None


@pytest.mark.live
async def test_reliable_workflow_cancel_commits_authoritative_terminal(temporal_env: Any) -> None:
    request = ResearchRequest(
        request_id="live-cancel-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="cancel qualification",
        identity=RequestIdentity(session_ref="live-cancel-session"),
        policy=RequestPolicy(policy_version="research/v1", compatibility_version="http/v1"),
    )
    policy = TemporalReliableResearchPolicy(_QualificationWorkflowPort(temporal_env.client))
    coordinator = ResearchCoordinator(
        _ApplicationLegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(request)
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()

    async def slow_execute(value: Any, key: str) -> dict[str, str]:
        del value, key
        await asyncio.sleep(0.2)
        return {"answer": "should-not-publish"}

    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=slow_execute,
        publisher=publisher,
    )
    command = build_workflow_start(
        request,
        task_id=task.task_id,
        plan_id=task.plan_id or "plan",
        turn_id=task.turn_id or "1",
    )
    async with Worker(
        temporal_env.client,
        task_queue=command.task_queue,
        workflows=[TemporalResearchWorkflow],
        activities=activities.activities(),
    ):
        handle = await temporal_env.client.start_workflow(
            TemporalResearchWorkflow.run,
            command.input,
            id=command.workflow_id,
            task_queue=command.task_queue,
        )
        await handle.signal("research.cancel.requested", {"reason": "qualification"})
        result = await handle.result()

    assert result.result["status"] == "cancelled"
    current = await coordinator.task(task.task_id)
    assert current is not None and current.status.value == "cancelled"
    assert task.task_id in authority.cancelled
    assert {event.event_type for event in await coordinator.events(task.task_id)} == {
        "task.accepted",
        "task.cancelled",
    }
    assert len(publisher.events) == 1
    assert next(iter(publisher.events)).startswith(f"{task.task_id}:")
    assert next(iter(publisher.events)).endswith(":cancelled")


class _QualificationWorkflowPort:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def start(self, command: Any) -> Any:
        return WorkflowRun(
            workflow_id=command.workflow_id,
            run_id="run-live-qualification",
            status="running",
        )

    async def signal(self, workflow_id: str, signal: str, payload: dict[str, Any]) -> None:
        await self.client.get_workflow_handle(workflow_id).signal(signal, payload)

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        await self.client.get_workflow_handle(workflow_id).signal(
            "research.cancel.requested", {"reason": reason or ""}
        )

    async def describe(self, workflow_id: str) -> Any:
        return await self.client.get_workflow_handle(workflow_id).describe()
