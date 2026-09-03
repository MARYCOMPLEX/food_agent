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
    personalization_canary_mode: Literal["off", "shadow", "canary"] = "off"
    personalization_canary_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    personalization_projection_warmup_enabled: bool = True
    database_url: str | None = None
    food_pack_version: Literal["1.0.0", "legacy/v1"] = "1.0.0"
    research_core_version: Literal["shared/v1", "legacy/v1"] = "shared/v1"

    # Provider account services are external, independently deployable HTTP
    # and/or MCP services.  The JSON value contains only service metadata and
    # opaque auth references; it never contains a token or cookie.
    account_services_json: str | None = None
    account_services_file: str | None = None
    account_service_refresh_seconds: int = Field(default=60, ge=5, le=86_400)
    # Managed MCP tools are fail-closed. The JSON document is validated into
    # AgentToolPolicy by the Composition Root and contains no credentials.
    agent_mcp_tool_policy_json: str | None = None

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_research_queue: str = "research"
    temporal_refresh_queue: str = "refresh"
    temporal_media_queue: str = "media"
    # Background workloads are opt-in.  A queue may be registered only after
    # the corresponding operational qualification gate has passed.
    refresh_enabled: bool = False
    media_enabled: bool = False

    object_store_endpoint_url: str | None = None
    object_store_bucket: str = "food-agent"
    object_store_region: str = "us-east-1"
    object_store_access_key: SecretStr | None = None
    object_store_secret_key: SecretStr | None = None
    object_store_max_concurrency: int = Field(default=4, ge=1, le=64)
    object_store_multipart_threshold: int = Field(default=8 * 1024 * 1024, ge=5 * 1024 * 1024)
    object_store_multipart_chunk_size: int = Field(default=8 * 1024 * 1024, ge=5 * 1024 * 1024)
    object_store_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    object_store_allowed_content_types: tuple[str, ...] = (
        "application/json",
        "audio/mpeg",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
        "video/mp4",
    )
    # Test is the safe local default.  Production deployments must opt in to
    # ``production`` and provide an encryption mode explicitly.
    object_store_environment: Literal["production", "local", "test"] = "test"
    object_store_server_side_encryption: Literal["AES256", "aws:kms", "test"] | None = None
    object_store_encryption_key_ref: str | None = None
    object_store_signed_url_ttl_seconds: int | None = Field(default=None, ge=1)
    object_store_orphan_grace_seconds: int | None = Field(default=None, ge=0)

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
        for name in queues:
            if (
                not isinstance(name, str)
                or not name
                or name != name.strip()
                or any(character.isspace() or ord(character) < 32 for character in name)
            ):
                raise ValueError(
                    "Temporal Research, Refresh, and Media queue names must be whitespace-free"
                )
        if (
            self.personalization_canary_mode == "off"
            and self.personalization_canary_sample_rate != 0
        ):
            raise ValueError("off personalization canary cannot carry a sample rate")
        if (
            self.personalization_canary_mode != "off"
            and self.personalization_canary_sample_rate <= 0
        ):
            raise ValueError("active personalization canary requires a positive sample rate")
        if self.account_services_json and self.account_services_file:
            raise ValueError(
                "account_services_json and account_services_file are mutually exclusive"
            )
        for name, value in (
            ("account_services_json", self.account_services_json),
            ("account_services_file", self.account_services_file),
            ("agent_mcp_tool_policy_json", self.agent_mcp_tool_policy_json),
        ):
            if value is not None and any(ord(character) < 32 for character in value):
                raise ValueError(f"{name} must not contain control characters")
        if len(self.object_store_allowed_content_types) != len(
            set(self.object_store_allowed_content_types)
        ):
            raise ValueError("object store content-type allow-list must be unique")
        if self.object_store_multipart_chunk_size > self.object_store_max_bytes:
            raise ValueError("object store multipart chunk size cannot exceed max bytes")
        if (
            self.object_store_environment == "production"
            and self.object_store_server_side_encryption is None
        ):
            raise ValueError(
                "production ObjectStore requires MODULAR_OBJECT_STORE_SERVER_SIDE_ENCRYPTION"
            )
        if (
            self.object_store_server_side_encryption == "aws:kms"
            and not self.object_store_encryption_key_ref
        ):
            raise ValueError(
                "aws:kms ObjectStore encryption requires MODULAR_OBJECT_STORE_ENCRYPTION_KEY_REF"
            )
        if (
            self.object_store_server_side_encryption != "aws:kms"
            and self.object_store_encryption_key_ref is not None
        ):
            raise ValueError("encryption key ref is only valid with aws:kms")
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
    refresh_enabled: bool = False
    media_enabled: bool = False


class ObjectStoreConfigView(_OwnerView):
    enabled: bool
    endpoint_url: str | None
    bucket: str
    region: str
    access_key: SecretStr | None
    secret_key: SecretStr | None
    max_concurrency: int
    multipart_threshold: int
    multipart_chunk_size: int
    max_bytes: int
    allowed_content_types: tuple[str, ...]
    environment: Literal["production", "local", "test"]
    server_side_encryption: Literal["AES256", "aws:kms", "test"] | None
    encryption_key_ref: str | None
    signed_url_ttl_seconds: int | None
    orphan_grace_seconds: int | None


class ObservabilityConfigView(_OwnerView):
    enabled: bool
    service_name: str
    exporter_endpoint: str | None


class EvidenceShadowConfigView(_OwnerView):
    enabled: bool
    sample_rate: float
    write_budget: int


class PersonalizationCanaryConfigView(_OwnerView):
    mode: Literal["off", "shadow", "canary"]
    sample_rate: float
    projection_warmup_enabled: bool


__all__ = [
    "ModelConfigView",
    "EvidenceShadowConfigView",
    "ObjectStoreConfigView",
    "ObservabilityConfigView",
    "PersonalizationCanaryConfigView",
    "RedisConfigView",
    "RepositoryConfigView",
    "TargetSettings",
    "TemporalConfigView",
]
