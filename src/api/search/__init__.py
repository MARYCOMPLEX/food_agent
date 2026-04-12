"""
Search Routes - 搜索 API 路由 (流式 SSE 输出).

Endpoints:
- POST /v1/search                   (推荐) 统一接口：新查询/追问/恢复
- GET  /v1/search/stream/{sessionId} (SSE 实时推送)

Legacy Endpoints (保留兼容):
- POST /v1/search/start             → 用 POST /v1/search { query }
- POST /v1/search/refine            → 用 POST /v1/search { sessionId, query }
- GET  /v1/search/recover/{id}      → 用 POST /v1/search { sessionId }
- GET  /v1/search/status/{sessionId}
- GET  /v1/search/results/{sessionId}

使用 SessionManager 进行对话上下文的 Redis 缓存 + PostgreSQL 持久化。
"""

from fastapi import APIRouter

from .routes import router as main_router
from .legacy import router as legacy_router
from .tasks import router as tasks_router

router = APIRouter(prefix="/v1/search", tags=["search"])
router.include_router(main_router)
router.include_router(legacy_router)
router.include_router(tasks_router)
