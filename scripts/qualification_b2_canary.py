"""Fail-closed evaluator for a privacy-preserving B2 canary sample.

The input contains only B2 observation digests, metrics, thresholds, and an
optional owner approval. It does not collect production traffic and it never
turns a fixture approval into a production approval.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xhs_food.contracts import (
    B2CanaryApproval,
    B2QualificationObservation,
    B2QualificationReport,
    B2QualificationThresholds,
    qualify_b2_observations,
)


def evaluate_payload(
    payload: Mapping[str, Any], *, require_production_scope: bool = False
) -> B2QualificationReport:
    """Evaluate one serialized sample and keep missing approval fail-closed."""

    observations = tuple(
        B2QualificationObservation.model_validate(item)
        for item in payload.get("observations", ())
    )
    thresholds = B2QualificationThresholds.model_validate(payload.get("thresholds", {}))
    raw_approval = payload.get("approval")
    approval = (
        B2CanaryApproval.model_validate(raw_approval)
        if isinstance(raw_approval, Mapping)
        else None
    )
    report = qualify_b2_observations(observations, thresholds, approval=approval)
    if require_production_scope and (
        approval is None or not approval.scope.startswith("production/")
    ):
        failures = tuple(dict.fromkeys((*report.failures, "production_scope_required")))
        report = report.model_copy(update={"status": "blocked", "failures": failures})
    return report


def _exit_code(status: str) -> int:
    return {"pass": 0, "fail": 1, "blocked": 2}[status]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file with observations/thresholds/approval")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--require-production-scope",
        action="store_true",
        help="Require an owner approval scope beginning with production/",
    )
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("B2 canary input must be a JSON object")
    report = evaluate_payload(
        payload, require_production_scope=args.require_production_scope
    )
    encoded = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    print(encoded)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return _exit_code(report.status)


if __name__ == "__main__":
    raise SystemExit(main())
