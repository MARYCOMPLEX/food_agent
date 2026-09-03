"""Infrastructure adapters behind project-owned contracts.

Exports are resolved lazily so Temporal workflow sandbox imports do not eagerly
load SQLAlchemy, pgvector, boto3, or other process-only infrastructure.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "B1_SHADOW_TABLES": ("xhs_food.foundation.evidence_schema", "B1_SHADOW_TABLES"),
    "B2_QUERY_REUSE_TABLES": ("xhs_food.foundation.evidence_schema", "B2_QUERY_REUSE_TABLES"),
    "B3_MEMORY_INDEXES": ("xhs_food.foundation.memory_schema", "B3_MEMORY_INDEXES"),
    "B3_MEMORY_TABLES": ("xhs_food.foundation.memory_schema", "B3_MEMORY_TABLES"),
    "Boto3ObjectStore": ("xhs_food.foundation.object_store", "Boto3ObjectStore"),
    "EvidenceShadowConfigView": ("xhs_food.foundation.config", "EvidenceShadowConfigView"),
    "EvidenceShadowTelemetry": ("xhs_food.foundation.observability", "EvidenceShadowTelemetry"),
    "FoundationAdapterError": ("xhs_food.foundation.failures", "FoundationAdapterError"),
    "LEGACY_METADATA": ("xhs_food.foundation.legacy_schema", "LEGACY_METADATA"),
    "LEGACY_TABLES": ("xhs_food.foundation.legacy_schema", "LEGACY_TABLES"),
    "MEMORY_METADATA": ("xhs_food.foundation.memory_schema", "MEMORY_METADATA"),
    "ModelConfigView": ("xhs_food.foundation.config", "ModelConfigView"),
    "ObjectStoreConfigView": ("xhs_food.foundation.config", "ObjectStoreConfigView"),
    "ObservabilityBootstrap": ("xhs_food.foundation.observability", "ObservabilityBootstrap"),
    "ObservabilityConfigView": ("xhs_food.foundation.config", "ObservabilityConfigView"),
    "PersonalizationCanaryConfigView": (
        "xhs_food.foundation.config",
        "PersonalizationCanaryConfigView",
    ),
    "PersonalizationCanaryTelemetry": (
        "xhs_food.foundation.observability",
        "PersonalizationCanaryTelemetry",
    ),
    "RateLimitDecision": ("xhs_food.foundation.redis", "RateLimitDecision"),
    "RedisConfigView": ("xhs_food.foundation.config", "RedisConfigView"),
    "RedisEventBusAdapter": ("xhs_food.foundation.redis", "RedisEventBusAdapter"),
    "RedisFixedWindowRateLimiter": ("xhs_food.foundation.redis", "RedisFixedWindowRateLimiter"),
    "RedisHotStateContract": ("xhs_food.foundation.redis", "RedisHotStateContract"),
    "RedisIdempotencyWindow": ("xhs_food.foundation.redis", "RedisIdempotencyWindow"),
    "RedisReplayExpiredError": ("xhs_food.foundation.redis", "RedisReplayExpiredError"),
    "RedisSessionWindow": ("xhs_food.foundation.redis", "RedisSessionWindow"),
    "RedisStateStore": ("xhs_food.foundation.redis", "RedisStateStore"),
    "RedisUserSessionWindow": ("xhs_food.foundation.redis", "RedisUserSessionWindow"),
    "RefreshMediaTelemetry": ("xhs_food.foundation.observability", "RefreshMediaTelemetry"),
    "RepositoryConfigView": ("xhs_food.foundation.config", "RepositoryConfigView"),
    "RepositorySlot": ("xhs_food.foundation.database", "RepositorySlot"),
    "SHADOW_METADATA": ("xhs_food.foundation.evidence_schema", "SHADOW_METADATA"),
    "SQLAlchemyDatabase": ("xhs_food.foundation.database", "SQLAlchemyDatabase"),
    "SQLAlchemyUnitOfWork": ("xhs_food.foundation.database", "SQLAlchemyUnitOfWork"),
    "TargetAdapterDisabled": ("xhs_food.foundation.base", "TargetAdapterDisabled"),
    "TargetSettings": ("xhs_food.foundation.config", "TargetSettings"),
    "TemporalActivityAdapter": ("xhs_food.foundation.temporal", "TemporalActivityAdapter"),
    "TemporalConfigView": ("xhs_food.foundation.config", "TemporalConfigView"),
    "TemporalTaskQueues": ("xhs_food.foundation.temporal", "TemporalTaskQueues"),
    "TemporalWorkerQuota": ("xhs_food.foundation.temporal", "TemporalWorkerQuota"),
    "TemporalWorkflowAdapter": ("xhs_food.foundation.temporal", "TemporalWorkflowAdapter"),
    "build_temporal_media_worker": ("xhs_food.foundation.temporal", "build_temporal_media_worker"),
    "build_temporal_refresh_worker": (
        "xhs_food.foundation.temporal",
        "build_temporal_refresh_worker",
    ),
    "build_temporal_worker": ("xhs_food.foundation.temporal", "build_temporal_worker"),
    "claim_events": ("xhs_food.foundation.memory_schema", "claim_events"),
    "consent_events": ("xhs_food.foundation.memory_schema", "consent_events"),
    "conversation_turns": ("xhs_food.foundation.memory_schema", "conversation_turns"),
    "correlation_attributes": ("xhs_food.foundation.observability", "correlation_attributes"),
    "create_redis_client": ("xhs_food.foundation.redis", "create_redis_client"),
    "deterministic_workflow_input": (
        "xhs_food.foundation.temporal",
        "deterministic_workflow_input",
    ),
    "foundation_error_from_exception": (
        "xhs_food.foundation.failures",
        "foundation_error_from_exception",
    ),
    "foundation_failure_boundary": ("xhs_food.foundation.failures", "foundation_failure_boundary"),
    "memory_events": ("xhs_food.foundation.memory_schema", "memory_events"),
    "memory_records": ("xhs_food.foundation.memory_schema", "memory_records"),
    "memory_summaries": ("xhs_food.foundation.memory_schema", "memory_summaries"),
    "minio_s3_client_factory": ("xhs_food.foundation.object_store", "minio_s3_client_factory"),
    "outbox": ("xhs_food.foundation.memory_schema", "outbox"),
    "preference_snapshots": ("xhs_food.foundation.memory_schema", "preference_snapshots"),
    "prometheus_labels": ("xhs_food.foundation.observability", "prometheus_labels"),
    "redact_log_context": ("xhs_food.foundation.observability", "redact_log_context"),
    "session_state": ("xhs_food.foundation.memory_schema", "session_state"),
}

__all__ = [
    "Boto3ObjectStore",
    "B1_SHADOW_TABLES",
    "B2_QUERY_REUSE_TABLES",
    "B3_MEMORY_INDEXES",
    "B3_MEMORY_TABLES",
    "FoundationAdapterError",
    "MEMORY_METADATA",
    "LEGACY_METADATA",
    "LEGACY_TABLES",
    "EvidenceShadowTelemetry",
    "PersonalizationCanaryTelemetry",
    "RefreshMediaTelemetry",
    "EvidenceShadowConfigView",
    "ModelConfigView",
    "ObjectStoreConfigView",
    "ObservabilityBootstrap",
    "ObservabilityConfigView",
    "PersonalizationCanaryConfigView",
    "RateLimitDecision",
    "RedisConfigView",
    "RedisEventBusAdapter",
    "RedisFixedWindowRateLimiter",
    "RedisHotStateContract",
    "RedisIdempotencyWindow",
    "RedisReplayExpiredError",
    "RedisSessionWindow",
    "RedisStateStore",
    "RedisUserSessionWindow",
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
    "TemporalWorkerQuota",
    "TemporalWorkflowAdapter",
    "claim_events",
    "consent_events",
    "conversation_turns",
    "memory_events",
    "memory_records",
    "memory_summaries",
    "outbox",
    "preference_snapshots",
    "session_state",
    "build_temporal_worker",
    "build_temporal_media_worker",
    "build_temporal_refresh_worker",
    "correlation_attributes",
    "create_redis_client",
    "deterministic_workflow_input",
    "foundation_error_from_exception",
    "foundation_failure_boundary",
    "minio_s3_client_factory",
    "prometheus_labels",
    "redact_log_context",
]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
