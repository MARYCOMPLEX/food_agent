"""B3 private feedback ingestion and idempotent authority-write tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xhs_food.contracts import (
    AnonymousIsolationKey,
    ConsentBasis,
    ConsentStatus,
    FeedbackAction,
    FeedbackIngestionRequest,
    MemoryAuthorityWrite,
    MemoryConsent,
    UserIsolationKey,
)
from xhs_food.personalization import FeedbackIngestor


def _scope() -> UserIsolationKey:
    return UserIsolationKey(
        tenant_id="tenant-cn-1",
        user_id="user-2b4aa1b95c884d64",
        session_id="session-1234567890",
    )


def _request(action: FeedbackAction = FeedbackAction.FAVORITE) -> FeedbackIngestionRequest:
    occurred = datetime(2026, 8, 24, tzinfo=UTC)
    return FeedbackIngestionRequest(
        feedback_id="feedback-001",
        scope=_scope(),
        action=action,
        target_id="restaurant-001",
        payload={"surface": "results"},
        consent=MemoryConsent(
            basis=ConsentBasis.PERSONALIZATION_OPT_IN,
            policy_version="memory-policy/v1",
            status=ConsentStatus.ACTIVE,
            captured_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        policy_version="memory-policy/v1",
        occurred_at=occurred,
        idempotency_key="feedback-idempotency-001",
    )


class _Repository:
    def __init__(self) -> None:
        self.writes: list[MemoryAuthorityWrite] = []

    async def commit_authority_write(self, write: MemoryAuthorityWrite) -> str:
        self.writes.append(write)
        return write.outbox.outbox_id


@pytest.mark.unit
async def test_feedback_writes_private_event_and_outbox_with_stable_ids() -> None:
    repository = _Repository()
    ingestor = FeedbackIngestor(repository)
    request = _request(FeedbackAction.CLICK)

    first = await ingestor.ingest(request, authorized_scope=_scope())
    second = await ingestor.ingest(request, authorized_scope=_scope())

    assert first == second
    assert first.event_id == "feedback:feedback-idempotency-001"
    assert len(repository.writes) == 2
    write = repository.writes[0]
    assert write.source_event is not None
    assert write.source_event.event_type == "feedback.click"
    assert write.outbox.event_type == "memory.feedback.project"
    assert write.source_event.idempotency_key == request.idempotency_key


@pytest.mark.unit
async def test_feedback_rejects_cross_scope_before_authority_write() -> None:
    repository = _Repository()
    with pytest.raises(PermissionError, match="outside the authorized scope"):
        await FeedbackIngestor(repository).ingest(
            _request(),
            authorized_scope=AnonymousIsolationKey(
                tenant_id="tenant-cn-1",
                anonymous_subject_id="anon-8bf1c0f4317f4e9d",
                session_id="session-1234567890",
            ),
        )
    assert repository.writes == []


@pytest.mark.unit
def test_feedback_requires_active_personalization_consent() -> None:
    with pytest.raises(ValueError, match="active consent"):
        FeedbackIngestionRequest.model_validate(
            _request().model_dump(mode="python")
            | {
                "consent": {
                    "basis": "personalization_opt_in",
                    "policy_version": "memory-policy/v1",
                    "status": "withdrawn",
                    "captured_at": datetime(2026, 8, 1, tzinfo=UTC),
                }
            }
        )
