"""
API Routes - 搜索路由定义 (含SSE流式输出 + 会话管理).
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator, Dict

from fastapi import APIRouter, Query, Header
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from api.schemas import SearchRequest, SearchResponse, StreamEvent
from xhs_food import XHSFoodOrchestrator
from xhs_food.di import get_xhs_tool_registry
from xhs_food.services import get_session_manager

router = APIRouter(prefix="/api/v1", tags=["search"])

# Session-based orchestrator instances
_orchestrators: Dict[str, XHSFoodOrchestrator] = {}


def get_orchestrator(session_id: str) -> XHSFoodOrchestrator:
    """Get or create orchestrator for a session."""
    if session_id not in _orchestrators:
        _orchestrators[session_id] = XHSFoodOrchestrator(
            xhs_registry=get_xhs_tool_registry()
        )
    return _orchestrators[session_id]


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """
    执行美食搜索.
    
    Request Body:
        - query: 搜索查询（如 "成都本地人常去的老店"）
        - session_id: 会话ID（可选，不提供则自动创建）
        - reset_context: 是否重置对话上下文（默认False）
    
    Returns:
        SearchResponse 包含推荐结果和session_id
    """
    # Get or create session_id
    session_id = request.session_id or str(uuid.uuid4())
    
    orchestrator = get_orchestrator(session_id)
    
    if request.reset_context:
        orchestrator.reset_context()
        # Also clear from session manager cache
        try:
            manager = await get_session_manager()
            manager._redis.clear_session(session_id)
        except Exception:
            pass
    
    try:
        # Store user message
        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, request.query)
        except Exception as e:
            logger.warning(f"Failed to save user message: {e}")
        
        result = await orchestrator.search(request.query)
        
        # Store assistant response
        try:
            manager = await get_session_manager()
            await manager.add_assistant_message(session_id, result.summary or str(result.recommendations))
        except Exception as e:
            logger.warning(f"Failed to save assistant message: {e}")
        
        return SearchResponse(
            status=result.status,
            session_id=session_id,
            recommendations=[r.to_dict() for r in result.recommendations],
            filtered_count=result.filtered_count,
            summary=result.summary,
            clarify_questions=result.clarify_questions,
            error_message=result.error_message,
        )
    except Exception as e:
        logger.exception("Search failed")
        return SearchResponse(
            status="error",
            session_id=session_id,
            error_message=str(e),
        )


@router.get("/search/stream")
async def search_stream(
    query: str = Query(..., description="搜索查询"),
    session_id: str = Query(None, description="会话ID，不提供则自动创建"),
    reset_context: bool = Query(False, description="是否重置上下文"),
):
    """
    SSE流式搜索接口.
    
    实时返回搜索进度和结果。
    
    Query Parameters:
        - query: 搜索查询
        - session_id: 会话ID（可选）
        - reset_context: 是否重置对话上下文
    
    SSE Events:
        - status: 搜索状态更新
        - progress: 搜索进度
        - result: 最终结果
        - error: 错误信息
    """
    # Get or create session_id
    sid = session_id or str(uuid.uuid4())
    
    async def generate_events() -> AsyncGenerator[dict, None]:
        orchestrator = get_orchestrator(sid)
        
        if reset_context:
            orchestrator.reset_context()
        
        try:
            # 发送开始事件
            yield {
                "event": "status",
                "data": json.dumps({
                    "status": "started",
                    "session_id": sid,
                    "message": f"开始搜索: {query}",
                }),
            }
            
            # 发送解析意图事件
            yield {
                "event": "progress",
                "data": json.dumps({
                    "phase": "parsing",
                    "message": "解析搜索意图...",
                }),
            }
            
            # 执行搜索
            result = await orchestrator.search(query)
            
            # 发送搜索完成事件
            yield {
                "event": "progress",
                "data": json.dumps({
                    "phase": "completed",
                    "message": f"搜索完成，找到 {len(result.recommendations)} 家推荐",
                }),
            }
            
            # 发送结果
            yield {
                "event": "result",
                "data": json.dumps({
                    "status": result.status,
                    "session_id": sid,
                    "recommendations": [r.to_dict() for r in result.recommendations],
                    "filtered_count": result.filtered_count,
                    "summary": result.summary,
                    "clarify_questions": result.clarify_questions,
                    "error_message": result.error_message,
                }, ensure_ascii=False),
            }
            
            # 发送结束事件
            yield {
                "event": "done",
                "data": json.dumps({"message": "搜索结束"}),
            }
            
        except Exception as e:
            logger.exception("Stream search failed")
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": str(e),
                }),
            }
    
    return EventSourceResponse(generate_events())


@router.post("/reset")
async def reset_context(session_id: str = Query(..., description="要重置的会话ID")):
    """重置指定会话的对话上下文."""
    if session_id in _orchestrators:
        _orchestrators[session_id].reset_context()
    
    try:
        manager = await get_session_manager()
        manager._redis.clear_session(session_id)
    except Exception:
        pass
    
    return {"status": "ok", "session_id": session_id, "message": "对话上下文已重置"}


@router.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """获取会话信息."""
    try:
        manager = await get_session_manager()
        
        exists = manager.session_exists(session_id)
        length = manager.get_session_length(session_id) if exists else 0
        context = await manager.get_context(session_id, count=5) if exists else []
        
        return {
            "session_id": session_id,
            "exists": exists,
            "message_count": length,
            "recent_messages": context,
        }
    except Exception as e:
        return {
            "session_id": session_id,
            "exists": False,
            "error": str(e),
        }


@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = Query(50, description="最大返回条数"),
):
    """获取会话完整历史（从PostgreSQL）."""
    try:
        manager = await get_session_manager()
        history = await manager.get_full_history(session_id, limit=limit)
        
        return {
            "session_id": session_id,
            "count": len(history),
            "messages": [h.to_dict() for h in history],
        }
    except Exception as e:
        return {
            "session_id": session_id,
            "error": str(e),
        }


@router.post("/session/create")
async def create_session():
    """创建新会话."""
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "message": "新会话已创建",
    }
