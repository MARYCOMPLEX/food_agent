"""Live PG/Temporal reconciliation after a worker crash post-commit."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import pytest_asyncio
from redis import asyncio as aioredis
from sqlalchemy import text
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from xhs_food.composition import build_reliable_research_worker
from xhs_food.composition.adapters import (
    PostgresReliableTaskAuthority,
    PostgresReliableTaskStore,
    PostgresTaskProgressProjectionStore,
    ReliableTaskEventBusPublisher,
)
from xhs_food.contracts import (
    ContractPayload,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    ResearchTask,
    TaskProgressProjection,
    TaskStatus,
)
from xhs_food.foundation import (
    RedisEventBusAdapter,
    SQLAlchemyDatabase,
    TemporalTaskQueues,
    TemporalWorkflowAdapter,
)
from xhs_food.orchestrator import (
    ReliableResearchActivities,
    ResearchWorkflowOutput,
    build_workflow_start,
    stable_research_task_id,
    stable_research_workflow_id,
)
from xhs_food.orchestrator.coordinator import ResearchCoordinator

QUEUE = "research"


class _LegacyPort:
    async def start_new(self, query: str) -> Any:
        raise AssertionError(query)

    async def refine(self, session_id: str, query: str) -> Any:
        raise AssertionError((session_id, query))

    async def recover(self, session_id: str) -> ContractPayload:
        return {"sessionId": session_id}

    async def status(self, session_id: str) -> None:
        del session_id
        return None

    async def results(self, session_id: str) -> None:
        del session_id
        return None


class _CrashBeforePublish:
    def __init__(self, delegate: Any, *, crash: bool, started: Any) -> None:
        self._delegate = delegate
        self._crash = crash
        self._started = started

    async def publish_task_event(self, event: Any, *, idempotency_key: str) -> str:
        if self._crash:
            self._started.set()
            os._exit(72)
        return await self._delegate.publish_task_event(event, idempotency_key=idempotency_key)


async def _execute(_: Any, __: str) -> dict[str, str]:
    return {"answer": "crash-reconcile"}


def _request(prefix: str) -> ResearchRequest:
    return ResearchRequest(
        request_id=f"{prefix}-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="PG commit 后进程崩溃对账",
        public_inputs={"idempotency_key": prefix},
        identity=RequestIdentity(session_ref=f"{prefix}-session"),
        policy=RequestPolicy(policy_version="research/v1", compatibility_version="http/v1"),
    )


async def _wait_event(event: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while not event.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return event.is_set()


async def _wait_process_exit(process: multiprocessing.Process, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return not process.is_alive()


async def _run_worker(
    target_host: str,
    namespace: str,
    postgres_url: str,
    redis_url: str,
    task_id: str,
    topic: str,
    crash: bool,
    ready: Any,
    go: Any,
    publish_started: Any,
    stop: Any,
) -> None:
    database = SQLAlchemyDatabase(postgres_url, enabled=True)
    database.start()
    redis_client = cast(Any, aioredis.from_url(redis_url, decode_responses=True))
    redis_events = RedisEventBusAdapter(redis_client)
    task_store = PostgresReliableTaskStore(database.unit_of_work)
    projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
    authority = PostgresReliableTaskAuthority(database.unit_of_work)
    owner = ResearchCoordinator(
        _LegacyPort(),
        projection_store=projection_store,
        reliable_task_store=task_store,
    )
    if await owner.reliable_task(task_id) is None:
        raise AssertionError(f"durable task {task_id!r} was not admitted")
    publisher = _CrashBeforePublish(
        ReliableTaskEventBusPublisher(
            redis_events,
            topic_resolver=lambda event: topic,
        ),
        crash=crash,
        started=publish_started,
    )
    activities = ReliableResearchActivities(
        owner=owner,
        authority=authority,
        executor=_execute,
        publisher=publisher,
    )
    client = await Client.connect(
        target_host,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )
    worker = build_reliable_research_worker(
        client,
        activities,
        task_queues=TemporalTaskQueues(research=QUEUE, refresh="refresh", media="media"),
    )
    ready.set()
    try:
        await asyncio.to_thread(go.wait)
        worker_task = asyncio.create_task(worker.run())
        try:
            await asyncio.to_thread(stop.wait)
        finally:
            if not worker_task.done():
                await worker.shutdown()
            await worker_task
    finally:
        await client.close()
        await redis_client.aclose()
        await database.aclose()


def _worker_process_entry(*args: Any) -> None:
    asyncio.run(_run_worker(*args))


@pytest_asyncio.fixture(scope="module")
async def temporal_env() -> Any:
    env = await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter)
    try:
        yield env
    finally:
        await env.shutdown()


@pytest.mark.live
async def test_worker_crash_after_postgres_commit_resumes_and_reconciles(
    temporal_env: Any,
) -> None:
    postgres_url = os.getenv("B0_POSTGRES_URL")
    redis_url = os.getenv("B0_REDIS_URL")
    if not postgres_url:
        pytest.skip("B0_POSTGRES_URL is required for crash reconciliation")
    if not redis_url:
        pytest.skip("B0_REDIS_URL is required for crash reconciliation")

    context = multiprocessing.get_context("spawn")
    prefix = f"live-b0-process-reconcile-{os.getpid()}"
    request = _request(prefix)
    task_id = stable_research_task_id(request)
    workflow_id = stable_research_workflow_id(task_id)
    topic = f"b0-{prefix}"
    now = datetime.now(UTC)
    task = ResearchTask(
        task_id=task_id,
        request_id=request.request_id,
        operation=request.operation,
        domain=request.domain,
        status=TaskStatus.RUNNING,
        turn_id="1",
        plan_id=f"plan:{task_id}:turn:1",
        workflow_id=workflow_id,
        run_id=None,
        created_at=now,
        updated_at=now,
    )
    database = SQLAlchemyDatabase(postgres_url, enabled=True)
    database.start()
    redis_client = cast(Any, aioredis.from_url(redis_url, decode_responses=True))
    task_store = PostgresReliableTaskStore(database.unit_of_work)
    projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
    authority = PostgresReliableTaskAuthority(database.unit_of_work)
    first_ready = context.Event()
    first_go = context.Event()
    first_publish_started = context.Event()
    first_stop = context.Event()
    first = context.Process(
        target=_worker_process_entry,
        args=(
            temporal_env.client.service_client.config.target_host,
            temporal_env.client.namespace,
            postgres_url,
            redis_url,
            task_id,
            topic,
            True,
            first_ready,
            first_go,
            first_publish_started,
            first_stop,
        ),
    )
    replacement: multiprocessing.Process | None = None
    replacement_ready = context.Event()
    replacement_go = context.Event()
    replacement_publish_started = context.Event()
    replacement_stop = context.Event()
    try:
        async with database.unit_of_work() as unit:
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_task_results WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.session_for_adapter().execute(
                text("DELETE FROM task_progress_projection WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.commit()
        await RedisEventBusAdapter(redis_client).delete_topic(topic)
        admitted, created = await task_store.admit(task, request)
        assert created is True
        assert admitted.task_id == task_id
        await projection_store.put(
            TaskProgressProjection(
                task_id=task_id,
                turn_id="1",
                workflow_id=workflow_id,
                run_id=None,
                status=TaskStatus.RUNNING,
                progress=0.0,
                updated_at=now,
            )
        )

        first.start()
        assert await _wait_event(first_ready, 20)
        workflow_port = TemporalWorkflowAdapter(
            temporal_env.client,
            task_queues=TemporalTaskQueues(research=QUEUE, refresh="refresh", media="media"),
            enabled=True,
        )
        run = await asyncio.wait_for(
            workflow_port.start(
                build_workflow_start(
                    request,
                    task_id=task_id,
                    plan_id=task.plan_id or f"plan:{task_id}:turn:1",
                    turn_id="1",
                )
            ),
            timeout=20,
        )
        await task_store.save(task.model_copy(update={"run_id": run.run_id}), request)
        first_go.set()
        assert await _wait_event(first_publish_started, 30)
        assert await _wait_process_exit(first, 30)
        assert first.exitcode == 72
        assert await authority.reconcile(task_id, workflow_id, run.run_id) == {
            "answer": "crash-reconcile",
            "status": "completed",
        }
        projection = await projection_store.get(task_id)
        assert projection is not None and projection.status is TaskStatus.COMPLETED

        replacement = context.Process(
            target=_worker_process_entry,
            args=(
                temporal_env.client.service_client.config.target_host,
                temporal_env.client.namespace,
                postgres_url,
                redis_url,
                task_id,
                topic,
                False,
                replacement_ready,
                replacement_go,
                replacement_publish_started,
                replacement_stop,
            ),
        )
        replacement.start()
        assert await _wait_event(replacement_ready, 20)
        replacement_go.set()
        handle = temporal_env.client.get_workflow_handle(workflow_id)
        result = ResearchWorkflowOutput.model_validate(
            await asyncio.wait_for(handle.result(), timeout=60)
        )
        assert result.committed is True
        assert result.published is True
        entries = await redis_client.xrange(f"events:{topic}:stream")
        assert len(entries) == 1
        payload = entries[0][1]["payload"]
        assert task_id in payload
        assert f"{task_id}:{run.run_id}:completed" in payload
    finally:
        if first.is_alive():
            first_stop.set()
            first.terminate()
        if not await _wait_process_exit(first, 10) and first.is_alive():
            first.kill()
            await _wait_process_exit(first, 5)
        if not first.is_alive():
            first.close()
        if replacement is not None:
            if replacement.is_alive():
                replacement_stop.set()
                replacement.terminate()
            if not await _wait_process_exit(replacement, 10) and replacement.is_alive():
                replacement.kill()
                await _wait_process_exit(replacement, 5)
            if not replacement.is_alive():
                replacement.close()
        await RedisEventBusAdapter(redis_client).delete_topic(topic)
        async with database.unit_of_work() as unit:
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_task_results WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.session_for_adapter().execute(
                text("DELETE FROM task_progress_projection WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.commit()
        await redis_client.aclose()
        await database.aclose()
