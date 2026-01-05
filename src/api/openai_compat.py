"""
OpenAI Compatible Chat API.

Provides /v1/chat/completions endpoint for integration with:
- Chatbox
- Open WebUI
- ChatGPT-Next-Web
- LobeChat
- Any OpenAI-compatible frontend
"""

import json
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from xhs_food import XHSFoodOrchestrator
from xhs_food.di import get_xhs_tool_registry
from xhs_food.services import get_session_manager

router = APIRouter(prefix="/v1", tags=["openai-compatible"])

# Session-based orchestrators
_orchestrators = {}


def get_orchestrator(session_id: str) -> XHSFoodOrchestrator:
    if session_id not in _orchestrators:
        _orchestrators[session_id] = XHSFoodOrchestrator(
            xhs_registry=get_xhs_tool_registry()
        )
    return _orchestrators[session_id]


# ============== Request/Response Models ==============

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: system, user, assistant")
    content: str = Field(..., description="Message content")


class ChatCompletionRequest(BaseModel):
    model: str = Field("xhs-food-agent", description="Model name (ignored)")
    messages: List[ChatMessage] = Field(..., description="Chat messages")
    stream: bool = Field(False, description="Enable streaming")
    temperature: Optional[float] = Field(0.7)
    max_tokens: Optional[int] = Field(None)


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ============== Endpoints ==============

@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completions endpoint.
    
    Integrates with any OpenAI-compatible frontend.
    """
    # Extract last user message
    user_message = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break
    
    if not user_message:
        raise HTTPException(400, "No user message found")
    
    # Generate session ID from conversation
    session_id = str(uuid.uuid4())
    
    try:
        orchestrator = get_orchestrator(session_id)
        
        if request.stream:
            return StreamingResponse(
                stream_response(orchestrator, user_message, session_id),
                media_type="text/event-stream"
            )
        else:
            # Non-streaming response
            result = await orchestrator.search(user_message)
            
            # Format response
            response_text = format_search_result(result)
            
            return ChatCompletionResponse(
                id=f"chatcmpl-{session_id[:8]}",
                created=int(time.time()),
                model="xhs-food-agent",
                choices=[
                    ChatChoice(
                        message=ChatMessage(role="assistant", content=response_text)
                    )
                ]
            )
    except Exception as e:
        logger.exception("Chat completion failed")
        raise HTTPException(500, str(e))


async def stream_response(orchestrator, query: str, session_id: str):
    """Generate SSE stream in OpenAI format."""
    try:
        # Send initial chunk
        yield format_sse_chunk(session_id, "")
        
        # Execute search
        result = await orchestrator.search(query)
        
        # Format and send response
        response_text = format_search_result(result)
        
        # Stream response in chunks
        chunk_size = 20
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i+chunk_size]
            yield format_sse_chunk(session_id, chunk)
        
        # Send done
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.exception("Stream failed")
        yield format_sse_chunk(session_id, f"\n\nError: {str(e)}")
        yield "data: [DONE]\n\n"


def format_sse_chunk(session_id: str, content: str) -> str:
    """Format SSE chunk in OpenAI format."""
    chunk = {
        "id": f"chatcmpl-{session_id[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "xhs-food-agent",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {"role": "assistant"},
                "finish_reason": None
            }
        ]
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def format_search_result(result) -> str:
    """Format search result as readable text."""
    if result.status == "error":
        return f"搜索出错: {result.error_message}"
    
    if result.status == "clarify":
        questions = "\n".join(f"- {q}" for q in result.clarify_questions)
        return f"需要更多信息:\n{questions}"
    
    if not result.recommendations:
        return "抱歉，没有找到符合条件的推荐。请尝试换个关键词或地点。"
    
    lines = [result.summary or "为你找到以下推荐:", ""]
    
    for i, rec in enumerate(result.recommendations[:5], 1):
        rec_dict = rec.to_dict() if hasattr(rec, 'to_dict') else rec
        name = rec_dict.get('name', '未知店铺')
        location = rec_dict.get('location', '')
        features = rec_dict.get('features', [])
        
        lines.append(f"**{i}. {name}**")
        if location:
            lines.append(f"   📍 {location}")
        if features:
            lines.append(f"   ✨ {', '.join(features[:3])}")
        lines.append("")
    
    if result.filtered_count > 0:
        lines.append(f"_(已过滤 {result.filtered_count} 家疑似网红店)_")
    
    return "\n".join(lines)


@router.get("/models")
async def list_models():
    """List available models (OpenAI compatibility)."""
    return {
        "object": "list",
        "data": [
            {
                "id": "xhs-food-agent",
                "object": "model",
                "created": 1704067200,
                "owned_by": "xhs-food-agent",
            }
        ]
    }
