"""
Help Routes - 帮助 API 路由.

Endpoints:
- GET /v1/help/faqs
- POST /v1/help/feedback
"""

from typing import List
from fastapi import APIRouter

from api.schemas import FeedbackRequest

router = APIRouter(prefix="/v1/help", tags=["help"])

# Mock FAQ data
_faqs = [
    {
        "id": "faq_1",
        "question": "信任分数是如何计算的？",
        "answer": "信任分数基于多个维度：本地人评价权重、评论真实性分析、店铺经营年限、以及交叉验证结果。分数越高，表示该店铺越受本地人认可。",
        "category": "功能",
    },
    {
        "id": "faq_2",
        "question": "如何识别网红店？",
        "answer": "系统会分析评论中的广告词汇、探店博主比例、赠品/优惠提及频率等指标来识别网红店，并自动过滤或标记。",
        "category": "功能",
    },
    {
        "id": "faq_3",
        "question": "推荐结果来自哪里？",
        "answer": "推荐结果来自小红书笔记和评论的分析。系统会提取真实用户的评价，过滤广告内容，优先展示本地人常去的店铺。",
        "category": "数据",
    },
    {
        "id": "faq_4",
        "question": "如何保存喜欢的店铺？",
        "answer": "点击店铺卡片上的心形图标即可收藏。您可以在'我的收藏'页面查看所有已收藏的店铺。",
        "category": "使用",
    },
]


@router.get("/faqs")
async def get_faqs():
    """Get FAQ list."""
    return {
        "success": True,
        "data": _faqs,
    }


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Submit user feedback."""
    # In production, save to database or send to support system
    
    return {
        "success": True,
        "message": "感谢您的反馈！我们会尽快处理。",
    }
