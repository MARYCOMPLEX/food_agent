"""Idempotent private feedback ingestion through the authority write port."""

from __future__ import annotations

from xhs_food.contracts import (
    AnonymousIsolationKey,
    FeedbackIngestionReceipt,
    FeedbackIngestionRequest,
    MemoryAuthorityWrite,
    MemoryEvent,
    MemoryIsolationKey,
    MemoryOutboxEvent,
    MemoryRepositoryPort,
    MemorySubject,
)

from .memory_authorization import MemoryScopeAuthorizer


class FeedbackIngestor:
    """Write one feedback event and its projection instruction atomically."""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        *,
        authorizer: MemoryScopeAuthorizer | None = None,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer or MemoryScopeAuthorizer()

    async def ingest(
        self,
        request: FeedbackIngestionRequest,
        *,
        authorized_scope: MemoryIsolationKey,
    ) -> FeedbackIngestionReceipt:
        self._authorizer.require_same_scope(request.scope, authorized_scope)
        subject_id = (
            request.scope.anonymous_subject_id
            if isinstance(request.scope, AnonymousIsolationKey)
            else request.scope.user_id
        )
        event_id = f"feedback:{request.idempotency_key}"
        outbox_id = f"feedback:{request.idempotency_key}:projection"
        event = MemoryEvent(
            event_id=event_id,
            tenant_id=request.scope.tenant_id,
            subject=MemorySubject(kind=request.scope.kind, id=subject_id),
            session_id=request.scope.session_id,
            event_type=f"feedback.{request.action.value}",
            payload={
                "schemaVersion": request.schema_version,
                "feedbackId": request.feedback_id,
                "action": request.action.value,
                "targetId": request.target_id,
                "payload": request.payload,
                "consentPolicyVersion": request.policy_version,
            },
            idempotency_key=request.idempotency_key,
            occurred_at=request.occurred_at,
            policy_version=request.policy_version,
            created_at=request.occurred_at,
        )
        outbox = MemoryOutboxEvent(
            outbox_id=outbox_id,
            scope=request.scope,
            event_type="memory.feedback.project",
            aggregate_id=request.feedback_id,
            payload={
                "eventId": event_id,
                "action": request.action.value,
                "targetId": request.target_id,
            },
            idempotency_key=f"{request.idempotency_key}:projection",
            available_at=request.occurred_at,
        )
        await self._repository.commit_authority_write(
            MemoryAuthorityWrite(source_event=event, outbox=outbox)
        )
        return FeedbackIngestionReceipt(
            feedback_id=request.feedback_id,
            event_id=event_id,
            outbox_id=outbox_id,
        )


__all__ = ["FeedbackIngestor"]
