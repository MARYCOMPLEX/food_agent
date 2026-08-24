"""Offline B0 reliable-task lifecycle contracts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from xhs_food.composition.adapters import (
    PostgresReliableTaskAuthority,
    PostgresReliableTaskStore,
    ReliableTaskEventBusPublisher,
)
from xhs_food.composition.adapters.reliable_task_authority import _projection_is_older
from xhs_food.contracts import (
    ContractError,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    TaskEvent,
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
from xhs_food.orchestrator.projections import InMemoryTaskProgressProjectionStore


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


class _BlockingWorkflow(_Workflow):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self, command: Any) -> WorkflowRun:
        self.starts.append(command)
        self.started.set()
        await self.release.wait()
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


class _ReliableTaskStore:
    def __init__(self) -> None:
        self.records: dict[str, tuple[Any, Any]] = {}
        self.admissions = 0
        self.saves = 0

    async def get(self, task_id: str) -> tuple[Any, Any] | None:
        return self.records.get(task_id)

    async def admit(self, task: Any, request: Any) -> tuple[Any, bool]:
        self.admissions += 1
        existing = self.records.get(task.task_id)
        if existing is not None:
            return existing[0], False
        self.records[task.task_id] = (task, request)
        return task, True

    async def save(self, task: Any, request: Any) -> Any:
        self.saves += 1
        self.records[task.task_id] = (task, request)
        return task


class _EventBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> str:
        self.events.append(event)
        return f"stream:{len(self.events)}"

    async def subscribe(
        self, topic: str, after: str | None = None
    ) -> AsyncIterator[Any]:
        del topic, after
        if False:  # pragma: no cover - protocol-only fixture path
            yield self.events[0]


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
async def test_concurrent_equivalent_admission_waits_for_one_workflow_attach() -> None:
    workflow = _BlockingWorkflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)

    first_request = asyncio.create_task(coordinator.submit(_request("request-1")))
    await workflow.started.wait()
    second_request = asyncio.create_task(coordinator.submit(_request("request-2")))
    await asyncio.sleep(0)
    workflow.release.set()
    first, second = await asyncio.gather(first_request, second_request)

    assert first.task_id == second.task_id
    assert first.workflow_id == second.workflow_id
    assert first.run_id == second.run_id
    assert len(workflow.starts) == 1


@pytest.mark.unit
async def test_reliable_owner_store_hydrates_duplicate_across_coordinator_instances() -> None:
    store = _ReliableTaskStore()
    first_workflow = _Workflow()
    first_policy = TemporalReliableResearchPolicy(first_workflow)
    first_coordinator = ResearchCoordinator(
        _LegacyPort(),
        reliable_task_store=store,
        reliable_policy=first_policy,
        reliable_policy_enabled=True,
    )
    first_policy.bind_owner(first_coordinator)
    first = await first_coordinator.submit(_request("request-1"))
    assert store.admissions == 1
    assert store.saves >= 1

    second_workflow = _Workflow()
    second_policy = TemporalReliableResearchPolicy(second_workflow)
    second_coordinator = ResearchCoordinator(
        _LegacyPort(),
        reliable_task_store=store,
        reliable_policy=second_policy,
        reliable_policy_enabled=True,
    )
    second_policy.bind_owner(second_coordinator)
    second = await second_coordinator.submit(_request("request-2"))

    assert second.task_id == first.task_id
    assert second.workflow_id == first.workflow_id
    assert second.run_id == first.run_id
    assert second_workflow.starts == []


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
async def test_reliable_event_publisher_maps_task_event_to_event_bus_envelope() -> None:
    event_bus = _EventBus()
    publisher = ReliableTaskEventBusPublisher(
        event_bus,
        topic_resolver=lambda event: f"session:{event.task_id}",
    )
    event = TaskEvent(
        event_id="task-1:run-1:completed",
        task_id="task-1",
        event_type="task.completed",
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        turn_id="1",
        status=TaskStatus.COMPLETED,
        payload={"result": {"answer": "ok"}},
    )

    entry_id = await publisher.publish_task_event(event, idempotency_key=event.event_id)

    assert entry_id == "stream:1"
    envelope = event_bus.events[0]
    assert envelope.event_id == event.event_id
    assert envelope.topic == "session:task-1"
    assert envelope.payload["eventType"] == "task.completed"
    assert envelope.payload["idempotencyKey"] == event.event_id
    assert envelope.payload["taskEvent"]["status"] == "completed"


@pytest.mark.unit
async def test_postgres_task_store_admission_and_cas_are_transactional() -> None:
    request = _request()
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.admit_reliable_task(
        request,
        task_id="task-1",
        workflow_id="research:task-1",
    )
    row = {
        "task_payload": task.model_dump(mode="json"),
        "request_payload": request.model_dump(mode="json"),
    }
    insert_session = _Session([row])
    insert_unit = _UnitOfWork(insert_session)
    store = PostgresReliableTaskStore(lambda: insert_unit)
    admitted, created = await store.admit(task, request)
    assert created is True
    assert admitted.task_id == task.task_id
    assert insert_unit.commits == 1
    assert len(insert_session.statements) == 1

    save_task = task.model_copy(update={"run_id": "run-1"})
    save_row = {
        "task_payload": save_task.model_dump(mode="json"),
        "request_payload": request.model_dump(mode="json"),
    }
    save_session = _Session([save_row, save_row])
    save_unit = _UnitOfWork(save_session)
    saved = await PostgresReliableTaskStore(lambda: save_unit).save(save_task, request)
    assert saved.run_id == "run-1"
    assert save_unit.commits == 1
    assert len(save_session.statements) == 2


@pytest.mark.unit
async def test_postgres_task_store_conflict_reads_existing_identity() -> None:
    request = _request()
    workflow = _Workflow()
    policy = TemporalReliableResearchPolicy(workflow)
    coordinator = ResearchCoordinator(
        _LegacyPort(), reliable_policy=policy, reliable_policy_enabled=True
    )
    policy.bind_owner(coordinator)
    task = await coordinator.admit_reliable_task(
        request,
        task_id="task-1",
        workflow_id="research:task-1",
    )
    row = {
        "task_payload": task.model_dump(mode="json"),
        "request_payload": request.model_dump(mode="json"),
    }
    session = _Session([None, row])
    unit = _UnitOfWork(session)
    admitted, created = await PostgresReliableTaskStore(lambda: unit).admit(task, request)
    assert created is False
    assert admitted.task_id == task.task_id
    assert unit.commits == 1
    assert len(session.statements) == 2


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
async def test_newer_turn_projection_wins_even_with_an_older_timestamp() -> None:
    store = InMemoryTaskProgressProjectionStore()
    current = TaskProgressProjection(
        task_id="task-1",
        turn_id="1",
        status=TaskStatus.COMPLETED,
        progress=1.0,
        updated_at="2026-08-24T00:01:00Z",
    )
    candidate = current.model_copy(
        update={
            "turn_id": "2",
            "status": TaskStatus.RUNNING,
            "progress": 0.0,
            "updated_at": "2026-08-24T00:00:00Z",
        }
    )
    assert await store.put(current) == current
    assert await store.put(candidate) == candidate
    assert await store.get("task-1") == candidate


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
