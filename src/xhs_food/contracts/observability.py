"""Project-owned contracts for redacted, replaceable observations.

The application and domain layers depend on these value objects instead of an
OpenTelemetry or Phoenix SDK. Foundation adapters may translate records to a
vendor representation, but the representation crossing this boundary is
always bounded and versioned.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from .base import ContractModel, ContractPayload, NonEmptyStr, Timestamp

OBSERVATION_SCHEMA_VERSION = "observation/v1"
OBSERVATION_REDACTION_VERSION = "observation-redaction/v1"


class ObservationOutcome(StrEnum):
    """Finite result vocabulary used by traces and health aggregates."""

    STARTED = "started"
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    DROPPED = "dropped"


class ObservationKind(StrEnum):
    """Stable boundary names for correlated Agent work."""

    AGENT_RUN = "agent.run"
    MODEL_CALL = "model.call"
    MCP_TOOL_CALL = "mcp.tool_call"
    CONNECTOR_CALL = "connector.call"
    EVIDENCE_TRANSFORM = "evidence.transform"
    QUERY_FAMILY_READ = "query_family.read"
    QUERY_FAMILY_REFRESH = "query_family.refresh"
    MEMORY_ASSEMBLY = "memory.assembly"
    RANKING_DECISION = "ranking.decision"
    TEMPORAL_ACTIVITY = "temporal.activity"
    EVALUATION = "evaluation"


# Correlation values are deliberately opaque at the contract boundary. The
# Foundation adapter hashes legacy/raw values once more before export.
_ALLOWED_CORRELATION_KEYS = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_span_id",
        "task",
        "workflow",
        "run",
        "family",
        "bundle",
        "profile",
        "pack",
        "connector",
        "provider",
        "model_role",
        "attempt",
    }
)
_ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "outcome",
        "boundary",
        "status",
        "status_code",
        "mode",
        "match_layer",
        "freshness_state",
        "coverage_state",
        "error_class",
        "sampled",
        "served",
        "attempt",
        "retry_count",
        "duration_ms",
        "item_count",
        "source_count",
        "private_record_count",
        "dropped_count",
        "queue_size",
        "batch_size",
        "drop_policy",
        "flush_state",
        "exporter_state",
        "classification",
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
_FORBIDDEN_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "prompt",
    "query",
    "secret",
    "token",
    "url",
    "body",
    "output",
    "argument",
    "payload",
    "session",
    "preference",
    "memory",
    "qr",
    "note",
    "header",
)


class ObservationRecord(ContractModel):
    """A bounded observation safe to retain or send to an exporter."""

    schema_version: Literal["observation/v1"] = OBSERVATION_SCHEMA_VERSION
    redaction_version: Literal["observation-redaction/v1"] = OBSERVATION_REDACTION_VERSION
    observation_id: NonEmptyStr
    kind: ObservationKind
    name: NonEmptyStr
    occurred_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = Field(default=None, ge=0.0, le=86_400_000)
    outcome: ObservationOutcome = ObservationOutcome.OK
    correlation: dict[str, NonEmptyStr | int] = Field(default_factory=dict)
    attributes: ContractPayload = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_redacted_shape(self) -> ObservationRecord:
        invalid_correlation = set(self.correlation) - _ALLOWED_CORRELATION_KEYS
        if invalid_correlation:
            raise ValueError(
                f"unapproved observation correlation keys: {sorted(invalid_correlation)}"
            )
        invalid_attributes = set(self.attributes) - _ALLOWED_ATTRIBUTE_KEYS
        if invalid_attributes:
            raise ValueError(f"unapproved observation attributes: {sorted(invalid_attributes)}")
        _reject_forbidden_values(self.correlation, "correlation")
        _reject_forbidden_values(self.attributes, "attributes")
        if self.name != self.name.strip() or any(character.isspace() for character in self.name):
            raise ValueError("observation name must be a stable token")
        for key, value in self.correlation.items():
            if isinstance(value, str) and len(value) > 128:
                raise ValueError(f"observation correlation value is too long: {key}")
            if isinstance(value, str) and any(ord(character) < 32 for character in value):
                raise ValueError(f"observation correlation value contains control characters: {key}")
            if isinstance(value, int) and value < 0:
                raise ValueError(f"observation correlation value cannot be negative: {key}")
        return self


@runtime_checkable
class ObservationPort(Protocol):
    """Project-owned non-authoritative observation sink."""

    def observe(self, record: ObservationRecord) -> bool: ...

    async def flush(self, deadline_seconds: float | None = None) -> str: ...

    def health(self) -> ContractPayload: ...


@runtime_checkable
class ObservationBackend(Protocol):
    """Minimal backend used by bounded Foundation delivery adapters."""

    async def export(self, records: tuple[ObservationRecord, ...]) -> None: ...

    async def close(self) -> None: ...


def _reject_forbidden_values(value: object, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if any(part in normalized for part in _FORBIDDEN_PARTS):
                raise ValueError(f"redacted observation contains forbidden field {path}.{key}")
            _reject_forbidden_values(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        if any(
            marker in lowered
            for marker in (
                "authorization=",
                "bearer ",
                "cookie:",
                "?token=",
                "http://",
                "https://",
            )
        ):
            raise ValueError(f"redacted observation contains forbidden value at {path}")


def _normalize_key(key: object) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    return value.casefold().replace("-", "_")


__all__ = [
    "OBSERVATION_REDACTION_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "ObservationBackend",
    "ObservationKind",
    "ObservationOutcome",
    "ObservationPort",
    "ObservationRecord",
]
