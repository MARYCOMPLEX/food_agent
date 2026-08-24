"""Framework-neutral ports implemented by adapters at the composition root."""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator
from enum import StrEnum
from typing import Literal, Protocol, Self, TypeVar, runtime_checkable
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
from .tasks import RecoverView, ResearchRequest, ResearchTask, TaskProgressProjection


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


class TemporalExecutionPolicy(_PortVersionedContract):
    """SDK-neutral retry, timeout, and heartbeat policy shared by workloads."""

    policy_version: NonEmptyStr = "temporal-activity/v1"
    activity_timeout_seconds: int = Field(default=300, ge=1)
    heartbeat_timeout_seconds: int = Field(default=30, ge=1)
    retry_initial_interval_seconds: int = Field(default=1, ge=1)
    retry_maximum_interval_seconds: int = Field(default=30, ge=1)
    retry_backoff_coefficient: float = Field(default=2.0, ge=1.0)
    retry_maximum_attempts: int = Field(default=3, ge=1)
    non_retryable_error_types: tuple[NonEmptyStr, ...] = (
        "ValidationError",
        "PolicyDeniedError",
        "NonRetryableApplicationError",
        "ResultCommitRejected",
    )


class WorkflowRun(_PortVersionedContract):
    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    status: NonEmptyStr


class FailedWorkflow(_PortVersionedContract):
    """Queryable failed execution metadata used by the operator boundary.

    Temporal history remains the executable checkpoint. This value is only a
    read model for inspection and recovery selection; it carries no queue or
    broker receipt.
    """

    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    workflow_type: NonEmptyStr
    task_queue: NonEmptyStr
    status: NonEmptyStr = "failed"
    failure_category: NonEmptyStr | None = None
    last_checkpoint: NonEmptyStr | None = None


class WorkflowRecoveryAction(StrEnum):
    RETRY = "retry"
    TERMINATE = "terminate"


class WorkflowRetryRequest(_PortVersionedContract):
    """Operator retry command carrying the original deterministic start input."""

    command: WorkflowStart
    expected_run_id: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None


class WorkflowTerminateRequest(_PortVersionedContract):
    """Operator termination command for a failed or stuck execution."""

    workflow_id: NonEmptyStr
    run_id: NonEmptyStr | None = None
    reason: NonEmptyStr


class WorkflowRecoveryReceipt(_PortVersionedContract):
    """Deterministic acknowledgement of a retry or termination command."""

    workflow_id: NonEmptyStr
    run_id: NonEmptyStr
    action: WorkflowRecoveryAction
    accepted: bool
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


class ObjectStorePolicy(_PortValue):
    """Fail-closed operational policy for binary object access."""

    policy_version: NonEmptyStr = "object-store-policy/v1"
    environment: Literal["production", "local", "test"] = "test"
    allowed_content_types: tuple[NonEmptyStr, ...] = (
        "application/json",
        "audio/mpeg",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
        "video/mp4",
    )
    max_object_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    multipart_threshold_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    multipart_chunk_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    server_side_encryption: Literal["AES256", "aws:kms", "test"] | None = None
    encryption_key_ref: NonEmptyStr | None = None
    signed_url_ttl_seconds: int | None = Field(default=None, ge=1)
    orphan_grace_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_security(self) -> Self:
        if len(self.allowed_content_types) != len(set(self.allowed_content_types)):
            raise ValueError("object content-type allow-list must be unique")
        if self.multipart_chunk_bytes > self.max_object_bytes:
            raise ValueError("multipart chunk size cannot exceed max object size")
        if self.environment == "production" and self.server_side_encryption is None:
            raise ValueError("production ObjectStore requires server-side encryption")
        if self.server_side_encryption == "aws:kms" and not self.encryption_key_ref:
            raise ValueError("aws:kms ObjectStore encryption requires an encryption key reference")
        if self.server_side_encryption != "aws:kms" and self.encryption_key_ref is not None:
            raise ValueError("encryption key reference is only valid with aws:kms")
        return self


class OrphanCleanupRequest(_PortValue):
    """An idempotent cleanup candidate emitted after metadata aborts."""

    object_ref: ObjectRef
    uploaded_at: Timestamp
    metadata_committed: bool = False
    referenced: bool = False
    legal_hold: bool = False


class OrphanCleanupResult(_PortValue):
    """Auditable cleanup outcome; deletion is never inferred from absence."""

    object_id: NonEmptyStr
    action: Literal["deleted", "retained", "missing", "deferred"]
    reason: NonEmptyStr


@runtime_checkable
class OrphanCleanupPort(Protocol):
    async def cleanup(self, request: OrphanCleanupRequest) -> OrphanCleanupResult: ...


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


class SourceAdmissionDecision(_PortVersionedContract):
    """Rate/circuit admission result; cursor state remains connector-owned."""

    allowed: bool
    retry_after_seconds: int = Field(default=0, ge=0)
    circuit_open: bool = False

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        if self.allowed and (self.retry_after_seconds or self.circuit_open):
            raise ValueError("allowed source admission cannot carry a retry or open circuit")
        if not self.allowed and self.retry_after_seconds == 0 and not self.circuit_open:
            raise ValueError("denied source admission must carry a retry or open circuit")
        return self


class SourceCollectionOutcome(_PortVersionedContract):
    """One source attempt, preserving empty-success versus failure semantics."""

    source_id: NonEmptyStr
    outcome: Literal["success_nonempty", "success_empty", "partial", "failure"]
    batch: CanonicalSourceBatch | None = None
    error: ContractError | None = None
    next_cursor: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        has_items = self.batch is not None and bool(
            self.batch.documents or self.batch.comments or self.batch.authors or self.batch.media_refs
        )
        if self.outcome == "failure":
            if self.error is None or self.batch is not None:
                raise ValueError("source failure requires an error and no successful batch")
        elif self.error is not None:
            if self.outcome != "partial" or self.batch is None:
                raise ValueError("only partial source outcomes may carry batch errors")
        elif self.outcome == "success_nonempty" and not has_items:
            raise ValueError("success_nonempty requires source items")
        elif self.outcome == "success_empty" and has_items:
            raise ValueError("success_empty cannot carry source items")
        if self.batch is not None and self.batch.source_id != self.source_id:
            raise ValueError("source outcome batch must match source_id")
        if self.next_cursor is None and self.batch is not None:
            object.__setattr__(self, "next_cursor", self.batch.next_cursor)
        return self


@runtime_checkable
class SourceControlPort(Protocol):
    async def admit(self, source_id: str) -> SourceAdmissionDecision: ...

    async def record_success(self, source_id: str) -> None: ...

    async def record_failure(self, source_id: str, *, retryable: bool) -> None: ...


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
class WorkflowOperatorPort(Protocol):
    """Inspection and manual recovery for retry-exhausted Temporal runs.

    Implementations must use the same Workflow ID and durable Temporal
    history. This port is intentionally separate from the request-time
    WorkflowPort so a failed-workflow operator cannot become a second queue or
    retry authority.
    """

    async def list_failed_workflows(
        self, *, task_queue: str | None = None, limit: int = 100
    ) -> tuple[FailedWorkflow, ...]: ...

    async def retry_workflow(self, request: WorkflowRetryRequest) -> WorkflowRecoveryReceipt: ...

    async def terminate_workflow(
        self, request: WorkflowTerminateRequest
    ) -> WorkflowRecoveryReceipt: ...


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


@runtime_checkable
class TaskProgressProjectionPort(Protocol):
    """Query-only task projection storage; never an execution checkpoint."""

    async def get(self, task_id: str) -> TaskProgressProjection | None: ...

    async def put(self, projection: TaskProgressProjection) -> TaskProgressProjection: ...

    async def delete(self, task_id: str) -> bool: ...


@runtime_checkable
class TaskProgressProjectionSessionLookupPort(Protocol):
    """Read-only lookup used by reliable SSE resynchronization."""

    async def get_by_session_id(self, session_id: str) -> TaskProgressProjection | None: ...


@runtime_checkable
class RecoverViewPort(Protocol):
    """Read-only recovery view; it never exposes an executable checkpoint."""

    async def recover_view(self, task_id: str) -> RecoverView: ...


TaskProgressProjectionStore = TaskProgressProjectionPort


@runtime_checkable
class ReliableTaskStorePort(Protocol):
    """Durable owner store for reliable task admission and state snapshots.

    Implementations own persistence only.  The Research Coordinator remains
    the sole component that computes semantic task transitions.
    """

    async def get(
        self, task_id: str
    ) -> tuple[ResearchTask, ResearchRequest] | None: ...

    async def admit(
        self, task: ResearchTask, request: ResearchRequest
    ) -> tuple[ResearchTask, bool]: ...

    async def save(self, task: ResearchTask, request: ResearchRequest) -> ResearchTask: ...


__all__ = [
    "ActivityCall",
    "ActivityPort",
    "ActivityResult",
    "CachePort",
    "EventBusPort",
    "FailedWorkflow",
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
    "RecoverViewPort",
    "SessionWindowPort",
    "SourceConnector",
    "SourceAdmissionDecision",
    "SourceCollectionOutcome",
    "SourceControlPort",
    "StateStorePort",
    "TaskProgressProjectionPort",
    "TaskProgressProjectionSessionLookupPort",
    "TaskProgressProjectionStore",
    "TemporalExecutionPolicy",
    "ReliableTaskStorePort",
    "ToolCall",
    "ToolGateway",
    "ToolResult",
    "WorkflowPort",
    "WorkflowOperatorPort",
    "WorkflowRecoveryAction",
    "WorkflowRecoveryReceipt",
    "WorkflowRetryRequest",
    "WorkflowRun",
    "WorkflowStart",
    "WorkflowTerminateRequest",
]
