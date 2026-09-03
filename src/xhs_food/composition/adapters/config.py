"""Translate legacy Settings into immutable owner-specific views."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from xhs_food.config import Settings
from xhs_food.foundation.config import (
    EvidenceShadowConfigView,
    ModelConfigView,
    ObjectStoreConfigView,
    ObservabilityConfigView,
    PersonalizationCanaryConfigView,
    RedisConfigView,
    RepositoryConfigView,
    TargetSettings,
    TemporalConfigView,
)


@dataclass(frozen=True, slots=True)
class OwnerConfigFacade:
    model: ModelConfigView
    repositories: RepositoryConfigView
    redis: RedisConfigView
    temporal: TemporalConfigView
    object_store: ObjectStoreConfigView
    observability: ObservabilityConfigView
    evidence_shadow: EvidenceShadowConfigView
    personalization_canary: PersonalizationCanaryConfigView


def build_owner_config(
    legacy: Settings,
    target: TargetSettings,
) -> OwnerConfigFacade:
    enabled = target.target_adapters_enabled
    return OwnerConfigFacade(
        model=ModelConfigView(
            api_key=SecretStr(legacy.openai_api_key) if legacy.openai_api_key else None,
            base_url=legacy.openai_api_base,
            model=legacy.default_llm_model,
            temperature=legacy.llm_temperature,
            max_tokens=legacy.llm_max_tokens,
            reasoning_effort=legacy.llm_reasoning_effort,
        ),
        repositories=RepositoryConfigView(
            legacy_database_url=legacy.resolved_database_url(),
            target_database_url=target.database_url or legacy.resolved_database_url(),
            target_enabled=enabled,
        ),
        redis=RedisConfigView(
            url=legacy.resolved_redis_url(),
            event_stream_ttl_seconds=legacy.event_stream_ttl_seconds,
            event_stream_maxlen=legacy.event_stream_maxlen,
        ),
        temporal=TemporalConfigView(
            enabled=enabled,
            reliable_task_lifecycle=target.reliable_task_lifecycle,
            address=target.temporal_address,
            namespace=target.temporal_namespace,
            research_queue=target.temporal_research_queue,
            refresh_queue=target.temporal_refresh_queue,
            media_queue=target.temporal_media_queue,
            refresh_enabled=target.refresh_enabled,
            media_enabled=target.media_enabled,
        ),
        object_store=ObjectStoreConfigView(
            enabled=enabled,
            endpoint_url=target.object_store_endpoint_url,
            bucket=target.object_store_bucket,
            region=target.object_store_region,
            access_key=target.object_store_access_key,
            secret_key=target.object_store_secret_key,
            max_concurrency=target.object_store_max_concurrency,
            multipart_threshold=target.object_store_multipart_threshold,
            multipart_chunk_size=target.object_store_multipart_chunk_size,
            max_bytes=target.object_store_max_bytes,
            allowed_content_types=target.object_store_allowed_content_types,
            environment=target.object_store_environment,
            server_side_encryption=target.object_store_server_side_encryption,
            encryption_key_ref=target.object_store_encryption_key_ref,
            signed_url_ttl_seconds=target.object_store_signed_url_ttl_seconds,
            orphan_grace_seconds=target.object_store_orphan_grace_seconds,
        ),
        observability=ObservabilityConfigView(
            enabled=target.otel_enabled,
            service_name=target.otel_service_name,
            exporter_endpoint=target.otel_exporter_endpoint,
        ),
        evidence_shadow=EvidenceShadowConfigView(
            enabled=target.evidence_shadow_enabled,
            sample_rate=target.evidence_shadow_sample_rate,
            write_budget=target.evidence_shadow_write_budget,
        ),
        personalization_canary=PersonalizationCanaryConfigView(
            mode=target.personalization_canary_mode,
            sample_rate=target.personalization_canary_sample_rate,
            projection_warmup_enabled=target.personalization_projection_warmup_enabled,
        ),
    )


__all__ = ["OwnerConfigFacade", "build_owner_config"]
