"""Explicit scope authorization for private memory operations."""

from __future__ import annotations

from xhs_food.contracts import (
    AnonymousClaimReceipt,
    AnonymousClaimRequest,
    AnonymousIsolationKey,
    MemoryIsolationKey,
    MemoryRepositoryPort,
)


class MemoryScopeAuthorizer:
    """Reject cross-user, cross-tenant, and anonymous-session access."""

    @staticmethod
    def require_same_scope(
        requested: MemoryIsolationKey,
        authorized: MemoryIsolationKey,
    ) -> None:
        if _scope_key(requested) != _scope_key(authorized):
            raise PermissionError("memory access is outside the authorized scope")


class AnonymousMemoryClaimService:
    """Validate caller binding before delegating an atomic authority claim."""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        *,
        authorizer: MemoryScopeAuthorizer | None = None,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer or MemoryScopeAuthorizer()

    async def claim(
        self,
        request: AnonymousClaimRequest,
        *,
        authorized_anonymous_scope: AnonymousIsolationKey,
        authorized_user_id: str,
    ) -> AnonymousClaimReceipt:
        self._authorizer.require_same_scope(
            request.source_scope,
            authorized_anonymous_scope,
        )
        if authorized_user_id != request.target_user_id:
            raise PermissionError("claim target does not match the authenticated user")
        return await self._repository.claim_anonymous(request)


def _scope_key(scope: MemoryIsolationKey) -> tuple[str, str, str, str | None]:
    if isinstance(scope, AnonymousIsolationKey):
        subject_id = scope.anonymous_subject_id
    else:
        subject_id = scope.user_id
    return (scope.tenant_id, str(scope.kind), subject_id, scope.session_id)


__all__ = ["AnonymousMemoryClaimService", "MemoryScopeAuthorizer"]
