"""Versioned milestone manifests and deterministic evaluation datasets."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import EvaluationDataset
from xhs_food.foundation import DeterministicEvaluator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "openspec" / "changes" / "enable-evidence-reuse-memory-phoenix"
MILESTONES = ("b1", "b2", "b3", "observability")
pytestmark = pytest.mark.unit


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("milestone", MILESTONES)
def test_milestone_manifest_references_versioned_immutable_dataset(milestone: str) -> None:
    manifest = _read_json(FIXTURE_ROOT / "fixtures" / f"qualification-manifest-{milestone}-v1.json")
    dataset_ref = manifest["dataset"]
    assert isinstance(dataset_ref, dict)
    assert manifest["schemaVersion"] == "qualification-manifest/v1"
    assert manifest["milestone"] == milestone
    assert manifest["evaluator"] == {
        "version": "deterministic-exact/v1",
        "deterministic": True,
    }
    assert dataset_ref["schemaVersion"] == "evaluation/v1"
    assert dataset_ref["version"] == "v1"

    dataset_path = FIXTURE_ROOT / str(dataset_ref["path"])
    dataset_payload = _read_json(dataset_path)
    dataset = EvaluationDataset.model_validate(dataset_payload)

    assert dataset_payload["digest"] == dataset.digest
    assert dataset.dataset_version == "v1"
    assert len(dataset.cases) >= 4
    assert any("privacy" in case.tags or "redaction" in case.tags for case in dataset.cases)
    assert manifest["requiredObservations"]
    assert manifest["failureInjection"]
    assert manifest["thresholds"]
    assert manifest["rollback"]


@pytest.mark.parametrize("milestone", MILESTONES)
def test_milestone_dataset_reruns_have_stable_digest_and_no_raw_private_values(
    milestone: str,
) -> None:
    path = FIXTURE_ROOT / "fixtures" / f"evaluation-dataset-{milestone}-v1.json"
    payload = _read_json(path)
    first = EvaluationDataset.model_validate(payload)
    second = EvaluationDataset.model_validate(json.loads(json.dumps(payload)))

    assert first.digest == second.digest == payload["digest"]
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "Bearer " not in serialized
    assert "https://" not in serialized
    assert "authorization:" not in serialized
    assert "cookie:" not in serialized

    evaluator = DeterministicEvaluator()
    actuals = {case.case_id: case.expected for case in first.cases}
    created_at = datetime(2026, 9, 5, tzinfo=UTC)
    run_one = evaluator.evaluate(
        first,
        actuals,
        configuration={"fixture": milestone},
        created_at=created_at,
    )
    run_two = evaluator.evaluate(
        second,
        actuals,
        configuration={"fixture": milestone},
        created_at=created_at,
    )

    assert run_one.result_digest == run_two.result_digest
    assert run_one.dataset_digest == first.digest
    assert all(result.outcome == "pass" for result in run_one.results)


def test_aggregate_manifest_points_to_all_milestone_artifacts() -> None:
    manifest = _read_json(FIXTURE_ROOT / "fixtures" / "qualification-manifest-v1.json")

    assert manifest["schemaVersion"] == "qualification-manifest/v1"
    assert manifest["evaluatorVersion"] == "deterministic-exact/v1"
    assert set(manifest["datasets"]) == set(MILESTONES)
    assert set(manifest["milestoneManifests"]) == set(MILESTONES)
    for milestone in MILESTONES:
        assert (FIXTURE_ROOT / str(manifest["datasets"][milestone])).exists()
        assert (FIXTURE_ROOT / str(manifest["milestoneManifests"][milestone])).exists()
