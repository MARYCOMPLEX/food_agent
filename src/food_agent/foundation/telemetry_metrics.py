"""Low-cardinality Prometheus metrics owned by the target Foundation."""

from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge


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

_OUTCOMES = frozenset(
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

    value = outcome if outcome in _OUTCOMES else "failed"
    otel_events_total.labels(outcome=value).inc(max(0, count))


def set_otel_health(healthy: bool) -> None:
    """Expose exporter health independently from business health."""

    otel_exporter_health.set(1 if healthy else 0)


__all__ = [
    "otel_events_total",
    "otel_exporter_health",
    "otel_queue_size",
    "record_otel_event",
    "set_otel_health",
]
