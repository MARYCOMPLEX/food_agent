"""Pure Travel Domain Contract implementation."""

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

from .resources import load_travel_manifest

_PERSONAL_KEYS = frozenset({"budget", "travel_style", "accessibility", "audience"})
_PUBLIC_KEYS = frozenset({"geo", "season", "time_range", "ticket", "crowding"})
_EVIDENCE_TYPES = frozenset(
    {"attraction", "route", "seasonality", "ticket", "crowding", "duration", "audience"}
)


@runtime_checkable
class TravelBehavior(Protocol):
    def describe(self) -> DomainPackManifest: ...


class TravelPack:
    """Side-effect-free travel semantics; all runtime access stays in adapters."""

    def __init__(self, manifest: DomainPackManifest | None = None) -> None:
        self._manifest = manifest or load_travel_manifest()

    def describe(self) -> DomainPackManifest:
        return self._manifest

    def classify_constraints(self, value: ContractPayload) -> ContractPayload:
        raw = value.get("constraints")
        constraints = raw if isinstance(raw, (list, tuple)) else ()
        results: list[JsonValue] = []
        for item in constraints:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("key") or "unknown")
            if key in _PERSONAL_KEYS:
                classification, action = "personal", "personalize"
            elif key in _PUBLIC_KEYS:
                classification, action = "public", "shared"
            else:
                classification, action = "unresolved", "clarify"
            results.append(
                {
                    "constraint_id": str(item.get("constraint_id") or "unknown"),
                    "classification": classification,
                    "rule_id": f"{key}.travel",
                    "rule_version": "travel-constraints/v1",
                    "projection": {"key": key, "value": cast(JsonValue, item.get("value"))},
                    "reason_code": "constraint_unclassified" if classification == "unresolved" else None,
                    "action": action,
                }
            )
        return {"schema_version": "domain-classify-constraints-output/v1", "results": results}

    def validate_evidence(self, evidence: EvidenceItem) -> ContractPayload:
        valid = evidence.evidence_type in _EVIDENCE_TYPES
        errors: list[JsonValue] = []
        if not valid:
            errors.append(
                cast(
                    JsonValue,
                    ContractError(
                        code="TRAVEL_EVIDENCE_TYPE_INVALID",
                        category=ErrorCategory.VALIDATION,
                        scope=ErrorScope.DOMAIN_PACK,
                        terminal=False,
                        message=f"unsupported Travel evidence type: {evidence.evidence_type}",
                        boundary_ref=f"travel@{self._manifest.pack_version}",
                    ).model_dump(mode="json"),
                )
            )
        return {"schema_version": "domain-validate-evidence-output/v1", "valid": valid, "errors": errors}

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
            if evidence.evidence_type in _EVIDENCE_TYPES:
                grouped.setdefault(entity_id, {})[evidence.evidence_type] = evidence.confidence
        return {
            "schema_version": "travel-feature-set/v1",
            "bundle_id": bundle.bundle_id,
            "features": [{"entity_id": key, "values": values} for key, values in grouped.items()],
        }

    def score_public(self, features: ContractPayload) -> ContractPayload:
        rows = features.get("features")
        rows = rows if isinstance(rows, (list, tuple)) else ()
        scores: list[JsonValue] = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("entity_id"), str):
                continue
            values = row.get("values")
            values = values if isinstance(values, Mapping) else {}
            numbers = [float(value) for value in values.values() if isinstance(value, (int, float))]
            score = sum(numbers) / len(numbers) if numbers else 0.0
            scores.append({"entity_id": row["entity_id"], "score": min(max(score, 0.0), 1.0), "explanation_refs": []})
        return {"schema_version": "domain-score-public-output/v1", "scores": scores}

    def build_final_output(self, value: ContractPayload) -> JsonValue:
        raw = value.get("public_scores")
        payload = raw if isinstance(raw, Mapping) else {}
        rows = payload.get("scores")
        rows = rows if isinstance(rows, (list, tuple)) else ()
        itineraries: list[JsonValue] = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("entity_id"), str):
                continue
            score = row.get("score")
            if not isinstance(score, (int, float)):
                continue
            itineraries.append(
                {
                    "entityId": row["entity_id"],
                    "publicScore": float(score),
                    "stops": list(row.get("stops", ())) if isinstance(row.get("stops"), (list, tuple)) else [],
                    "season": str(row.get("season", "")),
                    "ticket": str(row.get("ticket", "")),
                    "crowding": str(row.get("crowding", "")),
                    "durationMinutes": int(row.get("duration_minutes", 0)),
                    "suitableFor": list(row.get("suitable_for", ())) if isinstance(row.get("suitable_for"), (list, tuple)) else [],
                    "explanationRefs": list(row.get("explanation_refs", ())) if isinstance(row.get("explanation_refs"), (list, tuple)) else [],
                }
            )
        output: JsonValue = {
            "schemaVersion": "travel-agent-final-output/v1",
            "summary": f"Found {len(itineraries)} travel itinerary{'ies' if len(itineraries) != 1 else ''}.",
            "itineraries": itineraries,
        }
        self._manifest.validate_final_output(output)
        return output

    def map_error(self, error: ContractError) -> ContractError:
        return error


def create_travel_pack() -> TravelPack:
    return TravelPack()


__all__ = ["TravelBehavior", "TravelPack", "create_travel_pack"]
