"""Qualification probe for a real Temporal service in the release stack.

The probe uses disposable workflows and activities only. It exercises queue
isolation, a clean worker handoff, retry exhaustion, Temporal visibility, and
the operator retry port without making Temporal history or a broker queue a
second application authority.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker


@activity.defn(name="release.qualification.echo")
async def _echo(value: str) -> str:
    return value


@activity.defn(name="release.qualification.always_fail")
async def _always_fail() -> None:
    raise ApplicationError("qualification retry exhaustion", type="QualificationFailure")


@workflow.defn(name="ReleaseQueueQualificationWorkflow")
class _QueueQualificationWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return await workflow.execute_activity(
            _echo,
            value,
            start_to_close_timeout=timedelta(seconds=10),
        )


@workflow.defn(name="ReleaseRolloutQualificationWorkflow")
class _RolloutQualificationWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        await workflow.sleep(timedelta(seconds=1))
        return await workflow.execute_activity(
            _echo,
            value,
            start_to_close_timeout=timedelta(seconds=10),
        )


@workflow.defn(name="ReleaseOperatorQualificationWorkflow")
class _OperatorQualificationWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, bool]) -> str:
        if payload["should_fail"]:
            await workflow.execute_activity(
                _always_fail,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(milliseconds=100),
                    maximum_interval=timedelta(milliseconds=200),
                    maximum_attempts=2,
                ),
            )
            return "unreachable"
        return await workflow.execute_activity(
            _echo,
            "operator-recovered",
            start_to_close_timeout=timedelta(seconds=10),
        )


def _queues():
    from xhs_food.foundation import TemporalTaskQueues, TemporalWorkerQuota

    return TemporalTaskQueues(
        research_quota=TemporalWorkerQuota("research", 2, 2, 100, enabled=True),
        refresh_quota=TemporalWorkerQuota("refresh", 2, 2, 50, enabled=True),
        media_quota=TemporalWorkerQuota("media", 2, 2, 25, enabled=True),
    )


async def _queue_isolation(client: Client, queues) -> None:
    async def run(queue: str) -> str:
        async with Worker(
            client,
            task_queue=queue,
            workflows=[_QueueQualificationWorkflow],
            activities=[_echo],
        ):
            return await client.execute_workflow(
                _QueueQualificationWorkflow.run,
                f"queue:{queue}",
                id=f"release-queue-{queue}-{uuid4().hex}",
                task_queue=queue,
            )

    results = await asyncio.gather(*(run(queue) for queue in queues.priority_order))
    expected = [f"queue:{queue}" for queue in queues.priority_order]
    if results != expected:
        raise RuntimeError(f"queue isolation mismatch: expected {expected!r}, got {results!r}")


async def _worker_rollout(client: Client) -> None:
    workflow_id = f"release-rollout-{uuid4().hex}"
    handle = None
    async with Worker(
        client,
        task_queue="research",
        workflows=[_RolloutQualificationWorkflow],
        activities=[_echo],
    ):
        handle = await client.start_workflow(
            _RolloutQualificationWorkflow.run,
            "worker-handoff",
            id=workflow_id,
            task_queue="research",
        )

    # The first worker has exited; the second worker must resume the same
    # Temporal history rather than receive a new Workflow ID.
    assert handle is not None
    async with Worker(
        client,
        task_queue="research",
        workflows=[_RolloutQualificationWorkflow],
        activities=[_echo],
    ):
        result = await handle.result()
        if result != "worker-handoff":
            raise RuntimeError(f"worker rollout returned {result!r}")


async def _cleanup_previous_probe_runs(client: Client) -> None:
    executions = client.list_workflows(
        query='WorkflowType="ReleaseOperatorQualificationWorkflow"'
    )
    async for execution in executions:
        if str(execution.id).startswith("release-operator-"):
            status = getattr(getattr(execution, "status", None), "name", "")
            if status.endswith(("COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT")):
                continue
            await client.get_workflow_handle(
                execution.id,
                run_id=execution.run_id,
            ).terminate(reason="qualification cleanup before rerun")


async def _operator_recovery(client: Client, queues) -> None:
    from xhs_food.contracts import WorkflowRetryRequest, WorkflowStart
    from xhs_food.foundation import TemporalWorkflowAdapter

    workflow_id = f"release-operator-{uuid4().hex}"
    async with Worker(
        client,
        task_queue="research",
        workflows=[_OperatorQualificationWorkflow],
        activities=[_echo, _always_fail],
    ):
        failed_handle = await client.start_workflow(
            _OperatorQualificationWorkflow.run,
            {"should_fail": True},
            id=workflow_id,
            task_queue="research",
        )
        try:
            await failed_handle.result()
        except WorkflowFailureError:
            pass
        else:
            raise RuntimeError("retry-exhaustion workflow unexpectedly succeeded")

        adapter = TemporalWorkflowAdapter(client, task_queues=queues, enabled=True)
        failed = ()
        for _ in range(20):
            failed = await adapter.list_failed_workflows(task_queue="research")
            if any(item.workflow_id == workflow_id for item in failed):
                break
            await asyncio.sleep(0.25)
        match = next((item for item in failed if item.workflow_id == workflow_id), None)
        if match is None:
            raise RuntimeError("failed Workflow did not appear in Temporal visibility")
        retry_command = WorkflowStart(
            workflow_id=workflow_id,
            workflow_type="ReleaseOperatorQualificationWorkflow",
            task_queue="research",
            input={"should_fail": False},
            idempotency_key=f"{workflow_id}:retry",
        )
        receipt = await adapter.retry_workflow(
            WorkflowRetryRequest(command=retry_command, expected_run_id=match.run_id)
        )
        recovered = await client.get_workflow_handle(
            workflow_id,
            run_id=receipt.run_id,
        ).result()
        if recovered != "operator-recovered":
            raise RuntimeError(f"operator retry returned {recovered!r}")


async def main() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:17233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queues = _queues()
    client = await Client.connect(address, namespace=namespace)
    await _cleanup_previous_probe_runs(client)
    await _queue_isolation(client, queues)
    await _worker_rollout(client)
    await _operator_recovery(client, queues)
    print(
        "temporal release matrix: PASS "
        f"address={address} queues={','.join(queues.priority_order)} "
        "worker_rollout=PASS retry_exhaustion=PASS operator_retry=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
