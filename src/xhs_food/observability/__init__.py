"""Observability package: Prometheus metrics + /metrics route."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .metrics import (
    http_request_duration_seconds,
    http_requests_total,
    llm_calls_total,
    llm_duration_seconds,
    llm_tokens_total,
    otel_events_total,
    otel_exporter_health,
    otel_queue_size,
    record_otel_event,
    search_duration_seconds,
    search_finished_total,
    search_started_total,
    set_otel_health,
    sse_active_connections,
    xhs_notes_fetched_total,
)

metrics_router = APIRouter()


@metrics_router.get("/metrics")
def metrics_endpoint() -> Response:
    """Expose Prometheus metrics in the text exposition format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = [
    "metrics_router",
    "http_request_duration_seconds",
    "http_requests_total",
    "llm_calls_total",
    "llm_duration_seconds",
    "llm_tokens_total",
    "otel_events_total",
    "otel_exporter_health",
    "otel_queue_size",
    "record_otel_event",
    "search_duration_seconds",
    "search_finished_total",
    "search_started_total",
    "sse_active_connections",
    "xhs_notes_fetched_total",
    "set_otel_health",
]
