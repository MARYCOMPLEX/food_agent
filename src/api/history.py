"""
History Routes - 历史记录 API 路由.

Endpoints:
- GET /v1/history
- POST /v1/history
- DELETE /v1/history/{id}
- DELETE /v1/history (clear all)
"""

from typing import Optional

from fastapi import APIRouter, Path, Query, Depends
from pydantic import BaseModel, Field

from api.deps import get_current_user_id, get_storage
from xhs_food.services.user_storage import UserStorageService

router = APIRouter(prefix="/v1/history", tags=["history"])


# =============================================================================
# Schemas
# =============================================================================

class HistoryAddRequest(BaseModel):
    """POST /v1/history 请求体."""
    query: str = Field(..., description="搜索查询")
    resultsCount: int = Field(0, description="结果数量")
    location: Optional[str] = Field(None, description="搜索位置")


# =============================================================================
# Routes
# =============================================================================

@router.get("")
async def get_history(
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Get search history list."""
    items = await storage.get_history(user_id, limit=limit, offset=offset)
    total = await storage.get_history_count(user_id)
    
    return {
        "success": True,
        "data": {
            "items": [item.to_dict() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    }


@router.post("")
async def add_history(
    request: HistoryAddRequest,
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Add a search to history."""
    item = await storage.add_history(
        user_id=user_id,
        query=request.query,
        results_count=request.resultsCount,
        location=request.location,
    )
    
    return {
        "success": True,
        "data": item.to_dict() if item else None,
    }


@router.delete("/{historyId}")
async def delete_history_item(
    historyId: str = Path(..., description="历史记录ID"),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Delete a single history item."""
    # Parse ID (format: hist_123 -> 123)
    try:
        int_id = int(historyId.replace("hist_", ""))
    except ValueError:
        return {
            "success": False,
            "message": "无效的历史记录ID",
        }
    
    await storage.delete_history(user_id, int_id)
    
    return {
        "success": True,
        "message": "已删除",
    }


@router.delete("")
async def clear_history(
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Clear all history."""
    count = await storage.clear_history(user_id)
    
    return {
        "success": True,
        "message": f"已清空 {count} 条历史记录",
    }
