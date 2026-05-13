"""
Search Routes - 搜索 API 路由 (流式 SSE 输出).

Endpoints:
- POST /v1/search                   (推荐) 统一接口：新查询/追问/恢复
- GET  /v1/search/stream/{sessionId} (SSE 实时推送)

Task Endpoints:
- GET  /v1/search/status/{sessionId}
- GET  /v1/search/results/{sessionId}

使用 SessionManager 进行对话上下文的 Redis 缓存 + PostgreSQL 持久化。
"""

from fastapi import APIRouter

from .routes import router as main_router
from .tasks import router as tasks_router

router = APIRouter(prefix="/v1/search", tags=["search"])
router.include_router(main_router)
router.include_router(tasks_router)
