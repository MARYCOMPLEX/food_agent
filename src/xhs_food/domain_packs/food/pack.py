"""Pure Food Domain Contract implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast, runtime_checkable

from xhs_food.contracts import (
    ContractError,
    ContractPayload,
    DomainPackManifest,
    ErrorCategory,
    ErrorScope,
    EvidenceBundle,
    EvidenceItem,
)
from xhs_food.contracts.base import JsonValue

from .decision import FoodDecisionPolicy
from .resources import load_food_manifest
from .workflow import FoodWorkflowPolicy

_PERSONAL_CONSTRAINT_KEYS = frozenset(
    {
        "accessibility",
        "budget",
        "diet",
        "dietary_restriction",
        "taste",
        "travel_style",
    }
)
_PUBLIC_CONSTRAINT_KEYS = frozenset({"food_type", "geo", "location", "price", "time_filter"})
_EVIDENCE_TYPES = frozenset(
    {
        "advertising_risk",
        "locality",
        "menu",
        "price",
        "restaurant_identity",
        "review_trust",
    }
)


@runtime_checkable
class FoodBehavior(Protocol):
    workflow: FoodWorkflowPolicy
    decision: FoodDecisionPolicy

    def validate_final_output(self, value: JsonValue) -> None: ...


class FoodPack:
    """Side-effect-free Food semantics and approved public decision policies."""

    def __init__(self, manifest: DomainPackManifest | None = None) -> None:
        self._manifest = manifest or load_food_manifest()
        self.workflow = FoodWorkflowPolicy()
        self.decision = FoodDecisionPolicy()

    def describe(self) -> DomainPackManifest:
        return self._manifest

    def validate_final_output(self, value: JsonValue) -> None:
        self._manifest.validate_final_output(value)

    def classify_constraints(self, value: ContractPayload) -> ContractPayload:
        classifier_version = str(value.get("classifier_version") or "food-constraints/v1")
        raw_constraints = value.get("constraints")
        constraints = raw_constraints if isinstance(raw_constraints, (list, tuple)) else ()
        results: list[JsonValue] = []
        for raw in constraints:
            if not isinstance(raw, Mapping):
                continue
            constraint_id = str(raw.get("constraint_id") or "unknown")
            key = str(raw.get("key") or "unknown")
            projection = {"key": key, "value": cast(JsonValue, raw.get("value"))}
            if key in _PERSONAL_CONSTRAINT_KEYS:
                classification, action, suffix = "personal", "personalize", "personal"
                reason_code: str | None = None
            elif key in _PUBLIC_CONSTRAINT_KEYS:
                classification, action, suffix = "public", "shared", "public"
                reason_code = None
            else:
                classification, action, suffix = "unresolved", "clarify", "unresolved"
                reason_code = "constraint_unclassified"
            results.append(
                {
                    "constraint_id": constraint_id,
                    "classification": classification,
                    "rule_id": f"{key}.{suffix}",
                    "rule_version": classifier_version,
                    "projection": projection,
                    "reason_code": reason_code,
                    "action": action,
                }
            )
        return {
            "schema_version": "domain-classify-constraints-output/v1",
            "classifier_version": classifier_version,
            "results": results,
        }

    def validate_evidence(self, evidence: EvidenceItem) -> ContractPayload:
        errors: list[JsonValue] = []
        valid = evidence.evidence_type in _EVIDENCE_TYPES
        if not valid:
            error = ContractError(
                code="FOOD_EVIDENCE_TYPE_INVALID",
                category=ErrorCategory.VALIDATION,
                scope=ErrorScope.DOMAIN_PACK,
                terminal=False,
                message=f"unsupported Food evidence type: {evidence.evidence_type}",
                boundary_ref=f"food@{self._manifest.pack_version}",
            )
            errors.append(cast(JsonValue, error.model_dump(mode="json")))
        return {
            "schema_version": "domain-validate-evidence-output/v1",
            "evidence_id": evidence.evidence_id,
            "valid": valid,
            "errors": errors,
        }

    def compute_features(
        self,
        bundle: EvidenceBundle,
        evidence_items: tuple[EvidenceItem, ...],
    ) -> ContractPayload:
        grouped: dict[str, dict[str, float]] = {}
        for evidence in evidence_items:
            claim = evidence.claim_value
            entity_id = evidence.evidence_id
            if isinstance(claim, Mapping) and isinstance(claim.get("entity_id"), str):
                entity_id = cast(str, claim["entity_id"])
            values = grouped.setdefault(entity_id, {})
            if evidence.evidence_type in _EVIDENCE_TYPES:
                values[evidence.evidence_type] = evidence.confidence
        return cast(
            ContractPayload,
            {
                "schema_version": "food-feature-set/v1",
                "bundle_id": bundle.bundle_id,
                "features": [
                    {"entity_id": entity_id, "values": values}
                    for entity_id, values in grouped.items()
                ],
            },
        )

    def score_public(self, features: ContractPayload) -> ContractPayload:
        raw_features = features.get("features")
        feature_set = raw_features if isinstance(raw_features, Mapping) else {}
        bundle_id = str(feature_set.get("bundle_id") or "unknown")
        rows = feature_set.get("features")
        feature_rows = rows if isinstance(rows, (list, tuple)) else ()
        raw_config = features.get("config")
        config = raw_config if isinstance(raw_config, Mapping) else {}
        weights = {
            key.removesuffix("_weight"): float(value)
            for key, value in config.items()
            if key.endswith("_weight")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) >= 0
        }
        scores: list[JsonValue] = []
        for row in feature_rows:
            if not isinstance(row, Mapping):
                continue
            entity_id = row.get("entity_id")
            values = row.get("values")
            if not isinstance(entity_id, str) or not isinstance(values, Mapping):
                continue
            weighted_sum = 0.0
            total_weight = 0.0
            for name, weight in weights.items():
                feature_value = values.get(name)
                if isinstance(feature_value, (int, float)) and not isinstance(feature_value, bool):
                    weighted_sum += float(feature_value) * weight
                    total_weight += weight
            score = weighted_sum / total_weight if total_weight else 0.0
            scores.append(
                {
                    "entity_id": entity_id,
                    "score": min(max(score, 0.0), 1.0),
                    "explanation_refs": [],
                }
            )
        return {
            "schema_version": "domain-score-public-output/v1",
            "policy_id": str(features.get("policy_id") or self._manifest.scoring_policy.policy_id),
            "policy_version": str(
                features.get("policy_version") or self._manifest.scoring_policy.policy_version
            ),
            "bundle_id": bundle_id,
            "scores": scores,
        }

    def build_final_output(self, value: ContractPayload) -> JsonValue:
        raw_scores = value.get("public_scores")
        score_payload = raw_scores if isinstance(raw_scores, Mapping) else {}
        rows = score_payload.get("scores")
        score_rows = rows if isinstance(rows, (list, tuple)) else ()
        recommendations: list[JsonValue] = []
        for row in score_rows:
            if not isinstance(row, Mapping):
                continue
            entity_id = row.get("entity_id")
            public_score = row.get("score")
            refs = row.get("explanation_refs")
            if not isinstance(entity_id, str) or not isinstance(public_score, (int, float)):
                continue
            recommendations.append(
                {
                    "entityId": entity_id,
                    "publicScore": float(public_score),
                    "explanationRefs": list(refs) if isinstance(refs, (list, tuple)) else [],
                }
            )
        count = len(recommendations)
        output: JsonValue = {
            "schemaVersion": "food-agent-final-output/v1",
            "summary": f"Found {count} public candidate{'s' if count != 1 else ''}.",
            "recommendations": recommendations,
        }
        self.validate_final_output(output)
        return output

    def map_error(self, error: ContractError) -> ContractError:
        return error


def create_food_pack() -> FoodPack:
    """Create one immutable-behavior Food Pack candidate for registration."""

    return FoodPack()


__all__ = ["FoodBehavior", "FoodPack", "create_food_pack"]
