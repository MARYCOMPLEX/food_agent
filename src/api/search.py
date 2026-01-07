"""
Search Routes - 搜索 API 路由 (流式 SSE 输出).

Endpoints:
- POST /v1/search/start
- GET /v1/search/stream/{sessionId} (SSE 实时推送)
- GET /v1/search/status/{sessionId}
- GET /v1/search/results/{sessionId}
- POST /v1/search/refine

使用 SessionManager 进行对话上下文的 Redis 缓存 + PostgreSQL 持久化。
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
from xhs_food.services import get_session_manager, get_user_storage_service

router = APIRouter(prefix="/v1/search", tags=["search"])

# =============================================================================
# Session Storage (In-memory for transient state, SessionManager for context)
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
    对话历史会通过 SessionManager 持久化到 Redis + PostgreSQL。
    搜索历史会保存到 search_history 表，支持断线恢复。
    """
    session_id = str(uuid.uuid4())  # Use UUID format for PostgreSQL compatibility
    
    session = _get_session(session_id)
    session["status"] = "loading"
    session["query"] = request.query
    
    # 初始化事件发射器
    emitter = get_emitter(session_id)
    emitter.init_steps(request.query)
    
    # 保存用户消息到 SessionManager (Redis + PostgreSQL)
    try:
        manager = await get_session_manager()
        await manager.add_user_message(session_id, request.query)
        logger.debug(f"Saved user query to context: {session_id}")
    except Exception as e:
        logger.warning(f"Failed to save context: {e}")
    
    # 保存到搜索历史（支持断线恢复）
    try:
        storage = await get_user_storage_service()
        # 使用匿名用户（后续可从请求头获取 user_id）
        from xhs_food.services.user_storage import UserStorageService
        await storage.add_history(
            user_id=UserStorageService.ANONYMOUS_USER_ID,
            query=request.query,
            session_id=session_id,
            status="loading",
            location=request.location.get("city") if request.location else None,
        )
        logger.debug(f"Saved to search_history: {session_id}")
    except Exception as e:
        logger.warning(f"Failed to save search history: {e}")
    
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
        # 获取对话历史上下文
        manager = await get_session_manager()
        context = await manager.get_context(session_id)
        
        # 将历史上下文传递给 orchestrator
        if context and len(context) > 1:
            # 有历史记录，设置到 orchestrator 的上下文中
            for msg in context[:-1]:  # 最后一条是当前 query，已经传入
                if msg["role"] == "user":
                    orchestrator._context.history.append({
                        "role": "user",
                        "query": msg["content"],
                    })
                elif msg["role"] == "assistant":
                    orchestrator._context.history.append({
                        "role": "assistant",
                        "summary": msg["content"],
                    })
        
        await orchestrator.search_stream(query, emitter)
        session["status"] = "completed"
        
        # 保存 AI 响应摘要到 SessionManager
        summary = session.get("summary", "")
        if summary:
            await manager.add_assistant_message(session_id, summary)
            logger.debug(f"Saved assistant response to context: {session_id}")
        
        # 保存搜索结果到数据库（支持断线恢复）
        try:
            storage = await get_user_storage_service()
            from xhs_food.services.user_storage import generate_restaurant_hash
            
            # 从 emitter 获取已发送的 restaurant 事件并保存到 restaurants 表
            restaurants = []
            for event in emitter.get_sent_events():
                if event.type == SearchEventType.RESTAURANT:
                    restaurant_data = event.data.get("restaurant", {})
                    if restaurant_data.get("name"):
                        # Upsert to restaurants table and get hash ID
                        saved = await storage.upsert_restaurant(restaurant_data)
                        if saved:
                            # Add the hash ID to restaurant data
                            restaurant_data["id"] = saved.id
                        else:
                            # Generate hash ID even if save fails
                            restaurant_data["id"] = generate_restaurant_hash(
                                restaurant_data["name"], 
                                restaurant_data.get("tel")
                            )
                        restaurants.append(restaurant_data)
            
            # 获取 summary
            result_summary = ""
            for event in emitter.get_sent_events():
                if event.type == SearchEventType.RESULT:
                    result_summary = event.data.get("summary", "")
                    break
            
            # 保存结果
            await storage.save_search_result(
                session_id=session_id,
                restaurants=restaurants,
                summary=result_summary,
                filtered_count=session.get("filtered_count", 0),
            )
            
            # 更新历史状态
            await storage.update_history_status(
                session_id=session_id,
                status="completed",
                results_count=len(restaurants),
            )
            logger.debug(f"Saved search results: {session_id}, {len(restaurants)} restaurants")
            
        except Exception as e:
            logger.warning(f"Failed to save search results: {e}")
            
    except Exception as e:
        logger.exception(f"Stream search failed for {session_id}")
        session["status"] = "error"
        session["error"] = str(e)
        await emitter.emit_error(str(e))
        
        # 更新历史状态为 error
        try:
            storage = await get_user_storage_service()
            await storage.update_history_status(session_id, "error")
        except Exception:
            pass


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
# GET /v1/search/recover/{sessionId} (断线恢复)
# =============================================================================

@router.get("/recover/{sessionId}")
async def search_recover(sessionId: str = Path(..., description="会话ID")):
    """
    断线恢复端点.
    
    用于用户断线后恢复搜索：
    - 已完成: 返回完整结果
    - 进行中: 返回 SSE 流信息，支持继续接收
    - 不存在: 从数据库查询历史结果
    
    Returns:
        status: loading | completed | error | not_found
        如果 completed: 包含 restaurants 和 summary
        如果 loading: 包含 streamUrl 和 lastEventIndex
    """
    # 1. 检查内存中的 session
    session = _sessions.get(sessionId)
    emitter = get_emitter(sessionId) if sessionId in _sessions else None
    
    if session:
        if session.get("status") == "completed":
            # 任务已完成，返回结果
            if emitter:
                restaurants = []
                summary = ""
                for event in emitter.get_sent_events():
                    if event.type == SearchEventType.RESTAURANT:
                        restaurants.append(event.data.get("restaurant", {}))
                    elif event.type == SearchEventType.RESULT:
                        summary = event.data.get("summary", "")
                
                return {
                    "success": True,
                    "data": {
                        "sessionId": sessionId,
                        "status": "completed",
                        "restaurants": restaurants,
                        "summary": summary,
                        "total": len(restaurants),
                    }
                }
        
        elif session.get("status") == "loading":
            # 任务进行中，返回流信息
            last_index = emitter.get_sent_count() if emitter else 0
            return {
                "success": True,
                "data": {
                    "sessionId": sessionId,
                    "status": "loading",
                    "streamUrl": f"/v1/search/stream/{sessionId}?lastEventIndex={last_index}",
                    "lastEventIndex": last_index,
                    "message": "搜索进行中，请连接 SSE 流继续接收",
                }
            }
        
        elif session.get("status") == "error":
            return {
                "success": False,
                "data": {
                    "sessionId": sessionId,
                    "status": "error",
                    "error": session.get("error", "Unknown error"),
                }
            }
    
    # 2. 内存中没有，从数据库查询
    try:
        storage = await get_user_storage_service()
        
        # 查询搜索结果
        result = await storage.get_search_result(sessionId)
        if result:
            return {
                "success": True,
                "data": {
                    "sessionId": sessionId,
                    "status": "completed",
                    "restaurants": result["restaurants"],
                    "summary": result["summary"],
                    "total": len(result["restaurants"]),
                    "fromDatabase": True,
                }
            }
        
        # 查询历史状态
        history = await storage.get_history_by_session(sessionId)
        if history:
            if history.status == "loading":
                # 搜索中断了（可能服务重启）
                return {
                    "success": False,
                    "data": {
                        "sessionId": sessionId,
                        "status": "interrupted",
                        "query": history.query,
                        "message": "搜索已中断，请重新搜索",
                    }
                }
            elif history.status == "error":
                return {
                    "success": False,
                    "data": {
                        "sessionId": sessionId,
                        "status": "error",
                        "query": history.query,
                        "message": "搜索失败，请重试",
                    }
                }
    except Exception as e:
        logger.warning(f"Failed to query database: {e}")
    
    # 3. 完全找不到
    return {
        "success": False,
        "data": {
            "sessionId": sessionId,
            "status": "not_found",
            "message": "会话不存在或已过期",
        }
    }


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
    
    返回 SSE 流式结果。对话历史会自动从 SessionManager 加载。
    """
    session_id = request.sessionId
    
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = _get_session(session_id)
    session["status"] = "loading"
    
    # 保存用户追问到 SessionManager
    try:
        manager = await get_session_manager()
        await manager.add_user_message(session_id, request.query)
        logger.debug(f"Saved refine query to context: {session_id}")
    except Exception as e:
        logger.warning(f"Failed to save refine context: {e}")
    
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


# =============================================================================
# GET /v1/search/history/{sessionId} - 获取对话历史
# =============================================================================

@router.get("/history/{sessionId}")
async def search_history(sessionId: str = Path(..., description="会话ID")):
    """获取会话的对话历史（从 SessionManager 读取）."""
    try:
        manager = await get_session_manager()
        context = await manager.get_context(sessionId, count=50)
        
        return {
            "success": True,
            "data": {
                "sessionId": sessionId,
                "messages": context,
                "count": len(context),
            }
        }
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        return {
            "success": False,
            "error": str(e),
        }
