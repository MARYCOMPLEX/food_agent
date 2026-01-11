"""
Search Routes - 搜索 API 路由 (流式 SSE 输出).

Endpoints:
- POST /v1/search                   (推荐) 统一接口：新查询/追问/恢复
- GET  /v1/search/stream/{sessionId} (SSE 实时推送)

Legacy Endpoints (保留兼容):
- POST /v1/search/start             → 用 POST /v1/search { query }
- POST /v1/search/refine            → 用 POST /v1/search { sessionId, query }
- GET  /v1/search/recover/{id}      → 用 POST /v1/search { sessionId }
- GET  /v1/search/status/{sessionId}
- GET  /v1/search/results/{sessionId}

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
    UnifiedSearchRequest,
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
# POST /v1/search (推荐使用的统一接口)
# =============================================================================

@router.post("")
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
    return await search_recover(session_id)


# =============================================================================
# POST /v1/search/start [LEGACY - 建议使用 POST /v1/search]
# =============================================================================

@router.post("/start", response_model=SearchStartResponse)
async def search_start(request: SearchStartRequest):
    """
    [LEGACY] 启动新的搜索会话.
    
    ⚠️ 建议使用 POST /v1/search { query } 代替此接口。
    
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
        
        # 将历史上下文传递给 orchestrator（使用正确的方法）
        if context and len(context) > 1:
            # 有历史记录，设置到 orchestrator 的上下文中
            for msg in context[:-1]:  # 最后一条是当前 query，已经传入
                if msg["role"] == "user":
                    orchestrator._context.add_user_message(msg["content"])
                elif msg["role"] == "assistant":
                    orchestrator._context.add_assistant_message(msg["content"])
        
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
            
            # 保存结果（自动计算 turn_id）
            await storage.save_search_result(
                session_id=session_id,
                restaurants=restaurants,
                summary=result_summary,
                filtered_count=session.get("filtered_count", 0),
                query=query,  # 传递本轮的查询
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
# GET /v1/search/recover/{sessionId} [LEGACY - 建议使用 POST /v1/search]
# =============================================================================

@router.get("/recover/{sessionId}")
async def search_recover(sessionId: str = Path(..., description="会话ID")):
    """
    [LEGACY] 断线恢复端点.
    
    ⚠️ 建议使用 POST /v1/search { sessionId } 代替此接口。
    
    用于用户断线后恢复搜索：
    - 已完成: 返回所有轮次的完整结果
    - 进行中: 返回 SSE 流信息，支持继续接收
    - 不存在: 从数据库查询历史结果
    
    Returns:
        status: loading | completed | error | not_found
        如果 completed: 
            - restaurants/summary/total: 最新轮次的结果（向后兼容）
            - turns: 所有轮次的完整历史数组
            - turnCount: 总轮次数
        如果 loading: 包含 streamUrl 和 lastEventIndex
    """
    logger.info(f"=== [RECOVER DEBUG] 开始处理 sessionId: {sessionId} ===")
    
    # 1. 检查内存中的 session
    session = _sessions.get(sessionId)
    emitter = get_emitter(sessionId) if sessionId in _sessions else None
    
    logger.info(f"[RECOVER DEBUG] 第1层-内存查找: session存在={session is not None}, emitter存在={emitter is not None}")
    if session:
        logger.info(f"[RECOVER DEBUG] 第1层-session内容: status={session.get('status')}, keys={list(session.keys())}")
    
    if session:
        if session.get("status") == "completed":
            # 任务已完成，返回结果
            logger.info(f"[RECOVER DEBUG] 第1层-状态completed, emitter存在={emitter is not None}")
            if emitter:
                restaurants = []
                summary = ""
                sent_events = emitter.get_sent_events()
                logger.info(f"[RECOVER DEBUG] 第1层-事件数量: {len(sent_events)}")
                for event in sent_events:
                    if event.type == SearchEventType.RESTAURANT:
                        restaurants.append(event.data.get("restaurant", {}))
                    elif event.type == SearchEventType.RESULT:
                        summary = event.data.get("summary", "")
                
                logger.info(f"[RECOVER DEBUG] 第1层-提取结果: restaurants={len(restaurants)}, summary长度={len(summary)}")
                
                # BUG FIX: 如果 emitter 没有餐厅数据，fallback 到数据库查询
                if restaurants:
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
                else:
                    logger.warning(f"[RECOVER DEBUG] 第1层-emitter无数据，fallback到数据库查询")
        
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
    logger.info(f"[RECOVER DEBUG] 第2层-开始查询数据库...")
    try:
        storage = await get_user_storage_service()
        logger.info(f"[RECOVER DEBUG] 第2层-storage初始化成功: initialized={storage._initialized}")
        
        # 查询所有轮次的搜索结果
        all_results = await storage.get_all_search_results(sessionId)
        logger.info(f"[RECOVER DEBUG] 第2层-search_results查询结果: 共 {len(all_results)} 轮")
        if all_results:
            # 构建所有轮次数据
            turns = []
            for result in all_results:
                turns.append({
                    "turnId": result.get("turn_id", 1),
                    "query": result.get("query", ""),
                    "restaurants": result.get("restaurants", []),
                    "summary": result.get("summary", ""),
                    "total": len(result.get("restaurants", [])),
                    "createdAt": result.get("created_at"),
                })
            
            # 最新一轮作为主要结果
            latest = all_results[-1]
            logger.info(f"[RECOVER DEBUG] 第2层-返回 {len(turns)} 轮数据, 最新轮: turn_id={latest.get('turn_id')}")
            
            return {
                "success": True,
                "data": {
                    "sessionId": sessionId,
                    "status": "completed",
                    # 最新轮次的结果（向后兼容）
                    "turnId": latest.get("turn_id", 1),
                    "query": latest.get("query", ""),
                    "restaurants": latest.get("restaurants", []),
                    "summary": latest.get("summary", ""),
                    "total": len(latest.get("restaurants", [])),
                    # 所有轮次的完整历史
                    "turns": turns,
                    "turnCount": len(turns),
                    "fromDatabase": True,
                }
            }
        
        # 查询历史状态
        history = await storage.get_history_by_session(sessionId)
        logger.info(f"[RECOVER DEBUG] 第3层-search_history查询结果: {history is not None}")
        if history:
            logger.info(f"[RECOVER DEBUG] 第3层-search_history内容: status={history.status}, query={history.query[:50] if history.query else None}")
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
        logger.warning(f"[RECOVER DEBUG] 数据库查询异常: {e}")
    
    # 3. 完全找不到
    logger.info(f"[RECOVER DEBUG] 最终结果: not_found")
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
# POST /v1/search/refine [LEGACY - 建议使用 POST /v1/search]
# =============================================================================

@router.post("/refine")
async def search_refine(request: RefineRequest):
    """
    [LEGACY] 多轮对话追问.
    
    ⚠️ 建议使用 POST /v1/search { sessionId, query } 代替此接口。
    
    返回 SSE 流式结果。对话历史会自动从 SessionManager 加载。
    支持服务重启后从数据库恢复 session。
    """
    session_id = request.sessionId
    
    # 如果内存中没有 session，尝试从数据库恢复
    if session_id not in _sessions:
        logger.info(f"[REFINE DEBUG] Session {session_id} not in memory, trying to restore from database")
        try:
            storage = await get_user_storage_service()
            
            # 使用首次搜索结果来恢复 last_recommendations（不是最新轮次）
            # 这样用户可以在不同过滤条件之间切换
            first_result = await storage.get_first_search_result(session_id)
            if first_result:
                logger.info(f"[REFINE DEBUG] Found session in database, restoring...")
                # 恢复 session 到内存
                session = _get_session(session_id)  # 这会创建新的 session 条目
                session["status"] = "completed"
                session["query"] = first_result.get("query", "")
                session["restaurants"] = first_result.get("restaurants", [])
                session["summary"] = first_result.get("summary", "")
                
                # 恢复 orchestrator 的上下文（从 SessionManager 加载历史）
                orchestrator = _get_orchestrator(session_id)
                manager = await get_session_manager()
                context = await manager.get_context(session_id)
                
                if context:
                    for msg in context:
                        if msg["role"] == "user":
                            orchestrator._context.add_user_message(msg["content"])
                        elif msg["role"] == "assistant":
                            orchestrator._context.add_assistant_message(msg["content"])
                
                # 恢复首次搜索的推荐到 orchestrator 上下文
                # 这是完整列表，refine 可以从中过滤
                for restaurant in first_result.get("restaurants", []):
                    name = restaurant.get("name", "")
                    if name:
                        orchestrator._context.last_recommendations[name] = restaurant
                
                logger.info(f"[REFINE DEBUG] Session restored from turn 1: {len(first_result.get('restaurants', []))} restaurants")
            else:
                # 数据库中也没有
                logger.warning(f"[REFINE DEBUG] Session not found in database either")
                raise HTTPException(status_code=404, detail="Session not found")
                
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[REFINE DEBUG] Failed to restore session: {e}")
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
