"""Prometheus metric definitions for the XHS Food Agent.

Keep this file under 100 lines. Only declare metrics here — recording is
done at call sites. All labels must remain low-cardinality: use route
templates instead of raw paths, model names instead of prompts, and
status buckets instead of per-user identifiers.
"""

from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge, Histogram


def _registered_counter(name: str, documentation: str, labels: list[str]) -> Counter:
    cache_name = f"xhs_food_{name}"
    existing = getattr(REGISTRY, cache_name, None)
    if isinstance(existing, Counter):
        return existing
    metric = Counter(name, documentation, labels)
    setattr(REGISTRY, cache_name, metric)
    return metric


def _registered_gauge(name: str, documentation: str) -> Gauge:
    cache_name = f"xhs_food_{name}"
    existing = getattr(REGISTRY, cache_name, None)
    if isinstance(existing, Gauge):
        return existing
    metric = Gauge(name, documentation)
    setattr(REGISTRY, cache_name, metric)
    return metric


# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------

llm_calls_total: Counter = Counter(
    "xhs_llm_calls_total",
    "Total LLM calls",
    ["model", "outcome"],  # outcome: "ok" / "error"
)

llm_duration_seconds: Histogram = Histogram(
    "xhs_llm_duration_seconds",
    "LLM call latency",
    ["model"],
)

llm_tokens_total: Counter = Counter(
    "xhs_llm_tokens_total",
    "Cumulative tokens (best-effort, uses len(content) when API doesn't return)",
    ["model", "kind"],  # kind: "prompt" / "completion"
)


# ---------------------------------------------------------------------------
# Search pipeline metrics
# ---------------------------------------------------------------------------

search_started_total: Counter = Counter(
    "food_agent_search_started_total",
    "Search sessions started",
)

search_finished_total: Counter = Counter(
    "food_agent_search_finished_total",
    "Search sessions finished",
    ["status"],  # ok / error
)

search_duration_seconds: Histogram = Histogram(
    "food_agent_search_duration_seconds",
    "End-to-end search duration",
)

xhs_notes_fetched_total: Counter = Counter(
    "xhs_notes_fetched_total",
    "Notes returned by the managed XHS MCP source",
    ["keyword_phase"],  # search / analyzed
)


# ---------------------------------------------------------------------------
# SSE / transport metrics
# ---------------------------------------------------------------------------

sse_active_connections: Gauge = Gauge(
    "xhs_sse_active_connections",
    "Active SSE subscribers (in-memory backend only)",
)


# ---------------------------------------------------------------------------
# HTTP metrics
# ---------------------------------------------------------------------------

http_requests_total: Counter = Counter(
    "xhs_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds: Histogram = Histogram(
    "xhs_http_request_duration_seconds",
    "HTTP latency",
    ["method", "path"],
)


# ---------------------------------------------------------------------------
# Non-authoritative OTel/Phoenix exporter metrics
# ---------------------------------------------------------------------------

otel_events_total: Counter = _registered_counter(
    "xhs_otel_events_total",
    "Observation exporter events by bounded outcome",
    ["outcome"],
)
otel_queue_size: Gauge = _registered_gauge(
    "xhs_otel_queue_size",
    "Current queued observations",
)
otel_exporter_health: Gauge = _registered_gauge(
    "xhs_otel_exporter_health",
    "Observation exporter health (1 ready, 0 unavailable)",
)

_OTEL_OUTCOMES = frozenset(
    {
        "accepted",
        "exported",
        "failed",
        "malformed",
        "sampled",
        "saturated",
        "timed_out",
        "flushed",
        "skipped",
    }
)


def record_otel_event(outcome: str, *, count: int = 1) -> None:
    """Record a finite-vocabulary exporter event without affecting callers."""

    value = outcome if outcome in _OTEL_OUTCOMES else "failed"
    otel_events_total.labels(outcome=value).inc(max(0, count))


def set_otel_health(healthy: bool) -> None:
    """Expose exporter health independently from business health."""

    otel_exporter_health.set(1 if healthy else 0)

__all__ = [
    "llm_calls_total",
    "llm_duration_seconds",
    "llm_tokens_total",
    "search_started_total",
    "search_finished_total",
    "search_duration_seconds",
    "xhs_notes_fetched_total",
    "sse_active_connections",
    "http_requests_total",
    "http_request_duration_seconds",
    "otel_events_total",
    "otel_exporter_health",
    "otel_queue_size",
    "record_otel_event",
    "set_otel_health",
]
