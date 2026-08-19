"""Framework-neutral ports implemented by adapters at the composition root."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import Field

from .base import (
    ContractModel,
    ContractPayload,
    JsonValue,
    NonEmptyStr,
    Timestamp,
    VersionedContract,
)
from .errors import ContractError
from .evidence import (
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceDocument,
    CollectRequest,
    SourceLocator,
)


class ToolCall(VersionedContract):
    call_id: NonEmptyStr
    tool_name: NonEmptyStr
    arguments: ContractPayload
    task_id: str | None = None
    timeout_ms: int | None = Field(default=None, gt=0)


class ToolResult(VersionedContract):
    call_id: NonEmptyStr
    success: bool
    output: JsonValue = None
    error: ContractError | None = None
    metadata: ContractPayload = Field(default_factory=dict)


class WorkflowStart(VersionedContract):
    workflow_id: NonEmptyStr
    workflow_type: NonEmptyStr
    task_queue: NonEmptyStr
    input: ContractPayload
    idempotency_key: NonEmptyStr


class WorkflowRun(VersionedContract):
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    status: NonEmptyStr


class EventEnvelope(VersionedContract):
    event_id: NonEmptyStr
    topic: NonEmptyStr
    payload: ContractPayload
    published_at: Timestamp


class ObjectRef(VersionedContract):
    object_id: NonEmptyStr
    key: NonEmptyStr
    content_hash: NonEmptyStr
    size_bytes: int = Field(ge=0)
    content_type: NonEmptyStr


class ObjectStat(ContractModel):
    ref: ObjectRef
    metadata: ContractPayload = Field(default_factory=dict)


class ModelMessage(ContractModel):
    role: NonEmptyStr
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ModelToolDefinition(ContractModel):
    name: NonEmptyStr
    description: str
    input_schema: ContractPayload


class ModelRequest(VersionedContract):
    request_id: NonEmptyStr
    model_role: NonEmptyStr
    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()
    output_schema: ContractPayload | None = None
    timeout_ms: int | None = Field(default=None, gt=0)
    provider_options: ContractPayload = Field(default_factory=dict)


class ModelToolCall(ContractModel):
    call_id: NonEmptyStr
    name: NonEmptyStr
    arguments: ContractPayload


class ModelUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelResponse(VersionedContract):
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

    async def list_media_refs(
        self, owner_ref: SourceLocator
    ) -> tuple[CanonicalMediaRef, ...]: ...


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
class CachePort(Protocol):
    async def get(self, key: str) -> JsonValue: ...

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> bool: ...


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
    "Repository",
    "SourceConnector",
    "ToolCall",
    "ToolGateway",
    "ToolResult",
    "WorkflowPort",
    "WorkflowRun",
    "WorkflowStart",
]
