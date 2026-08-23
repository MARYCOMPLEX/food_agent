"""Deterministic public-query normalization for the B1 shadow path.

The normalizer owns no persistence and never reads identity or preference
state.  Domain Packs classify raw constraints; only the public projection is
eligible for a shared Canonical Query or Family identity.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import JsonValue

from xhs_food.contracts import (
    CanonicalQuery,
    CanonicalQueryValue,
    ConstraintOperator,
    ContractPayload,
    DomainContract,
    PublicConstraint,
)
from xhs_food.contracts.evidence import ContractVersion, IsolationCoordinates, RegisteredSlug
from xhs_food.contracts.evidence_shadow import (
    CANONICAL_QUERY_CLASSIFICATION_VERSION,
    FAMILY_MATCH_VERSION,
    CanonicalQueryResult,
    ConstraintClassification,
    FamilyMatchBasis,
    PersonalConstraint,
    UnclassifiedConstraint,
)


class UnclassifiedConstraintError(ValueError):
    """Prevent an unresolved constraint from entering a shared Family key."""

    def __init__(self, constraints: tuple[UnclassifiedConstraint, ...]) -> None:
        self.constraints = constraints
        ids = ", ".join(item.constraint_id for item in constraints)
        super().__init__(f"constraints require clarification before shared reuse: {ids}")


class CanonicalQueryNormalizer:
    """Build a stable Canonical Query from a domain classifier result."""

    def __init__(
        self,
        domain_contract: DomainContract,
        *,
        normalizer_version: ContractVersion = "canonical-normalizer/v1",
        classifier_version: ContractVersion = "food-constraints/v1",
    ) -> None:
        self._domain_contract = domain_contract
        self._normalizer_version = normalizer_version
        self._classifier_version = classifier_version

    def normalize(self, value: Mapping[str, object]) -> CanonicalQueryResult:
        payload = cast(Mapping[str, object], value)
        raw_query = payload.get("query", payload)
        if not isinstance(raw_query, Mapping):
            raise ValueError("canonical query input must contain an object query")

        raw_constraints = raw_query.get("constraints", ())
        if not isinstance(raw_constraints, (list, tuple)):
            raise ValueError("canonical query constraints must be an array")
        constraint_rows = tuple(self._constraint_row(item, index) for index, item in enumerate(raw_constraints))
        classification = self._classify(constraint_rows)
        if classification.unresolved_constraints:
            raise UnclassifiedConstraintError(classification.unresolved_constraints)

        query_payload = {
            "domain": self._canonicalize(raw_query.get("domain")),
            "geo": self._canonicalize(raw_query.get("geo")),
            "intent": self._canonicalize(raw_query.get("intent")),
            "audience": sorted(
                str(item)
                for item in self._sequence(raw_query.get("audience", ()))
            ),
            "constraints": [
                item.model_dump(mode="json") for item in classification.public_constraints
            ],
            "time_range": self._canonicalize(raw_query.get("time_range")),
            "freshness_policy": self._canonicalize(raw_query.get("freshness_policy")),
        }
        isolation_value = payload.get("isolation")
        if not isinstance(isolation_value, Mapping):
            raise ValueError("canonical query input must contain isolation coordinates")
        canonical_query = CanonicalQuery(
            normalizer_version=self._normalizer_version,
            classifier_version=classification.classifier_version,
            isolation=IsolationCoordinates.model_validate(self._canonicalize(isolation_value)),
            query=CanonicalQueryValue.model_validate(query_payload),
        )
        preimage = {
            "normalizer_version": canonical_query.normalizer_version,
            "classifier_version": canonical_query.classifier_version,
            "projection": canonical_query.family_identity_projection(),
        }
        encoded = _canonical_json(preimage)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        canonical_key = f"query.{digest}"
        family_id = f"family.{canonical_query.query.domain}.{digest[:32]}"
        basis = FamilyMatchBasis(
            confidence=1.0,
            canonical_key=canonical_key,
            preimage_sha256=digest,
        )
        return CanonicalQueryResult(
            canonical_query=canonical_query,
            classification=classification,
            canonical_key=canonical_key,
            family_id=family_id,
            family_match=basis,
        )

    def _classify(
        self, constraints: tuple[dict[str, object], ...]
    ) -> ConstraintClassification:
        raw = self._domain_contract.classify_constraints(
            cast(
                ContractPayload,
                {
                    "schema_version": "domain-classify-constraints-input/v1",
                    "classifier_version": self._classifier_version,
                    "constraints": [dict(item) for item in constraints],
                },
            )
        )
        if not isinstance(raw, Mapping):
            raise ValueError("domain constraint classifier returned a non-object")
        classifier_version = str(raw.get("classifier_version") or self._classifier_version)
        result_rows = raw.get("results", ())
        if not isinstance(result_rows, (list, tuple)):
            raise ValueError("domain constraint classifier results must be an array")
        by_id = {str(item["constraint_id"]): item for item in constraints}
        if len(by_id) != len(constraints):
            raise ValueError("canonical query constraints must have unique constraint_id values")
        public: list[PublicConstraint] = []
        personal: list[PersonalConstraint] = []
        unresolved: list[UnclassifiedConstraint] = []
        classified_ids: set[str] = set()
        for item in result_rows:
            if not isinstance(item, Mapping):
                raise ValueError("domain constraint classifier returned a malformed result")
            constraint_id = str(item.get("constraint_id") or "")
            if constraint_id in classified_ids:
                raise ValueError(f"classifier returned duplicate constraint {constraint_id!r}")
            source = by_id.get(constraint_id)
            if source is None:
                raise ValueError(f"classifier returned unknown constraint {constraint_id!r}")
            classified_ids.add(constraint_id)
            projection = item.get("projection")
            if not isinstance(projection, Mapping):
                raise ValueError(f"classifier projection is missing for {constraint_id!r}")
            key = _canonical_string(projection.get("key"))
            value = cast(JsonValue, self._canonicalize(projection.get("value")))
            classification = str(item.get("classification") or "unresolved")
            rule_id = _canonical_string(item.get("rule_id") or "unclassified.rule")
            reason_code = str(item.get("reason_code") or "constraint_unclassified")
            if classification == "public":
                operator = ConstraintOperator(str(source.get("operator") or "eq"))
                public.append(
                    PublicConstraint(
                        key=cast(RegisteredSlug, key),
                        operator=operator,
                        value=value,
                        classification_rule=cast(RegisteredSlug, rule_id),
                    )
                )
            elif classification == "personal":
                personal.append(
                    PersonalConstraint(
                        constraint_id=constraint_id,
                        key=key,
                        value=value,
                        rule_id=rule_id,
                        rule_version=classifier_version,
                    )
                )
            else:
                unresolved.append(
                    UnclassifiedConstraint(
                        constraint_id=constraint_id,
                        key=key,
                        reason_code=reason_code,
                    )
                )
        missing_ids = sorted(set(by_id) - classified_ids)
        if missing_ids:
            raise ValueError(
                "domain constraint classifier omitted constraints: "
                + ", ".join(missing_ids)
            )
        public.sort(key=lambda item: _canonical_json(item.model_dump(mode="json")))
        personal.sort(key=lambda item: item.constraint_id)
        unresolved.sort(key=lambda item: item.constraint_id)
        return ConstraintClassification(
            classifier_version=classifier_version,
            public_constraints=tuple(public),
            personal_constraints=tuple(personal),
            unresolved_constraints=tuple(unresolved),
        )

    @staticmethod
    def _constraint_row(value: object, index: int) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(f"constraint at index {index} must be an object")
        row = {str(key): item for key, item in value.items()}
        row.setdefault("constraint_id", f"constraint-{index + 1}")
        return row

    @staticmethod
    def _sequence(value: object) -> Sequence[object]:
        if isinstance(value, (list, tuple)):
            return value
        raise ValueError("canonical query audience must be an array")

    @classmethod
    def _canonicalize(cls, value: object) -> object:
        if isinstance(value, str):
            return _canonical_string(value)
        if isinstance(value, Mapping):
            return {str(key): cls._canonicalize(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [cls._canonicalize(item) for item in value]
        return value


def _canonical_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("canonical query string fields must be strings")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "CANONICAL_QUERY_CLASSIFICATION_VERSION",
    "FAMILY_MATCH_VERSION",
    "CanonicalQueryNormalizer",
    "CanonicalQueryResult",
    "ConstraintClassification",
    "FamilyMatchBasis",
    "PersonalConstraint",
    "UnclassifiedConstraint",
    "UnclassifiedConstraintError",
]
