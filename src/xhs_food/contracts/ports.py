"""Framework-neutral ports implemented by adapters at the composition root."""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol, Self, TypeVar, runtime_checkable
from urllib.parse import unquote, urlsplit

from pydantic import ConfigDict, Field, model_validator

from .base import (
    ContractPayload,
    JsonValue,
    NonEmptyStr,
    SchemaVersion,
    Timestamp,
    schema_version_v1,
)
from .errors import ContractError
from .evidence import (
    AuthorityModel,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceDocument,
    CollectRequest,
    SourceLocator,
)


class _PortValue(AuthorityModel):
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        str_strip_whitespace=False,
        use_enum_values=False,
    )


class _PortVersionedContract(_PortValue):
    schema_version: SchemaVersion = Field(default_factory=schema_version_v1)


class ToolCall(_PortVersionedContract):
    call_id: NonEmptyStr
    tool_name: NonEmptyStr
    arguments: ContractPayload
    task_id: str | None = None
    timeout_ms: int | None = Field(default=None, gt=0)


class ToolResult(_PortVersionedContract):
    call_id: NonEmptyStr
    success: bool
    output: JsonValue = None
    error: ContractError | None = None
    metadata: ContractPayload = Field(default_factory=dict)


class WorkflowStart(_PortVersionedContract):
    workflow_id: NonEmptyStr
    workflow_type: NonEmptyStr
    task_queue: NonEmptyStr
    input: ContractPayload
    idempotency_key: NonEmptyStr


class WorkflowRun(_PortVersionedContract):
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    status: NonEmptyStr


class ActivityCall(_PortVersionedContract):
    activity_id: NonEmptyStr
    activity_type: NonEmptyStr
    task_queue: NonEmptyStr
    input: ContractPayload
    idempotency_key: NonEmptyStr


class ActivityResult(_PortVersionedContract):
    activity_id: NonEmptyStr
    output: ContractPayload


class EventEnvelope(_PortVersionedContract):
    event_id: NonEmptyStr
    topic: NonEmptyStr
    payload: ContractPayload
    published_at: Timestamp


class ObjectRef(_PortVersionedContract):
    object_id: NonEmptyStr
    key: NonEmptyStr
    content_hash: NonEmptyStr
    size_bytes: int = Field(ge=0)
    content_type: NonEmptyStr

    @model_validator(mode="after")
    def validate_opaque_key(self) -> Self:
        decoded_key = unquote(self.key)
        parsed = urlsplit(decoded_key)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("ObjectRef key must be an opaque object key, not a URL")
        if decoded_key.startswith(("/", "\\")) or "\\" in decoded_key:
            raise ValueError("ObjectRef key must be relative and use object-key separators")
        if any(character.isspace() or ord(character) < 32 for character in decoded_key):
            raise ValueError("ObjectRef key must not contain whitespace or control characters")
        if any(segment in {"", ".", ".."} for segment in decoded_key.split("/")):
            raise ValueError("ObjectRef key must not contain empty or traversal segments")
        sensitive = re.compile(
            r"(?:^|[/._-])(?:token|credentials?|secrets?|password|passwd|authorization|"
            r"cookies?|x-amz-(?:credential|signature)|api[-_]?key|access[-_]?key)"
            r"(?:$|[/._=-])",
            re.IGNORECASE,
        )
        if sensitive.search(decoded_key):
            raise ValueError("ObjectRef key must not contain token or credential material")
        return self


class ObjectStat(_PortValue):
    ref: ObjectRef
    metadata: ContractPayload = Field(default_factory=dict)


class ModelMessage(_PortValue):
    role: NonEmptyStr
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ModelToolDefinition(_PortValue):
    name: NonEmptyStr
    description: str
    input_schema: ContractPayload


class ModelRequest(_PortVersionedContract):
    request_id: NonEmptyStr
    model_role: NonEmptyStr
    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()
    output_schema: ContractPayload | None = None
    timeout_ms: int | None = Field(default=None, gt=0)
    provider_options: ContractPayload = Field(default_factory=dict)


class ModelToolCall(_PortValue):
    call_id: NonEmptyStr
    name: NonEmptyStr
    arguments: ContractPayload


class ModelUsage(_PortValue):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelResponse(_PortVersionedContract):
    request_id: NonEmptyStr
    content: str | None = None
    structured_output: JsonValue = None
    tool_calls: tuple[ModelToolCall, ...] = ()
    usage: ModelUsage = Field(default_factory=ModelUsage)
    provider_ref: str | None = None
    model_ref: str | None = None


EntityT = TypeVar("EntityT")


@runtime_checkable
class SourceConnector(Protocol):
    @property
    def source_id(self) -> str: ...

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch: ...

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument: ...

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch: ...

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[CanonicalMediaRef, ...]: ...


@runtime_checkable
class PlaceLookupPort(Protocol):
    """Optional place enrichment exposed without a provider-specific client."""

    async def lookup(
        self, *, keywords: str, city: str = "", types: str = "050000"
    ) -> ContractPayload | None: ...


@runtime_checkable
class ToolGateway(Protocol):
    async def execute(self, call: ToolCall) -> ToolResult: ...

    async def health(self, tool_name: str) -> bool: ...


@runtime_checkable
class Repository(Protocol[EntityT]):
    async def get(self, identity: str) -> EntityT | None: ...

    async def save(self, entity: EntityT) -> EntityT: ...

    async def delete(self, identity: str) -> bool: ...


@runtime_checkable
class WorkflowPort(Protocol):
    async def start(self, command: WorkflowStart) -> WorkflowRun: ...

    async def signal(self, workflow_id: str, signal: str, payload: ContractPayload) -> None: ...

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None: ...

    async def describe(self, workflow_id: str) -> WorkflowRun | None: ...


@runtime_checkable
class ActivityPort(Protocol):
    async def execute(self, call: ActivityCall) -> ActivityResult: ...


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str) -> JsonValue: ...

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> bool: ...


@runtime_checkable
class StateStorePort(Protocol):
    """Short-lived rebuildable state; intentionally exposes no locks or leases."""

    async def get(self, key: str) -> ContractPayload | None: ...

    async def set(self, key: str, value: ContractPayload, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> bool: ...


@runtime_checkable
class SessionWindowPort(Protocol):
    async def append(self, session_id: str, message: ContractPayload, ttl_seconds: int) -> None: ...

    async def recent(self, session_id: str, limit: int) -> tuple[ContractPayload, ...]: ...

    async def clear(self, session_id: str) -> bool: ...


@runtime_checkable
class EventBusPort(Protocol):
    async def publish(self, event: EventEnvelope) -> str: ...

    def subscribe(self, topic: str, after: str | None = None) -> AsyncIterator[EventEnvelope]: ...


@runtime_checkable
class ObjectStore(Protocol):
    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        content_type: str,
        metadata: ContractPayload | None = None,
    ) -> ObjectRef: ...

    def get(self, ref: ObjectRef) -> AsyncIterator[bytes]: ...

    async def stat(self, ref: ObjectRef) -> ObjectStat | None: ...

    async def delete(self, ref: ObjectRef) -> bool: ...


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


@runtime_checkable
class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...


__all__ = [
    "ActivityCall",
    "ActivityPort",
    "ActivityResult",
    "CachePort",
    "EventBusPort",
    "EventEnvelope",
    "LLMProvider",
    "ModelGateway",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelToolCall",
    "ModelToolDefinition",
    "ModelUsage",
    "ObjectRef",
    "ObjectStat",
    "ObjectStore",
    "PlaceLookupPort",
    "Repository",
    "SessionWindowPort",
    "SourceConnector",
    "StateStorePort",
    "ToolCall",
    "ToolGateway",
    "ToolResult",
    "WorkflowPort",
    "WorkflowRun",
    "WorkflowStart",
]
