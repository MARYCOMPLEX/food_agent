"""Live Redis Streams qualification for the B0 event projection contract."""

from __future__ import annotations

import os
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
