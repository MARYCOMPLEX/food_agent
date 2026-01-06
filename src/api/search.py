"""
Search Routes - 搜索 API 路由 (流式 SSE 输出).

Endpoints:
- POST /v1/search/start
- GET /v1/search/stream/{sessionId} (SSE 实时推送)
- GET /v1/search/status/{sessionId}
- GET /v1/search/results/{sessionId}
- POST /v1/search/refine
"""

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import APIRouter, Query, Path, HTTPException
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from api.schemas import (
    SearchStartRequest, SearchStartResponse,
    SearchStatusResponse, SearchResultsResponse,
    RefineRequest, ErrorResponse,
)
from xhs_food import XHSFoodOrchestrator
from xhs_food.di import get_xhs_tool_registry
from xhs_food.events import get_emitter, remove_emitter, SearchEventType

router = APIRouter(prefix="/v1/search", tags=["search"])

# =============================================================================
# Session Storage
# =============================================================================

_sessions: Dict[str, Dict[str, Any]] = {}
_orchestrators: Dict[str, XHSFoodOrchestrator] = {}


def _get_session(session_id: str) -> Dict[str, Any]:
    """Get or create session state."""
    if session_id not in _sessions:
        _sessions[session_id] = {
            "id": session_id,
            "status": "idle",
            "restaurants": [],
            "summary": "",
            "error": None,
            "created_at": time.time(),
        }
    return _sessions[session_id]


def _get_orchestrator(session_id: str) -> XHSFoodOrchestrator:
    """Get or create orchestrator for a session."""
    if session_id not in _orchestrators:
        _orchestrators[session_id] = XHSFoodOrchestrator(
            xhs_registry=get_xhs_tool_registry()
        )
    return _orchestrators[session_id]


# =============================================================================
# POST /v1/search/start
# =============================================================================

@router.post("/start", response_model=SearchStartResponse)
async def search_start(request: SearchStartRequest):
    """
    启动新的搜索会话.
    
    返回 sessionId，前端应立即连接 SSE 流接收更新。
    """
    session_id = f"sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    
    session = _get_session(session_id)
    session["status"] = "loading"
    session["query"] = request.query
    
    # 初始化事件发射器
    emitter = get_emitter(session_id)
    emitter.init_steps(request.query)
    
    # 启动后台搜索任务
    asyncio.create_task(_run_stream_search(session_id, request.query))
    
    return SearchStartResponse(
        success=True,
        data={
            "sessionId": session_id,
            "loadingSteps": emitter._steps,
        }
    )


async def _run_stream_search(session_id: str, query: str):
    """后台流式搜索任务."""
    session = _get_session(session_id)
    orchestrator = _get_orchestrator(session_id)
    emitter = get_emitter(session_id)
    
    try:
        await orchestrator.search_stream(query, emitter)
        session["status"] = "completed"
    except Exception as e:
        logger.exception(f"Stream search failed for {session_id}")
        session["status"] = "error"
        session["error"] = str(e)
        await emitter.emit_error(str(e))


# =============================================================================
# GET /v1/search/stream/{sessionId} (SSE)
# =============================================================================

@router.get("/stream/{sessionId}")
async def search_stream(sessionId: str = Path(..., description="会话ID")):
    """
    SSE 流式搜索端点.
    
    Events:
    - step_start: 步骤开始
    - step_done: 步骤完成
    - step_error: 步骤失败
    - restaurant: 单个店铺结果（流式）
    - result: 最终汇总
    - error: 错误
    - done: 完成
    """
    emitter = get_emitter(sessionId)
    
    async def generate_events() -> AsyncGenerator[dict, None]:
        try:
            async for event in emitter.events(timeout=120.0):
                yield event.to_sse()
                
                if event.type in (SearchEventType.DONE, SearchEventType.ERROR):
                    break
        finally:
            # 清理
            remove_emitter(sessionId)
    
    return EventSourceResponse(generate_events())


# =============================================================================
# GET /v1/search/status/{sessionId}
# =============================================================================

@router.get("/status/{sessionId}", response_model=SearchStatusResponse)
async def search_status(sessionId: str = Path(..., description="会话ID")):
    """获取搜索状态."""
    if sessionId not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = _get_session(sessionId)
    emitter = get_emitter(sessionId)
    
    return SearchStatusResponse(
        success=True,
        data={
            "sessionId": sessionId,
            "status": session["status"],
            "loadingSteps": emitter._steps,
        }
    )


# =============================================================================
# GET /v1/search/results/{sessionId}
# =============================================================================

@router.get("/results/{sessionId}", response_model=SearchResultsResponse)
async def search_results(sessionId: str = Path(..., description="会话ID")):
    """获取搜索结果."""
    if sessionId not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = _get_session(sessionId)
    
    return SearchResultsResponse(
        success=True,
        data={
            "sessionId": sessionId,
            "restaurants": session.get("restaurants", []),
            "summary": session.get("summary", ""),
        }
    )


# =============================================================================
# POST /v1/search/refine
# =============================================================================

@router.post("/refine")
async def search_refine(request: RefineRequest):
    """
    多轮对话追问.
    
    返回 SSE 流式结果。
    """
    session_id = request.sessionId
    
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = _get_session(session_id)
    session["status"] = "loading"
    
    # 重置 emitter
    emitter = get_emitter(session_id)
    emitter.reset()
    emitter.init_steps(request.query)
    
    # 启动后台任务
    asyncio.create_task(_run_stream_search(session_id, request.query))
    
    return {
        "success": True,
        "data": {
            "sessionId": session_id,
            "message": "请连接 SSE 流接收结果",
        }
    }
