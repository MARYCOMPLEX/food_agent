"""
XHS Food Agent API - FastAPI 服务入口.

Endpoints (API.md):
- /v1/search/* - 搜索 API (含 SSE)
- /v1/favorites/* - 收藏 API
- /v1/user/* - 用户 API
- /v1/help/* - 帮助 API

Legacy:
- /api/v1/* - 旧版 API (兼容)
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# Import after loading env
from api.routes import router as legacy_router
from api.openai_compat import router as openai_router
from api.search import router as search_router
from api.favorites import router as favorites_router
from api.user import router as user_router
from api.help import router as help_router
from api.history import router as history_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    from loguru import logger
    logger.info("XHS Food Agent API starting up...")
    
    # Verify environment
    if not os.getenv("XHS_COOKIES"):
        logger.warning("XHS_COOKIES not set - XHS searches will fail")
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set - LLM calls will fail")
    
    yield
    
    # Shutdown
    logger.info("XHS Food Agent API shutting down...")


app = FastAPI(
    title="XHS Food Agent API",
    description="小红书美食智能推荐Agent API服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# New API routes (API.md spec)
app.include_router(search_router)
app.include_router(favorites_router)
app.include_router(user_router)
app.include_router(help_router)
app.include_router(history_router)


# Legacy routes (backward compatibility)
app.include_router(legacy_router)
app.include_router(openai_router)


@app.get("/health")
async def health_check():
    """健康检查端点."""
    return {
        "status": "ok",
        "service": "xhs-food-agent",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
