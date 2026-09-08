"""Small, replaceable observation adapter for the adaptive Agent loop.

The adaptive runtime depends only on the project-owned ``ObservationPort``
contract.  This module keeps the mechanics of creating bounded records in one
place so planner, MCP, and Food-reduction code cannot accidentally export raw
provider payloads or credentials.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any

from xhs_food.contracts import (
    ObservationKind,
    ObservationOutcome,
    ObservationPort,
    ObservationRecord,
)

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "schema_version",
        "operation",
        "outcome",
        "boundary",
        "status",
        "status_code",
        "mode",
        "coverage_state",
        "error_class",
        "sampled",
        "attempt",
        "retry_count",
        "duration_ms",
        "item_count",
        "source_count",
        "dropped_count",
        "classification",
        "source",
    }
)
_ALLOWED_CORRELATION = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_span_id",
        "task",
        "workflow",
        "run",
        "provider",
        "model_role",
        "attempt",
    }
)


def _scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, float, bool)) and not isinstance(value, bytes):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            return None
        return value
    return None


class AdaptiveObservationRecorder:
    """Best-effort bounded recorder owned by one investigation run.

    Observation failures are intentionally swallowed.  Telemetry must never
    change whether evidence is collected or how the investigation terminates.
    """

    def __init__(self, port: ObservationPort | Any | None, run_id: str) -> None:
        self._port = port
        self.run_id = str(run_id)
        digest = hashlib.sha256(self.run_id.encode("utf-8")).hexdigest()
        self._trace_id = digest[:32]
        self._span_seed = digest[32:]
        self._counter = 0
        self._terminal_emitted = False

    @property
    def enabled(self) -> bool:
        return self._port is not None

    def emit(
        self,
        kind: ObservationKind,
        name: str,
        *,
        outcome: ObservationOutcome = ObservationOutcome.OK,
        duration_ms: float | None = None,
        correlation: Mapping[str, str | int] | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> bool:
        if self._port is None:
            return False
        self._counter += 1
        span_id = hashlib.sha256(
            f"{self._span_seed}:{self._counter}:{name}".encode()
        ).hexdigest()[:16]
        merged_correlation: dict[str, str | int] = {
            "trace_id": self._trace_id,
            "span_id": span_id,
            "run": self.run_id[:128] or "run",
        }
        for key, value in (correlation or {}).items():
            if key not in _ALLOWED_CORRELATION:
                continue
            scalar = _scalar(value)
            if scalar is not None and (not isinstance(scalar, str) or scalar):
                merged_correlation[key] = scalar  # type: ignore[assignment]
        bounded_attributes: dict[str, str | int | float | bool] = {}
        for key, value in (attributes or {}).items():
            if key not in _ALLOWED_ATTRIBUTES:
                continue
            scalar = _scalar(value)
            if scalar is None:
                continue
            if isinstance(scalar, str):
                scalar = scalar[:128]
            bounded_attributes[key] = scalar
        if duration_ms is not None:
            bounded_attributes.setdefault("duration_ms", max(0.0, float(duration_ms)))
        bounded_attributes.setdefault("outcome", outcome.value)
        try:
            record = ObservationRecord(
                observation_id=f"{self.run_id}:observation:{self._counter}",
                kind=kind,
                name=name.replace(" ", "_")[:128] or "adaptive.operation",
                duration_ms=duration_ms,
                outcome=outcome,
                correlation=merged_correlation,
                attributes=bounded_attributes,
            )
            result = self._port.observe(record)
            return bool(result) if isinstance(result, bool) else True
        except Exception:
            return False

    @asynccontextmanager
    async def span(
        self,
        kind: ObservationKind,
        name: str,
        *,
        correlation: Mapping[str, str | int] | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[None]:
        started = monotonic()
        try:
            yield
        except BaseException as exc:
            self.emit(
                kind,
                name,
                outcome=(
                    ObservationOutcome.TIMEOUT
                    if isinstance(exc, (TimeoutError,))
                    else ObservationOutcome.ERROR
                ),
                duration_ms=(monotonic() - started) * 1000,
                correlation=correlation,
                attributes={
                    **dict(attributes or {}),
                    "error_class": type(exc).__name__,
                },
            )
            raise
        else:
            self.emit(
                kind,
                name,
                duration_ms=(monotonic() - started) * 1000,
                correlation=correlation,
                attributes=attributes,
            )

    def terminal(
        self,
        *,
        outcome: ObservationOutcome,
        status: str,
        duration_ms: float | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        self.emit(
            ObservationKind.AGENT_RUN,
            "adaptive.agent.run",
            outcome=outcome,
            duration_ms=duration_ms,
            attributes={
                **dict(attributes or {}),
                "status": status,
                "boundary": "adaptive_loop",
            },
        )


def recorder_for(port: Any | None, run_id: str) -> AdaptiveObservationRecorder:
    """Factory kept as a seam for composition tests and future backends."""

    return AdaptiveObservationRecorder(port, run_id)


__all__ = ["AdaptiveObservationRecorder", "recorder_for"]
