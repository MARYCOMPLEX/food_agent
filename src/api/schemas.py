"""
API Schemas - Pydantic 请求/响应模型.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """搜索请求."""
    query: str = Field(..., description="搜索查询，如 '成都本地人常去的老店'")
    reset_context: bool = Field(False, description="是否重置对话上下文")


class RecommendationItem(BaseModel):
    """推荐店铺."""
    name: str = Field(..., description="店铺名称")
    location: Optional[str] = Field(None, description="位置描述")
    features: List[str] = Field(default_factory=list, description="店铺特点")
    source_notes: List[str] = Field(default_factory=list, description="来源笔记ID")
    confidence: float = Field(0.5, description="推荐置信度 0-1")
    is_recommended: bool = Field(True, description="是否推荐")
    filter_reason: Optional[str] = Field(None, description="被过滤的原因")
    wanghong_analysis: Optional[Dict[str, Any]] = Field(None, description="网红店分析")


class SearchResponse(BaseModel):
    """搜索响应."""
    status: str = Field("ok", description="状态: ok, clarify, error")
    recommendations: List[Dict[str, Any]] = Field(default_factory=list, description="推荐列表")
    filtered_count: int = Field(0, description="被过滤的店铺数")
    summary: str = Field("", description="结果摘要")
    clarify_questions: List[str] = Field(default_factory=list, description="需要澄清的问题")
    error_message: Optional[str] = Field(None, description="错误信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "recommendations": [
                    {
                        "name": "老字号米粉店",
                        "location": "XX路XX号",
                        "features": ["本地人推荐", "开了20年"],
                        "confidence": 0.85,
                    }
                ],
                "filtered_count": 2,
                "summary": "在成都找到 5 家推荐店铺，过滤了 2 家网红店",
            }
        }


class StreamEvent(BaseModel):
    """SSE事件."""
    event: str = Field(..., description="事件类型: status, progress, result, error, done")
    data: Dict[str, Any] = Field(..., description="事件数据")
