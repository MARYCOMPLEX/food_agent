"""Live Redis Streams qualification for the B0 event projection contract."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from redis import asyncio as aioredis

from xhs_food.contracts import EventEnvelope
from xhs_food.foundation import RedisEventBusAdapter, RedisHotStateContract, RedisReplayExpiredError


@pytest.mark.live
async def test_b0_redis_stream_replays_exclusively_and_expires_unknown_cursor() -> None:
    url = os.getenv("B0_REDIS_URL")
    if not url:
        pytest.skip("B0_REDIS_URL is required for live Redis qualification")

    client = cast(Any, aioredis.from_url(url, decode_responses=True))
    topic = "live-b0-redis"
    events = RedisEventBusAdapter(
        client,
        RedisHotStateContract(event_read_block_ms=100, event_stream_ttl_seconds=60),
    )
    first = EventEnvelope(
        event_id="live-b0-redis-1",
        topic=topic,
        payload={"status": "running"},
        published_at=datetime.now(UTC),
    )
    second = first.model_copy(
        update={"event_id": "live-b0-redis-2", "payload": {"status": "completed"}}
    )

    try:
        await events.delete_topic(topic)
        first_cursor = await events.publish(first)
        second_cursor = await events.publish(second)
        iterator = events.subscribe(topic, after=first_cursor)
        replayed = await anext(iterator)
        await cast(Any, iterator).aclose()
        assert replayed.event_id == second.event_id
        assert second_cursor != first_cursor

        expired = events.subscribe(topic, after="9999999999999-0")
        with pytest.raises(RedisReplayExpiredError) as caught:
            await anext(expired)
        assert caught.value.error.code == "SSE_REPLAY_EXPIRED"
        assert caught.value.error.details["recovery"] == "resync"
    finally:
        await events.delete_topic(topic)
        await client.aclose()


@pytest.mark.live
async def test_b0_redis_stream_trim_ttl_and_restart_expire_replay_cursor() -> None:
    url = os.getenv("B0_REDIS_URL")
    if not url:
        pytest.skip("B0_REDIS_URL is required for live Redis qualification")

    client = cast(Any, aioredis.from_url(url, decode_responses=True))
    topic = "live-b0-redis-retention"
    events = RedisEventBusAdapter(
        client,
        RedisHotStateContract(
            event_read_block_ms=50,
            event_stream_ttl_seconds=2,
            event_stream_maxlen=1000,
        ),
    )

    try:
        await events.delete_topic(topic)
        first_cursor = await events.publish(
            EventEnvelope(
                event_id="live-b0-retention-0",
                topic=topic,
                payload={"index": 0},
                published_at=datetime.now(UTC),
            )
        )
        for index in range(1, 1_101):
            await events.publish(
                EventEnvelope(
                    event_id=f"live-b0-retention-{index}",
                    topic=topic,
                    payload={"index": index},
                    published_at=datetime.now(UTC),
                )
            )

        redis_key = f"events:{topic}:stream"
        stream_length = await client.xlen(redis_key)
        ttl_seconds = await client.ttl(redis_key)
        # Redis XADD uses the adapter's approximate MAXLEN contract; the
        # implementation may retain a small radix-tree boundary overrun.
        assert 1_000 <= stream_length <= 1_024
        assert ttl_seconds > 0

        trimmed = events.subscribe(topic, after=first_cursor)
        with pytest.raises(RedisReplayExpiredError):
            await anext(trimmed)

        # A Redis restart/flush removes the rebuildable stream but not the
        # PostgreSQL task authority. The old browser cursor must resync.
        await client.flushdb()
        restarted = events.subscribe(topic, after=first_cursor)
        with pytest.raises(RedisReplayExpiredError):
            await anext(restarted)
    finally:
        await events.delete_topic(topic)
        await client.aclose()


@pytest.mark.live
async def test_b0_redis_service_restart_preserves_or_expires_cursor_without_duplication() -> None:
    url = os.getenv("B0_REDIS_URL")
    container = os.getenv("B0_REDIS_CONTAINER")
    if not url:
        pytest.skip("B0_REDIS_URL is required for live Redis qualification")
    if not container:
        pytest.skip("B0_REDIS_CONTAINER is required for Redis service restart smoke")

    client = cast(Any, aioredis.from_url(url, decode_responses=True))
    topic = f"live-b0-redis-restart-{os.getpid()}"
    events = RedisEventBusAdapter(
        client,
        RedisHotStateContract(event_read_block_ms=100, event_stream_ttl_seconds=60),
    )
    restarted_client: Any | None = None
    restarted_events: RedisEventBusAdapter | None = None
    try:
        await events.delete_topic(topic)
        first = EventEnvelope(
            event_id=f"{topic}-1",
            topic=topic,
            payload={"status": "running"},
            published_at=datetime.now(UTC),
        )
        first_cursor = await events.publish(first)
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "restart", container],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        restarted_client = cast(Any, aioredis.from_url(url, decode_responses=True))
        deadline = time.monotonic() + 30
        while True:
            try:
                await restarted_client.ping()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.25)

        restarted_events = RedisEventBusAdapter(
            restarted_client,
            RedisHotStateContract(event_read_block_ms=100, event_stream_ttl_seconds=60),
        )
        second = first.model_copy(
            update={"event_id": f"{topic}-2", "payload": {"status": "completed"}}
        )
        await restarted_events.publish(second)
        replay = restarted_events.subscribe(topic, after=first_cursor)
        try:
            observed = await asyncio.wait_for(anext(replay), timeout=5)
        except RedisReplayExpiredError:
            observed = None
        finally:
            await cast(Any, replay).aclose()
        if observed is not None:
            assert observed.event_id == second.event_id
    finally:
        if restarted_events is not None:
            await restarted_events.delete_topic(topic)
        else:
            await events.delete_topic(topic)
        if restarted_client is not None:
            await restarted_client.aclose()
        await client.aclose()
