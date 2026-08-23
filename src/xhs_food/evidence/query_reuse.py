"""Three-tier Query Family matching and freshness orchestration."""

from __future__ import annotations

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    FreshnessDecision,
    FreshnessInput,
    FreshnessPolicy,
    QueryFamilyMatch,
    QueryFamilyRepository,
    QueryMatchLayer,
    QueryReuseDecision,
    QueryReuseRequest,
    RefreshClaim,
    RefreshSingleFlightKey,
    decide_freshness,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
    validate_embedding_vector,
)


class QueryFamilyReuseService:
    """Resolve a public query without allowing personal data into the key."""

    def __init__(
        self,
        repository: QueryFamilyRepository,
        *,
        trigram_threshold: float = 0.90,
        vector_threshold: float = 0.82,
    ) -> None:
        if not 0.0 <= vector_threshold <= trigram_threshold <= 1.0:
            raise ValueError("matching thresholds must satisfy 0 <= vector <= trigram <= 1")
        self._repository = repository
        self._trigram_threshold = trigram_threshold
        self._vector_threshold = vector_threshold

    async def resolve(self, request: QueryReuseRequest) -> QueryReuseDecision:
        attempted: list[QueryMatchLayer] = [QueryMatchLayer.DETERMINISTIC]
        exact = await self._repository.get_exact(request.canonical_key)
        if exact is not None:
            _ensure_layer(exact, QueryMatchLayer.DETERMINISTIC)
            return QueryReuseDecision(
                request=request,
                match=exact,
                attempted_layers=tuple(attempted),
            )

        attempted.append(QueryMatchLayer.TRIGRAM)
        trigram = await self._repository.search_trigram(request.alias_text)
        approved_trigram = _best_approved(trigram, self._trigram_threshold)
        if approved_trigram is not None:
            _ensure_layer(approved_trigram, QueryMatchLayer.TRIGRAM)
            return QueryReuseDecision(
                request=request,
                match=approved_trigram,
                attempted_layers=tuple(attempted),
            )

        attempted.append(QueryMatchLayer.VECTOR)
        if request.vector is None:
            return QueryReuseDecision(request=request, attempted_layers=tuple(attempted))
        if request.embedding_profile != BGE_M3_PROFILE_V1:
            raise ValueError("B2 vector reuse is pinned to bge-m3/profile_v1")
        validate_embedding_vector(request.embedding_profile, request.vector)
        vector_matches = await self._repository.search_vector(
            request.vector, request.embedding_profile
        )
        approved_vector = _best_approved(vector_matches, self._vector_threshold)
        if approved_vector is not None:
            _ensure_layer(approved_vector, QueryMatchLayer.VECTOR)
        return QueryReuseDecision(
            request=request,
            match=approved_vector,
            attempted_layers=tuple(attempted),
        )

    async def freshness(
        self,
        current: FreshnessInput | None,
        policy: FreshnessPolicy,
    ) -> FreshnessDecision:
        return decide_freshness(current, policy)


class RefreshSingleFlightService:
    """Use Temporal IDs and PostgreSQL claims; Redis is deliberately absent."""

    def __init__(self, repository: QueryFamilyRepository) -> None:
        self._repository = repository

    async def claim(self, key: RefreshSingleFlightKey) -> RefreshClaim:
        claim = await self._repository.claim_refresh(key)
        expected = stable_refresh_workflow_id(key)
        if claim.workflow_id != expected:
            raise ValueError("repository returned a non-deterministic refresh workflow id")
        if claim.claim_key != stable_refresh_claim_key(key):
            raise ValueError("repository returned a non-deterministic refresh claim key")
        return claim

    async def activate_bundle_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
    ) -> bool:
        return await self._repository.activate_bundle_if_current(
            family_id,
            expected_bundle_version,
            bundle_id,
            bundle_version,
        )


def _best_approved(
    matches: tuple[QueryFamilyMatch, ...], threshold: float
) -> QueryFamilyMatch | None:
    approved = [item for item in matches if item.confidence >= threshold]
    if not approved:
        return None
    return max(approved, key=lambda item: (item.confidence, item.family_id, item.canonical_key))


def _ensure_layer(match: QueryFamilyMatch, expected: QueryMatchLayer) -> None:
    if match.layer is not expected:
        raise ValueError(f"repository returned {match.layer.value} for {expected.value} tier")


__all__ = [
    "QueryFamilyReuseService",
    "RefreshSingleFlightService",
]
