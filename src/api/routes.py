"""
API Routes - 搜索路由定义 (含SSE流式输出).
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from api.schemas import SearchRequest, SearchResponse, StreamEvent
from xhs_food import XHSFoodOrchestrator
from xhs_food.di import get_xhs_tool_registry

router = APIRouter(prefix="/api/v1", tags=["search"])

# Global orchestrator instance (per-request would be inefficient)
_orchestrator = None


def get_orchestrator() -> XHSFoodOrchestrator:
    """Get or create orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = XHSFoodOrchestrator(
            xhs_registry=get_xhs_tool_registry()
        )
    return _orchestrator


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """
    执行美食搜索.
    
    Request Body:
        - query: 搜索查询（如 "成都本地人常去的老店"）
        - reset_context: 是否重置对话上下文（默认False）
    
    Returns:
        SearchResponse 包含推荐结果
    """
    orchestrator = get_orchestrator()
    
    if request.reset_context:
        orchestrator.reset_context()
    
    try:
        result = await orchestrator.search(request.query)
        
        return SearchResponse(
            status=result.status,
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
            error_message=str(e),
        )


@router.get("/search/stream")
async def search_stream(
    query: str = Query(..., description="搜索查询"),
    reset_context: bool = Query(False, description="是否重置上下文"),
):
    """
    SSE流式搜索接口.
    
    实时返回搜索进度和结果。
    
    Query Parameters:
        - query: 搜索查询
        - reset_context: 是否重置对话上下文
    
    SSE Events:
        - status: 搜索状态更新
        - progress: 搜索进度
        - result: 最终结果
        - error: 错误信息
    """
    async def generate_events() -> AsyncGenerator[dict, None]:
        orchestrator = get_orchestrator()
        
        if reset_context:
            orchestrator.reset_context()
        
        try:
            # 发送开始事件
            yield {
                "event": "status",
                "data": json.dumps({
                    "status": "started",
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
async def reset_context():
    """重置对话上下文."""
    orchestrator = get_orchestrator()
    orchestrator.reset_context()
    return {"status": "ok", "message": "对话上下文已重置"}
