"""
XHS Food Agent API - FastAPI 服务入口.

提供:
- /health - 健康检查
- /api/v1/search - 普通搜索
- /api/v1/search/stream - SSE流式搜索
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
from api.routes import router


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

# Include routes
app.include_router(router)


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
