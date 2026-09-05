"""Bounded B1 shadow outcome telemetry.

The Evidence path reports only finite outcome names and item counts.  It never
accepts query text, source URLs, user/session identifiers, or arbitrary
attributes.  An optional project-owned observation port receives the same
redacted record and is intentionally best effort.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from xhs_food.contracts import (
    ObservationKind,
    ObservationOutcome,
    ObservationPort,
    ObservationRecord,
)


class ShadowOutcome(StrEnum):
    """Finite B1 lifecycle outcomes used by metrics and qualification gates."""

    SAMPLED = "sampled"
    SKIPPED = "skipped"
    PRIVACY_REJECTED = "privacy_rejected"
    PROVENANCE_REJECTED = "provenance_rejected"
    PERSISTED = "persisted"
    FAILED = "failed"


_OUTCOMES = tuple(ShadowOutcome)


@dataclass(frozen=True, slots=True)
class ShadowTelemetryEvent:
    outcome: ShadowOutcome
    item_count: int
    occurred_at: datetime


class B1ShadowTelemetry:
    """Keep bounded aggregate counters and optional redacted observations."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_events: int = 1_024,
        observation_port: ObservationPort | None = None,
    ) -> None:
        if max_events < 1:
            raise ValueError("B1 telemetry max_events must be positive")
        self._enabled = enabled
        self._max_events = max_events
        self._observation_port = observation_port
        self._counts: dict[ShadowOutcome, int] = {outcome: 0 for outcome in _OUTCOMES}
        self._events: deque[ShadowTelemetryEvent] = deque(maxlen=max_events)
        self._exporter_failures = 0

    def record(
        self,
        *,
        outcome: str | ShadowOutcome,
        connector: str | None = None,
        item_count: int = 0,
    ) -> None:
        del connector  # Connector identity is intentionally not retained here.
        if not self._enabled:
            return
        try:
            selected = ShadowOutcome(outcome)
        except ValueError:
            selected = ShadowOutcome.FAILED
        count = max(0, int(item_count))
        self._counts[selected] += 1
        self._events.append(
            ShadowTelemetryEvent(selected, count, datetime.now(UTC))
        )
        if self._observation_port is None:
            return
        try:
            self._observation_port.observe(
                ObservationRecord(
                    observation_id=f"b1-shadow-{sum(self._counts.values())}",
                    kind=ObservationKind.EVIDENCE_TRANSFORM,
                    name="evidence.shadow",
                    outcome=_observation_outcome(selected),
                    attributes={
                        "operation": "shadow_write",
                        "outcome": selected.value,
                        "item_count": count,
                    },
                )
            )
        except Exception:
            self._exporter_failures += 1

    @property
    def counts(self) -> Mapping[str, int]:
        return {outcome.value: self._counts[outcome] for outcome in _OUTCOMES}

    @property
    def events(self) -> tuple[ShadowTelemetryEvent, ...]:
        return tuple(self._events)

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ready" if self._enabled else "disabled",
            "max_events": self._max_events,
            "queued_events": len(self._events),
            "exporter_failures": self._exporter_failures,
        }
        payload.update(self.counts)
        return payload


def _observation_outcome(outcome: ShadowOutcome) -> ObservationOutcome:
    if outcome is ShadowOutcome.SKIPPED:
        return ObservationOutcome.DROPPED
    if outcome is ShadowOutcome.FAILED:
        return ObservationOutcome.ERROR
    return ObservationOutcome.OK


# The foundation module retains its historical class name.  This alias keeps
# Evidence-owned tests and adapters independent from exporter dependencies.
EvidenceShadowTelemetry = B1ShadowTelemetry


__all__ = [
    "B1ShadowTelemetry",
    "EvidenceShadowTelemetry",
    "ShadowOutcome",
    "ShadowTelemetryEvent",
]
