"""XHS Food Agent — FastAPI application entry point."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

load_dotenv()

from xhs_food.config import settings  # noqa: E402 — must come after load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_LOGS_DIR.mkdir(exist_ok=True)


def _configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        str(_LOGS_DIR / "xhs_food_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        ),
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
    )

    class _InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.DEBUG, force=True)
    for name in ("xhs_food", "api", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.DEBUG)


_configure_logging()


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Routers (post-logging so module-level loguru calls are formatted)
# ---------------------------------------------------------------------------

from api.favorites import router as favorites_router  # noqa: E402
from api.help import router as help_router  # noqa: E402
from api.history import router as history_router  # noqa: E402
from api.platform import router as platform_router  # noqa: E402
from api.search import router as search_router  # noqa: E402
from api.user import router as user_router  # noqa: E402
from xhs_food.observability import (  # noqa: E402
    http_request_duration_seconds,
    http_requests_total,
    metrics_router,
)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("XHS Food Agent API starting…")

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — LLM calls will fail")
    from xhs_food.composition import (
        build_legacy_composition_root,
        build_reliable_runtime_bindings,
    )
    from xhs_food.events.bus import get_event_bus, shutdown_event_bus
    from xhs_food.foundation import TargetSettings
    from xhs_food.services import get_session_manager
    from xhs_food.services.user_storage import get_user_storage_service

    target_settings = TargetSettings()
    reliable_runtime = None
    if target_settings.reliable_task_lifecycle:
        reliable_runtime = await build_reliable_runtime_bindings(
            target_settings=target_settings,
        )
        try:
            composition_root = build_legacy_composition_root(
                reliable_policy=reliable_runtime.policy,
                reliable_task_store=reliable_runtime.task_store,
                reliable_projection_store=reliable_runtime.projection_store,
                reliable_event_bus=reliable_runtime.event_bus,
                reliable_task_lifecycle=True,
                target_settings=target_settings,
            )
        except BaseException:
            await reliable_runtime.aclose()
            raise
    else:
        composition_root = build_legacy_composition_root(target_settings=target_settings)
    application.state.composition_root = composition_root
    from xhs_food.composition.account_services import (
        AccountServiceRegistry,
        RemoteAccountServiceFacade,
    )

    application.state.account_service_registry = None
    application.state.agent_tool_catalog = None
    application.state.managed_search_tool = None
    if "account_services" in composition_root.logical_bindings:
        resolved_registry = await composition_root.resolve_logical("account_services")
        if not isinstance(resolved_registry, AccountServiceRegistry):
            raise RuntimeError("account_services binding must resolve to AccountServiceRegistry")
        application.state.account_service_registry = resolved_registry
        try:
            await resolved_registry.refresh()
        except Exception:
            logger.warning("Remote account-service capability refresh failed")
    if "agent_tool_catalog" in composition_root.logical_bindings:
        application.state.agent_tool_catalog = await composition_root.resolve_logical(
            "agent_tool_catalog"
        )
    if "managed_search_tool" in composition_root.logical_bindings:
        from api.search.state import configure_search_tool
        from xhs_food.composition.managed_search import bind_managed_search_context
        from xhs_food.contracts import SearchToolPort

        managed_search_tool = await composition_root.resolve_logical("managed_search_tool")
        if not isinstance(managed_search_tool, SearchToolPort):
            raise RuntimeError("managed_search_tool binding must implement SearchToolPort")
        application.state.managed_search_tool = managed_search_tool

        configure_search_tool(
            managed_search_tool,
            context_binder=bind_managed_search_context,
        )
    application.state.account_service_control_plane = None
    if isinstance(application.state.account_service_registry, AccountServiceRegistry):
        application.state.account_service_control_plane = RemoteAccountServiceFacade(
            application.state.account_service_registry
        )
    application.state.reliable_runtime = reliable_runtime
    application.state.reliable_task_lifecycle = (
        "reliable_task_lifecycle" in composition_root.logical_bindings
    )
    application.state.research_task = await composition_root.resolve_logical("modular_core")
    if application.state.reliable_task_lifecycle:
        application.state.reliable_projection_store = await composition_root.resolve_logical(
            "reliable_projection_store"
        )
        if "reliable_event_bus" in composition_root.logical_bindings:
            application.state.reliable_event_bus = await composition_root.resolve_logical(
                "reliable_event_bus"
            )

    storage = await get_user_storage_service()
    if storage._initialized:
        logger.info("UserStorageService ready (multi-user)")
    else:
        logger.warning("UserStorageService unavailable — anonymous mode")

    session_manager = await get_session_manager()
    if session_manager._initialized:
        logger.info("SessionManager ready (Redis + PostgreSQL)")
    else:
        logger.warning("SessionManager degraded")

    if reliable_runtime is None:
        bus = await get_event_bus()
        logger.info(f"EventBus backend: {type(bus).__name__}")
    else:
        await reliable_runtime.event_bus.ensure_available()
        logger.info("EventBus backend: RedisEventBusAdapter (reliable runtime)")

    try:
        yield
    finally:
        logger.info("XHS Food Agent API shutting down…")
        if storage._initialized:
            await storage.close()
        await session_manager.close()
        await shutdown_event_bus()
        await composition_root.close()
        if reliable_runtime is not None:
            await reliable_runtime.aclose()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


app = FastAPI(
    title="XHS Food Agent API",
    description="小红书美食智能推荐 Agent — Production API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"success": False, "error": "rate_limited", "detail": str(exc)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(favorites_router)
app.include_router(user_router)
app.include_router(help_router)
app.include_router(history_router)
app.include_router(platform_router)
app.include_router(metrics_router)


# ---------------------------------------------------------------------------
# Prometheus HTTP metrics middleware
# ---------------------------------------------------------------------------


def _route_template(request: Request) -> str | None:
    """Return the matched route template (low cardinality) if available."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return None


@app.middleware("http")
async def _prometheus_http_metrics(request: Request, call_next) -> Response:
    """Time every request, record counters/histograms keyed by route template.

    We deliberately skip /metrics itself to avoid self-monitoring noise, and
    use the matched route template (not request.url.path) so dynamic ids
    (e.g. /users/{user_id}) collapse into a single label.
    """
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        # Record as 500 then re-raise so FastAPI's exception handlers run.
        elapsed = time.perf_counter() - start
        template = _route_template(request) or "__unmatched__"
        if template != "/metrics":
            http_requests_total.labels(method=request.method, path=template, status="500").inc()
            http_request_duration_seconds.labels(method=request.method, path=template).observe(
                elapsed
            )
        raise

    elapsed = time.perf_counter() - start
    template = _route_template(request) or "__unmatched__"
    if template != "/metrics":
        http_requests_total.labels(
            method=request.method, path=template, status=str(status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=template).observe(elapsed)
    return response


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "xhs-food-agent", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
