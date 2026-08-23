"""Versioned, privacy-preserving qualification contracts for B2 read reuse."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyStr, Timestamp
from .query_reuse import QueryMatchLayer

B2_QUALIFICATION_VERSION = "b2-qualification/v1"


class B2ErrorClass(StrEnum):
    NONE = "none"
    AUTHORIZATION = "authorization"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CONNECTOR_TIMEOUT = "connector_timeout"
    MALFORMED_EVIDENCE = "malformed_evidence"
    STALE_BUNDLE = "stale_bundle"
    UNKNOWN = "unknown"


class B2CanaryDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class B2QualificationObservation(ContractModel):
    """One replayable observation; payloads are represented by public digests."""

    schema_version: Literal["b2-qualification/v1"] = B2_QUALIFICATION_VERSION
    case_id: NonEmptyStr
    layer: QueryMatchLayer
    expected_family_id: str | None = None
    observed_family_id: str | None = None
    legacy_result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    legacy_source_requests: int = Field(ge=0)
    reuse_source_requests: int = Field(ge=0)
    expected_error: B2ErrorClass = B2ErrorClass.NONE
    observed_error: B2ErrorClass = B2ErrorClass.NONE

    @model_validator(mode="after")
    def validate_match_identity(self) -> B2QualificationObservation:
        if self.expected_family_id is None and self.observed_family_id is not None:
            raise ValueError("an observed Family requires an expected Family")
        return self


class B2QualificationThresholds(ContractModel):
    """Explicit gates; production values remain an owner-approved input."""

    schema_version: Literal["b2-qualification/v1"] = B2_QUALIFICATION_VERSION
    minimum_result_equivalence: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_recall_by_layer: dict[QueryMatchLayer, float] = Field(default_factory=dict)
    maximum_p95_latency_ms_by_layer: dict[QueryMatchLayer, float] = Field(default_factory=dict)
    minimum_source_request_reduction: float = Field(default=0.0, ge=0.0, le=1.0)
    minimum_error_classification_accuracy: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_layer_values(self) -> B2QualificationThresholds:
        if any(value < 0 for value in self.maximum_p95_latency_ms_by_layer.values()):
            raise ValueError("latency thresholds must be non-negative")
        return self


class B2CanaryApproval(ContractModel):
    schema_version: Literal["b2-qualification/v1"] = B2_QUALIFICATION_VERSION
    approval_id: NonEmptyStr
    owner: NonEmptyStr
    approved_at: Timestamp
    scope: NonEmptyStr
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: B2CanaryDecision
    notes: str = ""


class B2QualificationReport(ContractModel):
    schema_version: Literal["b2-qualification/v1"] = B2_QUALIFICATION_VERSION
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_size: int = Field(ge=1)
    result_equivalence: float = Field(ge=0.0, le=1.0)
    recall_by_layer: dict[QueryMatchLayer, float]
    p95_latency_ms_by_layer: dict[QueryMatchLayer, float]
    source_request_reduction: float
    error_classification_accuracy: float = Field(ge=0.0, le=1.0)
    status: Literal["pass", "fail", "blocked"]
    failures: tuple[NonEmptyStr, ...] = ()
    canary_approval_id: str | None = None


def qualify_b2_observations(
    observations: tuple[B2QualificationObservation, ...],
    thresholds: B2QualificationThresholds,
    *,
    approval: B2CanaryApproval | None = None,
) -> B2QualificationReport:
    """Evaluate a fixed sample without exposing result payloads or user identity."""

    if not observations:
        raise ValueError("at least one B2 qualification observation is required")
    input_digest = qualification_input_digest(observations, thresholds)
    failures: list[str] = []
    equivalence = _ratio(
        sum(item.legacy_result_digest == item.candidate_result_digest for item in observations),
        len(observations),
    )
    if equivalence < thresholds.minimum_result_equivalence:
        failures.append("result_equivalence_below_threshold")

    recall_by_layer: dict[QueryMatchLayer, float] = {}
    p95_by_layer: dict[QueryMatchLayer, float] = {}
    for layer in QueryMatchLayer:
        layer_items = tuple(item for item in observations if item.layer is layer)
        expected = tuple(item for item in layer_items if item.expected_family_id is not None)
        recall = _ratio(
            sum(item.observed_family_id == item.expected_family_id for item in expected),
            len(expected),
        )
        recall_by_layer[layer] = recall
        if layer in thresholds.minimum_recall_by_layer and not expected:
            failures.append(f"{layer.value}_recall_has_no_eligible_cases")
        if layer in thresholds.minimum_recall_by_layer and recall < thresholds.minimum_recall_by_layer[layer]:
            failures.append(f"{layer.value}_recall_below_threshold")
        p95 = _percentile95(tuple(item.latency_ms for item in layer_items)) if layer_items else 0.0
        p95_by_layer[layer] = p95
        maximum = thresholds.maximum_p95_latency_ms_by_layer.get(layer)
        if maximum is not None and (not layer_items or p95 > maximum):
            failures.append(f"{layer.value}_p95_latency_above_threshold")

    legacy_requests = sum(item.legacy_source_requests for item in observations)
    reuse_requests = sum(item.reuse_source_requests for item in observations)
    reduction = _ratio(legacy_requests - reuse_requests, legacy_requests)
    if legacy_requests == 0:
        failures.append("source_request_baseline_missing")
    elif reduction < thresholds.minimum_source_request_reduction:
        failures.append("source_request_reduction_below_threshold")

    error_accuracy = _ratio(
        sum(item.expected_error is item.observed_error for item in observations),
        len(observations),
    )
    if error_accuracy < thresholds.minimum_error_classification_accuracy:
        failures.append("error_classification_below_threshold")

    status: Literal["pass", "fail", "blocked"] = "pass"
    if approval is None:
        status = "blocked"
        failures.append("canary_approval_missing")
    elif approval.input_digest != input_digest:
        status = "blocked"
        failures.append("canary_approval_input_mismatch")
    elif approval.decision is not B2CanaryDecision.APPROVED:
        status = "blocked"
        failures.append("canary_approval_rejected")
    elif failures:
        status = "fail"
    return B2QualificationReport(
        input_digest=input_digest,
        sample_size=len(observations),
        result_equivalence=equivalence,
        recall_by_layer=recall_by_layer,
        p95_latency_ms_by_layer=p95_by_layer,
        source_request_reduction=reduction,
        error_classification_accuracy=error_accuracy,
        status=status,
        failures=tuple(failures),
        canary_approval_id=approval.approval_id if approval is not None else None,
    )


def qualification_input_digest(
    observations: tuple[B2QualificationObservation, ...],
    thresholds: B2QualificationThresholds,
) -> str:
    value = {
        "observations": [item.model_dump(mode="json") for item in observations],
        "thresholds": thresholds.model_dump(mode="json"),
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 1.0


def _percentile95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


__all__ = [
    "B2CanaryApproval",
    "B2CanaryDecision",
    "B2ErrorClass",
    "B2QualificationObservation",
    "B2QualificationReport",
    "B2QualificationThresholds",
    "B2_QUALIFICATION_VERSION",
    "qualification_input_digest",
    "qualify_b2_observations",
]
