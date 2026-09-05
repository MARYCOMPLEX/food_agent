"""Target-only settings and immutable owner-scoped configuration views."""

from __future__ import annotations

from typing import Any, Literal, Never

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
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
    # B2 is independently controlled.  The read path is still legacy-only
    # unless an operator explicitly selects shadow/canary after qualification.
    query_reuse_read_mode: Literal["off", "shadow", "canary"] = "off"
    query_reuse_read_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    query_reuse_min_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    query_reuse_max_staleness_seconds: int = Field(default=86_400, gt=0)
    query_reuse_minimum_coverage: dict[str, float] = Field(default_factory=dict)
    # Serving B2 is a separate release decision.  Configuration alone must
    # never be able to claim that the B1 qualification gate passed.
    query_reuse_b1_gate_approved: bool = False
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
    phoenix_enabled: bool = False
    phoenix_evaluation_endpoint: str | None = None
    phoenix_api_version: str = "v1"
    phoenix_token_ref: str | None = None
    otel_max_queue_size: int = Field(default=2048, ge=1, le=100_000)
    otel_max_batch_size: int = Field(default=128, ge=1, le=10_000)
    otel_schedule_delay_ms: int = Field(default=5_000, ge=0, le=300_000)
    otel_export_timeout_ms: int = Field(default=10_000, ge=1, le=300_000)
    otel_retry_limit: int = Field(default=2, ge=0, le=10)
    otel_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    otel_shutdown_flush_timeout_ms: int = Field(default=5_000, ge=0, le=300_000)
    otel_drop_policy: Literal["drop_oldest", "drop_newest"] = "drop_oldest"
    # Short aliases are accepted for callers that use the names from the
    # exporter contract.  The max_* values remain the canonical settings.
    otel_queue_size: int | None = Field(default=None, ge=1, le=100_000)
    otel_batch_size: int | None = Field(default=None, ge=1, le=10_000)
    otel_shutdown_timeout_ms: int | None = Field(default=None, ge=0, le=300_000)

    # ``pydantic-settings`` intentionally merges process environment values
    # even when a caller passes ``_env_file=None``.  Keep a private marker so
    # composition/unit callers can opt out of ambient dotenv-derived account
    # and Agent-tool bindings without changing the normal deployment behavior
    # of ``TargetSettings()``.
    _ambient_environment_enabled: bool = PrivateAttr(default=True)
    _explicit_input_fields: frozenset[str] = PrivateAttr(default_factory=frozenset)

    def __init__(self, **values: Any) -> None:
        explicit_env_file = "_env_file" in values
        env_file = values.get("_env_file")
        explicit_input_fields = frozenset(
            name for name in values if not name.startswith("_")
        )
        super().__init__(**values)
        self._ambient_environment_enabled = not explicit_env_file or env_file is not None
        self._explicit_input_fields = explicit_input_fields

    @property
    def ambient_environment_enabled(self) -> bool:
        return self._ambient_environment_enabled

    @property
    def explicit_input_fields(self) -> frozenset[str]:
        """Fields supplied by the caller rather than loaded from the environment."""

        return self._explicit_input_fields

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
        if (
            self.query_reuse_read_mode == "off"
            and self.query_reuse_read_sample_rate != 0
        ):
            raise ValueError("off query reuse read mode cannot carry a sample rate")
        if (
            self.query_reuse_read_mode != "off"
            and self.query_reuse_read_sample_rate <= 0
        ):
            raise ValueError("active query reuse read mode requires a positive sample rate")
        if any(
            not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0
            for value in self.query_reuse_minimum_coverage.values()
        ):
            raise ValueError("query reuse minimum coverage must be between 0 and 1")
        if self.query_reuse_read_mode == "canary" and not self.query_reuse_b1_gate_approved:
            raise ValueError("query reuse canary requires an approved B1 qualification gate")
        if self.evidence_shadow_enabled and (
            self.evidence_shadow_sample_rate <= 0 or self.evidence_shadow_write_budget <= 0
        ):
            raise ValueError("enabled evidence shadow requires a positive sample rate and budget")
        if self.phoenix_enabled and not self.otel_exporter_endpoint:
            raise ValueError("phoenix_enabled requires MODULAR_OTEL_EXPORTER_ENDPOINT")
        if not self.phoenix_api_version or any(
            ord(character) < 32 or character.isspace() for character in self.phoenix_api_version
        ):
            raise ValueError("phoenix_api_version must be a non-empty token")
        queue_size = self.otel_queue_size or self.otel_max_queue_size
        batch_size = self.otel_batch_size or self.otel_max_batch_size
        if batch_size > queue_size:
            raise ValueError("OTel batch size cannot exceed queue size")
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
    reasoning_effort: str = "medium"


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
    phoenix_enabled: bool = False
    phoenix_evaluation_endpoint: str | None = None
    phoenix_api_version: str = "v1"
    phoenix_token_ref: str | None = None
    max_queue_size: int = Field(default=2_048, ge=1, le=100_000)
    max_batch_size: int = Field(default=128, ge=1, le=10_000)
    schedule_delay_ms: int = Field(default=5_000, ge=0, le=300_000)
    export_timeout_ms: int = Field(default=10_000, ge=1, le=300_000)
    retry_limit: int = Field(default=2, ge=0, le=10)
    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    shutdown_flush_timeout_ms: int = Field(default=5_000, ge=0, le=300_000)
    drop_policy: Literal["drop_oldest", "drop_newest"] = "drop_oldest"

    @model_validator(mode="after")
    def validate_exporter_limits(self) -> ObservabilityConfigView:
        if self.max_batch_size > self.max_queue_size:
            raise ValueError("OTel batch size cannot exceed queue size")
        if self.phoenix_enabled and not self.exporter_endpoint:
            raise ValueError("phoenix_enabled requires an exporter endpoint")
        if not self.phoenix_api_version or any(
            ord(character) < 32 or character.isspace() for character in self.phoenix_api_version
        ):
            raise ValueError("phoenix_api_version must be a non-empty token")
        return self


class EvidenceShadowConfigView(_OwnerView):
    enabled: bool
    sample_rate: float = Field(ge=0.0, le=1.0)
    write_budget: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_shadow_limits(self) -> EvidenceShadowConfigView:
        if self.enabled and (self.sample_rate <= 0 or self.write_budget <= 0):
            raise ValueError("enabled evidence shadow requires a positive sample rate and budget")
        return self


class _FrozenCoverage(dict[str, float]):
    """Mapping used by immutable owner views without exposing mutable config."""

    def _immutable(self) -> Never:
        raise TypeError("configuration views are immutable")

    def __setitem__(self, key: str, value: float) -> None:
        del key, value
        self._immutable()

    def __delitem__(self, key: str) -> None:
        del key
        self._immutable()

    def clear(self) -> None:
        self._immutable()

    def pop(self, key: str, default: float | None = None) -> Never:
        del key, default
        self._immutable()

    def popitem(self) -> Never:
        self._immutable()

    def setdefault(self, key: str, default: float = 0.0) -> Never:
        del key, default
        self._immutable()

    def update(self, *args: object, **kwargs: float) -> None:
        del args, kwargs
        self._immutable()

    def __ior__(self, value: object) -> _FrozenCoverage:
        del value
        self._immutable()
        return self


class QueryReuseReadConfigView(_OwnerView):
    """Immutable B2 read controls owned by Evidence Intelligence."""

    mode: Literal["off", "shadow", "canary"]
    sample_rate: float = Field(ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.82, ge=0.0, le=1.0)
    max_staleness_seconds: int = Field(default=86_400, gt=0)
    minimum_coverage: dict[str, float] = Field(default_factory=dict)
    b1_gate_approved: bool = False

    @field_validator("minimum_coverage", mode="after")
    @classmethod
    def freeze_coverage(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 0.0 <= float(item) <= 1.0 for item in value.values()):
            raise ValueError("query reuse minimum coverage must be between 0 and 1")
        return _FrozenCoverage(value)

    @model_validator(mode="after")
    def validate_read_mode(self) -> QueryReuseReadConfigView:
        if self.mode == "off" and self.sample_rate != 0:
            raise ValueError("off query reuse read mode cannot carry a sample rate")
        if self.mode != "off" and self.sample_rate <= 0:
            raise ValueError("active query reuse read mode requires a positive sample rate")
        if self.mode == "canary" and not self.b1_gate_approved:
            raise ValueError("query reuse canary requires an approved B1 qualification gate")
        return self


class PersonalizationCanaryConfigView(_OwnerView):
    mode: Literal["off", "shadow", "canary"]
    sample_rate: float = Field(ge=0.0, le=1.0)
    projection_warmup_enabled: bool

    @model_validator(mode="after")
    def validate_canary_mode(self) -> PersonalizationCanaryConfigView:
        if self.mode == "off" and self.sample_rate != 0:
            raise ValueError("off personalization canary cannot carry a sample rate")
        if self.mode != "off" and self.sample_rate <= 0:
            raise ValueError("active personalization canary requires a positive sample rate")
        return self


__all__ = [
    "ModelConfigView",
    "EvidenceShadowConfigView",
    "ObjectStoreConfigView",
    "ObservabilityConfigView",
    "QueryReuseReadConfigView",
    "PersonalizationCanaryConfigView",
    "RedisConfigView",
    "RepositoryConfigView",
    "TargetSettings",
    "TemporalConfigView",
]
