"""
Main search endpoints.

- POST /v1/search          (unified_search)
- GET  /v1/search/stream   (search_stream / SSE)
- GET  /v1/search/status   (search_status)
- GET  /v1/search/results  (search_results)
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Query, Path, HTTPException
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from api.schemas import (
    SearchStatusResponse, SearchResultsResponse,
    UnifiedSearchRequest,
)
from xhs_food.events import get_emitter, remove_emitter, SearchEventType
from xhs_food.services import get_session_manager, get_user_storage_service

from .state import _sessions, _get_session, _get_orchestrator
from .tasks import _run_stream_search

router = APIRouter()


# =============================================================================
# POST /v1/search (推荐使用的统一接口)
# =============================================================================

@router.post("/")
async def unified_search(request: UnifiedSearchRequest):
    """
    统一搜索接口 - 智能判断操作类型.

    根据参数自动执行对应操作：
    - 无 sessionId → 新查询（必须有 query）
    - 有 sessionId + query → 追问/继续对话
    - 有 sessionId + 无 query → 恢复历史会话

    Returns:
        - 新查询/追问: { sessionId, streamUrl } → 前端连接 SSE 流
        - 恢复: 根据状态返回完整结果或流信息
    """
    # Case 1: 新查询（无 sessionId）
    if not request.sessionId:
        if not request.query:
            raise HTTPException(400, "新查询必须提供 query 参数")

        session_id = str(uuid.uuid4())
        session = _get_session(session_id)
        session["status"] = "loading"
        session["query"] = request.query

        # 初始化事件发射器
        emitter = get_emitter(session_id)
        emitter.init_steps(request.query)

        # 保存用户消息到 SessionManager
        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, request.query)
        except Exception as e:
            logger.warning(f"Failed to save user message: {e}")

        # 保存到数据库
        try:
            storage = await get_user_storage_service()
            await storage.create_search_history(
                session_id=session_id,
                query=request.query,
                status="loading",
            )
        except Exception as e:
            logger.warning(f"Failed to save search history: {e}")

        # 启动后台搜索任务
        asyncio.create_task(_run_stream_search(session_id, request.query))

        return {
            "success": True,
            "data": {
                "sessionId": session_id,
                "streamUrl": f"/v1/search/stream/{session_id}",
                "action": "new_search",
            }
        }

    # Case 2: 有 sessionId
    session_id = request.sessionId

    # Case 2a: 追问（有 sessionId + query）
    if request.query:
        # 如果内存中没有 session，尝试从数据库恢复完整上下文
        if session_id not in _sessions:
            try:
                storage = await get_user_storage_service()

                # 1. 恢复首次搜索的 restaurants（完整列表，用于后续筛选）
                first_result = await storage.get_first_search_result(session_id)
                if not first_result:
                    raise HTTPException(404, "Session not found")

                session = _get_session(session_id)
                session["status"] = "completed"
                session["query"] = first_result.get("query", "")
                session["restaurants"] = first_result.get("restaurants", [])

                # 2. 获取所有轮次数据，计算 turn_id
                all_results = await storage.get_all_search_results(session_id)
                session["turn_id"] = len(all_results) if all_results else 1

                # 3. 恢复 orchestrator 的对话上下文（从 SessionManager）
                orchestrator = _get_orchestrator(session_id)
                manager = await get_session_manager()
                context = await manager.get_context(session_id)

                if context:
                    for msg in context:
                        if msg["role"] == "user":
                            orchestrator._context.add_user_message(msg["content"])
                        elif msg["role"] == "assistant":
                            orchestrator._context.add_assistant_message(msg["content"])

                # 4. 恢复首次搜索的推荐到 orchestrator（完整列表）
                for restaurant in first_result.get("restaurants", []):
                    name = restaurant.get("name", "")
                    if name:
                        orchestrator._context.last_recommendations[name] = restaurant

                logger.info(f"[UNIFIED] Session restored: {len(first_result.get('restaurants', []))} restaurants, {len(context or [])} messages, turn_id={session['turn_id']}")

            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Failed to restore session: {e}")
                raise HTTPException(404, f"Session not found: {e}")

        session = _get_session(session_id)
        turn_id = session.get("turn_id", 1) + 1
        session["status"] = "loading"
        session["query"] = request.query
        session["turn_id"] = turn_id

        # 保存用户追问到 SessionManager
        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, request.query)
        except Exception as e:
            logger.warning(f"Failed to save refine context: {e}")

        # 重置 emitter
        emitter = get_emitter(session_id)
        emitter.reset()
        emitter.init_steps(request.query)

        # 启动后台追问任务
        asyncio.create_task(_run_stream_search(session_id, request.query))

        return {
            "success": True,
            "data": {
                "sessionId": session_id,
                "streamUrl": f"/v1/search/stream/{session_id}",
                "turnId": turn_id,
                "action": "refine",
            }
        }

    # Case 2b: 恢复历史（有 sessionId，无 query）
    # 复用现有的 recover 逻辑
    from .tasks import search_recover
    return await search_recover(session_id)


# =============================================================================
# GET /v1/search/stream/{sessionId} (SSE)
# =============================================================================

@router.get("/stream/{sessionId}")
async def search_stream(
    sessionId: str = Path(..., description="会话ID"),
    lastEventIndex: int = Query(0, description="上次收到的事件索引，用于重放"),
):
    """
    SSE 流式搜索端点.

    支持断线重连：用户断开后可重新连接继续接收事件。

    Args:
        sessionId: 会话ID
        lastEventIndex: 断线前收到的最后一个事件索引，0 表示从头开始

    Events:
    - step_start: 步骤开始
    - step_done: 步骤完成
    - step_error: 步骤失败
    - restaurant: 单个店铺结果（流式）
    - result: 最终汇总
    - error: 错误
    - done: 完成
    """
    # 检查 session 状态
    session = _sessions.get(sessionId)
    if session and session.get("status") == "completed":
        # 任务已完成，返回提示使用 /recover 获取结果
        return {
            "success": True,
            "data": {
                "sessionId": sessionId,
                "status": "completed",
                "message": "搜索已完成，请使用 /recover/{sessionId} 获取结果"
            }
        }

    emitter = get_emitter(sessionId)

    async def generate_events() -> AsyncGenerator[dict, None]:
        completed = False
        try:
            # 重放断线期间错过的事件
            sent_events = emitter.get_sent_events()
            if lastEventIndex > 0 and lastEventIndex < len(sent_events):
                logger.debug(f"Replaying events from index {lastEventIndex}, total {len(sent_events)}")
                for event in sent_events[lastEventIndex:]:
                    # 添加 replayed 标记
                    sse_data = event.to_sse()
                    event_data = json.loads(sse_data["data"])
                    event_data["replayed"] = True
                    sse_data["data"] = json.dumps(event_data, ensure_ascii=False)
                    yield sse_data

                    if event.type in (SearchEventType.DONE, SearchEventType.ERROR):
                        completed = True
                        return

            # 继续接收新事件
            async for event in emitter.events():
                yield event.to_sse()

                if event.type in (SearchEventType.DONE, SearchEventType.ERROR):
                    completed = True
                    break
        finally:
            # 只在任务完成后清理，断线不清理（支持重连）
            if completed:
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
