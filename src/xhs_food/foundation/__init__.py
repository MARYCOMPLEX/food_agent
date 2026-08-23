"""Infrastructure adapters behind project-owned contracts."""

from .base import TargetAdapterDisabled
from .config import (
    EvidenceShadowConfigView,
    ModelConfigView,
    ObjectStoreConfigView,
    ObservabilityConfigView,
    RedisConfigView,
    RepositoryConfigView,
    TargetSettings,
    TemporalConfigView,
)
from .database import RepositorySlot, SQLAlchemyDatabase, SQLAlchemyUnitOfWork
from .evidence_schema import B1_SHADOW_TABLES, SHADOW_METADATA
from .failures import (
    FoundationAdapterError,
    foundation_error_from_exception,
    foundation_failure_boundary,
)
from .object_store import Boto3ObjectStore, minio_s3_client_factory
from .observability import (
    EvidenceShadowTelemetry,
    ObservabilityBootstrap,
    correlation_attributes,
    redact_log_context,
    prometheus_labels,
)
from .redis import (
    RateLimitDecision,
    RedisEventBusAdapter,
    RedisFixedWindowRateLimiter,
    RedisHotStateContract,
    RedisIdempotencyWindow,
    RedisReplayExpiredError,
    RedisSessionWindow,
    RedisStateStore,
)
from .temporal import (
    TemporalActivityAdapter,
    TemporalTaskQueues,
    TemporalWorkflowAdapter,
    deterministic_workflow_input,
)

__all__ = [
    "Boto3ObjectStore",
    "B1_SHADOW_TABLES",
    "FoundationAdapterError",
    "EvidenceShadowTelemetry",
    "EvidenceShadowConfigView",
    "ModelConfigView",
    "ObjectStoreConfigView",
    "ObservabilityBootstrap",
    "ObservabilityConfigView",
    "RateLimitDecision",
    "RedisConfigView",
    "RedisEventBusAdapter",
    "RedisFixedWindowRateLimiter",
    "RedisHotStateContract",
    "RedisIdempotencyWindow",
    "RedisReplayExpiredError",
    "RedisSessionWindow",
    "RedisStateStore",
    "RepositoryConfigView",
    "RepositorySlot",
    "SQLAlchemyDatabase",
    "SQLAlchemyUnitOfWork",
    "SHADOW_METADATA",
    "TargetAdapterDisabled",
    "TargetSettings",
    "TemporalActivityAdapter",
    "TemporalConfigView",
    "TemporalTaskQueues",
    "TemporalWorkflowAdapter",
    "correlation_attributes",
    "deterministic_workflow_input",
    "foundation_error_from_exception",
    "foundation_failure_boundary",
    "minio_s3_client_factory",
    "prometheus_labels",
    "redact_log_context",
]
