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

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    SearchResultsResponse,
    SearchStatusResponse,
    UnifiedSearchRequest,
)
from xhs_food.contracts import ResearchTaskNotFoundError, ResearchTaskPort
from xhs_food.events.bus import STREAM_START, get_event_bus

from .dependencies import get_research_task

router = APIRouter()


def _stream_url(session_id: str) -> str:
    return f"/v1/search/stream/{session_id}"


# ---------------------------------------------------------------------------
# POST /v1/search (unified)
# ---------------------------------------------------------------------------


@router.post("/")
async def unified_search(
    request: UnifiedSearchRequest,
    tasks: Annotated[ResearchTaskPort, Depends(get_research_task)],
):
    """Single entry point — branches on ``(sessionId, query)`` presence."""
    # Case 1: new search
    if not request.sessionId:
        if not request.query:
            raise HTTPException(400, "新查询必须提供 query 参数")
        admission = await tasks.start_new(request.query)
        return {
            "success": True,
            "data": {
                "sessionId": admission.session_id,
                "streamUrl": admission.stream_ref,
                "action": "new_search",
            },
        }

    session_id = request.sessionId

    # Case 2: refine (sessionId + query)
    if request.query:
        try:
            admission = await tasks.refine(session_id, request.query)
        except ResearchTaskNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc
        return {
            "success": True,
            "data": {
                "sessionId": session_id,
                "streamUrl": admission.stream_ref,
                "turnId": admission.turn_id,
                "action": "refine",
            },
        }

    # Case 3: recover (sessionId only)
    return await tasks.recover(session_id)


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
async def search_status(
    tasks: Annotated[ResearchTaskPort, Depends(get_research_task)],
    sessionId: str = Path(..., description="会话ID"),
):
    snapshot = await tasks.status(sessionId)
    if snapshot is None:
        raise HTTPException(404, "Session not found")
    return SearchStatusResponse(success=True, data=snapshot)


# ---------------------------------------------------------------------------
# GET /v1/search/results/{sessionId}
# ---------------------------------------------------------------------------


@router.get("/results/{sessionId}", response_model=SearchResultsResponse)
async def search_results(
    tasks: Annotated[ResearchTaskPort, Depends(get_research_task)],
    sessionId: str = Path(..., description="会话ID"),
):
    snapshot = await tasks.results(sessionId)
    if snapshot is None:
        raise HTTPException(404, "Session not found")
    return SearchResultsResponse(success=True, data=snapshot)
