"""Provider-neutral contracts for remote account services."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

ACCOUNT_SERVICE_CONTRACT_VERSION = "account-service/v1"
MCP_PROTOCOL_VERSION = "2025-06-18"


class PlatformChannel(StrEnum):
    """Remote account-service channels with isolated account namespaces."""

    DIANPING = "dianping"
    XHS_PC = "xhs_pc"
    XHS_CREATOR = "xhs_creator"


class AccountServiceProtocol(StrEnum):
    HTTP = "http"
    MCP = "mcp"
    HTTP_MCP = "http+mcp"


class RemoteErrorCategory(StrEnum):
    DEPENDENCY_UNAVAILABLE = "dependency-unavailable"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate-limited"
    PROVIDER_RISK = "provider-risk"
    INVALID = "invalid"
    INTERNAL = "internal"


class RemoteSideEffect(StrEnum):
    READ_ONLY = "read_only"
    ACCOUNT_LOGIN = "account_login"
    ACCOUNT_MUTATION = "account_mutation"
    PUBLISH = "publish"
    UPLOAD = "upload"
    SHELL = "shell"
    CREDENTIAL_EXPORT = "credential_export"


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}$")
_SECRET_KEY = re.compile(
    r"(?:cookie|authorization|bearer|password|passwd|secret|token|signature|"
    r"qr(?:[_ -]?(?:id|url|payload|bytes))?|storage[_ -]?state|"
    r"signer(?:[_ -]?(?:input|state))?|decrypted[_ -]?(?:envelope|session)|"
    r"browser[_ -]?(?:profile|path))",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:cookie|authorization|bearer|password|passwd|secret|token|signature|"
    r"qruuid|qr(?:[_ -]?(?:id|url|payload|bytes))?|storage[_ -]?state|"
    r"signer(?:[_ -]?(?:input|state))?|decrypted[_ -]?(?:envelope|session)|"
    r"browser[_ -]?(?:profile|path))\s*[:=]",
    re.IGNORECASE,
)


class RemotePayloadRejected(ValueError):
    """Raised before a remote boundary accepts secret-shaped material."""


class AccountServiceControlPlaneError(RuntimeError):
    """Stable failure exposed by the remote account-service control plane."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_remote_payload(value: object, path: str = "payload") -> None:
    """Reject secret-bearing keys/assignments recursively."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text):
                raise RemotePayloadRejected(f"{path} contains forbidden field {key_text!r}")
            validate_remote_payload(item, f"{path}.{key_text}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            validate_remote_payload(item, f"{path}[{index}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise RemotePayloadRejected(f"{path} must not contain binary material")
    if isinstance(value, str) and _SECRET_ASSIGNMENT.search(value):
        raise RemotePayloadRejected(f"{path} appears to contain secret material")


def sanitize_remote_payload(value: object) -> object:
    """Return a JSON-safe projection with secret-shaped values removed."""

    if isinstance(value, Mapping):
        return {
            str(key): sanitize_remote_payload(item)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_remote_payload(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[REDACTED]"
    if isinstance(value, str) and _SECRET_ASSIGNMENT.search(value):
        return "[REDACTED]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _validate_id(value: str, field_name: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be an opaque identifier")
    return value


def _validate_version(value: str, field_name: str) -> str:
    if not _SAFE_VERSION.fullmatch(value):
        raise ValueError(f"{field_name} must be a version identifier")
    return value


def _validate_ref(value: str, field_name: str, *, max_length: int = 256) -> str:
    if (
        not value
        or len(value) > max_length
        or any(char.isspace() or ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{field_name} must be a non-empty opaque reference")
    return value


def _validate_url(value: Any, field_name: str) -> Any:
    parsed = urlsplit(str(value))
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain embedded credentials")
    return value


class _RemoteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class AccountServiceConfig(_RemoteModel):
    """Deployment-owned entry describing one independent upstream service."""

    service_id: str = Field(min_length=1, max_length=128)
    base_url: AnyHttpUrl
    protocol: AccountServiceProtocol = AccountServiceProtocol.HTTP_MCP
    channels: tuple[PlatformChannel, ...] = Field(min_length=1)
    capabilities: tuple[str, ...] = ()
    descriptor_version: str = ACCOUNT_SERVICE_CONTRACT_VERSION
    mcp_url: AnyHttpUrl | None = None
    auth_ref: str | None = Field(default=None, min_length=1, max_length=128)
    timeout_seconds: float = Field(default=10.0, gt=0.1, le=120.0)
    descriptor_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    @field_validator("service_id")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        return _validate_id(value, info.field_name)

    @field_validator("descriptor_version")
    @classmethod
    def _descriptor_version(cls, value: str, info: Any) -> str:
        return _validate_version(value, info.field_name)

    @field_validator("base_url", "mcp_url")
    @classmethod
    def _url(cls, value: Any, info: Any) -> Any:
        return _validate_url(value, info.field_name)

    @field_validator("auth_ref")
    @classmethod
    def _auth_ref(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _validate_id(value, info.field_name)

    @field_validator("capabilities")
    @classmethod
    def _capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("service capabilities must be unique")
        if any(not item or any(char.isspace() for char in item) for item in values):
            raise ValueError("service capabilities must be whitespace-free")
        return values

    @field_validator("channels")
    @classmethod
    def _channels(cls, values: tuple[PlatformChannel, ...]) -> tuple[PlatformChannel, ...]:
        if len(values) != len(set(values)):
            raise ValueError("service channels must be unique")
        return values


class AccountServiceDescriptor(_RemoteModel):
    service_id: str
    service_version: str
    contract_version: str = ACCOUNT_SERVICE_CONTRACT_VERSION
    protocol: AccountServiceProtocol
    platform_channels: tuple[PlatformChannel, ...]
    capabilities: tuple[str, ...] = ()
    login_modes: tuple[str, ...] = ()
    mcp_endpoint: AnyHttpUrl | None = None
    expires_at: datetime
    refreshed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("service_id", "service_version")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        return _validate_id(value, info.field_name)

    @field_validator("contract_version")
    @classmethod
    def _contract_version(cls, value: str, info: Any) -> str:
        return _validate_version(value, info.field_name)

    @field_validator("mcp_endpoint")
    @classmethod
    def _mcp_endpoint(cls, value: Any, info: Any) -> Any:
        return None if value is None else _validate_url(value, info.field_name)


class AccountServiceHealth(_RemoteModel):
    service_id: str
    state: Literal["ready", "degraded", "dependency-unavailable", "disabled"]
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str | None = None
    descriptor_version: str | None = None

    @field_validator("detail")
    @classmethod
    def _detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        validate_remote_payload(value, "detail")
        return value[:256]


class RemoteAccountProjection(_RemoteModel):
    service_id: str
    platform: PlatformChannel
    account_ref: str
    alias: str
    status: str
    health: str
    session_version: int | None = None
    provider_subject_ref: str | None = None

    @field_validator("account_ref", "provider_subject_ref")
    @classmethod
    def _references(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _validate_ref(value, info.field_name)


class RemoteLoginFlowProjection(_RemoteModel):
    service_id: str
    platform: PlatformChannel
    account_ref: str
    flow_id: str
    state: str
    created_at: datetime
    expires_at: datetime
    updated_at: datetime
    qr_expires_at: datetime | None = None
    provider_subject_ref: str | None = None
    error_code: RemoteErrorCategory | None = None
    error_message: str | None = None

    @field_validator("error_message")
    @classmethod
    def _error_message(cls, value: str | None) -> str | None:
        if value is not None:
            validate_remote_payload(value, "error_message")
        return value

    @field_validator("account_ref", "flow_id", "provider_subject_ref")
    @classmethod
    def _references(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _validate_ref(value, info.field_name)


class RemoteQrPresentation(_RemoteModel):
    service_id: str
    flow_id: str
    object_ref: str
    expires_at: datetime
    content_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"

    @field_validator("flow_id", "object_ref")
    @classmethod
    def _references(cls, value: str, info: Any) -> str:
        return _validate_ref(value, info.field_name, max_length=512)


class RemoteSourceInvocation(_RemoteModel):
    service_id: str
    tenant_ref: str
    platform: PlatformChannel
    account_ref: str
    expected_session_version: int | None = Field(default=None, ge=1)
    correlation_id: str = Field(min_length=1, max_length=128)
    capability: str = Field(min_length=1, max_length=128)
    query: Mapping[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0.1, le=300.0)

    @field_validator("query")
    @classmethod
    def _query(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_remote_payload(value, "query")
        return value

    @field_validator("tenant_ref", "account_ref", "correlation_id")
    @classmethod
    def _references(cls, value: str, info: Any) -> str:
        return _validate_ref(value, info.field_name)


class RemoteErrorEnvelope(_RemoteModel):
    code: RemoteErrorCategory
    message: str
    service_id: str
    capability: str | None = None
    retryable: bool = False

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        validate_remote_payload(value, "message")
        return value[:256]


class McpToolDescriptor(_RemoteModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    input_schema: Mapping[str, Any] = Field(default_factory=dict)
    output_schema: Mapping[str, Any] | None = None
    capability: str = Field(min_length=1, max_length=128)
    capability_version: str = ACCOUNT_SERVICE_CONTRACT_VERSION
    side_effect: RemoteSideEffect = RemoteSideEffect.READ_ONLY

    @field_validator("name", "capability")
    @classmethod
    def _safe_name(cls, value: str, info: Any) -> str:
        return _validate_id(value, info.field_name)

    @field_validator("capability_version")
    @classmethod
    def _capability_version(cls, value: str, info: Any) -> str:
        return _validate_version(value, info.field_name)

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        validate_remote_payload(value, "description")
        return value[:512]


class McpToolCallResult(_RemoteModel):
    tool_name: str
    is_error: bool = False
    content: object = None


__all__ = [
    "ACCOUNT_SERVICE_CONTRACT_VERSION",
    "MCP_PROTOCOL_VERSION",
    "AccountServiceControlPlaneError",
    "AccountServiceConfig",
    "AccountServiceDescriptor",
    "AccountServiceHealth",
    "AccountServiceProtocol",
    "McpToolCallResult",
    "McpToolDescriptor",
    "RemoteAccountProjection",
    "RemoteErrorCategory",
    "RemoteErrorEnvelope",
    "RemoteLoginFlowProjection",
    "RemotePayloadRejected",
    "RemoteQrPresentation",
    "RemoteSideEffect",
    "RemoteSourceInvocation",
    "sanitize_remote_payload",
    "validate_remote_payload",
]
