"""XHS Food Agent — FastAPI application entry point."""
from __future__ import annotations

import inspect
import logging
import sys
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
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


async def _load_platform_runtime(
    application: FastAPI,
    target_settings: Any,
) -> tuple[Any | None, Any | None, dict[str, Any]]:
    """Resolve an explicitly injected platform bundle for the lifespan.

    The default path returns an empty kwargs mapping, preserving the legacy
    composition-root call exactly.  A deployment may set
    ``app.state.platform_runtime_factory`` before entering lifespan; the
    factory may be synchronous or asynchronous and may return a mapping or an
    object with equivalent attributes.  No provider, key, cookie, or in-memory
    authority is constructed here.
    """

    factory = getattr(application.state, "platform_runtime_factory", None)
    if not callable(factory):
        return None, None, {}

    runtime = await _invoke_platform_factory(factory, target_settings)
    cleanup = _bundle_get(runtime, "cleanup", "close_runtime", "aclose")
    if cleanup is None:
        # A returned runtime object may own its resources.  Keep the cleanup
        # callable separate so the bundle itself can remain in app.state for
        # diagnostics without being closed twice.
        candidate = getattr(runtime, "aclose", None) or getattr(runtime, "close", None)
        cleanup = candidate if callable(candidate) else None

    bundle = _bundle_get(runtime, "assembly", "platform_assembly") or runtime
    authority = _bundle_get(
        bundle,
        "platform_account_authority",
        "account_authority",
        "platform_account_repository",
        "account_repository",
        "platform_authority",
        "authority",
    )
    session_codec = _bundle_get(
        bundle,
        "platform_session_codec",
        "session_codec",
        "platform_session_envelope_codec",
        "session_envelope_codec",
    )
    connector_factories = _bundle_get(
        bundle,
        "platform_connector_factories",
        "connector_factories",
        "platform_factories",
        "factories",
    )
    provider_factories = _bundle_get(
        bundle,
        "platform_provider_factories",
        "provider_factories",
    )
    source_control = _bundle_get(bundle, "platform_source_control", "source_control")
    health = _bundle_get(bundle, "platform_health", "health")
    capability_registry = _bundle_get(
        bundle,
        "platform_capability_registry",
        "capability_registry",
    )
    login_service = _bundle_get(bundle, "platform_login_service", "login_service")
    workflow = _bundle_get(bundle, "platform_workflow", "workflow", "workflow_port")
    coordinator = _bundle_get(
        bundle,
        "platform_login_coordinator",
        "login_coordinator",
        "coordinator",
    )
    workflow_builder = _bundle_get(
        bundle,
        "platform_workflow_start_builder",
        "workflow_start_builder",
        "builder",
    )
    object_store = _bundle_get(bundle, "platform_object_store", "object_store")
    flow_store = _bundle_get(bundle, "platform_login_flows", "flows", "flow_store")
    execution_policy = _bundle_get(bundle, "platform_execution_policy", "execution_policy")
    queue = _bundle_get(bundle, "platform_login_queue", "login_queue", "queue")
    if queue is None:
        queue = getattr(target_settings, "temporal_account_auth_queue", None) or "account-auth"
    flow_ttl = _bundle_get(bundle, "platform_flow_ttl_seconds", "flow_ttl_seconds")

    # Build the project-owned use case only when an explicitly injected
    # authority and execution boundary are available.  Missing pieces remain
    # disabled and are surfaced by the control-plane readiness route.
    if login_service is None and authority is not None and (workflow is not None or coordinator is not None):
        from xhs_food.experience import PlatformLoginService

        if workflow is not None and workflow_builder is None:
            # The Temporal command builder is imported lazily only for an
            # explicitly enabled platform runtime; the default API import path
            # remains free of Temporal/provider SDK side effects.
            from xhs_food.foundation import build_account_auth_workflow_start

            workflow_builder = build_account_auth_workflow_start
        login_service = PlatformLoginService(
            accounts=authority,
            flows=flow_store,
            workflow=workflow,
            coordinator=coordinator,
            workflow_start_builder=workflow_builder,
            object_store=object_store,
            queue=str(queue),
            flow_ttl_seconds=int(flow_ttl or 300),
            execution_policy=execution_policy,
        )

    platform_requested = bool(
        getattr(target_settings, "platform_connectors_enabled", False)
        or getattr(target_settings, "platform_login_enabled", False)
        or authority is not None
        or session_codec is not None
        or connector_factories
        or provider_factories
        or login_service is not None
        or object_store is not None
    )
    kwargs: dict[str, Any] = {}
    if platform_requested:
        kwargs["target_settings"] = target_settings
        values = {
            "platform_account_authority": authority,
            "platform_session_codec": session_codec,
            "platform_connector_factories": connector_factories,
            "platform_provider_factories": provider_factories,
            "platform_source_control": source_control,
            "platform_health": health,
            "platform_capability_registry": capability_registry,
            "platform_login_service": login_service,
            "platform_object_store": object_store,
            "platform_provenance_ref": _bundle_get(bundle, "platform_provenance_ref", "provenance_ref"),
            "platform_license_approval_ref": _bundle_get(bundle, "platform_license_approval_ref", "license_approval_ref"),
            "platform_dependency_digests": _bundle_get(bundle, "platform_dependency_digests", "dependency_digests"),
        }
        kwargs.update({name: value for name, value in values.items() if value is not None})

    return runtime, cleanup, kwargs


async def _invoke_platform_factory(factory: Any, target_settings: Any) -> Any:
    """Call a sync/async factory without masking errors raised by its body."""

    keyword_target: str | None = None
    try:
        signature = inspect.signature(factory)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        keyword_target = next(
            (
                parameter.name
                for parameter in signature.parameters.values()
                if parameter.kind is inspect.Parameter.KEYWORD_ONLY
                and parameter.name in {"target_settings", "settings", "config"}
            ),
            None,
        )
        accepts_target = bool(positional) or any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
    except (TypeError, ValueError):
        accepts_target = True
    if accepts_target:
        value = factory(target_settings)
    elif keyword_target is not None:
        value = factory(**{keyword_target: target_settings})
    else:
        value = factory()
    if inspect.isawaitable(value):
        return await value
    return value


def _bundle_get(bundle: Any, *names: str) -> Any:
    if bundle is None:
        return None
    if isinstance(bundle, Mapping):
        for name in names:
            if name in bundle:
                return bundle[name]
        return None
    for name in names:
        value = getattr(bundle, name, None)
        if value is not None:
            return value
    return None


async def _close_platform_runtime(cleanup: Any) -> None:
    """Close a factory-owned runtime/cleanup hook once, swallowing no errors."""

    value = cleanup() if callable(cleanup) else cleanup
    if inspect.isawaitable(value):
        await value


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("XHS Food Agent API starting…")

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — LLM calls will fail")
    if not settings.xhs_cookies and not settings.xhs_profile_dir:
        logger.warning("XHS auth not configured — spider requests will fail")

    from xhs_food.composition import (
        build_legacy_composition_root,
        build_reliable_runtime_bindings,
    )
    from xhs_food.events.bus import get_event_bus, shutdown_event_bus
    from xhs_food.foundation import TargetSettings
    from xhs_food.services import get_session_manager
    from xhs_food.services.user_storage import get_user_storage_service

    target_settings = TargetSettings()
    platform_runtime, platform_cleanup, platform_kwargs = await _load_platform_runtime(
        application,
        target_settings,
    )
    reliable_runtime = None
    if target_settings.reliable_task_lifecycle:
        try:
            reliable_runtime = await build_reliable_runtime_bindings(
                target_settings=target_settings,
            )
        except BaseException:
            if platform_cleanup is not None:
                await _close_platform_runtime(platform_cleanup)
            raise
        try:
            composition_root = build_legacy_composition_root(
                reliable_policy=reliable_runtime.policy,
                reliable_task_store=reliable_runtime.task_store,
                reliable_projection_store=reliable_runtime.projection_store,
                reliable_event_bus=reliable_runtime.event_bus,
                reliable_task_lifecycle=True,
                **platform_kwargs,
            )
        except BaseException:
            await reliable_runtime.aclose()
            if platform_cleanup is not None:
                await _close_platform_runtime(platform_cleanup)
            raise
    else:
        try:
            composition_root = build_legacy_composition_root(**platform_kwargs)
        except BaseException:
            if platform_cleanup is not None:
                await _close_platform_runtime(platform_cleanup)
            raise
    application.state.composition_root = composition_root
    application.state.platform_runtime = platform_runtime
    application.state.platform_login_service = platform_kwargs.get("platform_login_service")
    application.state.platform_readiness = getattr(composition_root, "platform_readiness", None)
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
        if platform_cleanup is not None:
            await _close_platform_runtime(platform_cleanup)


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
            http_requests_total.labels(
                method=request.method, path=template, status="500"
            ).inc()
            http_request_duration_seconds.labels(
                method=request.method, path=template
            ).observe(elapsed)
        raise

    elapsed = time.perf_counter() - start
    template = _route_template(request) or "__unmatched__"
    if template != "/metrics":
        http_requests_total.labels(
            method=request.method, path=template, status=str(status_code)
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method, path=template
        ).observe(elapsed)
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
