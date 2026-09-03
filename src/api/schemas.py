"""
API Schemas - Pydantic 请求/响应模型.

按照 API.md 规范定义。
"""

from typing import Any

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
    """POST /v1/search/start 请求体.

    [DEPRECATED] 建议使用 POST /v1/search 统一接口。
    """

    query: str = Field(..., description="搜索查询")
    location: dict[str, float] | None = Field(None, description="位置坐标 {lat, lng}")


class UnifiedSearchRequest(BaseModel):
    """POST /v1/search 统一请求体.

    智能判断操作类型：
    - 无 sessionId → 新查询（必须有 query）
    - 有 sessionId + query → 追问/继续对话
    - 有 sessionId + 无 query → 恢复历史会话
    """

    query: str | None = Field(None, description="搜索查询（新查询/追问时必填）")
    sessionId: str | None = Field(None, description="会话ID（复用现有会话时填写）")
    location: dict[str, float] | None = Field(None, description="位置坐标 {lat, lng}")
    platforms: list[str] = Field(
        default_factory=lambda: ["xhs_pc"],
        description="本次允许使用的 MCP 平台",
    )
    accountRefs: dict[str, str] = Field(
        default_factory=dict,
        description="按平台选择的账户引用，不包含凭据",
    )
    expectedSessionVersions: dict[str, int] = Field(
        default_factory=dict,
        description="按平台固定的账户会话版本",
    )


class SearchStartResponse(BaseModel):
    """POST /v1/search/start 响应体."""

    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class SearchStatusResponse(BaseModel):
    """GET /v1/search/status/{sessionId} 响应体."""

    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


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
    reason: str | None = None
    img: str | None = None


class BlackListItem(BaseModel):
    """避雷菜品."""

    name: str
    reason: str | None = None


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
    chnName: str | None = None
    distance: str | None = None
    price: str = "$$"
    trustScore: float = 7.0
    oneLiner: str = ""
    isNegativeOneLiner: bool = False
    tags: list[str] = Field(default_factory=list)
    coverImage: str | None = None
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    warning: str | None = None
    mustTry: list[MustTryItem] = Field(default_factory=list)
    blackList: list[BlackListItem] = Field(default_factory=list)
    stats: RestaurantStats | None = None


class SearchResultsResponse(BaseModel):
    """GET /v1/search/results/{sessionId} 响应体."""

    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


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

    name: str | None = None
    email: str | None = None
    location: str | None = None


# =============================================================================
# Help API
# =============================================================================


class FeedbackRequest(BaseModel):
    """POST /v1/help/feedback 请求体."""

    type: str = Field(..., description="类型: bug, feature, other")
    content: str = Field(..., description="反馈内容")
    contact: str | None = None  # 联系方式（邮箱/手机）


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
    data: dict[str, Any] = Field(..., description="事件数据")


# =============================================================================
# Legacy (保留向后兼容)
# =============================================================================


class SearchRequest(BaseModel):
    """搜索请求 (旧版)."""

    query: str = Field(..., description="搜索查询")
    session_id: str | None = Field(None, description="会话ID")
    reset_context: bool = Field(False, description="是否重置对话上下文")


class SearchResponse(BaseModel):
    """搜索响应 (旧版)."""

    status: str = Field("ok", description="状态: ok, clarify, error")
    session_id: str | None = Field(None, description="会话ID")
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    filtered_count: int = Field(0)
    summary: str = Field("")
    clarify_questions: list[str] = Field(default_factory=list)
    error_message: str | None = None
