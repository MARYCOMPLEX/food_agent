"""
API Schemas - Pydantic 请求/响应模型.

按照 API.md 规范定义。
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Loading Steps
# =============================================================================

class LoadingStep(BaseModel):
    """加载步骤."""
    id: str = Field(..., description="步骤ID")
    label: str = Field(..., description="步骤描述")
    status: str = Field("pending", description="状态: pending, loading, done, error")


# =============================================================================
# Search API
# =============================================================================

class SearchStartRequest(BaseModel):
    """POST /v1/search/start 请求体."""
    query: str = Field(..., description="搜索查询")
    location: Optional[Dict[str, float]] = Field(None, description="位置坐标 {lat, lng}")


class SearchStartResponse(BaseModel):
    """POST /v1/search/start 响应体."""
    success: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


class SearchStatusResponse(BaseModel):
    """GET /v1/search/status/{sessionId} 响应体."""
    success: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


class RefineRequest(BaseModel):
    """POST /v1/search/refine 请求体."""
    sessionId: str = Field(..., description="会话ID")
    query: str = Field(..., description="追问查询")


# =============================================================================
# Restaurant (完整格式)
# =============================================================================

class MustTryItem(BaseModel):
    """必点菜品."""
    name: str
    reason: Optional[str] = None
    img: Optional[str] = None


class BlackListItem(BaseModel):
    """避雷菜品."""
    name: str
    reason: Optional[str] = None


class RestaurantStats(BaseModel):
    """店铺评分."""
    flavor: str = "B"
    cost: str = "$$"
    wait: str = "15min"
    env: str = "Normal"


class Restaurant(BaseModel):
    """店铺详情 (API.md 格式)."""
    id: str  # Hash ID (32 chars)
    name: str
    chnName: Optional[str] = None
    distance: Optional[str] = None
    price: str = "$$"
    trustScore: float = 7.0
    oneLiner: str = ""
    isNegativeOneLiner: bool = False
    tags: List[str] = Field(default_factory=list)
    coverImage: Optional[str] = None
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    warning: Optional[str] = None
    mustTry: List[MustTryItem] = Field(default_factory=list)
    blackList: List[BlackListItem] = Field(default_factory=list)
    stats: Optional[RestaurantStats] = None


class SearchResultsResponse(BaseModel):
    """GET /v1/search/results/{sessionId} 响应体."""
    success: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Favorites API
# =============================================================================

class FavoriteAddRequest(BaseModel):
    """POST /v1/favorites 请求体."""
    restaurantId: str = Field(..., description="餐厅Hash ID (32字符)")


class FavoriteResponse(BaseModel):
    """收藏操作响应."""
    success: bool = True
    message: str = ""
    isFavorite: bool = False


# =============================================================================
# User API
# =============================================================================

class UserProfileUpdateRequest(BaseModel):
    """PUT /v1/user/profile 请求体."""
    name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None


# =============================================================================
# Help API
# =============================================================================

class FeedbackRequest(BaseModel):
    """POST /v1/help/feedback 请求体."""
    type: str = Field(..., description="类型: bug, feature, other")
    content: str = Field(..., description="反馈内容")
    contact: Optional[str] = None  # 联系方式（邮箱/手机）


# =============================================================================
# Error Response
# =============================================================================

class ErrorResponse(BaseModel):
    """错误响应."""
    success: bool = False
    error: str = ""
    message: str = ""


# =============================================================================
# SSE Event (保留兼容)
# =============================================================================

class StreamEvent(BaseModel):
    """SSE事件."""
    event: str = Field(..., description="事件类型: status, progress, result, error, done")
    data: Dict[str, Any] = Field(..., description="事件数据")


# =============================================================================
# Legacy (保留向后兼容)
# =============================================================================

class SearchRequest(BaseModel):
    """搜索请求 (旧版)."""
    query: str = Field(..., description="搜索查询")
    session_id: Optional[str] = Field(None, description="会话ID")
    reset_context: bool = Field(False, description="是否重置对话上下文")


class SearchResponse(BaseModel):
    """搜索响应 (旧版)."""
    status: str = Field("ok", description="状态: ok, clarify, error")
    session_id: Optional[str] = Field(None, description="会话ID")
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    filtered_count: int = Field(0)
    summary: str = Field("")
    clarify_questions: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
