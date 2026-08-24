"""Live PostgreSQL qualification for the B0 reliable task authority."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from xhs_food.composition.adapters import (
    PostgresReliableTaskAuthority,
    PostgresReliableTaskStore,
    PostgresTaskProgressProjectionStore,
)
from xhs_food.contracts import (
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    ResearchTask,
    TaskProgressProjection,
    TaskStatus,
)
from xhs_food.foundation.database import SQLAlchemyDatabase


def _request(prefix: str) -> ResearchRequest:
    return ResearchRequest(
        request_id=f"{prefix}-request",
        operation=ResearchOperation.QUERY,
        domain="food",
        query="自贡本地美食",
        identity=RequestIdentity(session_ref=f"{prefix}-session"),
        policy=RequestPolicy(
            policy_version="research/v1",
            compatibility_version="http/v1",
        ),
    )


@pytest.mark.live
async def test_b0_postgres_authority_admission_commit_reconcile_and_projection() -> None:
    url = os.getenv("B0_POSTGRES_URL")
    if not url:
        pytest.skip("B0_POSTGRES_URL is required for live PostgreSQL qualification")

    prefix = "live-b0-reliable"
    database = SQLAlchemyDatabase(url, enabled=True)
    database.start()
    second_database = SQLAlchemyDatabase(url, enabled=True)
    second_database.start()
    now = datetime.now(UTC)
    task_id = f"{prefix}-task"
    workflow_id = f"research:{task_id}"
    run_id = f"{prefix}-run"
    request = _request(prefix)
    task = ResearchTask(
        task_id=task_id,
        request_id=request.request_id,
        operation=request.operation,
        domain=request.domain,
        status=TaskStatus.RUNNING,
        turn_id="1",
        plan_id=f"{prefix}-plan",
        workflow_id=workflow_id,
        run_id=None,
        created_at=now,
        updated_at=now,
    )
    projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
    task_store = PostgresReliableTaskStore(database.unit_of_work)
    authority = PostgresReliableTaskAuthority(database.unit_of_work)
    second_task_store = PostgresReliableTaskStore(second_database.unit_of_work)
    second_authority = PostgresReliableTaskAuthority(second_database.unit_of_work)

    try:
        async with database.unit_of_work() as unit:
            await unit.session_for_adapter().execute(
                text(
                    "DELETE FROM reliable_task_results WHERE task_id LIKE :prefix "
                    "OR task_id = :task_id"
                ),
                {"prefix": f"{prefix}%", "task_id": task_id},
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

        admissions = await asyncio.gather(
            task_store.admit(task, request),
            second_task_store.admit(task, request),
        )
        assert sum(created for _, created in admissions) == 1
        assert {admitted.task_id for admitted, _ in admissions} == {task_id}
        admitted, created = await task_store.admit(task, request)
        assert created is False
        assert admitted.task_id == task_id
        duplicate, duplicate_created = await task_store.admit(task, request)
        assert duplicate_created is False
        assert duplicate.workflow_id == workflow_id

        attached = task.model_copy(update={"run_id": run_id, "updated_at": now + timedelta(seconds=1)})
        saved = await task_store.save(attached, request)
        assert saved.run_id == run_id
        hydrated = await task_store.get(task_id)
        assert hydrated is not None and hydrated[0].run_id == run_id

        projection = TaskProgressProjection(
            task_id=task_id,
            turn_id="1",
            workflow_id=workflow_id,
            run_id=run_id,
            status=TaskStatus.COMPLETED,
            progress=1.0,
            updated_at=now + timedelta(seconds=2),
        )
        assert await projection_store.put(projection) == projection
        newer_turn = projection.model_copy(
            update={
                "turn_id": "2",
                "run_id": f"{prefix}-retry",
                "status": TaskStatus.RUNNING,
                "progress": 0.0,
                "updated_at": now,
            }
        )
        assert await projection_store.put(newer_turn) == newer_turn
        assert await projection_store.get(task_id) == newer_turn

        receipt = await authority.commit_result(
            task_id,
            workflow_id,
            run_id,
            {"answer": "已提交"},
            idempotency_key=f"{prefix}:result",
        )
        assert receipt.committed is True
        duplicate_receipt = await authority.commit_result(
            task_id,
            workflow_id,
            run_id,
            {"answer": "已提交"},
            idempotency_key=f"{prefix}:result",
        )
        assert duplicate_receipt.already_committed is True
        assert duplicate_receipt.result_version == receipt.result_version
        assert await authority.reconcile(task_id, workflow_id, run_id) == {
            "answer": "已提交",
            "status": "completed",
        }

        race_task_id = f"{prefix}-race-task"
        race_workflow_id = f"research:{race_task_id}"
        race_run_id = f"{prefix}-race-run"
        race_results = await asyncio.gather(
            authority.commit_result(
                race_task_id,
                race_workflow_id,
                race_run_id,
                {"answer": "race"},
                idempotency_key=f"{prefix}:race:result",
            ),
            second_authority.commit_cancelled(
                race_task_id,
                race_workflow_id,
                race_run_id,
                idempotency_key=f"{prefix}:race:cancel",
            ),
        )
        statuses = {receipt.terminal_status for receipt in race_results}
        assert len(statuses) == 1
        assert statuses.pop() in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
        reconciled = await authority.reconcile(race_task_id, race_workflow_id, race_run_id)
        assert reconciled is not None
        assert reconciled["status"] in {"completed", "cancelled"}
    finally:
        async with database.unit_of_work() as unit:
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_task_results WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            await unit.session_for_adapter().execute(
                text("DELETE FROM reliable_task_results WHERE task_id = :task_id"),
                {"task_id": f"{prefix}-race-task"},
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
        await database.aclose()
        await second_database.aclose()
