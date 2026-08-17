"""Search endpoints (unified search + SSE stream).

Endpoints:
- ``POST /v1/search`` — new search / refine / recover (auto-dispatched by params)
- ``GET  /v1/search/stream/{sessionId}`` — SSE event stream backed by the
  EventBus. The ``Last-Event-ID`` header (sent automatically by browser
  EventSource on reconnect) is used for replay; no client-side bookkeeping
  required.
- ``GET  /v1/search/status/{sessionId}``
- ``GET  /v1/search/results/{sessionId}``
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Header, HTTPException, Path
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    SearchResultsResponse,
    SearchStatusResponse,
    UnifiedSearchRequest,
)
from xhs_food.events import get_emitter
from xhs_food.events.bus import STREAM_START, get_event_bus
from xhs_food.services import get_session_manager, get_user_storage_service

from .state import (
    get_orchestrator,
    load_state,
    update_state,
)
from .tasks import (
    build_recovery_payload,
    release_stream_search,
    reserve_stream_search,
    run_stream_search,
    start_reserved_stream_search,
)

router = APIRouter()


def _stream_url(session_id: str) -> str:
    return f"/v1/search/stream/{session_id}"


def _truncate(text: str | None, n: int = 30) -> str:
    if not text:
        return ""
    return text[:n] + ("…" if len(text) > n else "")


# ---------------------------------------------------------------------------
# POST /v1/search (unified)
# ---------------------------------------------------------------------------


@router.post("/")
async def unified_search(request: UnifiedSearchRequest):
    """Single entry point — branches on ``(sessionId, query)`` presence."""
    # Case 1: new search
    if not request.sessionId:
        if not request.query:
            raise HTTPException(400, "新查询必须提供 query 参数")
        session_id = str(uuid.uuid4())
        await _kick_off_new_search(session_id, request.query)
        return {
            "success": True,
            "data": {
                "sessionId": session_id,
                "streamUrl": _stream_url(session_id),
                "action": "new_search",
            },
        }

    session_id = request.sessionId

    # Case 2: refine (sessionId + query)
    if request.query:
        turn_id = await _kick_off_refine(session_id, request.query)
        return {
            "success": True,
            "data": {
                "sessionId": session_id,
                "streamUrl": _stream_url(session_id),
                "turnId": turn_id,
                "action": "refine",
            },
        }

    # Case 3: recover (sessionId only)
    return await build_recovery_payload(session_id)


async def _kick_off_new_search(session_id: str, query: str) -> None:
    if not await reserve_stream_search(session_id):
        raise HTTPException(409, "Session already has an active search")
    try:
        await update_state(
            session_id,
            status="loading",
            query=query,
            turn_id=1,
        )

        emitter = await get_emitter(session_id)
        await emitter.reset_stream()
        emitter.init_steps(query)

        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, query)
        except Exception as exc:
            logger.warning(f"add_user_message failed: {exc}")

        try:
            storage = await get_user_storage_service()
            await storage.create_search_history(
                session_id=session_id,
                query=query,
                status="loading",
            )
        except Exception as exc:
            logger.warning(f"create_search_history failed: {exc}")

        started = await start_reserved_stream_search(
            session_id,
            query,
            run_stream_search,
        )
        if not started:
            raise RuntimeError("search reservation was lost before task start")
    except BaseException:
        await release_stream_search(session_id)
        raise


async def _kick_off_refine(session_id: str, query: str) -> int:
    if not await reserve_stream_search(session_id):
        raise HTTPException(409, "Session already has an active search")
    try:
        # Restore orchestrator context lazily if memory cache evicted.
        state = await load_state(session_id)
        if state is None:
            state = await _restore_state_from_storage(session_id)

        turn_id = (state.get("turn_id") or 1) + 1
        await update_state(
            session_id,
            status="loading",
            query=query,
            turn_id=turn_id,
        )

        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, query)
        except Exception as exc:
            logger.warning(f"add_user_message failed: {exc}")

        emitter = await get_emitter(session_id)
        await emitter.reset_stream()
        emitter.init_steps(query)

        started = await start_reserved_stream_search(
            session_id,
            query,
            run_stream_search,
        )
        if not started:
            raise RuntimeError("search reservation was lost before task start")
        return turn_id
    except BaseException:
        await release_stream_search(session_id)
        raise


async def _restore_state_from_storage(session_id: str) -> dict:
    """Repopulate orchestrator + state from persistent storage."""
    storage = await get_user_storage_service()
    first_result = await storage.get_first_search_result(session_id)
    if not first_result:
        raise HTTPException(404, "Session not found")

    all_results = await storage.get_all_search_results(session_id)
    state = await update_state(
        session_id,
        status="completed",
        query=first_result.get("query", ""),
        turn_id=len(all_results) if all_results else 1,
        restaurants=first_result.get("restaurants", []),
    )

    orchestrator = get_orchestrator(session_id)
    manager = await get_session_manager()
    history = await manager.get_context(session_id)
    if history:
        context = orchestrator.context
        for msg in history:
            if msg["role"] == "user":
                context.add_user_message(msg["content"])
            elif msg["role"] == "assistant":
                context.add_assistant_message(msg["content"])

    for restaurant in first_result.get("restaurants", []):
        name = restaurant.get("name")
        if name:
            orchestrator.context.last_recommendations[name] = restaurant

    logger.info(
        f"session restored: {len(first_result.get('restaurants', []))} restaurants, "
        f"turn_id={state['turn_id']}"
    )
    return state


# ---------------------------------------------------------------------------
# GET /v1/search/stream/{sessionId} (SSE)
# ---------------------------------------------------------------------------


@router.get("/stream/{sessionId}")
async def search_stream(
    sessionId: str = Path(..., description="会话ID"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """Server-sent events with Redis-Stream-backed replay.

    The browser's ``EventSource`` records ``id:`` on every event and sends
    it back as ``Last-Event-ID`` on reconnect. The EventBus replays from
    that id, so the client needs no special reconnection logic.
    """
    bus = await get_event_bus()
    start_from = last_event_id or STREAM_START

    async def generate() -> AsyncGenerator[dict, None]:
        async for entry_id, event in bus.subscribe(sessionId, start_from):
            sse = event.to_sse()
            sse["id"] = entry_id
            yield sse

    return EventSourceResponse(generate())


# ---------------------------------------------------------------------------
# GET /v1/search/status/{sessionId}
# ---------------------------------------------------------------------------


@router.get("/status/{sessionId}", response_model=SearchStatusResponse)
async def search_status(sessionId: str = Path(..., description="会话ID")):
    state = await load_state(sessionId)
    if state is None:
        raise HTTPException(404, "Session not found")
    emitter = await get_emitter(sessionId)
    return SearchStatusResponse(
        success=True,
        data={
            "sessionId": sessionId,
            "status": state["status"],
            "loadingSteps": emitter.steps,
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/search/results/{sessionId}
# ---------------------------------------------------------------------------


@router.get("/results/{sessionId}", response_model=SearchResultsResponse)
async def search_results(sessionId: str = Path(..., description="会话ID")):
    state = await load_state(sessionId)
    if state is None:
        raise HTTPException(404, "Session not found")
    return SearchResultsResponse(
        success=True,
        data={
            "sessionId": sessionId,
            "restaurants": state.get("restaurants", []),
            "summary": state.get("summary", ""),
        },
    )
