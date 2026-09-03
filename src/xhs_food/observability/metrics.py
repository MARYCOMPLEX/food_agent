"""Prometheus metric definitions for the XHS Food Agent.

Keep this file under 100 lines. Only declare metrics here — recording is
done at call sites. All labels must remain low-cardinality: use route
templates instead of raw paths, model names instead of prompts, and
status buckets instead of per-user identifiers.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


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
]
