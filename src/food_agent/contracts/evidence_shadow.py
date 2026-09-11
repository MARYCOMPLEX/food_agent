"""Versioned contracts shared by the B1 Canonical Query shadow path."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from .base import ContractModel, NonEmptyStr
from .evidence import CanonicalQuery, ContractVersion, PublicConstraint

CANONICAL_QUERY_CLASSIFICATION_VERSION = "canonical-query-classification/v1"
FAMILY_MATCH_VERSION = "family-match/v1"


class PersonalConstraint(ContractModel):
    """A user/session constraint excluded from shared query identity."""

    constraint_id: NonEmptyStr
    key: NonEmptyStr
    value: JsonValue
    rule_id: NonEmptyStr
    rule_version: ContractVersion


class UnclassifiedConstraint(ContractModel):
    """A constraint that must follow clarification or an explicit no-share path."""

    constraint_id: NonEmptyStr
    key: NonEmptyStr
    reason_code: NonEmptyStr


class ConstraintClassification(ContractModel):
    """Versioned output of the public/personal constraint partition."""

    schema_version: Literal["canonical-query-classification/v1"] = (
        CANONICAL_QUERY_CLASSIFICATION_VERSION
    )
    classifier_version: ContractVersion
    public_constraints: tuple[PublicConstraint, ...] = ()
    personal_constraints: tuple[PersonalConstraint, ...] = ()
    unresolved_constraints: tuple[UnclassifiedConstraint, ...] = ()


class FamilyMatchBasis(ContractModel):
    """Explainable deterministic matching evidence retained by a shadow writer."""

    basis_version: Literal["family-match/v1"] = FAMILY_MATCH_VERSION
    strategy: Literal["deterministic"] = "deterministic"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: tuple[NonEmptyStr, ...] = ("exact_canonical_projection",)
    canonical_key: NonEmptyStr
    preimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CanonicalQueryResult(ContractModel):
    """Normalizer output used by B1 shadow persistence, not by response reads."""

    canonical_query: CanonicalQuery
    classification: ConstraintClassification
    canonical_key: NonEmptyStr
    family_id: NonEmptyStr
    family_match: FamilyMatchBasis


__all__ = [
    "CANONICAL_QUERY_CLASSIFICATION_VERSION",
    "FAMILY_MATCH_VERSION",
    "CanonicalQueryResult",
    "ConstraintClassification",
    "FamilyMatchBasis",
    "PersonalConstraint",
    "UnclassifiedConstraint",
]
