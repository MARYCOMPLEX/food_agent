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

# ========== Loguru 日志配置 ==========
import sys
import logging
from pathlib import Path
from loguru import logger

# 获取项目根目录（src 的上级目录）
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# 移除默认 handler
logger.remove()

# 控制台输出（INFO 级别，简洁摘要）
logger.add(
    sys.stderr,
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True,
)

# 文件输出（DEBUG 级别，按天轮换）
logger.add(
    str(LOGS_DIR / "xhs_food_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="00:00",  # 每天凌晨轮换
    retention="7 days",  # 保留 7 天
    encoding="utf-8",
)


# 拦截标准 logging 模块，路由到 loguru
class InterceptHandler(logging.Handler):
    """拦截标准 logging 日志，转发到 loguru."""
    
    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到调用者
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


# 配置标准 logging 拦截
logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)

# 设置各模块日志级别
for name in ["xhs_food", "api", "uvicorn.access"]:
    logging.getLogger(name).setLevel(logging.DEBUG)

logger.info(f"Loguru configured: console=DEBUG, file={LOGS_DIR / 'xhs_food_*.log'}")
# ========== End Loguru 配置 ==========

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
    
    # Initialize user storage service
    from xhs_food.services.user_storage import get_user_storage_service
    storage = await get_user_storage_service()
    if storage._initialized:
        logger.info("UserStorageService initialized - multi-user support enabled")
    else:
        logger.warning("UserStorageService not available - using anonymous mode")
    
    # Initialize session manager (Redis + PostgreSQL for conversation context)
    from xhs_food.services import get_session_manager
    session_manager = await get_session_manager()
    if session_manager._initialized:
        logger.info("SessionManager initialized - context caching enabled (Redis + PostgreSQL)")
    else:
        logger.warning("SessionManager not fully initialized - using fallback mode")
    
    yield
    
    # Shutdown
    logger.info("XHS Food Agent API shutting down...")
    if storage._initialized:
        await storage.close()
    await session_manager.close()



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
