"""Target-stack B0 reconciliation against real PostgreSQL, Redis, and Temporal."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

import pytest
from redis import asyncio as aioredis
from sqlalchemy import text
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

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
    stable_research_task_id,
)
from xhs_food.orchestrator.coordinator import ResearchCoordinator


class _LegacyPort:
    async def start_new(self, query: str) -> Any:
        raise AssertionError(query)

    async def refine(self, session_id: str, query: str) -> Any:
        raise AssertionError((session_id, query))

    async def recover(self, session_id: str) -> ContractPayload:
        return {"sessionId": session_id}

    async def status(self, session_id: str) -> None:
        del session_id

    async def results(self, session_id: str) -> None:
        del session_id


class _FailOncePublisher:
    def __init__(
        self,
        delegate: Any,
        *,
        on_failure: Callable[[], Awaitable[None]],
    ) -> None:
        self._delegate = delegate
        self._on_failure = on_failure
        self._failed = False

    async def publish_task_event(self, event: Any, *, idempotency_key: str) -> str:
        if not self._failed:
            self._failed = True
            await self._on_failure()
            raise RuntimeError("target-stack Redis publication failure")
        return await self._delegate.publish_task_event(event, idempotency_key=idempotency_key)


def _request() -> ResearchRequest:
    suffix = uuid4().hex
    return ResearchRequest(
        request_id=f"target-stack-{suffix}",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="target stack B0 reconciliation",
        public_inputs={"idempotency_key": suffix},
        identity=RequestIdentity(session_ref=f"target-stack-session-{suffix}"),
        policy=RequestPolicy(policy_version="research/v1", compatibility_version="http/v1"),
    )


@pytest.mark.live
async def test_target_stack_pg_commit_survives_redis_loss_and_reconciles() -> None:
    postgres_url = os.getenv("B0_POSTGRES_URL") or os.getenv("DATABASE_URL")
    redis_url = os.getenv("B0_REDIS_URL") or os.getenv("REDIS_URL")
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    if not postgres_url or not redis_url:
        pytest.skip("B0_POSTGRES_URL/DATABASE_URL and B0_REDIS_URL/REDIS_URL are required")

    request = _request()
    expected_task_id = stable_research_task_id(request)
    topic = f"target-stack-b0-{uuid4().hex}"
    database = SQLAlchemyDatabase(postgres_url, enabled=True)
    database.start()
    redis_client = cast(Any, aioredis.from_url(redis_url, decode_responses=True))
    redis_events = RedisEventBusAdapter(redis_client)
    client = await Client.connect(
        temporal_address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )
    task_id: str | None = None
    recovery_client: Any | None = None
    recovery_events: RedisEventBusAdapter | None = None
    try:
        async with database.unit_of_work() as unit:
            for table in ("reliable_task_results", "task_progress_projection", "reliable_tasks"):
                await unit.session_for_adapter().execute(
                    text(f"DELETE FROM {table} WHERE task_id = :task_id"),
                    {"task_id": expected_task_id},
                )
            await unit.commit()
        await redis_events.delete_topic(topic)

        task_store = PostgresReliableTaskStore(database.unit_of_work)
        projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
        authority = PostgresReliableTaskAuthority(database.unit_of_work)
        workflow_port = TemporalWorkflowAdapter(
            client,
            task_queues=TemporalTaskQueues(),
            enabled=True,
        )
        from xhs_food.orchestrator import TemporalReliableResearchPolicy

        policy = TemporalReliableResearchPolicy(workflow_port)

        async def execute(value: Any, idempotency_key: str) -> dict[str, str]:
            assert value.task_id.startswith("task-")
            assert idempotency_key.endswith(":execute")
            return {"answer": "target-stack-ok"}

        coordinator = ResearchCoordinator(
            _LegacyPort(),
            projection_store=projection_store,
            reliable_task_store=task_store,
            reliable_policy=policy,
            reliable_policy_enabled=True,
        )
        policy.bind_owner(coordinator)

        async def drop_redis() -> None:
            await redis_client.aclose()

        publisher = _FailOncePublisher(
            ReliableTaskEventBusPublisher(redis_events, topic_resolver=lambda event: topic),
            on_failure=drop_redis,
        )
        activities = ReliableResearchActivities(
            owner=coordinator,
            authority=authority,
            executor=execute,
            publisher=publisher,
        )

        async with build_reliable_research_worker(client, activities):
            task = await coordinator.submit(request)
            task_id = task.task_id
            assert task.workflow_id is not None
            raw_result = await client.get_workflow_handle(task.workflow_id).result()
            result = ResearchWorkflowOutput.model_validate(raw_result)

        assert result.committed is True
        assert result.published is False
        assert await authority.reconcile(task.task_id, task.workflow_id, task.run_id or "") == {
            "answer": "target-stack-ok",
            "status": "completed",
        }

        recovery_client = cast(Any, aioredis.from_url(redis_url, decode_responses=True))
        recovery_events = RedisEventBusAdapter(recovery_client)
        recovery_activities = ReliableResearchActivities(
            owner=coordinator,
            authority=authority,
            executor=execute,
            publisher=ReliableTaskEventBusPublisher(
                recovery_events,
                topic_resolver=lambda event: topic,
            ),
        )
        assert await recovery_activities.reconcile(
            {
                "task_id": task.task_id,
                "workflow_id": task.workflow_id,
                "run_id": task.run_id or "",
            }
        ) is True
        stream = recovery_events.subscribe(topic)
        terminal = await asyncio.wait_for(anext(stream), timeout=10)
        await cast(Any, stream).aclose()
        event_payload = cast(dict[str, Any], terminal.payload)
        task_event = cast(dict[str, Any], event_payload["taskEvent"])
        assert event_payload["eventType"] == "task.completed"
        assert task_event["task_id"] == task.task_id
    finally:
        if recovery_events is not None:
            await recovery_events.delete_topic(topic)
        else:
            await redis_events.delete_topic(topic)
        async with database.unit_of_work() as unit:
            if task_id is not None:
                for table in (
                    "reliable_task_results",
                    "task_progress_projection",
                    "reliable_tasks",
                ):
                    await unit.session_for_adapter().execute(
                        text(f"DELETE FROM {table} WHERE task_id = :task_id"),
                        {"task_id": task_id},
                    )
            await unit.commit()
        if recovery_client is not None:
            await recovery_client.aclose()
        else:
            await redis_client.aclose()
        await database.aclose()
