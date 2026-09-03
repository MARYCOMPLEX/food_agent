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

import json
from collections.abc import AsyncGenerator, Mapping
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    SearchResultsResponse,
    SearchStatusResponse,
    UnifiedSearchRequest,
)
from xhs_food.contracts import (
    AgentToolExecutionContext,
    ContractError,
    ErrorCategory,
    EventBusPort,
    PlatformChannel,
    ReliableResearchTaskPort,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    ResearchTaskNotFoundError,
    ResearchTaskPort,
    TaskEvent,
    TaskProgressProjection,
    TaskProgressProjectionSessionLookupPort,
)
from xhs_food.events.bus import STREAM_START, get_event_bus
from xhs_food.experience import EventMappingError, ReliableEventMapper

from .dependencies import get_research_task

router = APIRouter()
# Preserve direct unit calls while FastAPI injects the real request object.
_OPTIONAL_REQUEST = cast(Request, None)


def _stream_url(session_id: str) -> str:
    return f"/v1/search/stream/{session_id}"


def _subject_ref(http_request: Request) -> str:
    headers = getattr(http_request, "headers", {})
    return headers.get("X-User-Id") or headers.get("X-Device-Id") or "anonymous"


def _tool_context(
    request: UnifiedSearchRequest,
    http_request: Request,
) -> AgentToolExecutionContext:
    return AgentToolExecutionContext(
        tenant_ref=_subject_ref(http_request),
        platforms=tuple(PlatformChannel(item) for item in request.platforms),
        account_refs=request.accountRefs,
        expected_session_versions=request.expectedSessionVersions,
    )


# ---------------------------------------------------------------------------
# POST /v1/search (unified)
# ---------------------------------------------------------------------------


@router.post("/")
async def unified_search(
    request: UnifiedSearchRequest,
    tasks: Annotated[ResearchTaskPort, Depends(get_research_task)],
    http_request: Request = _OPTIONAL_REQUEST,
):
    """Single entry point — branches on ``(sessionId, query)`` presence."""
    app_state = getattr(getattr(http_request, "app", None), "state", None)
    reliable_enabled = bool(getattr(app_state, "reliable_task_lifecycle", False))
    # Case 1: new search
    if not request.sessionId:
        if not request.query:
            raise HTTPException(400, "新查询必须提供 query 参数")
        if reliable_enabled:
            reliable_port = cast(ReliableResearchTaskPort, tasks)
            if not callable(getattr(reliable_port, "submit", None)):
                raise HTTPException(status_code=503, detail=_reliable_dependency_detail())
            session_id = f"session-{uuid4().hex}"
            subject_ref = _subject_ref(http_request)
            public_inputs: dict[str, Any] = {}
            if request.location is not None:
                public_inputs["location"] = dict(request.location)
            reliable_request = ResearchRequest(
                request_id=f"http:{session_id}",
                operation=ResearchOperation.QUERY,
                domain="food",
                query=request.query,
                public_inputs=public_inputs,
                identity=RequestIdentity(
                    subject_ref=subject_ref,
                    tenant_ref=subject_ref,
                    session_ref=session_id,
                    authorization_refs=tuple(
                        f"{platform}:{account_ref}"
                        for platform, account_ref in sorted(request.accountRefs.items())
                    ),
                ),
                policy=RequestPolicy(
                    policy_version="research/v1",
                    compatibility_version="http/v1",
                ),
            )
            try:
                task = await reliable_port.submit(reliable_request)
            except Exception as exc:
                error = getattr(exc, "error", None)
                if isinstance(error, ContractError):
                    status_code = (
                        503
                        if error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
                        else 409
                    )
                    raise HTTPException(
                        status_code=status_code,
                        detail=error.model_dump(mode="json"),
                    ) from exc
                raise
            projection = task.progress_projection
            if projection is None or projection.session_id != session_id:
                raise HTTPException(status_code=500, detail="reliable task session projection missing")
            return {
                "success": True,
                "data": {
                    "sessionId": session_id,
                    "taskId": task.task_id,
                    "turnId": int(projection.turn_id or "1"),
                    "streamUrl": f"/v1/search/stream/{session_id}?sseVersion=v1",
                    "action": "new_search",
                },
            }
        admission = await tasks.start_new(
            request.query,
            tool_context=_tool_context(request, http_request),
        )
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
            admission = await tasks.refine(
                session_id,
                request.query,
                tool_context=_tool_context(request, http_request),
            )
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
    request: Request,
    sessionId: str = Path(..., description="会话ID"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    sse_version: str | None = Query(None, alias="sseVersion"),
):
    """Server-sent events with Redis-Stream-backed replay.

    The browser's ``EventSource`` records ``id:`` on every event and sends
    it back as ``Last-Event-ID`` on reconnect. The EventBus replays from
    that id, so the client needs no special reconnection logic.
    """
    if sse_version not in {None, "legacy", "v1"}:
        raise HTTPException(
            status_code=406,
            detail={
                "code": "unsupported_sse_version",
                "supported": ["legacy", "v1"],
            },
        )
    if sse_version == "v1":
        return await _reliable_sse_response(request, sessionId, last_event_id)

    reliable_enabled = bool(getattr(request.app.state, "reliable_task_lifecycle", False))
    try:
        bus = await (
            get_event_bus(require_redis=True)
            if reliable_enabled
            else get_event_bus()
        )
    except RuntimeError as exc:
        error = getattr(exc, "error", None)
        if not isinstance(error, ContractError):
            raise
        raise HTTPException(status_code=503, detail=error.model_dump(mode="json")) from exc
    start_from = last_event_id or STREAM_START

    async def generate() -> AsyncGenerator[dict, None]:
        async for entry_id, event in bus.subscribe(sessionId, start_from):
            sse = event.to_sse()
            sse["id"] = entry_id
            yield sse

    return EventSourceResponse(generate())


def _reliable_dependency_detail() -> dict[str, str]:
    return {
        "code": "RELIABLE_TASK_DEPENDENCY_UNAVAILABLE",
        "message": "reliable task bindings are not configured",
    }


def _reliable_projection_store(request: Request) -> TaskProgressProjectionSessionLookupPort:
    store = getattr(request.app.state, "reliable_projection_store", None)
    if not callable(getattr(store, "get_by_session_id", None)):
        raise HTTPException(status_code=503, detail=_reliable_dependency_detail())
    return cast(TaskProgressProjectionSessionLookupPort, store)


def _reliable_event_bus(request: Request) -> EventBusPort:
    bus = getattr(request.app.state, "reliable_event_bus", None)
    if not callable(getattr(bus, "subscribe", None)):
        raise HTTPException(status_code=503, detail=_reliable_dependency_detail())
    return cast(EventBusPort, bus)


def _projection_snapshot(projection: TaskProgressProjection) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "snapshotVersion": int(projection.updated_at.timestamp() * 1000),
        "status": projection.status.value,
    }
    if projection.status.value == "completed":
        snapshot["terminal"] = {"event": "done", "message": "搜索完成"}
    elif projection.status.is_terminal:
        snapshot["terminal"] = {
            "event": "error",
            "error": {
                "code": "TASK_CANCELLED"
                if projection.status.value == "cancelled"
                else "TASK_FAILED",
                "message": "任务已取消"
                if projection.status.value == "cancelled"
                else "研究任务失败",
                "retryable": False,
            },
        }
    else:
        snapshot["resumeFromEventId"] = projection.last_event_id or "0-0"
    return snapshot


async def _reliable_sse_response(
    request: Request,
    session_id: str,
    last_event_id: str | None,
) -> EventSourceResponse:
    bus = _reliable_event_bus(request)
    ensure_available = getattr(bus, "ensure_available", None)
    if callable(ensure_available):
        try:
            await ensure_available()
        except Exception as exc:
            error = getattr(exc, "error", None)
            detail = (
                error.model_dump(mode="json")
                if isinstance(error, ContractError)
                else _reliable_dependency_detail()
            )
            raise HTTPException(status_code=503, detail=detail) from exc
    projection_store = _reliable_projection_store(request)
    projection = await projection_store.get_by_session_id(session_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="Session not found")
    start_from = last_event_id or STREAM_START
    mapper = ReliableEventMapper()

    async def generate() -> AsyncGenerator[dict[str, str], None]:
        try:
            async for envelope in bus.subscribe(session_id, start_from):
                raw_event = envelope.payload.get("taskEvent")
                if not isinstance(raw_event, Mapping):
                    raise EventMappingError("reliable stream event is missing taskEvent")
                stable = mapper.map(
                    TaskEvent.model_validate(raw_event),
                    session_id=session_id,
                )
                yield {
                    "id": envelope.event_id,
                    "event": stable.event,
                    "data": json.dumps(
                        stable.data,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
                if stable.event in {"done", "error"}:
                    return
        except Exception as exc:
            error = getattr(exc, "error", None)
            if not (
                isinstance(error, ContractError)
                and error.category is ErrorCategory.REPLAY_EXPIRED
            ):
                raise
            current = await projection_store.get_by_session_id(session_id)
            if current is None:
                return
            expired = mapper.replay_expired(
                current,
                session_id=session_id,
                snapshot=_projection_snapshot(current),
            )
            yield {
                "event": expired.event,
                "data": json.dumps(
                    expired.data,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }

    return EventSourceResponse(generate(), headers={"X-SSE-Version": "v1"})


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
