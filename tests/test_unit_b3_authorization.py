"""B3 private-memory authorization and anonymous-claim contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xhs_food.contracts import (
    AnonymousClaimReceipt,
    AnonymousClaimRequest,
    AnonymousIsolationKey,
    UserIsolationKey,
)
from xhs_food.personalization import AnonymousMemoryClaimService, MemoryScopeAuthorizer


def _anonymous_scope() -> AnonymousIsolationKey:
    return AnonymousIsolationKey(
        tenant_id="tenant-cn-1",
        anonymous_subject_id="anon-8bf1c0f4317f4e9d",
        session_id="sess-anon-001",
    )


def _request() -> AnonymousClaimRequest:
    return AnonymousClaimRequest(
        claim_id="claim-001",
        source_scope=_anonymous_scope(),
        target_user_id="user-2b4aa1b95c884d64",
        one_time_token="one-time-token-fixture",
        consent_policy_version="memory-policy/v1",
        idempotency_key="claim-idempotency-001",
        requested_at=datetime(2026, 8, 24, tzinfo=UTC),
    )


class _Repository:
    def __init__(self) -> None:
        self.requests: list[AnonymousClaimRequest] = []

    async def claim_anonymous(self, request: AnonymousClaimRequest) -> AnonymousClaimReceipt:
        self.requests.append(request)
        return AnonymousClaimReceipt(
            claim_id=request.claim_id,
            source_scope=request.source_scope,
            target_scope=UserIsolationKey(
                tenant_id=request.source_scope.tenant_id,
                user_id=request.target_user_id,
                session_id=request.source_scope.session_id,
            ),
        )


@pytest.mark.unit
async def test_claim_requires_matching_anonymous_scope_and_authenticated_user() -> None:
    repository = _Repository()
    request = _request()
    receipt = await AnonymousMemoryClaimService(repository).claim(
        request,
        authorized_anonymous_scope=_anonymous_scope(),
        authorized_user_id=request.target_user_id,
    )
    assert receipt.target_scope.user_id == request.target_user_id
    assert repository.requests == [request]

    with pytest.raises(PermissionError, match="outside the authorized scope"):
        await AnonymousMemoryClaimService(repository).claim(
            request,
            authorized_anonymous_scope=AnonymousIsolationKey(
                tenant_id="tenant-other-1",
                anonymous_subject_id="anon-other-8bf1c0f4317f4e9d",
                session_id="sess-anon-001",
            ),
            authorized_user_id=request.target_user_id,
        )
    with pytest.raises(PermissionError, match="authenticated user"):
        await AnonymousMemoryClaimService(repository).claim(
            request,
            authorized_anonymous_scope=_anonymous_scope(),
            authorized_user_id="user-other-2b4aa1b95c884d64",
        )
    assert len(repository.requests) == 1


@pytest.mark.unit
def test_scope_authorizer_rejects_cross_tenant_and_cross_session_access() -> None:
    scope = _anonymous_scope()
    with pytest.raises(PermissionError):
        MemoryScopeAuthorizer.require_same_scope(
            scope,
            AnonymousIsolationKey(
                tenant_id=scope.tenant_id,
                anonymous_subject_id=scope.anonymous_subject_id,
                session_id="sess-other-001",
            ),
        )


@pytest.mark.unit
def test_claim_rejects_forbidden_or_same_subject_target() -> None:
    with pytest.raises(ValueError, match="at least 16|authenticated user identity"):
        AnonymousClaimRequest.model_validate(
            _request().model_dump(mode="python") | {"target_user_id": "anonymous"}
        )
    with pytest.raises(ValueError, match="differ"):
        AnonymousClaimRequest(
            claim_id="claim-same-subject",
            source_scope=_anonymous_scope(),
            target_user_id=_anonymous_scope().anonymous_subject_id,
            one_time_token="one-time-token-fixture",
            consent_policy_version="memory-policy/v1",
            idempotency_key="claim-idempotency-same",
            requested_at=datetime(2026, 8, 24, tzinfo=UTC),
        )
