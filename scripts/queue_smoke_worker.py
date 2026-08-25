"""Run one disposable Temporal workflow against a named task queue."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker


@activity.defn
async def queue_smoke_activity() -> str:
    return "ok"


@workflow.defn
class QueueSmokeWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            queue_smoke_activity,
            start_to_close_timeout=timedelta(seconds=10),
        )


async def main() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    queue = os.environ["QUEUE"]
    client = await Client.connect(address, namespace=os.getenv("TEMPORAL_NAMESPACE", "default"))
    async with Worker(
        client,
        task_queue=queue,
        workflows=[QueueSmokeWorkflow],
        activities=[queue_smoke_activity],
    ):
        result = await client.execute_workflow(
            QueueSmokeWorkflow.run,
            id=f"release-gate-{queue}-{uuid4().hex}",
            task_queue=queue,
        )
    if result != "ok":
        raise RuntimeError(f"queue {queue!r} smoke returned {result!r}")


if __name__ == "__main__":
    asyncio.run(main())
