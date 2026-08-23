"""Central OpenTelemetry wiring and bounded observability attributes."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import Counter
from temporalio.contrib.opentelemetry import TracingInterceptor

_CORRELATION_KEYS = frozenset(
    {
        "task_id",
        "family_id",
        "bundle_version",
        "profile_version",
        "workflow_id",
        "pack_id",
        "pack_version",
        "provider",
        "model",
        "connector_id",
    }
)
_METRIC_LABEL_KEYS = frozenset(
    {"operation", "outcome", "provider", "model_role", "connector", "task_queue", "status"}
)
_METRIC_LABEL_VALUES = {
    "operation": frozenset(
        {
            "cancel",
            "collect",
            "delete",
            "describe",
            "download",
            "extract",
            "lookup",
            "process",
            "publish",
            "read",
            "refresh",
            "search",
            "signal",
            "start",
            "stat",
            "subscribe",
            "upload",
            "write",
        }
    ),
    "outcome": frozenset(
        {
            "cancelled",
            "dependency_unavailable",
            "error",
            "failure",
            "ok",
            "partial",
            "rate_limited",
            "success",
            "success_empty",
            "timeout",
        }
    ),
    "provider": frozenset({"deepseek", "openai", "siliconflow"}),
    "model_role": frozenset({"analysis", "follow_up", "intent", "orchestration"}),
    "connector": frozenset({"amap", "place", "xhs"}),
    "task_queue": frozenset({"media", "refresh", "research"}),
    "status": frozenset(
        {"completed", "disabled", "failed", "healthy", "ready", "running", "unhealthy"}
    ),
}
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|preference|prompt|query|secret|token|url)",
    re.IGNORECASE,
)
_BOUNDED_VALUE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")
_LOG_CONTEXT_KEYS = frozenset(
    {
        "task_id",
        "family_id",
        "workflow_id",
        "bundle_version",
        "profile_version",
        "operation",
        "outcome",
        "connector",
    }
)


def correlation_attributes(values: Mapping[str, object]) -> dict[str, str | int]:
    """Return an allow-listed, redacted span attribute set."""

    attributes: dict[str, str | int] = {}
    for key, value in values.items():
        if key not in _CORRELATION_KEYS or _SENSITIVE_KEY.search(key):
            continue
        if value is None:
            continue
        if key == "bundle_version" and isinstance(value, int):
            attributes[key] = value
        elif key.endswith("_id") or key == "workflow_id":
            attributes[key] = _opaque_digest(str(value))
        else:
            text = str(value)
            attributes[key] = text[:128] if _BOUNDED_VALUE.fullmatch(text) else "redacted"
    return attributes


def prometheus_labels(values: Mapping[str, object]) -> dict[str, str]:
    """Reject identifiers, free text, and unbounded labels at the adapter boundary."""

    unexpected = set(values) - _METRIC_LABEL_KEYS
    if unexpected:
        raise ValueError(f"unapproved Prometheus labels: {sorted(unexpected)}")
    labels: dict[str, str] = {}
    for key, value in values.items():
        text = str(value)
        if not _BOUNDED_VALUE.fullmatch(text):
            raise ValueError(f"unbounded Prometheus label value for {key}")
        if text not in _METRIC_LABEL_VALUES[key]:
            raise ValueError(f"unregistered Prometheus label value for {key}: {text}")
        labels[key] = text
    return labels


def redact_log_context(values: Mapping[str, object]) -> dict[str, str | int]:
    """Build bounded log context without copying private or free-text data."""

    context: dict[str, str | int] = {}
    for key, value in values.items():
        if key not in _LOG_CONTEXT_KEYS or value is None:
            continue
        if key in {"task_id", "family_id", "workflow_id"}:
            context[key] = _opaque_digest(str(value))
        elif key == "bundle_version":
            if isinstance(value, int) and value >= 0:
                context[key] = value
        elif key in {"operation", "outcome", "connector"}:
            context.update(prometheus_labels({key: value}))
        else:
            text = str(value)
            if _BOUNDED_VALUE.fullmatch(text):
                context[key] = text
    return context


class ObservabilityBootstrap:
    """Composition-owned instrumentation; exporters remain separately replaceable."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled
        self._configured: set[str] = set()

    def instrument_fastapi(self, application: Any) -> None:
        if self._once("fastapi"):
            FastAPIInstrumentor.instrument_app(
                application,
                excluded_urls="health,metrics",
            )

    def instrument_httpx(self) -> None:
        if self._once("httpx"):
            HTTPXClientInstrumentor().instrument()

    def instrument_redis(self) -> None:
        if self._once("redis"):
            RedisInstrumentor().instrument()

    def instrument_sqlalchemy(self, engine: Any) -> None:
        if self._once("sqlalchemy"):
            sync_engine = getattr(engine, "sync_engine", engine)
            SQLAlchemyInstrumentor().instrument(engine=sync_engine)

    def temporal_interceptor(self) -> TracingInterceptor | None:
        if not self._enabled:
            return None
        return TracingInterceptor()

    def instrument_default_clients(self) -> None:
        self.instrument_httpx()
        self.instrument_redis()

    def _once(self, name: str) -> bool:
        if not self._enabled or name in self._configured:
            return False
        self._configured.add(name)
        return True


_evidence_shadow_writes = Counter(
    "xhs_evidence_shadow_writes_total",
    "Evidence shadow writes by bounded connector and outcome",
    ["operation", "outcome", "connector"],
)


class EvidenceShadowTelemetry:
    """Trace shadow lifecycle with redacted IDs and bounded Prometheus labels."""

    def __init__(self, *, enabled: bool = False, tracer: Any | None = None) -> None:
        self._enabled = enabled
        self._tracer = tracer or trace.get_tracer("xhs_food.evidence.shadow")

    @contextmanager
    def span(
        self,
        *,
        task_id: str | None,
        family_id: str | None,
        bundle_version: int | None,
        profile_version: str | None,
    ):
        if not self._enabled:
            yield None
            return
        with self._tracer.start_as_current_span(
            "evidence.shadow",
            attributes=correlation_attributes(
                {
                    "task_id": task_id,
                    "family_id": family_id,
                    "bundle_version": bundle_version,
                    "profile_version": profile_version,
                }
            ),
        ) as active_span:
            yield active_span

    def record(self, *, connector: str, outcome: str) -> None:
        labels = prometheus_labels(
            {"operation": "write", "outcome": outcome, "connector": connector}
        )
        _evidence_shadow_writes.labels(**labels).inc()


def _opaque_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


__all__ = [
    "ObservabilityBootstrap",
    "EvidenceShadowTelemetry",
    "correlation_attributes",
    "redact_log_context",
    "prometheus_labels",
]
