"""SearchTaskSupervisor concurrency and idempotency tests."""

from __future__ import annotations

import asyncio

from api.search.tasks import SearchTaskSupervisor


async def test_supervisor_rejects_duplicate_active_session() -> None:
    release = asyncio.Event()

    async def runner(session_id: str, query: str) -> None:
        await release.wait()

    supervisor = SearchTaskSupervisor(max_concurrency=2)
    assert await supervisor.submit("same", "first", runner)
    assert not await supervisor.submit("same", "duplicate", runner)

    release.set()
    await asyncio.gather(*list(supervisor._tasks.values()))  # noqa: SLF001


async def test_supervisor_caps_cross_session_concurrency() -> None:
    release = asyncio.Event()
    started: list[str] = []

    async def runner(session_id: str, query: str) -> None:
        started.append(session_id)
        await release.wait()

    supervisor = SearchTaskSupervisor(max_concurrency=1)
    assert await supervisor.submit("one", "q", runner)
    assert await supervisor.submit("two", "q", runner)
    await asyncio.sleep(0.01)

    assert started == ["one"]
    release.set()
    await asyncio.gather(*list(supervisor._tasks.values()))  # noqa: SLF001
    assert started == ["one", "two"]


async def test_supervisor_reserves_session_before_task_start() -> None:
    started = asyncio.Event()

    async def runner(session_id: str, query: str) -> None:
        started.set()

    supervisor = SearchTaskSupervisor(max_concurrency=1)
    assert await supervisor.reserve("same")
    assert not await supervisor.reserve("same")
    assert not await supervisor.submit("same", "duplicate", runner)
    assert not started.is_set()

    assert await supervisor.start_reserved("same", "q", runner)
    await asyncio.gather(*list(supervisor._tasks.values()))  # noqa: SLF001
    assert started.is_set()


async def test_supervisor_releases_failed_setup_reservation() -> None:
    supervisor = SearchTaskSupervisor(max_concurrency=1)
    assert await supervisor.reserve("same")
    assert await supervisor.release("same")
    assert await supervisor.reserve("same")
    assert await supervisor.cancel("same")
