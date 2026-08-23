"""Deterministic B2 quality, latency, request-reduction, and approval gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import (
    B2CanaryApproval,
    B2CanaryDecision,
    B2ErrorClass,
    B2QualificationObservation,
    B2QualificationThresholds,
    QueryMatchLayer,
    qualification_input_digest,
    qualify_b2_observations,
)

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "b2_qualification_v1.json"


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _observations() -> tuple[B2QualificationObservation, ...]:
    values = (
        ("exact-1", QueryMatchLayer.DETERMINISTIC, 1.2, 4, 0, B2ErrorClass.NONE),
        ("exact-2", QueryMatchLayer.DETERMINISTIC, 1.8, 3, 0, B2ErrorClass.NONE),
        ("trigram-1", QueryMatchLayer.TRIGRAM, 4.1, 4, 0, B2ErrorClass.NONE),
        ("trigram-2", QueryMatchLayer.TRIGRAM, 4.8, 3, 1, B2ErrorClass.NONE),
        ("vector-1", QueryMatchLayer.VECTOR, 8.2, 4, 1, B2ErrorClass.NONE),
        ("vector-2", QueryMatchLayer.VECTOR, 9.4, 4, 1, B2ErrorClass.CONNECTOR_TIMEOUT),
    )
    return tuple(
        B2QualificationObservation(
            case_id=case_id,
            layer=layer,
            expected_family_id="family.zigong",
            observed_family_id="family.zigong",
            legacy_result_digest=_digest(f"result:{case_id}"),
            candidate_result_digest=_digest(f"result:{case_id}"),
            latency_ms=latency,
            legacy_source_requests=legacy_requests,
            reuse_source_requests=reuse_requests,
            expected_error=error,
            observed_error=error,
        )
        for case_id, layer, latency, legacy_requests, reuse_requests, error in values
    )


def _thresholds() -> B2QualificationThresholds:
    return B2QualificationThresholds(
        minimum_result_equivalence=1.0,
        minimum_recall_by_layer={
            QueryMatchLayer.DETERMINISTIC: 1.0,
            QueryMatchLayer.TRIGRAM: 1.0,
            QueryMatchLayer.VECTOR: 1.0,
        },
        maximum_p95_latency_ms_by_layer={
            QueryMatchLayer.DETERMINISTIC: 2.0,
            QueryMatchLayer.TRIGRAM: 5.0,
            QueryMatchLayer.VECTOR: 10.0,
        },
        minimum_source_request_reduction=0.80,
        minimum_error_classification_accuracy=1.0,
    )


def _approval(
    observations: tuple[B2QualificationObservation, ...],
    thresholds: B2QualificationThresholds,
) -> B2CanaryApproval:
    return B2CanaryApproval(
        approval_id="b2-fixture-canary-20260824",
        owner="QA + Evidence",
        approved_at=datetime(2026, 8, 24, tzinfo=UTC),
        scope="offline-fixed-fixture-only",
        input_digest=qualification_input_digest(observations, thresholds),
        decision=B2CanaryDecision.APPROVED,
        notes="This approval is not a production target-stack approval.",
    )


@pytest.mark.unit
def test_fixed_observations_pass_all_b2_qualification_dimensions() -> None:
    observations = _observations()
    thresholds = _thresholds()

    report = qualify_b2_observations(
        observations,
        thresholds,
        approval=_approval(observations, thresholds),
    )

    assert report.status == "pass"
    assert report.result_equivalence == 1.0
    assert report.recall_by_layer == {
        QueryMatchLayer.DETERMINISTIC: 1.0,
        QueryMatchLayer.TRIGRAM: 1.0,
        QueryMatchLayer.VECTOR: 1.0,
    }
    assert report.p95_latency_ms_by_layer == {
        QueryMatchLayer.DETERMINISTIC: 1.8,
        QueryMatchLayer.TRIGRAM: 4.8,
        QueryMatchLayer.VECTOR: 9.4,
    }
    assert report.source_request_reduction == pytest.approx(19 / 22)
    assert report.error_classification_accuracy == 1.0
    assert report.failures == ()


@pytest.mark.unit
def test_metrics_never_self_approve_without_an_owner_record() -> None:
    report = qualify_b2_observations(_observations(), _thresholds())

    assert report.status == "blocked"
    assert report.failures == ("canary_approval_missing",)


@pytest.mark.unit
def test_approval_is_bound_to_the_exact_observation_and_threshold_digest() -> None:
    observations = _observations()
    thresholds = _thresholds()
    approval = _approval(observations, thresholds)
    changed = observations[:-1]

    report = qualify_b2_observations(changed, thresholds, approval=approval)

    assert report.status == "blocked"
    assert "canary_approval_input_mismatch" in report.failures


@pytest.mark.unit
def test_equivalence_recall_latency_reduction_and_error_regressions_fail_closed() -> None:
    original = _observations()
    regressions = (
        original[0].model_copy(update={"candidate_result_digest": _digest("changed")}),
        original[1].model_copy(update={"observed_family_id": "family.wrong"}),
        original[2].model_copy(update={"latency_ms": 50.0}),
        original[3].model_copy(update={"reuse_source_requests": 20}),
        original[4].model_copy(update={"observed_error": B2ErrorClass.UNKNOWN}),
        original[5],
    )
    thresholds = _thresholds()

    report = qualify_b2_observations(
        regressions,
        thresholds,
        approval=_approval(regressions, thresholds),
    )

    assert report.status == "fail"
    assert set(report.failures) == {
        "result_equivalence_below_threshold",
        "deterministic_recall_below_threshold",
        "trigram_p95_latency_above_threshold",
        "source_request_reduction_below_threshold",
        "error_classification_below_threshold",
    }


@pytest.mark.unit
def test_report_contains_only_metrics_digests_and_bounded_labels() -> None:
    observations = _observations()
    thresholds = _thresholds()
    report = qualify_b2_observations(
        observations,
        thresholds,
        approval=_approval(observations, thresholds),
    )
    encoded = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)

    assert "自贡哪些本地人吃的美食" not in encoded
    assert "user_id" not in encoded
    assert "session_id" not in encoded
    assert set(report.recall_by_layer) == set(QueryMatchLayer)


@pytest.mark.unit
def test_recorded_canary_fixture_replays_to_the_approved_input_digest() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    observations = tuple(
        B2QualificationObservation.model_validate(item) for item in value["observations"]
    )
    thresholds = B2QualificationThresholds.model_validate(value["thresholds"])
    approval = B2CanaryApproval.model_validate(value["approval"])

    assert approval.input_digest == qualification_input_digest(observations, thresholds)
    report = qualify_b2_observations(observations, thresholds, approval=approval)
    assert report.status == "pass"
    assert report.canary_approval_id == "b2-fixture-canary-20260824"
