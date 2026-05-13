"""Shared state for search routes.

Two layers:

- **Orchestrator cache** — a bounded TTL LRU. The orchestrator object holds
  in-memory conversation context that we want to reuse within a session,
  but never indefinitely.
- **Task state store** — small per-session JSON document (status, query,
  turn_id, …) persisted to Redis when configured, otherwise to an
  in-process dict. This lets multiple workers (and the recover endpoint)
  see consistent state.

Long-term, completed-search data still lives in PostgreSQL
(:mod:`xhs_food.services.user_storage`).
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Protocol

from cachetools import TTLCache
from loguru import logger

from xhs_food import XHSFoodOrchestrator
from xhs_food.config import settings
from xhs_food.di import get_xhs_tool_registry


# ---------------------------------------------------------------------------
# Orchestrator LRU
# ---------------------------------------------------------------------------

_ORCHESTRATOR_TTL_SECONDS = 3600
_ORCHESTRATOR_MAX = 500

_orchestrators: TTLCache[str, XHSFoodOrchestrator] = TTLCache(
    maxsize=_ORCHESTRATOR_MAX,
    ttl=_ORCHESTRATOR_TTL_SECONDS,
)


def get_orchestrator(session_id: str) -> XHSFoodOrchestrator:
    cached = _orchestrators.get(session_id)
    if cached is not None:
        return cached
    orch = XHSFoodOrchestrator(xhs_registry=get_xhs_tool_registry())
    _orchestrators[session_id] = orch
    return orch


def drop_orchestrator(session_id: str) -> None:
    _orchestrators.pop(session_id, None)


# ---------------------------------------------------------------------------
# Task state store
# ---------------------------------------------------------------------------


_STATE_TTL_SECONDS = 3600


class _StateStore(Protocol):
    async def get(self, sid: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, sid: str, value: Dict[str, Any]) -> None: ...
    async def delete(self, sid: str) -> None: ...


class _MemoryStateStore:
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._store.get(sid)

    async def set(self, sid: str, value: Dict[str, Any]) -> None:
        self._store[sid] = value

    async def delete(self, sid: str) -> None:
        self._store.pop(sid, None)


class _RedisStateStore:
    KEY_PREFIX = "task"

    def __init__(self, client) -> None:
        self._r = client

    def _key(self, sid: str) -> str:
        return f"{self.KEY_PREFIX}:{sid}:state"

    async def get(self, sid: str) -> Optional[Dict[str, Any]]:
        raw = await self._r.get(self._key(sid))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"corrupt state json for {sid}")
            return None

    async def set(self, sid: str, value: Dict[str, Any]) -> None:
        await self._r.set(
            self._key(sid),
            json.dumps(value, ensure_ascii=False),
            ex=_STATE_TTL_SECONDS,
        )

    async def delete(self, sid: str) -> None:
        await self._r.delete(self._key(sid))


_state_store: Optional[_StateStore] = None


async def _build_store() -> _StateStore:
    url = settings.resolved_redis_url()
    if url and settings.event_bus_backend == "redis":
        try:
            from redis import asyncio as aioredis

            client = aioredis.from_url(url, decode_responses=True)
            await client.ping()
            logger.info("search state backed by Redis")
            return _RedisStateStore(client)
        except Exception as exc:
            logger.warning(f"Redis state store init failed ({exc}); using in-memory")
    return _MemoryStateStore()


async def get_state_store() -> _StateStore:
    global _state_store
    if _state_store is None:
        _state_store = await _build_store()
    return _state_store


def _default_state(session_id: str, status: str = "idle") -> Dict[str, Any]:
    now = time.time()
    return {
        "id": session_id,
        "status": status,
        "query": "",
        "turn_id": 0,
        "summary": "",
        "filtered_count": 0,
        "error": None,
        "restaurants": [],
        "created_at": now,
        "updated_at": now,
    }


async def load_state(session_id: str) -> Optional[Dict[str, Any]]:
    store = await get_state_store()
    return await store.get(session_id)


async def get_or_init_state(session_id: str, status: str = "idle") -> Dict[str, Any]:
    store = await get_state_store()
    state = await store.get(session_id)
    if state is None:
        state = _default_state(session_id, status)
        await store.set(session_id, state)
    return state


async def save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    store = await get_state_store()
    await store.set(state["id"], state)


async def update_state(session_id: str, **changes: Any) -> Dict[str, Any]:
    state = await get_or_init_state(session_id)
    state.update(changes)
    await save_state(state)
    return state


async def clear_state(session_id: str) -> None:
    store = await get_state_store()
    await store.delete(session_id)
