"""
History Routes - 历史记录 API 路由.

Endpoints:
- GET /v1/history
- POST /v1/history
- DELETE /v1/history/{id}
- DELETE /v1/history (clear all)
"""

import time
import uuid
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Path, Query

from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/history", tags=["history"])


# =============================================================================
# Schemas
# =============================================================================

class HistoryAddRequest(BaseModel):
    """POST /v1/history 请求体."""
    query: str = Field(..., description="搜索查询")
    resultsCount: int = Field(0, description="结果数量")
    location: Optional[str] = Field(None, description="搜索位置")


class HistoryItem(BaseModel):
    """历史记录项."""
    id: str
    query: str
    timestamp: float
    resultsCount: int = 0
    location: Optional[str] = None


# =============================================================================
# In-Memory Storage
# =============================================================================

# Structure: { user_id: [ HistoryItem, ... ] }
_user_history: Dict[str, List[Dict[str, Any]]] = {}


def _get_user_history(user_id: str = "default") -> List[Dict[str, Any]]:
    """Get user's history list."""
    if user_id not in _user_history:
        _user_history[user_id] = []
    return _user_history[user_id]


# =============================================================================
# Routes
# =============================================================================

@router.get("")
async def get_history(
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """Get search history list."""
    history = _get_user_history()
    
    # Sort by timestamp descending (newest first)
    sorted_history = sorted(history, key=lambda x: x.get("timestamp", 0), reverse=True)
    
    # Pagination
    paginated = sorted_history[offset:offset + limit]
    
    return {
        "success": True,
        "data": {
            "items": paginated,
            "total": len(history),
            "limit": limit,
            "offset": offset,
        }
    }


@router.post("")
async def add_history(request: HistoryAddRequest):
    """Add a search to history."""
    history = _get_user_history()
    
    # Create history item
    item = {
        "id": f"hist_{uuid.uuid4().hex[:8]}",
        "query": request.query,
        "timestamp": time.time(),
        "resultsCount": request.resultsCount,
        "location": request.location,
    }
    
    # Add to beginning (newest first in storage)
    history.insert(0, item)
    
    # Keep only last 100 items
    if len(history) > 100:
        history[:] = history[:100]
    
    return {
        "success": True,
        "data": item,
    }


@router.delete("/{historyId}")
async def delete_history_item(historyId: str = Path(..., description="历史记录ID")):
    """Delete a single history item."""
    history = _get_user_history()
    
    for i, item in enumerate(history):
        if item.get("id") == historyId:
            history.pop(i)
            return {
                "success": True,
                "message": "已删除",
            }
    
    return {
        "success": True,
        "message": "记录不存在",
    }


@router.delete("")
async def clear_history():
    """Clear all history."""
    history = _get_user_history()
    history.clear()
    
    return {
        "success": True,
        "message": "已清空所有历史记录",
    }
