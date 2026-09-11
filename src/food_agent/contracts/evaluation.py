"""Repository-owned evaluation contracts and release-gate ports.

Evaluation artifacts are immutable, synthetic/redacted, and reproducible
without a Phoenix deployment. Phoenix is only a projection sink behind the
``EvaluationPort`` protocol.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Never, Protocol, runtime_checkable

from pydantic import Field, model_validator

from .base import ContractModel, ContractPayload, JsonValue, NonEmptyStr, Timestamp

EVALUATION_SCHEMA_VERSION = "evaluation/v1"
EVALUATION_REDACTION_VERSION = "evaluation-redaction/v1"


class EvaluationOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class EvaluationCase(ContractModel):
    """One synthetic or explicitly redacted fixture case."""

    schema_version: Literal["evaluation/v1"] = EVALUATION_SCHEMA_VERSION
    case_id: NonEmptyStr
    input: JsonValue
    expected: JsonValue = None
    tags: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_case(self) -> EvaluationCase:
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("evaluation case tags must be unique")
        _reject_private_values(self.input, "input")
        _reject_private_values(self.expected, "expected")
        object.__setattr__(self, "input", _freeze_json(self.input))
        object.__setattr__(self, "expected", _freeze_json(self.expected))
        return self


class EvaluationDataset(ContractModel):
    """Immutable fixture and digest retained as the qualification authority."""

    schema_version: Literal["evaluation/v1"] = EVALUATION_SCHEMA_VERSION
    dataset_id: NonEmptyStr
    dataset_version: NonEmptyStr
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)
    redaction_version: NonEmptyStr = EVALUATION_REDACTION_VERSION
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_dataset(self) -> EvaluationDataset:
        ids = tuple(case.case_id for case in self.cases)
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        calculated = dataset_digest(self)
        if self.digest is not None and self.digest != calculated:
            raise ValueError("evaluation dataset digest does not match its immutable cases")
        object.__setattr__(self, "digest", calculated)
        return self


class EvaluationCaseResult(ContractModel):
    """A case result that never stores the raw candidate output."""

    schema_version: Literal["evaluation/v1"] = EVALUATION_SCHEMA_VERSION
    case_id: NonEmptyStr
    outcome: Literal["pass", "fail", "blocked"]
    evaluator_version: NonEmptyStr
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    details: ContractPayload = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result(self) -> EvaluationCaseResult:
        _reject_private_values(self.details, "details")
        object.__setattr__(self, "details", _freeze_json(self.details))
        return self


class EvaluationRun(ContractModel):
    """A reproducible result retained independently from Phoenix."""

    schema_version: Literal["evaluation/v1"] = EVALUATION_SCHEMA_VERSION
    run_id: NonEmptyStr
    dataset_id: NonEmptyStr
    dataset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_version: NonEmptyStr
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: tuple[EvaluationCaseResult, ...] = Field(min_length=1)
    outcome: EvaluationOutcome
    created_at: Timestamp = Field(default_factory=lambda: datetime.now(UTC))
    provider: str | None = None
    model_version: str | None = None
    rubric_version: str | None = None
    template_version: str | None = None
    approval_id: str | None = None
    expires_at: Timestamp | None = None
    result_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_run(self) -> EvaluationRun:
        case_ids = tuple(result.case_id for result in self.results)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation result case IDs must be unique")
        if self.outcome is EvaluationOutcome.PASS and any(
            result.outcome != EvaluationOutcome.PASS.value for result in self.results
        ):
            raise ValueError("a passing evaluation run cannot contain a failing case")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("evaluation approval expiry must follow creation")
        judge_fields = (
            self.provider,
            self.model_version,
            self.rubric_version,
            self.template_version,
        )
        if any(value is not None for value in judge_fields) and not all(
            value is not None for value in judge_fields
        ):
            raise ValueError("LLM judge metadata must be complete when present")
        calculated = evaluation_run_digest(self)
        if self.result_digest is not None and self.result_digest != calculated:
            raise ValueError("evaluation result digest does not match immutable results")
        object.__setattr__(self, "result_digest", calculated)
        return self


class EvaluationGate(ContractModel):
    """Explicit operator decision bound to promotion inputs and expiry."""

    schema_version: Literal["evaluation/v1"] = EVALUATION_SCHEMA_VERSION
    milestone: Literal["b1", "b2", "b3", "observability"]
    report: EvaluationOutcome
    dataset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_revision: NonEmptyStr
    evaluator_version: NonEmptyStr
    thresholds: ContractPayload = Field(default_factory=dict)
    configuration_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider: str | None = None
    model_version: str | None = None
    core_version: str | None = None
    pack_version: str | None = None
    failure_injection_passed: bool | None = None
    approval_id: NonEmptyStr | None = None
    expires_at: Timestamp | None = None
    phoenix_evidence_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    phoenix_evidence_required: bool = False

    @model_validator(mode="after")
    def validate_gate(self) -> EvaluationGate:
        _reject_private_values(self.thresholds, "thresholds")
        if self.report is EvaluationOutcome.PASS and not self.approval_id:
            raise ValueError("a passing evaluation gate requires explicit approval")
        if self.report is EvaluationOutcome.PASS and self.expires_at is None:
            raise ValueError("a passing evaluation gate requires expiry")
        if (
            self.report is EvaluationOutcome.PASS
            and self.phoenix_evidence_required
            and self.phoenix_evidence_digest is None
        ):
            raise ValueError("required Phoenix evidence must include a digest")
        if self.expires_at is not None and self.expires_at <= datetime.now(UTC):
            raise ValueError("evaluation gate approval is expired")
        object.__setattr__(self, "thresholds", _freeze_json(self.thresholds))
        return self


@runtime_checkable
class EvaluationPort(Protocol):
    """Project-owned evaluation sink; implementations are non-authoritative."""

    async def submit_dataset(self, dataset: EvaluationDataset) -> bool: ...

    async def submit_run(self, run: EvaluationRun) -> bool: ...

    async def close(self) -> str: ...

    def health(self) -> ContractPayload: ...


class InMemoryEvaluationPort(EvaluationPort):
    """Deterministic repository-owned projection used with Phoenix off."""

    def __init__(self) -> None:
        self.datasets: dict[str, EvaluationDataset] = {}
        self.runs: dict[str, EvaluationRun] = {}
        self.closed = False

    async def submit_dataset(self, dataset: EvaluationDataset) -> bool:
        if self.closed:
            return False
        existing = self.datasets.get(dataset.dataset_id)
        if existing is not None and existing.digest != dataset.digest:
            raise ValueError("evaluation dataset identity is immutable")
        self.datasets[dataset.dataset_id] = dataset
        return True

    async def submit_run(self, run: EvaluationRun) -> bool:
        if self.closed:
            return False
        existing = self.runs.get(run.run_id)
        if existing is not None and existing.result_digest != run.result_digest:
            raise ValueError("evaluation run identity is immutable")
        self.runs[run.run_id] = run
        return True

    async def close(self) -> str:
        if self.closed:
            return "closed"
        self.closed = True
        return "closed"

    async def flush(self, deadline_seconds: float | None = None) -> str:
        del deadline_seconds
        return "closed" if self.closed else "flushed"

    def health(self) -> ContractPayload:
        return {
            "status": "closed" if self.closed else "ready",
            "datasets": len(self.datasets),
            "runs": len(self.runs),
        }


class NoopEvaluationPort(InMemoryEvaluationPort):
    """Disabled evaluation sink that retains no datasets or runs."""

    def __init__(self, *, reason: str = "disabled") -> None:
        super().__init__()
        self.reason = reason

    async def submit_dataset(self, dataset: EvaluationDataset) -> bool:
        del dataset
        return False

    async def submit_run(self, run: EvaluationRun) -> bool:
        del run
        return False

    def health(self) -> ContractPayload:
        return {"status": "disabled", "reason": self.reason, "datasets": 0, "runs": 0}


def dataset_digest(dataset: EvaluationDataset | Mapping[str, object]) -> str:
    """Hash a canonical dataset preimage, excluding the stored digest itself."""

    if isinstance(dataset, EvaluationDataset):
        value: object = {
            "schema_version": dataset.schema_version,
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.dataset_version,
            "redaction_version": dataset.redaction_version,
            "cases": [case.model_dump(mode="json") for case in dataset.cases],
        }
    else:
        value = dataset
    return _sha256_json(value)


def evaluation_run_digest(run: EvaluationRun | Mapping[str, object]) -> str:
    """Hash stable run inputs/results; timestamps and approval are excluded."""

    if isinstance(run, EvaluationRun):
        value: object = {
            "schema_version": run.schema_version,
            "run_id": run.run_id,
            "dataset_id": run.dataset_id,
            "dataset_digest": run.dataset_digest,
            "evaluator_version": run.evaluator_version,
            "configuration_digest": run.configuration_digest,
            "results": [result.model_dump(mode="json") for result in run.results],
            "outcome": run.outcome.value,
            "provider": run.provider,
            "model_version": run.model_version,
            "rubric_version": run.rubric_version,
            "template_version": run.template_version,
        }
    else:
        value = run
    return _sha256_json(value)


def configuration_digest(configuration: object) -> str:
    """Return a deterministic digest for evaluator configuration metadata."""

    return _sha256_json(configuration)


_PRIVATE_NAMES = frozenset(
    {
        "user",
        "user_id",
        "session",
        "session_id",
        "preference",
        "preferences",
        "memory",
        "prompt",
        "query",
        "output",
        "token",
        "cookie",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "secrets",
        "url",
        "source_url",
        "signed_url",
        "body",
        "header",
        "headers",
        "qr",
        "qr_data",
        "account",
        "account_state",
        "private",
        "private_value",
        "private_data",
        "note",
        "note_text",
        "raw",
        "raw_text",
        "raw_output",
    }
)


def _reject_private_values(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in _PRIVATE_NAMES or any(
                normalized.startswith(prefix + "_")
                for prefix in (
                    "user",
                    "session",
                    "preference",
                    "memory",
                    "prompt",
                    "token",
                    "credential",
                    "password",
                    "secret",
                    "private",
                    "account",
                    "qr",
                    "header",
                    "body",
                    "output",
                    "query",
                    "url",
                    "note",
                )
            ):
                raise ValueError(f"evaluation fixture contains private field {path}.{key}")
            _reject_private_values(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_private_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in ("bearer ", "authorization:", "cookie:", "http://", "https://")):
            raise ValueError(f"evaluation fixture contains sensitive value at {path}")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_key(key: object) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    return value.casefold().replace("-", "_")


class _FrozenDict(dict[str, Any]):
    """JSON-compatible mapping that rejects mutation after validation."""

    @staticmethod
    def _immutable() -> Never:
        raise TypeError("evaluation artifacts are immutable")

    def __setitem__(self, key: str, value: Any) -> Never:
        del key, value
        self._immutable()

    def __delitem__(self, key: str) -> Never:
        del key
        self._immutable()

    def clear(self) -> Never:
        self._immutable()

    def pop(self, key: str, default: Any = None) -> Never:
        del key, default
        self._immutable()

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, key: str, default: Any = None) -> Never:
        del key, default
        self._immutable()

    def update(self, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        self._immutable()

    def __ior__(self, value: object) -> Never:
        del value
        self._immutable()


class _FrozenList(list[Any]):
    @staticmethod
    def _immutable() -> Never:
        raise TypeError("evaluation artifacts are immutable")

    def __setitem__(self, key: object, value: object) -> Never:
        del key, value
        self._immutable()

    def __delitem__(self, key: object) -> Never:
        del key
        self._immutable()

    def append(self, value: Any) -> Never:
        del value
        self._immutable()

    def clear(self) -> Never:
        self._immutable()

    def extend(self, values: object) -> Never:
        del values
        self._immutable()

    def insert(self, index: object, value: Any) -> Never:
        del index, value
        self._immutable()

    def pop(self, index: object = -1) -> Never:
        del index
        self._immutable()

    def remove(self, value: Any) -> Never:
        del value
        self._immutable()

    def reverse(self) -> Never:
        self._immutable()

    def sort(self, *, key: Any = None, reverse: bool = False) -> Never:
        del key, reverse
        self._immutable()

    def __iadd__(self, value: object) -> Never:
        del value
        self._immutable()

    def __imul__(self, value: object) -> Never:
        del value
        self._immutable()


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


__all__ = [
    "EVALUATION_REDACTION_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationCase",
    "EvaluationCaseResult",
    "EvaluationDataset",
    "EvaluationGate",
    "EvaluationOutcome",
    "EvaluationPort",
    "EvaluationRun",
    "InMemoryEvaluationPort",
    "NoopEvaluationPort",
    "configuration_digest",
    "dataset_digest",
    "evaluation_run_digest",
]
