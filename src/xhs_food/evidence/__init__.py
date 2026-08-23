"""Evidence Intelligence value transformations kept outside runtime adapters."""

from xhs_food.contracts.evidence_shadow import (
    CANONICAL_QUERY_CLASSIFICATION_VERSION,
    FAMILY_MATCH_VERSION,
    CanonicalQueryResult,
    ConstraintClassification,
    FamilyMatchBasis,
    PersonalConstraint,
    UnclassifiedConstraint,
)

from .canonical import (
    CanonicalQueryNormalizer,
    UnclassifiedConstraintError,
)

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
