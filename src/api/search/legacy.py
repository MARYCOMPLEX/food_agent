"""
Legacy search endpoints (preserved for backward compatibility).

- POST /v1/search/start   → use POST /v1/search { query }
- POST /v1/search/refine  → use POST /v1/search { sessionId, query }
- GET  /v1/search/history  → conversation history
"""

import asyncio
import uuid

from fastapi import APIRouter, Path, HTTPException
from loguru import logger

from api.schemas import (
    SearchStartRequest, SearchStartResponse,
    RefineRequest,
)
from xhs_food.events import get_emitter
from xhs_food.services import get_session_manager, get_user_storage_service

from .state import _sessions, _get_session, _get_orchestrator
from .tasks import _run_stream_search

router = APIRouter()


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
