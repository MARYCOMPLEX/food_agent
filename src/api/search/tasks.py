"""Background search task + recovery payload builder."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from xhs_food.config import settings
from xhs_food.events import get_emitter
from xhs_food.services import get_session_manager, get_user_storage_service
from xhs_food.services.user_storage import generate_restaurant_hash

from .state import get_orchestrator, load_state, update_state

SearchRunner = Callable[[str, str], Awaitable[None]]


class SearchTaskSupervisor:
    """Own in-process task lifecycle and enforce one active turn per session.

    A durable queue can replace this class later; API routes do not create raw
    tasks anymore and therefore keep idempotency/cancellation in one place.
    """

    def __init__(self, max_concurrency: int = 20) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._reservations: set[str] = set()
        self._lock = asyncio.Lock()
        self._capacity = asyncio.Semaphore(max(1, max_concurrency))

    async def reserve(self, session_id: str) -> bool:
        """Claim a session before its state and event stream are mutated."""
        async with self._lock:
            current = self._tasks.get(session_id)
            if session_id in self._reservations or (current is not None and not current.done()):
                return False
            self._reservations.add(session_id)
            return True

    async def start_reserved(
        self,
        session_id: str,
        query: str,
        runner: SearchRunner | None = None,
    ) -> bool:
        """Start a previously reserved session after route setup completes."""
        async with self._lock:
            if session_id not in self._reservations:
                return False
            self._reservations.remove(session_id)
            self._start_locked(session_id, query, runner or run_stream_search)
            return True

    async def release(self, session_id: str) -> bool:
        """Release a reservation when request setup fails."""
        async with self._lock:
            if session_id not in self._reservations:
                return False
            self._reservations.remove(session_id)
            return True

    async def submit(
        self,
        session_id: str,
        query: str,
        runner: SearchRunner | None = None,
    ) -> bool:
        async with self._lock:
            current = self._tasks.get(session_id)
            if session_id in self._reservations or (current is not None and not current.done()):
                return False
            self._start_locked(session_id, query, runner or run_stream_search)
            return True

    def _start_locked(
        self,
        session_id: str,
        query: str,
        runner: SearchRunner,
    ) -> None:
        task = asyncio.create_task(self._run(session_id, query, runner))
        self._tasks[session_id] = task
        task.add_done_callback(
            lambda done, sid=session_id, owned=task: self._remove_if_current(sid, owned)
        )

    async def _run(
        self,
        session_id: str,
        query: str,
        runner: SearchRunner,
    ) -> None:
        async with self._capacity:
            await runner(session_id, query)

    def _remove_if_current(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(session_id) is task:
            self._tasks.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._reservations:
                self._reservations.remove(session_id)
                return True
            task = self._tasks.get(session_id)
            if task is None or task.done():
                return False
            task.cancel()
            return True


_supervisor = SearchTaskSupervisor(settings.search_task_concurrency)


async def submit_stream_search(
    session_id: str,
    query: str,
    runner: SearchRunner | None = None,
) -> bool:
    """Submit a turn through the supervised task boundary."""
    return await _supervisor.submit(session_id, query, runner)


async def reserve_stream_search(session_id: str) -> bool:
    """Reserve one session while its route-level state is initialized."""
    return await _supervisor.reserve(session_id)


async def start_reserved_stream_search(
    session_id: str,
    query: str,
    runner: SearchRunner | None = None,
) -> bool:
    """Start a search after a successful reservation and initialization."""
    return await _supervisor.start_reserved(session_id, query, runner)


async def release_stream_search(session_id: str) -> bool:
    """Release a route-level reservation after initialization fails."""
    return await _supervisor.release(session_id)


async def run_stream_search(session_id: str, query: str) -> None:
    """Background task driving the orchestrator + persisting results."""
    orchestrator = get_orchestrator(session_id)
    emitter = await get_emitter(session_id)

    try:
        manager = await get_session_manager()
        history = await manager.get_context(session_id)
        if history and len(history) > 1 and not orchestrator.context.conversation_history:
            context = orchestrator.context
            for msg in history[:-1]:
                if msg["role"] == "user":
                    context.add_user_message(msg["content"])
                elif msg["role"] == "assistant":
                    context.add_assistant_message(msg["content"])

        await orchestrator.search_stream(query, emitter)

        run = getattr(orchestrator, "last_run", None)
        response = getattr(orchestrator, "last_response", None)
        if (run is not None and run.status != "completed") or (run is None and response is None):
            message = getattr(run, "stopped_reason", None) or "agent loop failed"
            await update_state(session_id, status="error", error=message)
            try:
                storage = await get_user_storage_service()
                await storage.update_history_status(session_id, "error")
            except Exception:
                pass
            return

        if response is not None:
            await update_state(
                session_id,
                status="completed",
                summary=response.summary,
                filtered_count=response.filtered_count,
                restaurants=[rec.to_dict() for rec in response.recommendations],
            )

        await update_state(session_id, status="completed")
        await _persist_results(session_id, query, orchestrator, manager)

    except Exception as exc:
        logger.exception(f"stream search failed: {session_id}")
        await update_state(session_id, status="error", error=str(exc))
        await emitter.emit_error(str(exc))
        try:
            storage = await get_user_storage_service()
            await storage.update_history_status(session_id, "error")
        except Exception:
            pass


async def _persist_results(
    session_id: str,
    query: str,
    orchestrator,
    manager,
) -> None:
    state = await load_state(session_id) or {}
    summary = state.get("summary", "")
    if summary:
        try:
            await manager.add_assistant_message(session_id, summary)
        except Exception as exc:
            logger.warning(f"add_assistant_message failed: {exc}")

    storage = await get_user_storage_service()

    restaurants: list[dict[str, Any]] = []
    result_summary = ""
    response = getattr(orchestrator, "last_response", None)
    if response is not None:
        source_restaurants = [rec.to_dict() for rec in response.recommendations]
        result_summary = response.summary
    else:
        context = orchestrator.context
        source_restaurants = list(context.last_recommendations.values())
        result_summary = getattr(context, "last_summary", "") or summary

    for rec_dict in source_restaurants:
        if not rec_dict:
            continue
        rec_name = rec_dict.get("name", "restaurant")
        if "id" not in rec_dict:
            rec_dict["id"] = generate_restaurant_hash(rec_name, rec_dict.get("tel"))
        try:
            saved = await storage.upsert_restaurant(rec_dict)
            if saved:
                rec_dict["id"] = saved.id
        except Exception as exc:
            logger.warning(f"upsert_restaurant failed: {exc}")
        restaurants.append(rec_dict)

    try:
        turn_id = int(state.get("turn_id") or 1)
        await storage.save_search_result(
            session_id=session_id,
            restaurants=restaurants,
            summary=result_summary or summary,
            filtered_count=state.get("filtered_count", 0),
            query=query,
            turn_id=turn_id,
        )
        await storage.update_history_status(
            session_id=session_id,
            status="completed",
            results_count=len(restaurants),
        )
    except Exception as exc:
        logger.warning(f"save_search_result failed: {exc}")

    await update_state(
        session_id,
        restaurants=restaurants,
        summary=result_summary or summary,
    )


# ---------------------------------------------------------------------------
# Recovery payload (used by POST /v1/search when only sessionId provided)
# ---------------------------------------------------------------------------


async def build_recovery_payload(session_id: str) -> dict[str, Any]:
    """Return the unified-search response for the recover branch.

    Source-of-truth order: PostgreSQL (search_results) → search_history →
    in-memory state. The bus replay handles in-flight reconnects; this
    endpoint reports the higher-level session state.
    """
    try:
        storage = await get_user_storage_service()
        all_results = await storage.get_all_search_results(session_id)
        if all_results:
            turns = [
                {
                    "turnId": r.get("turn_id", 1),
                    "query": r.get("query", ""),
                    "restaurants": r.get("restaurants", []),
                    "summary": r.get("summary", ""),
                    "total": len(r.get("restaurants", [])),
                    "createdAt": r.get("created_at"),
                }
                for r in all_results
            ]
            latest = all_results[-1]
            return {
                "success": True,
                "data": {
                    "sessionId": session_id,
                    "status": "completed",
                    "turnId": latest.get("turn_id", 1),
                    "query": latest.get("query", ""),
                    "restaurants": latest.get("restaurants", []),
                    "summary": latest.get("summary", ""),
                    "total": len(latest.get("restaurants", [])),
                    "turns": turns,
                    "turnCount": len(turns),
                    "fromDatabase": True,
                },
            }

        history = await storage.get_history_by_session(session_id)
        if history:
            if history.status == "loading":
                state = await load_state(session_id)
                if state and state.get("status") == "loading":
                    return {
                        "success": True,
                        "data": {
                            "sessionId": session_id,
                            "status": "loading",
                            "streamUrl": f"/v1/search/stream/{session_id}",
                            "message": "搜索进行中，请连接 SSE 流继续接收",
                        },
                    }
                return {
                    "success": False,
                    "data": {
                        "sessionId": session_id,
                        "status": "interrupted",
                        "query": history.query,
                        "message": "搜索已中断，请重新搜索",
                    },
                }
            if history.status == "error":
                return {
                    "success": False,
                    "data": {
                        "sessionId": session_id,
                        "status": "error",
                        "query": history.query,
                        "message": "搜索失败，请重试",
                    },
                }
    except Exception as exc:
        logger.warning(f"recover from storage failed: {exc}")

    return {
        "success": False,
        "data": {
            "sessionId": session_id,
            "status": "not_found",
            "message": "会话不存在或已过期",
        },
    }


# Re-export for symmetry — old code expected a router on this module.
# The router is now empty; routes live in ``routes.py``. Importers that
# referenced this module's router will receive an empty include.
from fastapi import APIRouter  # noqa: E402

router = APIRouter()
