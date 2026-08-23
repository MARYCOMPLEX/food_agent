"""Target-only settings and immutable owner-scoped configuration views."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TargetSettings(BaseSettings):
    """Additive target settings; legacy names and defaults remain untouched."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MODULAR_",
        case_sensitive=False,
        extra="ignore",
    )

    target_adapters_enabled: bool = False
    # B0 is opt-in and has no effect unless the Composition Root is supplied
    # with durable Temporal/PostgreSQL adapters.  Legacy routing remains the
    # default for every existing deployment.
    reliable_task_lifecycle: bool = False
    evidence_shadow_enabled: bool = False
    evidence_shadow_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_shadow_write_budget: int = Field(default=0, ge=0)
    database_url: str | None = None
    food_pack_version: Literal["1.0.0", "legacy/v1"] = "1.0.0"
    research_core_version: Literal["shared/v1", "legacy/v1"] = "shared/v1"

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_research_queue: str = "research"
    temporal_refresh_queue: str = "refresh"
    temporal_media_queue: str = "media"

    object_store_endpoint_url: str | None = None
    object_store_bucket: str = "food-agent"
    object_store_region: str = "us-east-1"
    object_store_access_key: SecretStr | None = None
    object_store_secret_key: SecretStr | None = None
    object_store_max_concurrency: int = Field(default=4, ge=1, le=64)
    object_store_multipart_threshold: int = Field(default=8 * 1024 * 1024, ge=5 * 1024 * 1024)

    otel_enabled: bool = False
    otel_service_name: str = "food-agent"
    otel_exporter_endpoint: str | None = None

    @model_validator(mode="after")
    def validate_distinct_task_queues(self) -> TargetSettings:
        queues = {
            self.temporal_research_queue,
            self.temporal_refresh_queue,
            self.temporal_media_queue,
        }
        if len(queues) != 3:
            raise ValueError("Temporal Research, Refresh, and Media queues must be distinct")
        return self


class _OwnerView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelConfigView(_OwnerView):
    api_key: SecretStr | None
    base_url: str
    model: str
    temperature: float
    max_tokens: int


class RepositoryConfigView(_OwnerView):
    legacy_database_url: str | None
    target_database_url: str | None
    target_enabled: bool


class RedisConfigView(_OwnerView):
    url: str | None
    session_window_size: int = 20
    session_ttl_seconds: int = 86_400
    event_stream_ttl_seconds: int = 3_600
    event_stream_maxlen: int = 1_000


class TemporalConfigView(_OwnerView):
    enabled: bool
    reliable_task_lifecycle: bool = False
    address: str
    namespace: str
    research_queue: str
    refresh_queue: str
    media_queue: str


class ObjectStoreConfigView(_OwnerView):
    enabled: bool
    endpoint_url: str | None
    bucket: str
    region: str
    access_key: SecretStr | None
    secret_key: SecretStr | None
    max_concurrency: int
    multipart_threshold: int


class ObservabilityConfigView(_OwnerView):
    enabled: bool
    service_name: str
    exporter_endpoint: str | None


class EvidenceShadowConfigView(_OwnerView):
    enabled: bool
    sample_rate: float
    write_budget: int


__all__ = [
    "ModelConfigView",
    "EvidenceShadowConfigView",
    "ObjectStoreConfigView",
    "ObservabilityConfigView",
    "RedisConfigView",
    "RepositoryConfigView",
    "TargetSettings",
    "TemporalConfigView",
]
