"""Bounded, redacted OpenTelemetry delivery owned by Foundation.

Business code records project-owned :class:`ObservationRecord` values. The
exporter drains those values outside the request path and translates them to
OTLP only at the Foundation boundary. Phoenix and any future backend therefore
remain replaceable without changing domain or API contracts.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any, cast
from urllib.parse import urlparse

from xhs_food.contracts import (
    ContractPayload,
    ObservationBackend,
    ObservationKind,
    ObservationOutcome,
    ObservationPort,
    ObservationRecord,
)
from xhs_food.foundation.telemetry_metrics import (
    otel_queue_size,
    record_otel_event,
    set_otel_health,
)

try:  # The exporter is pinned in the runtime dependency set but optional locally.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except ImportError:  # pragma: no cover - exercised by minimal local installs.
    OTLPSpanExporter = None  # type: ignore[assignment,misc]

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import Event as OtelEvent
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
    from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceState
except ImportError:  # pragma: no cover - OTel is a locked runtime dependency.
    otel_trace = None  # type: ignore[assignment]
    Resource = OtelEvent = ReadableSpan = TracerProvider = BatchSpanProcessor = SpanExportResult = None  # type: ignore[assignment,misc]
    SpanContext = SpanKind = Status = StatusCode = TraceState = None  # type: ignore[assignment,misc]


OBSERVATION_EXPORTER_VERSION = "otel-exporter/v1"
_MAX_STRING = 128
_MAX_ITEMS = 64
_SAFE_KEYS = frozenset(
    {
        "name",
        "kind",
        "operation",
        "outcome",
        "status",
        "status_code",
        "code",
        "error_class",
        "classification",
        "attempt",
        "retry_count",
        "duration_ms",
        "item_count",
        "source_count",
        "sampled",
        "served",
        "service.name",
        "telemetry.sdk.name",
        "telemetry.sdk.version",
        "scope",
        "scope.name",
        "instrumentation_scope",
        "instrumentation_scope.name",
        "schema_version",
        "redaction_version",
        "boundary",
        "mode",
        "match_layer",
        "freshness_state",
        "coverage_state",
        "private_record_count",
        "dropped_count",
        "queue_size",
        "batch_size",
        "drop_policy",
        "flush_state",
        "exporter_state",
        "evaluator_version",
        "dataset_version",
        "case_count",
        "result_digest",
        "dataset_digest",
        "gate_status",
        "privacy_status",
        "source",
        "trace_state",
    }
)
_STRUCTURAL_KEYS = frozenset(
    {
        "attributes",
        "resource",
        "events",
        "links",
        "status",
        "scope",
        "scopeSpans",
        "resourceSpans",
        "spans",
        "instrumentationScope",
        "instrumentation_scope",
    }
)
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|prompt|query|secret|token|signed.?url|"
    r"request.?body|response.?body|mcp|qr|preference|memory|session|account|source.?url|"
    r"headers?|\burl\b|exception\.(?:message|stacktrace)|(?:^|[._-])body(?:$|[._-]))",
    re.IGNORECASE,
)
_ID_KEY = re.compile(
    r"(?:^|[._-])(?:trace|span|parent.?span|task|workflow|run|family|bundle|profile|pack|"
    r"connector)[._-]?(?:id|key)?$",
    re.IGNORECASE,
)
_TOKEN_VALUE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")


def opaque_digest(value: str) -> str:
    """Return a short stable opaque identifier suitable for correlation."""

    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


def _safe_scalar(value: object, *, key: str | None = None) -> object | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if -(2**63) <= value < 2**63 else None
    if isinstance(value, float):
        return value if value == value and abs(value) < 1e15 else None
    if not isinstance(value, str):
        return None
    if len(value) > _MAX_STRING or any(ord(character) < 32 for character in value):
        return None
    lowered = value.casefold()
    if any(
        marker in lowered
        for marker in (
            "bearer ",
            "authorization:",
            "cookie:",
            "?token=",
            "http://",
            "https://",
            "data:",
        )
    ):
        return None
    normalized_key = _normalize_key(key) if key is not None else None
    if normalized_key is not None and _ID_KEY.search(normalized_key):
        return opaque_digest(value)
    if (
        normalized_key is not None
        and key is not None
        and key.casefold() not in _SAFE_KEYS
        and normalized_key not in {item.casefold().replace("-", "_") for item in _SAFE_KEYS}
        and not _ID_KEY.search(normalized_key)
    ):
        return None
    if not _TOKEN_VALUE.fullmatch(value):
        return None
    return value


def redact_telemetry(value: object, *, _key: str | None = None) -> object:
    """Recursively retain only bounded and allow-listed telemetry values.

    This function is intentionally conservative. Unknown values are removed,
    sensitive keys are removed before traversing their values, and correlation
    identifiers are represented by stable digests.
    """

    if _key is not None and _SENSITIVE_KEY.search(_key):
        return None
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, child in list(value.items())[:_MAX_ITEMS]:
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                continue
            normalized = _normalize_key(key)
            structural = key in _STRUCTURAL_KEYS or normalized in {
                item.casefold().replace("-", "_") for item in _STRUCTURAL_KEYS
            }
            safe = (
                key.casefold() in {item.casefold() for item in _SAFE_KEYS}
                or normalized in {item.casefold().replace("-", "_") for item in _SAFE_KEYS}
                or _ID_KEY.search(normalized)
            )
            if not structural and not safe:
                continue
            sanitized = redact_telemetry(child, _key=key)
            if sanitized is not None:
                result[key] = sanitized
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [redact_telemetry(item, _key=_key) for item in list(value)[:_MAX_ITEMS]]
        return [item for item in values if item is not None]
    if isinstance(value, (bool, int, float)) or value is None:
        return _safe_scalar(value, key=_key)
    if isinstance(value, str):
        return _safe_scalar(value, key=_key)
    return None


def _normalize_key(key: object) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    return value.casefold().replace("-", "_")


def _read_otel_object(value: object) -> Mapping[str, object] | None:
    """Extract the inspectable portion of a ReadableSpan without SDK leakage."""

    if isinstance(value, Mapping):
        return value
    name = getattr(value, "name", None)
    attributes = getattr(value, "attributes", None)
    resource = getattr(value, "resource", None)
    events = getattr(value, "events", None)
    status = getattr(value, "status", None)
    if name is None and attributes is None and resource is None and events is None:
        return None
    resource_attributes = getattr(resource, "attributes", resource)
    status_code = getattr(status, "status_code", None)
    if status_code is not None and not isinstance(status_code, (str, int, float, bool)):
        status_code = getattr(status_code, "name", None) or getattr(status_code, "value", None)
    event_values: list[object] = []
    for event in events or ():
        event_attributes = getattr(event, "attributes", None)
        event_values.append(
            {
                "name": getattr(event, "name", None),
                "attributes": dict(event_attributes or {}),
            }
        )
    return {
        "name": name,
        "attributes": dict(attributes or {}),
        "resource": dict(resource_attributes or {}),
        "events": event_values,
        "status": {
            "status_code": status_code,
        },
    }


def scrub_otel_record(value: object) -> ContractPayload:
    """Scrub a mapping or automatic OTel span immediately before export."""

    source = _read_otel_object(value)
    sanitized = redact_telemetry(source if source is not None else value)
    if not isinstance(sanitized, Mapping):
        return {}
    return cast(ContractPayload, _json_only(sanitized))


def _otel_attribute_value(value: object) -> object | None:
    """Return a value accepted by the OTel SDK after the export scrub."""

    if isinstance(value, (str, bool, int, float)):
        return value
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    values = list(value)[:_MAX_ITEMS]
    if not values:
        return []
    value_type = type(values[0])
    if value_type not in {str, bool, int, float} or any(type(item) is not value_type for item in values):
        return None
    return values


def _otel_attributes(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    attributes: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:_MAX_ITEMS]:
        key = str(raw_key)
        if len(key) > _MAX_STRING or any(ord(character) < 32 for character in key):
            continue
        cleaned = _otel_attribute_value(raw_value)
        if cleaned is not None:
            attributes[key] = cleaned
    return attributes


def _otel_name(value: object, *, fallback: str) -> str:
    if isinstance(value, str) and 0 < len(value) <= _MAX_STRING and not any(
        ord(character) < 32 for character in value
    ) and _TOKEN_VALUE.fullmatch(value):
        # ``redact_telemetry`` has already rejected URLs, credentials, and
        # unbounded values. Keep names token-shaped so paths cannot be leaked.
        return value
    return fallback


def _safe_span_context(value: object) -> Any | None:
    """Copy only the bounded numeric W3C IDs needed by OTLP encoding."""

    if value is None or SpanContext is None or TraceState is None:
        return None
    try:
        context = cast(Any, value)
        trace_id = int(context.trace_id)
        span_id = int(context.span_id)
        if trace_id <= 0 or span_id <= 0:
            return None
        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=bool(getattr(context, "is_remote", False)),
            trace_flags=getattr(context, "trace_flags", None),
            trace_state=TraceState(),
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _safe_status(value: object) -> Any:
    if Status is None or StatusCode is None:
        return value
    raw_code = getattr(value, "status_code", None)
    if isinstance(raw_code, StatusCode):
        code = raw_code
    else:
        name = getattr(raw_code, "name", None) or str(raw_code or "UNSET")
        try:
            code = StatusCode[name.upper()]
        except (KeyError, AttributeError):
            code = StatusCode.UNSET
    # Status descriptions frequently contain exception messages. Omit them.
    return Status(code)


def _scrub_readable_span(value: object) -> object | None:
    """Rebuild an automatic span from its allow-listed export projection."""

    if ReadableSpan is None:
        return None
    source = _read_otel_object(value)
    if source is None:
        return None
    sanitized = scrub_otel_record(value)
    name = _otel_name(sanitized.get("name"), fallback="otel.span")
    attributes = _otel_attributes(sanitized.get("attributes"))

    original_events = tuple(getattr(value, "events", ()) or ())
    sanitized_events = sanitized.get("events")
    events: list[Any] = []
    if isinstance(sanitized_events, Sequence) and not isinstance(sanitized_events, (str, bytes)):
        for original, candidate in zip(original_events, sanitized_events, strict=False):
            if not isinstance(candidate, Mapping) or OtelEvent is None:
                continue
            event_name = _otel_name(candidate.get("name"), fallback="otel.event")
            try:
                events.append(
                    OtelEvent(
                        event_name,
                        attributes=_otel_attributes(candidate.get("attributes")),
                        timestamp=getattr(original, "timestamp", None),
                    )
                )
            except (TypeError, ValueError):
                continue

    resource_attributes = _otel_attributes(sanitized.get("resource"))
    try:
        resource = Resource(resource_attributes) if Resource is not None else None
        readable_span_type = cast(Any, ReadableSpan)
        return readable_span_type(
            name=name,
            context=_safe_span_context(getattr(value, "context", None)),
            parent=_safe_span_context(getattr(value, "parent", None)),
            resource=resource,
            attributes=attributes,
            events=events,
            links=(),
            kind=getattr(value, "kind", cast(Any, SpanKind.INTERNAL if SpanKind is not None else None)),
            status=_safe_status(getattr(value, "status", None)),
            start_time=getattr(value, "start_time", None),
            end_time=getattr(value, "end_time", None),
            instrumentation_info=None,
            instrumentation_scope=None,
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


class _RedactingSpanExporter:
    """SpanExporter-compatible boundary that scrubs automatic SDK spans."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[object]) -> object:
        scrubbed: list[object] = []
        for span in spans:
            with suppress(Exception):
                cleaned = _scrub_readable_span(span)
                if cleaned is not None:
                    scrubbed.append(cleaned)
        if not scrubbed:
            return SpanExportResult.SUCCESS if SpanExportResult is not None else None
        return self._delegate.export(scrubbed)

    def shutdown(self) -> object:
        shutdown = getattr(self._delegate, "shutdown", None)
        return shutdown() if callable(shutdown) else None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        force_flush = getattr(self._delegate, "force_flush", None)
        if not callable(force_flush):
            return True
        result = force_flush(timeout_millis=timeout_millis)
        return result is not False


def _json_only(value: object) -> object:
    if isinstance(value, Mapping):
        mapping_result: dict[str, object] = {}
        for key, child in value.items():
            cleaned = _json_only(child)
            if cleaned is not None:
                mapping_result[str(key)] = cleaned
        return mapping_result
    if isinstance(value, (list, tuple)):
        list_result: list[object] = []
        for child in value:
            cleaned = _json_only(child)
            if cleaned is not None:
                list_result.append(cleaned)
        return list_result
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return None


def _record_for_export(record: ObservationRecord) -> ObservationRecord:
    """Apply the export scrub and normalize raw legacy correlation IDs."""

    validated = ObservationRecord.model_validate(record)
    correlation: dict[str, str | int] = {}
    for key, value in validated.correlation.items():
        if key == "attempt" and isinstance(value, int):
            correlation[key] = value
        else:
            correlation[key] = opaque_digest(str(value))
    attrs: dict[str, Any] = {}
    for key, value in validated.attributes.items():
        cleaned = redact_telemetry({key: value})
        if isinstance(cleaned, Mapping) and key in cleaned:
            attrs[key] = cleaned[key]
    return validated.model_copy(update={"correlation": correlation, "attributes": attrs})


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Bounded propagation metadata for API, worker, and activity boundaries."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    attempt: int = 0

    def child(self, seed: str, *, attempt: int | None = None) -> TraceContext:
        digest = hashlib.sha256(f"{self.trace_id}:{self.span_id}:{seed}".encode()).hexdigest()
        return TraceContext(
            trace_id=self.trace_id,
            span_id=digest[:16],
            parent_span_id=self.span_id,
            attempt=self.attempt if attempt is None else max(0, attempt),
        )

    def as_correlation(self) -> dict[str, str | int]:
        values: dict[str, str | int] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attempt": self.attempt,
        }
        if self.parent_span_id:
            values["parent_span_id"] = self.parent_span_id
        return values


_TRACE_CONTEXT: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "xhs_food_trace_context", default=None
)


def new_trace_context(seed: str | None = None) -> TraceContext:
    seed_value = seed or f"trace:{id(object())}:{monotonic()}"
    digest = hashlib.sha256(seed_value.encode("utf-8")).hexdigest()
    return TraceContext(trace_id=digest[:32], span_id=digest[32:48])


def current_trace_context() -> TraceContext | None:
    return _TRACE_CONTEXT.get()


@contextmanager
def observation_context(
    *,
    seed: str,
    trace_id: str | None = None,
    attempt: int | None = None,
):
    current = _TRACE_CONTEXT.get()
    if current is not None:
        context = current.child(seed, attempt=attempt)
    else:
        context = new_trace_context(trace_id or seed)
        if attempt is not None and attempt:
            context = TraceContext(context.trace_id, context.span_id, attempt=max(0, attempt))
    token = _TRACE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _TRACE_CONTEXT.reset(token)


def inject_trace_context(carrier: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Inject a W3C traceparent into a worker/activity carrier."""

    context = _TRACE_CONTEXT.get()
    if context is None:
        return carrier
    trace_hex = context.trace_id.replace("sha256:", "")[:32].ljust(32, "0")
    span_hex = context.span_id.replace("sha256:", "")[:16].ljust(16, "0")
    carrier["traceparent"] = f"00-{trace_hex}-{span_hex}-01"
    if context.attempt:
        carrier["x-food-attempt"] = str(context.attempt)
    return carrier


def extract_trace_context(carrier: Mapping[str, str]) -> TraceContext | None:
    value = carrier.get("traceparent", "")
    parts = value.split("-")
    if (
        len(parts) != 4
        or parts[0] != "00"
        or len(parts[1]) != 32
        or len(parts[2]) != 16
        or len(parts[3]) != 2
        or parts[1] == "0" * 32
        or parts[2] == "0" * 16
    ):
        return None
    try:
        int(parts[1], 16)
        int(parts[2], 16)
        int(parts[3], 16)
    except ValueError:
        return None
    attempt = 0
    with suppress(ValueError):
        attempt = max(0, int(carrier.get("x-food-attempt", "0")))
    return TraceContext(trace_id=parts[1], span_id=parts[2], attempt=attempt)


class ObservationExportError(RuntimeError):
    """An exporter failure with a stable bounded classification."""

    def __init__(self, classification: str, message: str = "") -> None:
        self.classification = classification
        super().__init__(message or classification)


class InMemoryObservationBackend:
    """Deterministic backend used by tests and local diagnostics."""

    def __init__(self) -> None:
        self.records: list[ObservationRecord] = []
        self.batches: list[tuple[ObservationRecord, ...]] = []
        self.closed = False

    async def export(self, records: tuple[ObservationRecord, ...]) -> None:
        if self.closed:
            raise ObservationExportError("closed")
        cleaned = tuple(_record_for_export(record) for record in records)
        self.batches.append(cleaned)
        self.records.extend(cleaned)

    async def close(self) -> None:
        self.closed = True


class CapturingObservationBackend(InMemoryObservationBackend):
    """Named capture sink used by redaction and backend replacement tests."""


class NoopObservationPort(ObservationPort):
    """Disabled backend with the same lifecycle surface as a real exporter."""

    def __init__(self, *, reason: str = "disabled") -> None:
        self.reason = reason
        self.observed = 0
        self.closed = False

    def observe(self, record: ObservationRecord) -> bool:
        del record
        self.observed += 1
        return False

    record = observe
    emit = observe

    async def flush(self, deadline_seconds: float | None = None) -> str:
        del deadline_seconds
        return "skipped"

    def health(self) -> ContractPayload:
        return {
            "status": "closed" if self.closed else "disabled",
            "reason": self.reason,
            "queued": 0,
            "dropped": self.observed,
        }

    async def aclose(self) -> str:
        self.closed = True
        return "skipped"

    async def close(self) -> str:
        return await self.aclose()


class BoundedObservationExporter(ObservationPort):
    """Non-blocking bounded queue with batch, retry, and shutdown controls."""

    def __init__(
        self,
        backend: ObservationBackend | None = None,
        *,
        max_queue_size: int = 2_048,
        max_batch_size: int = 128,
        schedule_delay_ms: int = 5_000,
        export_timeout_ms: int = 10_000,
        retry_limit: int = 2,
        sampling_rate: float = 1.0,
        shutdown_flush_timeout_ms: int = 5_000,
        drop_policy: str = "drop_oldest",
        clock: Callable[[], float] = monotonic,
        auto_start: bool = False,
    ) -> None:
        if max_queue_size < 1 or max_batch_size < 1 or max_batch_size > max_queue_size:
            raise ValueError("observation queue and batch limits are invalid")
        if schedule_delay_ms < 0 or export_timeout_ms < 1 or retry_limit < 0:
            raise ValueError("observation schedule, timeout, or retry limits are invalid")
        if shutdown_flush_timeout_ms < 0:
            raise ValueError("observation shutdown timeout cannot be negative")
        if not 0.0 <= sampling_rate <= 1.0:
            raise ValueError("observation sampling rate must be between 0 and 1")
        if drop_policy not in {"drop_oldest", "drop_newest"}:
            raise ValueError("observation drop policy must be drop_oldest or drop_newest")
        self._backend = backend
        self._queue: deque[ObservationRecord] = deque()
        self._max_queue_size = max_queue_size
        self._max_batch_size = max_batch_size
        self._schedule_delay_seconds = schedule_delay_ms / 1000.0
        self._timeout_seconds = export_timeout_ms / 1000.0
        self._retry_limit = retry_limit
        self._sampling_rate = sampling_rate
        self._shutdown_timeout_seconds = shutdown_flush_timeout_ms / 1000.0
        self._drop_policy = drop_policy
        self._clock = clock
        self._lock = threading.Lock()
        self._flush_lock = asyncio.Lock()
        self._closed = False
        self._flush_started = False
        self._background_task: asyncio.Task[None] | None = None
        self._auto_start = auto_start
        self._accepted = 0
        self._exported = 0
        self._dropped = 0
        self._failed = 0
        self._malformed = 0
        self._saturated = 0
        self._last_flush = "never"
        self._last_error: str | None = None

    def start(self) -> None:
        """Start scheduled draining on the current event loop."""

        if self._closed or self._backend is None or self._background_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._background_task = loop.create_task(self._run_background(), name="otel-exporter")

    async def _run_background(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._schedule_delay_seconds)
                if self.queue_size:
                    await self.flush(self._schedule_delay_seconds or self._timeout_seconds)
        except asyncio.CancelledError:
            raise

    def observe(self, record: ObservationRecord) -> bool:
        """Validate, redact, sample, and enqueue without awaiting or raising."""

        if self._closed:
            self._dropped += 1
            return False
        try:
            cleaned = _record_for_export(ObservationRecord.model_validate(record))
        except Exception:
            self._malformed += 1
            self._record_metric("malformed")
            return False
        if not _sample(cleaned.observation_id, self._sampling_rate):
            self._dropped += 1
            self._record_metric("sampled")
            return False
        with self._lock:
            if len(self._queue) >= self._max_queue_size:
                self._saturated += 1
                self._dropped += 1
                self._record_metric("saturated")
                if self._drop_policy == "drop_newest":
                    return False
                self._queue.popleft()
            self._queue.append(cleaned)
            self._accepted += 1
            queue_size = len(self._queue)
        self._record_metric("accepted")
        self._set_queue_metric(queue_size)
        if self._auto_start:
            self.start()
        return True

    record = observe
    emit = observe

    async def flush(self, deadline_seconds: float | None = None) -> str:
        """Attempt exactly one bounded drain and classify its outcome."""

        if self._backend is None:
            self._last_flush = "skipped"
            return self._last_flush
        duration = self._shutdown_timeout_seconds if deadline_seconds is None else max(0.0, deadline_seconds)
        async with self._flush_lock:
            if self._flush_started:
                return self._last_flush
            self._flush_started = True
            deadline = self._clock() + duration
            had_failures = False
            try:
                while self.queue_size:
                    if self._clock() >= deadline:
                        self._last_flush = "timed_out"
                        self._record_metric("timed_out")
                        self._set_health_metric(False)
                        return self._last_flush
                    with self._lock:
                        batch = tuple(list(self._queue)[: self._max_batch_size])
                    if not batch:
                        break
                    exported = await self._export_batch(batch, deadline)
                    if exported == len(batch):
                        self._remove_batch(batch)
                        self._exported += len(batch)
                        self._record_metric("exported", count=len(batch))
                    else:
                        self._remove_batch(batch)
                        failed = len(batch) - exported
                        self._exported += exported
                        self._failed += failed
                        had_failures = True
                        if exported:
                            self._record_metric("exported", count=exported)
                        if failed:
                            self._record_metric("failed", count=failed)
                backend_flush = getattr(self._backend, "flush", None)
                if callable(backend_flush):
                    remaining = max(0.0, deadline - self._clock())
                    if remaining <= 0:
                        self._last_flush = "timed_out"
                        self._record_metric("timed_out")
                        self._set_health_metric(False)
                        return self._last_flush
                    try:
                        result = backend_flush(remaining)
                        if asyncio.iscoroutine(result):
                            result = await asyncio.wait_for(result, timeout=remaining)
                        if result in {"timed_out", "failed"}:
                            self._last_flush = str(result)
                            self._record_metric(self._last_flush)
                            return self._last_flush
                    except TimeoutError:
                        self._last_flush = "timed_out"
                        self._last_error = "timeout"
                        self._record_metric("timed_out")
                        self._set_health_metric(False)
                        return self._last_flush
                    except Exception as exc:
                        self._last_error = _error_class(exc)
                        self._last_flush = "failed"
                        self._record_metric("failed")
                        self._set_health_metric(False)
                        return self._last_flush
                self._last_flush = "failed" if had_failures else (
                    "flushed" if not self.queue_size else "timed_out"
                )
                self._record_metric(self._last_flush)
                self._set_health_metric(self._last_flush == "flushed")
                return self._last_flush
            finally:
                self._flush_started = False

    async def _export_batch(self, batch: tuple[ObservationRecord, ...], deadline: float) -> int:
        last_error: BaseException | None = None
        for _attempt in range(self._retry_limit + 1):
            remaining = min(self._timeout_seconds, deadline - self._clock())
            if remaining <= 0:
                self._last_error = "timeout"
                self._set_health_metric(False)
                return 0
            try:
                await asyncio.wait_for(self._backend.export(batch), timeout=max(0.001, remaining))  # type: ignore[union-attr]
                self._last_error = None
                self._set_health_metric(True)
                return len(batch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                self._last_error = _error_class(exc)
        # A schema failure is isolated one record at a time. Other failures are
        # discarded after bounded retries because retrying an uncertain batch
        # could duplicate a backend-side commit.
        if isinstance(last_error, ObservationExportError) and last_error.classification == "schema_error" and len(batch) > 1:
            exported = 0
            for record in batch:
                remaining = min(self._timeout_seconds, deadline - self._clock())
                if remaining <= 0:
                    self._set_health_metric(False)
                    return exported
                try:
                    await asyncio.wait_for(self._backend.export((record,)), timeout=max(0.001, remaining))  # type: ignore[union-attr]
                    exported += 1
                except Exception as exc:
                    self._last_error = _error_class(exc)
            if exported:
                self._set_health_metric(True)
            return exported
        self._set_health_metric(False)
        return 0

    def _remove_batch(self, batch: tuple[ObservationRecord, ...]) -> None:
        with self._lock:
            for _ in batch:
                if self._queue:
                    self._queue.popleft()
            queue_size = len(self._queue)
        self._set_queue_metric(queue_size)

    async def aclose(self) -> str:
        if self._closed:
            return self._last_flush
        started = self._clock()
        if self._background_task is not None:
            self._background_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._background_task
            self._background_task = None
        remaining = max(0.0, self._shutdown_timeout_seconds - (self._clock() - started))
        result = await self.flush(remaining)
        remaining = max(0.0, self._shutdown_timeout_seconds - (self._clock() - started))
        if self._backend is not None:
            try:
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.wait_for(self._backend.close(), timeout=remaining)
            except TimeoutError:
                self._last_error = "timeout"
                result = "timed_out"
            except Exception as exc:
                self._last_error = _error_class(exc)
                if result == "flushed":
                    result = "failed"
        self._closed = True
        self._last_flush = result
        self._set_health_metric(False)
        return result

    async def close(self) -> str:
        return await self.aclose()

    def health(self) -> ContractPayload:
        self._set_queue_metric()
        self._set_health_metric(not self._closed and self._last_error is None)
        payload: ContractPayload = {
            "status": "closed" if self._closed else ("unhealthy" if self._last_error else "ready"),
            "queued": self.queue_size,
            "accepted": self._accepted,
            "exported": self._exported,
            "dropped": self._dropped,
            "failed": self._failed,
            "malformed": self._malformed,
            "saturated": self._saturated,
            "max_queue_size": self._max_queue_size,
            "max_batch_size": self._max_batch_size,
            "schedule_delay_ms": int(self._schedule_delay_seconds * 1000),
            "export_timeout_ms": int(self._timeout_seconds * 1000),
            "retry_limit": self._retry_limit,
            "sampling_rate": self._sampling_rate,
            "shutdown_flush_timeout_ms": int(self._shutdown_timeout_seconds * 1000),
            "drop_policy": self._drop_policy,
            "last_flush": self._last_flush,
            "exporter_version": OBSERVATION_EXPORTER_VERSION,
        }
        if self._last_error is not None:
            payload["last_error"] = self._last_error
        return payload

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def _record_metric(self, outcome: str, *, count: int = 1) -> None:
        with suppress(Exception):
            record_otel_event(outcome, count=count)

    def _set_queue_metric(self, value: int | None = None) -> None:
        with suppress(Exception):
            otel_queue_size.set(self.queue_size if value is None else value)

    def _set_health_metric(self, healthy: bool) -> None:
        with suppress(Exception):
            set_otel_health(healthy)


class OTLPHTTPObservationBackend:
    """OTLP/HTTP adapter using the pinned SDK exporter when available.

    A lightweight injected-client mode is retained for deterministic tests and
    minimal installations. The public surface exposes no exporter SDK type.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        client: Any | None = None,
        api_version: str = "v1",
        service_name: str = "food-agent",
        timeout_ms: int = 10_000,
        max_queue_size: int = 2_048,
        max_batch_size: int = 128,
        schedule_delay_ms: int = 5_000,
        exporter: Any | None = None,
        use_sdk: bool = True,
    ) -> None:
        if not endpoint or any(ord(character) < 32 for character in endpoint):
            raise ValueError("OTLP endpoint must be a valid non-empty value")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OTLP endpoint must include an HTTP(S) host")
        if timeout_ms < 1:
            raise ValueError("OTLP timeout must be positive")
        if not api_version or any(character.isspace() for character in api_version):
            raise ValueError("OTLP API version must be a non-empty token")
        if not service_name or any(character.isspace() for character in service_name):
            raise ValueError("OTLP service name must be a non-empty token")
        normalized = endpoint.rstrip("/")
        self.endpoint = normalized if normalized.endswith("/v1/traces") else normalized + "/v1/traces"
        self.api_version = api_version
        self.service_name = service_name
        self._token = token
        self._client = client
        self._owned_client = False
        self._timeout_ms = timeout_ms
        self._sdk_provider: Any | None = None
        self._sdk_processor: Any | None = None
        self._sdk_tracer: Any | None = None
        self._sdk_exporter = exporter
        self._use_sdk = use_sdk and client is None
        self._max_queue_size = max_queue_size
        self._max_batch_size = max_batch_size
        self._schedule_delay_ms = schedule_delay_ms
        self._sdk_init_error: str | None = None

    def _ensure_sdk(self) -> bool:
        if not self._use_sdk or self._sdk_tracer is not None:
            return self._sdk_tracer is not None
        if OTLPSpanExporter is None or TracerProvider is None or BatchSpanProcessor is None:
            self._sdk_init_error = "exporter_dependency_missing"
            return False
        try:
            if self._sdk_exporter is None:
                headers = {"x-observation-api-version": self.api_version}
                if self._token:
                    headers["Authorization"] = f"Bearer {self._token}"
                self._sdk_exporter = OTLPSpanExporter(
                    endpoint=self.endpoint,
                    headers=headers,
                    timeout=self._timeout_ms / 1000.0,
                )
            resource_type = cast(Any, Resource)
            resource = resource_type.create({"service.name": self.service_name})
            provider = TracerProvider(resource=resource, shutdown_on_exit=False)
            processor = BatchSpanProcessor(
                cast(Any, _RedactingSpanExporter(self._sdk_exporter)),
                max_queue_size=self._max_queue_size,
                max_export_batch_size=self._max_batch_size,
                schedule_delay_millis=self._schedule_delay_ms,
                export_timeout_millis=self._timeout_ms,
            )
            provider.add_span_processor(processor)
            self._sdk_provider = provider
            self._sdk_processor = processor
            self._sdk_tracer = provider.get_tracer("xhs_food", OBSERVATION_EXPORTER_VERSION)
            return True
        except Exception:
            self._sdk_init_error = "exporter_initialization_failed"
            self._sdk_provider = None
            self._sdk_processor = None
            self._sdk_tracer = None
            return False

    async def export(self, records: tuple[ObservationRecord, ...]) -> None:
        cleaned = tuple(_record_for_export(record) for record in records)
        if self._ensure_sdk():
            for record in cleaned:
                self._emit_sdk_span(record)
            return
        client = self._client
        if client is None:
            httpx = importlib.import_module("httpx")
            client = httpx.AsyncClient(timeout=self._timeout_ms / 1000.0)
            self._client = client
            self._owned_client = True
        response = await client.post(
            self.endpoint,
            json=_otlp_payload(cleaned, service_name=self.service_name),
            headers=self._headers(),
        )
        self._raise_for_response(response)

    def _emit_sdk_span(self, record: ObservationRecord) -> None:
        tracer = self._sdk_tracer
        if tracer is None:
            return
        attributes = {
            key: value
            for key, value in {**record.correlation, **record.attributes}.items()
            if isinstance(value, (str, int, float, bool))
        }
        kwargs: dict[str, Any] = {"kind": SpanKind.INTERNAL} if SpanKind is not None else {}
        span = tracer.start_span(record.name, attributes=attributes, **kwargs)
        status_type = cast(Any, Status)
        status_code_type = cast(Any, StatusCode)
        if record.outcome in {ObservationOutcome.ERROR, ObservationOutcome.TIMEOUT} and Status is not None:
            span.set_status(status_type(status_code_type.ERROR))
        elif Status is not None:
            span.set_status(status_type(status_code_type.OK))
        span.end()

    async def flush(self, timeout_seconds: float | None = None) -> str:
        duration = self._timeout_ms / 1000.0 if timeout_seconds is None else max(0.0, timeout_seconds)
        timeout_ms = max(0, int(duration * 1000))
        if self._sdk_provider is not None:
            try:
                ok = self._sdk_provider.force_flush(timeout_millis=timeout_ms)
                return "flushed" if ok is not False else "timed_out"
            except Exception:
                return "failed"
        return "flushed"

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "x-observation-api-version": self.api_version,
        }
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _raise_for_response(response: Any) -> None:
        status = int(getattr(response, "status_code", 0))
        if 200 <= status < 300:
            return
        classification = (
            "authorization"
            if status in {401, 403}
            else "not_found"
            if status == 404
            else "rate_limited"
            if status == 429
            else "server_error"
            if status >= 500
            else "http_error"
        )
        raise ObservationExportError(classification, f"OTLP export returned {status}")

    async def close(self) -> None:
        if self._sdk_provider is not None:
            with suppress(Exception):
                self._sdk_provider.shutdown()
            self._sdk_provider = None
            self._sdk_processor = None
            self._sdk_tracer = None
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class OpenTelemetryObservationPort(BoundedObservationExporter):
    """Concrete project-owned ObservationPort backed by OTLP/HTTP."""

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        service_name: str = "food-agent",
        api_version: str = "v1",
        max_queue_size: int = 2_048,
        max_batch_size: int = 128,
        schedule_delay_ms: int = 5_000,
        export_timeout_ms: int = 10_000,
        retry_limit: int = 2,
        sampling_rate: float = 1.0,
        shutdown_flush_timeout_ms: int = 5_000,
        drop_policy: str = "drop_oldest",
        client: Any | None = None,
        exporter: Any | None = None,
        auto_start: bool = False,
    ) -> None:
        backend = OTLPHTTPObservationBackend(
            endpoint,
            token=token,
            client=client,
            api_version=api_version,
            service_name=service_name,
            timeout_ms=export_timeout_ms,
            max_queue_size=max_queue_size,
            max_batch_size=max_batch_size,
            schedule_delay_ms=schedule_delay_ms,
            exporter=exporter,
        )
        self.backend = backend
        super().__init__(
            backend,
            max_queue_size=max_queue_size,
            max_batch_size=max_batch_size,
            schedule_delay_ms=schedule_delay_ms,
            export_timeout_ms=export_timeout_ms,
            retry_limit=retry_limit,
            sampling_rate=sampling_rate,
            shutdown_flush_timeout_ms=shutdown_flush_timeout_ms,
            drop_policy=drop_policy,
            auto_start=auto_start,
        )


class InMemoryObservationPort(BoundedObservationExporter):
    """Deterministic bounded ObservationPort for local and qualification runs."""

    def __init__(self, **kwargs: Any) -> None:
        backend = kwargs.pop("backend", None) or InMemoryObservationBackend()
        super().__init__(backend, **kwargs)
        self.backend = backend


# Common names used by composition code and qualification fixtures.
OTelObservationPort = OpenTelemetryObservationPort
OTLPObservationPort = OpenTelemetryObservationPort


def build_observation_exporter(
    *,
    endpoint: str | None,
    enabled: bool,
    token: str | None = None,
    service_name: str = "food-agent",
    api_version: str = "v1",
    backend: ObservationBackend | None = None,
    max_queue_size: int = 2_048,
    max_batch_size: int = 128,
    schedule_delay_ms: int = 5_000,
    export_timeout_ms: int = 10_000,
    retry_limit: int = 2,
    sampling_rate: float = 1.0,
    shutdown_flush_timeout_ms: int = 5_000,
    drop_policy: str = "drop_oldest",
    auto_start: bool = False,
) -> ObservationPort:
    """Build a disabled, deterministic, or OTLP ObservationPort."""

    if not enabled:
        return NoopObservationPort()
    if backend is not None:
        return BoundedObservationExporter(
            backend,
            max_queue_size=max_queue_size,
            max_batch_size=max_batch_size,
            schedule_delay_ms=schedule_delay_ms,
            export_timeout_ms=export_timeout_ms,
            retry_limit=retry_limit,
            sampling_rate=sampling_rate,
            shutdown_flush_timeout_ms=shutdown_flush_timeout_ms,
            drop_policy=drop_policy,
            auto_start=auto_start,
        )
    if not endpoint:
        return NoopObservationPort(reason="endpoint_missing")
    return OpenTelemetryObservationPort(
        endpoint,
        token=token,
        service_name=service_name,
        api_version=api_version,
        max_queue_size=max_queue_size,
        max_batch_size=max_batch_size,
        schedule_delay_ms=schedule_delay_ms,
        export_timeout_ms=export_timeout_ms,
        retry_limit=retry_limit,
        sampling_rate=sampling_rate,
        shutdown_flush_timeout_ms=shutdown_flush_timeout_ms,
        drop_policy=drop_policy,
        auto_start=auto_start,
    )


def _otlp_payload(
    records: tuple[ObservationRecord, ...], *, service_name: str = "food-agent"
) -> dict[str, object]:
    spans: list[dict[str, object]] = []
    for record in records:
        trace_id = _hex_id(record.correlation.get("trace_id", record.observation_id), 32)
        span_id = _hex_id(record.correlation.get("span_id", record.observation_id), 16)
        attrs = {**record.correlation, **record.attributes}
        spans.append(
            {
                "traceId": trace_id,
                "spanId": span_id,
                "name": record.name,
                "kind": 1,
                "startTimeUnixNano": int(record.occurred_at.timestamp() * 1_000_000_000),
                "endTimeUnixNano": int(
                    (record.occurred_at.timestamp() + (record.duration_ms or 0.0) / 1000.0)
                    * 1_000_000_000
                ),
                "attributes": [
                    {"key": key, "value": _otlp_value(value)}
                    for key, value in attrs.items()
                    if isinstance(value, (str, int, float, bool))
                ],
                "status": {"code": 2 if record.outcome in {ObservationOutcome.ERROR, ObservationOutcome.TIMEOUT} else 1},
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}}
                    ]
                },
                "scopeSpans": [{"scope": {"name": "xhs_food"}, "spans": spans}],
            }
        ]
    }


def _hex_id(value: object, length: int) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return digest[:length]


def _otlp_value(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _sample(identity: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    value = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16], 16) / 16**16
    return value < rate


def _error_class(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, ObservationExportError):
        return exc.classification
    return "dependency_unavailable"


@asynccontextmanager
async def observed_operation(
    port: ObservationPort,
    *,
    observation_id: str,
    kind: ObservationKind | str,
    name: str,
    correlation: Mapping[str, str | int] | None = None,
    attributes: Mapping[str, Any] | None = None,
):
    """Record one boundary while preserving parent trace context."""

    started = monotonic()
    with observation_context(seed=observation_id):
        current = current_trace_context()
        merged_correlation = dict(current.as_correlation() if current else {})
        merged_correlation.update(correlation or {})
        try:
            yield
        except Exception:
            port.observe(
                ObservationRecord(
                    observation_id=observation_id,
                    kind=cast(ObservationKind, kind),
                    name=name,
                    duration_ms=(monotonic() - started) * 1000,
                    outcome=ObservationOutcome.ERROR,
                    correlation=merged_correlation,
                    attributes={**dict(attributes or {}), "outcome": "error"},
                )
            )
            raise
        else:
            port.observe(
                ObservationRecord(
                    observation_id=observation_id,
                    kind=cast(ObservationKind, kind),
                    name=name,
                    duration_ms=(monotonic() - started) * 1000,
                    outcome=ObservationOutcome.OK,
                    correlation=merged_correlation,
                    attributes=dict(attributes or {}),
                )
            )


__all__ = [
    "BoundedObservationExporter",
    "CapturingObservationBackend",
    "InMemoryObservationBackend",
    "InMemoryObservationPort",
    "NoopObservationPort",
    "OTLPHTTPObservationBackend",
    "OTLPObservationPort",
    "OTelObservationPort",
    "OBSERVATION_EXPORTER_VERSION",
    "ObservationExportError",
    "OpenTelemetryObservationPort",
    "TraceContext",
    "current_trace_context",
    "extract_trace_context",
    "inject_trace_context",
    "new_trace_context",
    "observation_context",
    "opaque_digest",
    "observed_operation",
    "build_observation_exporter",
    "redact_telemetry",
    "scrub_otel_record",
]
