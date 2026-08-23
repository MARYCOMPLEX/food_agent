"""Offline B0 reliable-task lifecycle contracts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_food.composition.adapters import PostgresReliableTaskAuthority
from xhs_food.composition.adapters.reliable_task_authority import _projection_is_older
from xhs_food.contracts import (
    ContractError,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    TaskProgressProjection,
    TaskStatus,
    WorkflowRun,
)
from xhs_food.orchestrator import (
    InMemoryReliableTaskAuthority,
    InMemoryReliableTaskEventPublisher,
    ReliableResearchActivities,
    TemporalReliableResearchPolicy,
    build_workflow_start,
    stable_research_task_id,
)
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


class _Workflow:
    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.cancels: list[tuple[str, str | None]] = []
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
        self.cancels.append((workflow_id, reason))

    async def describe(self, workflow_id: str) -> WorkflowRun | None:
        return self.runs.get(workflow_id)


class _Rows:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def first(self) -> dict[str, Any] | None:
        return self._row


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Rows:
        return _Rows(self._row)


class _Session:
    def __init__(self, results: list[dict[str, Any] | None]) -> None:
        self.results = list(results)
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        del params
        self.statements.append(str(statement))
        return _Result(self.results.pop(0))


class _UnitOfWork:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.commits = 0

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args

    def session_for_adapter(self) -> _Session:
        return self.session

    async def commit(self) -> None:
        self.commits += 1


def _request(
    request_id: str = "request-1",
    *,
    session: str = "session-1",
    query: str = "成都火锅",
) -> ResearchRequest:
    return ResearchRequest(
        request_id=request_id,
        operation=ResearchOperation.QUERY,
        domain="food",
        query=query,
        identity=RequestIdentity(session_ref=session),
        policy=RequestPolicy(policy_version="research/v1", compatibility_version="http/v1"),
    )


@pytest.mark.unit
async def test_duplicate_submission_returns_one_task_and_one_temporal_identity() -> None:
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)

    first = await coordinator.submit(_request())
    second = await coordinator.submit(_request("request-2"))

    assert first.task_id == second.task_id == stable_research_task_id(_request())
    assert first.workflow_id == second.workflow_id
    assert first.run_id == second.run_id
    assert len(workflow.starts) == 1
    assert workflow.starts[0].input["task_id"] == first.task_id
    assert workflow.starts[0].input["request"]["query"] == "成都火锅"


@pytest.mark.unit
async def test_activity_commit_barrier_precedes_terminal_event_and_is_idempotent() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()
    request = _request()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(request)
    assert task.workflow_id is not None and task.run_id is not None

    async def execute(value: Any, idempotency_key: str) -> dict[str, Any]:
        assert value.task_id == task.task_id
        assert idempotency_key.endswith(":execute")
        return {"summary": "已验证", "recommendations": []}

    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=execute,
        publisher=publisher,
    )
    raw = build_workflow_start(
        request,
        task_id=task.task_id,
        plan_id=task.plan_id or "plan",
        turn_id=task.turn_id or "1",
    ).input
    result = await activities.execute(raw, "research-activity/v1")
    await activities.progress(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "progress": 0.8,
            "current_step_id": "research.commit",
        }
    )
    receipt = await activities.commit(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "result": result,
            "idempotency_key": f"{task.task_id}:{task.run_id}:result",
        }
    )
    assert receipt["committed"] is True
    assert (await coordinator.task(task.task_id)).status is TaskStatus.COMPLETED  # type: ignore[union-attr]
    assert len(await coordinator.events(task.task_id)) == 2  # accepted + terminal

    published = await activities.publish_terminal(
        {
            "event_id": f"{task.task_id}:{task.run_id}:completed",
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "turn_id": task.turn_id,
            "status": "completed",
            "result": result,
            "idempotency_key": f"{task.task_id}:{task.run_id}:completed",
        }
    )
    assert published is True
    assert list(publisher.events) == [f"{task.task_id}:{task.run_id}:completed"]

    # A redelivered commit does not create another result or terminal event.
    await activities.commit(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "result": result,
            "idempotency_key": f"{task.task_id}:{task.run_id}:result",
        }
    )
    assert len(await coordinator.events(task.task_id)) == 2
    assert len(authority.receipts) == 1


@pytest.mark.unit
async def test_cancellation_is_a_temporal_command_and_does_not_fabricate_terminal_state() -> None:
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())

    assert await policy.cancel(task.task_id, "user requested") is True
    assert workflow.cancels == [(task.workflow_id or "", "user requested")]
    current = await coordinator.task(task.task_id)
    assert current is not None and current.status is TaskStatus.RUNNING


@pytest.mark.unit
async def test_postgres_authority_uses_one_transaction_and_idempotent_receipt() -> None:
    row = {
        "task_id": "task-1",
        "workflow_id": "research:task-1",
        "run_id": "run-1",
        "status": "completed",
        "payload": {"answer": "ok"},
        "idempotency_key": "task-1:run-1:result",
        "result_version": "result-1",
    }
    first_session = _Session([row])
    first_unit = _UnitOfWork(first_session)
    authority = PostgresReliableTaskAuthority(lambda: first_unit)
    receipt = await authority.commit_result(
        "task-1",
        "research:task-1",
        "run-1",
        {"answer": "ok"},
        idempotency_key="task-1:run-1:result",
    )
    assert receipt.committed is True
    assert receipt.already_committed is False
    assert first_unit.commits == 1
    assert len(first_session.statements) == 1

    duplicate_session = _Session([None, row])
    duplicate_unit = _UnitOfWork(duplicate_session)
    duplicate_authority = PostgresReliableTaskAuthority(lambda: duplicate_unit)
    duplicate = await duplicate_authority.commit_result(
        "task-1",
        "research:task-1",
        "run-1",
        {"answer": "ok"},
        idempotency_key="task-1:run-1:result",
    )
    assert duplicate.already_committed is True
    assert duplicate_unit.commits == 1
    assert len(duplicate_session.statements) == 2


@pytest.mark.unit
async def test_postgres_failed_receipt_preserves_terminal_status() -> None:
    row = {
        "task_id": "task-1",
        "workflow_id": "research:task-1",
        "run_id": "run-1",
        "status": "failed",
        "payload": {"error": {"code": "RESEARCH_EXECUTION_FAILED"}},
        "idempotency_key": "task-1:run-1:failed",
        "result_version": "failure-1",
    }
    session = _Session([row])
    unit = _UnitOfWork(session)
    authority = PostgresReliableTaskAuthority(lambda: unit)
    receipt = await authority.commit_failed(
        "task-1",
        "research:task-1",
        "run-1",
        ContractError(
            code="RESEARCH_EXECUTION_FAILED",
            category="internal",
            scope="task",
            terminal=True,
            message="provider failed",
        ),
        idempotency_key="task-1:run-1:failed",
    )

    assert receipt.committed is True
    assert receipt.terminal_status is TaskStatus.FAILED


@pytest.mark.unit
async def test_pg_commit_failure_does_not_finalize_or_publish_terminal() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    authority.fail_commits = True
    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=lambda value, key: _result_payload(value, key),
        publisher=publisher,
    )

    with pytest.raises(Exception):
        await activities.commit(
            {
                "task_id": task.task_id,
                "workflow_id": task.workflow_id,
                "run_id": task.run_id,
                "result": {"answer": "ok"},
                "idempotency_key": f"{task.task_id}:{task.run_id}:result",
            }
        )
    current = await coordinator.task(task.task_id)
    assert current is not None and current.status is TaskStatus.RUNNING
    assert publisher.events == {}


@pytest.mark.unit
async def test_late_old_run_progress_cannot_move_new_run_projection() -> None:
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    assert task.workflow_id is not None
    await coordinator.attach_reliable_run(
        task.task_id,
        WorkflowRun(workflow_id=task.workflow_id, run_id="run-new", status="running"),
    )
    current = await coordinator.record_reliable_progress(
        task.task_id,
        workflow_id=task.workflow_id,
        run_id="run-new",
        progress=0.8,
        current_step_id="research.commit",
    )
    old = await coordinator.record_reliable_progress(
        task.task_id,
        workflow_id=task.workflow_id,
        run_id="run-old",
        progress=0.1,
        current_step_id="research.execute",
    )
    assert old.run_id == "run-new"
    assert old.progress == current.progress == 0.8


@pytest.mark.unit
def test_newer_turn_can_replace_terminal_projection() -> None:
    current = TaskProgressProjection(
        task_id="task-1",
        turn_id="1",
        status=TaskStatus.COMPLETED,
        progress=1.0,
        updated_at="2026-08-24T00:00:00Z",
    )
    candidate = current.model_copy(
        update={
            "turn_id": "2",
            "status": TaskStatus.RUNNING,
            "progress": 0.0,
            "updated_at": "2026-08-24T00:01:00Z",
        }
    )

    assert _projection_is_older(current, candidate) is False


@pytest.mark.unit
async def test_reconciliation_after_commit_republishes_one_terminal_event() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    assert task.workflow_id is not None and task.run_id is not None
    authority.results[task.task_id] = {"answer": "committed-before-crash"}
    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=_result_payload,
        publisher=publisher,
    )

    assert await activities.reconcile(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
        }
    ) is True
    assert (await coordinator.task(task.task_id)).status is TaskStatus.COMPLETED  # type: ignore[union-attr]
    assert len(publisher.events) == 1
    assert await activities.reconcile(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
        }
    ) is True
    assert len(publisher.events) == 1


@pytest.mark.unit
async def test_terminal_event_type_matches_failed_and_cancelled_status() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=_result_payload,
        publisher=publisher,
    )
    for status in ("failed", "cancelled"):
        event_id = f"{task.task_id}:run-{status}:{status}"
        await activities.publish_terminal(
            {
                "event_id": event_id,
                "task_id": task.task_id,
                "workflow_id": task.workflow_id,
                "run_id": f"run-{status}",
                "turn_id": task.turn_id,
                "status": status,
                "result": {},
                "idempotency_key": event_id,
            }
        )
    assert [event.event_type for event in publisher.events.values()] == [
        "task.failed",
        "task.cancelled",
    ]


@pytest.mark.unit
async def test_failed_activity_uses_authority_barrier_before_terminal_publication() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    publisher = InMemoryReliableTaskEventPublisher()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    activities = ReliableResearchActivities(
        owner=coordinator,
        authority=authority,
        executor=_result_payload,
        publisher=publisher,
    )
    error = {
        "code": "RESEARCH_EXECUTION_FAILED",
        "category": "internal",
        "scope": "task",
        "terminal": True,
        "message": "provider failed",
    }
    receipt = await activities.fail(
        {
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "error": error,
            "idempotency_key": f"{task.task_id}:{task.run_id}:failed",
        }
    )
    assert receipt["committed"] is True
    current = await coordinator.task(task.task_id)
    assert current is not None and current.status is TaskStatus.FAILED
    assert publisher.events == {}
    assert await activities.publish_terminal(
        {
            "event_id": f"{task.task_id}:{task.run_id}:failed",
            "task_id": task.task_id,
            "workflow_id": task.workflow_id,
            "run_id": task.run_id,
            "turn_id": task.turn_id,
            "status": "failed",
            "result": {"error": error},
            "idempotency_key": f"{task.task_id}:{task.run_id}:failed",
        }
    ) is True
    assert len(publisher.events) == 1


@pytest.mark.unit
async def test_same_run_terminal_race_keeps_one_authoritative_status() -> None:
    workflow = _Workflow()
    authority = InMemoryReliableTaskAuthority()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.submit(_request())
    completed, cancelled = await asyncio.gather(
        authority.commit_result(
            task.task_id,
            task.workflow_id or "",
            task.run_id or "",
            {"answer": "ok"},
            idempotency_key=f"{task.task_id}:{task.run_id}:result",
        ),
        authority.commit_cancelled(
            task.task_id,
            task.workflow_id or "",
            task.run_id or "",
            idempotency_key=f"{task.task_id}:{task.run_id}:cancel",
        ),
    )
    assert completed.terminal_status is cancelled.terminal_status
    assert completed.already_committed != cancelled.already_committed


@pytest.mark.unit
async def test_reliable_refine_is_rejected_until_identity_contract_is_approved() -> None:
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    request = _request(query="换个口味", session="session-1")
    request = request.model_copy(
        update={"operation": ResearchOperation.REFINE, "target_task_id": "task-existing"}
    )
    with pytest.raises(Exception, match="refine identity"):
        await coordinator.submit(request)
async def _result_payload(value: Any, key: str) -> dict[str, Any]:
    del key
    return {"task_id": value.task_id, "answer": "ok"}


@pytest.mark.unit
def test_workflow_command_uses_versioned_input_and_stable_idempotency_key() -> None:
    request = _request()
    command = build_workflow_start(
        request,
        task_id="task-fixed",
        plan_id="plan-fixed",
        turn_id="1",
    )
    assert command.workflow_id == "research:task-fixed"
    assert command.workflow_type == "research-task/v1"
    assert command.task_queue == "research"
    assert command.idempotency_key == "task-fixed"
    assert command.input["policy_version"] == "reliable-task/v1"
    assert command.input["activity_policy"]["retry_maximum_attempts"] == 3
