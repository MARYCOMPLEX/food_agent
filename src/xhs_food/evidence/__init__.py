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
from .diff import ShadowDiffApproval, ShadowDifference, ShadowDiffReport, compare_shadow_legacy
from .embedding_shadow import (
    EmbeddingBackfillInput,
    EmbeddingCompareStatus,
    EmbeddingShadowComparison,
    EmbeddingShadowRepository,
    EmbeddingShadowRow,
    EmbeddingShadowService,
)
from .query_reuse import QueryFamilyReuseService, RefreshSingleFlightService
from .shadow_writer import (
    EvidenceShadowGate,
    EvidenceShadowPolicy,
    EvidenceShadowSettings,
    EvidenceShadowSink,
    ShadowSourceConnector,
    ShadowWriteRecord,
    build_shadow_record,
    write_shadow_record,
)
from .source import (
    CanonicalSourceBatchNormalizer,
    EvidenceQuarantineError,
    SourceNormalizationError,
    quarantine_evidence,
    validate_evidence_provenance,
)

__all__ = [
    "CANONICAL_QUERY_CLASSIFICATION_VERSION",
    "FAMILY_MATCH_VERSION",
    "CanonicalQueryNormalizer",
    "CanonicalSourceBatchNormalizer",
    "CanonicalQueryResult",
    "ConstraintClassification",
    "FamilyMatchBasis",
    "PersonalConstraint",
    "UnclassifiedConstraint",
    "UnclassifiedConstraintError",
    "ShadowDiffApproval",
    "ShadowDiffReport",
    "ShadowDifference",
    "EvidenceQuarantineError",
    "EmbeddingBackfillInput",
    "EmbeddingCompareStatus",
    "EmbeddingShadowComparison",
    "EmbeddingShadowRepository",
    "EmbeddingShadowRow",
    "EmbeddingShadowService",
    "QueryFamilyReuseService",
    "RefreshSingleFlightService",
    "EvidenceShadowPolicy",
    "EvidenceShadowGate",
    "EvidenceShadowSettings",
    "EvidenceShadowSink",
    "ShadowSourceConnector",
    "ShadowWriteRecord",
    "SourceNormalizationError",
    "quarantine_evidence",
    "build_shadow_record",
    "compare_shadow_legacy",
    "validate_evidence_provenance",
    "write_shadow_record",
]
