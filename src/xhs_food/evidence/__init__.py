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

from .bundle_lifecycle import BundleLifecycleService
from .bundle_refresh import (
    BundleRefreshService,
    InMemoryBundleDerivationRepository,
    build_candidate_bundle,
)
from .canonical import (
    CanonicalQueryNormalizer,
    UnclassifiedConstraintError,
)
from .continuous_refresh import ContinuousRefreshCoordinator
from .diff import ShadowDiffApproval, ShadowDifference, ShadowDiffReport, compare_shadow_legacy
from .embedding_shadow import (
    EmbeddingBackfillInput,
    EmbeddingCompareStatus,
    EmbeddingProducer,
    EmbeddingShadowComparison,
    EmbeddingShadowRepository,
    EmbeddingShadowRow,
    EmbeddingShadowService,
    ProfileBackfillQuality,
    ProfileBackfillService,
)
from .explicit_refresh import ExplicitRefreshRequestMapper, ExplicitRefreshService
from .media_pipeline import EvidenceExtractorRegistry, MediaAssetFetcher, MediaProcessorRegistry
from .query_reuse import (
    DomainPackFreshnessPolicyAdapter,
    InMemoryQueryFamilyRepository,
    QueryFamilyReuseService,
    RefreshSingleFlightService,
    freshness_policy_from_domain_pack,
)
from .query_reuse_read import QueryReuseReadService
from .shadow_writer import (
    CanonicalQueryShadowSink,
    EvidenceShadowGate,
    EvidenceShadowPolicy,
    EvidenceShadowSettings,
    EvidenceShadowSink,
    ShadowConnectorFactory,
    ShadowSourceConnector,
    ShadowWriteRecord,
    build_shadow_connector_factory,
    build_shadow_record,
    source_batch_identity,
    write_shadow_record,
)
from .source import (
    CanonicalSourceBatchNormalizer,
    EvidenceQuarantineError,
    SourceNormalizationError,
    evidence_content_hash,
    quarantine_evidence,
    validate_evidence_provenance,
)
from .telemetry import B1ShadowTelemetry, ShadowOutcome, ShadowTelemetryEvent

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
    "EmbeddingProducer",
    "EmbeddingShadowComparison",
    "EmbeddingShadowRepository",
    "EmbeddingShadowRow",
    "EmbeddingShadowService",
    "ProfileBackfillQuality",
    "ProfileBackfillService",
    "BundleLifecycleService",
    "BundleRefreshService",
    "ContinuousRefreshCoordinator",
    "EvidenceExtractorRegistry",
    "MediaAssetFetcher",
    "MediaProcessorRegistry",
    "InMemoryBundleDerivationRepository",
    "build_candidate_bundle",
    "ExplicitRefreshService",
    "ExplicitRefreshRequestMapper",
    "QueryFamilyReuseService",
    "DomainPackFreshnessPolicyAdapter",
    "InMemoryQueryFamilyRepository",
    "RefreshSingleFlightService",
    "freshness_policy_from_domain_pack",
    "QueryReuseReadService",
    "EvidenceShadowPolicy",
    "EvidenceShadowGate",
    "EvidenceShadowSettings",
    "EvidenceShadowSink",
    "CanonicalQueryShadowSink",
    "ShadowConnectorFactory",
    "ShadowSourceConnector",
    "ShadowWriteRecord",
    "build_shadow_connector_factory",
    "SourceNormalizationError",
    "quarantine_evidence",
    "build_shadow_record",
    "source_batch_identity",
    "evidence_content_hash",
    "compare_shadow_legacy",
    "validate_evidence_provenance",
    "write_shadow_record",
    "B1ShadowTelemetry",
    "ShadowOutcome",
    "ShadowTelemetryEvent",
]
