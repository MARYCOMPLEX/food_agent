"""Live process-level Temporal worker crash and history-resume qualification."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

QUEUE = "research-process-crash"

_PROCESS_CRASH_MODE = False
_PROCESS_ACTIVITY_STARTED: Any = None


@activity.defn(name="b0.process-crash.activity")
async def _process_crash_activity(value: str) -> str:
    if _PROCESS_ACTIVITY_STARTED is not None:
        _PROCESS_ACTIVITY_STARTED.set()
    if _PROCESS_CRASH_MODE:
        os._exit(71)
    return value


@workflow.defn(name="B0ProcessCrashWorkflow")
class _ProcessCrashWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return await workflow.execute_activity(
            _process_crash_activity,
            value,
            start_to_close_timeout=timedelta(seconds=1),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=100),
                maximum_interval=timedelta(milliseconds=250),
                maximum_attempts=3,
            ),
            activity_id="b0-process-crash-activity",
        )


async def _run_worker(
    target_host: str,
    namespace: str,
    crash: bool,
    ready: Any,
    activity_started: Any,
    stop: Any,
) -> None:
    global _PROCESS_ACTIVITY_STARTED, _PROCESS_CRASH_MODE
    _PROCESS_CRASH_MODE = crash
    _PROCESS_ACTIVITY_STARTED = activity_started
    client = await Client.connect(
        target_host,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )
    worker = Worker(
        client,
        task_queue=QUEUE,
        workflows=[_ProcessCrashWorkflow],
        activities=[_process_crash_activity],
        disable_eager_activity_execution=True,
    )
    ready.set()
    worker_task = asyncio.create_task(worker.run())
    try:
        await asyncio.to_thread(stop.wait)
    finally:
        if not worker_task.done():
            await worker.shutdown()
        await worker_task
        await client.close()


def _worker_process_entry(
    target_host: str,
    namespace: str,
    crash: bool,
    ready: Any,
    activity_started: Any,
    stop: Any,
) -> None:
    asyncio.run(_run_worker(target_host, namespace, crash, ready, activity_started, stop))


async def _wait_process_exit(process: multiprocessing.Process, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return not process.is_alive()


async def _wait_event(event: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while not event.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return event.is_set()


@pytest_asyncio.fixture(scope="module")
async def temporal_env() -> Any:
    env = await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter)
    try:
        yield env
    finally:
        await env.shutdown()


@pytest.mark.live
async def test_process_crash_after_activity_start_resumes_same_temporal_history(
    temporal_env: Any,
) -> None:
    context = multiprocessing.get_context("spawn")
    target_host = temporal_env.client.service_client.config.target_host
    namespace = temporal_env.client.namespace
    first_ready = context.Event()
    first_started = context.Event()
    first_stop = context.Event()
    first = context.Process(
        target=_worker_process_entry,
        args=(target_host, namespace, True, first_ready, first_started, first_stop),
    )
    replacement_ready = context.Event()
    replacement_started = context.Event()
    replacement_stop = context.Event()
    replacement: multiprocessing.Process | None = None

    try:
        first.start()
        assert await _wait_event(first_ready, 15)
        handle = await asyncio.wait_for(
            temporal_env.client.start_workflow(
                _ProcessCrashWorkflow.run,
                "resume-after-process-crash",
                id="b0-process-crash-workflow",
                task_queue=QUEUE,
            ),
            timeout=15,
        )
        assert await _wait_event(first_started, 15)
        assert await _wait_process_exit(first, 15)
        assert first.exitcode == 71
        await asyncio.sleep(2)

        replacement = context.Process(
            target=_worker_process_entry,
            args=(
                target_host,
                namespace,
                False,
                replacement_ready,
                replacement_started,
                replacement_stop,
            ),
        )
        replacement.start()
        assert await _wait_event(replacement_ready, 15)
        await asyncio.sleep(2)
        assert await asyncio.wait_for(handle.result(), timeout=20) == "resume-after-process-crash"
        history = await handle.fetch_history()
        names = [EventType.Name(event.event_type).removeprefix("EVENT_TYPE_") for event in history.events]
        # Temporal may reassign an in-flight Activity task after a worker
        # process crash without appending a second STARTED event.
        assert names.count("ACTIVITY_TASK_STARTED") >= 1
        assert "ACTIVITY_TASK_COMPLETED" in names
        assert "WORKFLOW_EXECUTION_COMPLETED" in names
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
