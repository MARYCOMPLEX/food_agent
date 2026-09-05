"""Three-tier Query Family matching and freshness orchestration."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from difflib import SequenceMatcher
from typing import cast

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    CurrentBundleRef,
    DomainContract,
    EmbeddingProfile,
    FreshnessDecision,
    FreshnessInput,
    FreshnessPolicy,
    FreshnessPolicyAdapter,
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
            _ensure_match(exact, QueryMatchLayer.DETERMINISTIC, request)
            if exact.normalization_version == request.normalization_version:
                return QueryReuseDecision(
                    request=request,
                    match=exact,
                    attempted_layers=tuple(attempted),
                )

        attempted.append(QueryMatchLayer.TRIGRAM)
        trigram = await self._repository.search_trigram(request.alias_text)
        approved_trigram = _best_approved(
            _validate_matches(trigram, QueryMatchLayer.TRIGRAM, request),
            self._trigram_threshold,
        )
        if approved_trigram is not None:
            _ensure_match(approved_trigram, QueryMatchLayer.TRIGRAM, request)
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
        approved_vector = _best_approved(
            _validate_matches(vector_matches, QueryMatchLayer.VECTOR, request),
            self._vector_threshold,
        )
        if approved_vector is not None:
            _ensure_match(approved_vector, QueryMatchLayer.VECTOR, request)
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

    async def route(
        self,
        request: QueryReuseRequest,
        policy: FreshnessPolicy,
        *,
        now: datetime | None = None,
    ) -> tuple[QueryReuseDecision, FreshnessDecision | None]:
        """Resolve a Family and evaluate its persisted freshness facts.

        A missing match is deliberately represented by ``None`` freshness;
        callers must create a new research task instead of inventing a Family.
        """

        decision = await self.resolve(request)
        if decision.match is None:
            return decision, None
        current = await self._repository.get_freshness(decision.match.family_id)
        freshness = decide_freshness(
            current,
            policy,
            now=now,
            family_id=decision.match.family_id,
        )
        return decision, freshness


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

    async def finish(
        self,
        key: RefreshSingleFlightKey,
        status: str,
    ) -> bool:
        """Persist a terminal claim state without changing its identity."""

        if status not in {"completed", "failed", "cancelled", "active"}:
            raise ValueError("unsupported refresh claim status")
        update = getattr(self._repository, "update_refresh_status", None)
        if not callable(update):
            raise TypeError("repository does not support refresh claim lifecycle")
        update_fn = cast(Callable[[str, str], Awaitable[object]], update)
        return bool(await update_fn(stable_refresh_claim_key(key), status))


class DomainPackFreshnessPolicyAdapter(FreshnessPolicyAdapter):
    """Bind freshness thresholds to a validated Domain Pack manifest.

    The adapter is intentionally small: the Domain Pack owns the policy
    version, while deployment supplies the reviewed threshold values.
    """

    def __init__(
        self,
        domain: DomainContract,
        *,
        policy_id: str | None = None,
        max_staleness_seconds: int,
        minimum_coverage: Mapping[str, float] | None = None,
        fresh_for_seconds: int | None = None,
        max_stale_for_seconds: int | None = None,
        maximum_staleness_seconds: int | None = None,
    ) -> None:
        manifest = domain.describe()
        policy_version = manifest.policy_profiles.freshness
        resolved_policy_id = policy_id or f"{manifest.domain_id}.default"
        self._policy = FreshnessPolicy(
            policy_id=resolved_policy_id,
            policy_version=policy_version,
            max_staleness_seconds=max_staleness_seconds,
            minimum_coverage=dict(minimum_coverage or {}),
            fresh_for_seconds=fresh_for_seconds,
            max_stale_for_seconds=max_stale_for_seconds,
            maximum_staleness_seconds=maximum_staleness_seconds,
        )

    def policy(self) -> FreshnessPolicy:
        return self._policy


def freshness_policy_from_domain_pack(
    domain: DomainContract,
    *,
    policy_id: str | None = None,
    max_staleness_seconds: int,
    minimum_coverage: Mapping[str, float] | None = None,
    fresh_for_seconds: int | None = None,
    max_stale_for_seconds: int | None = None,
    maximum_staleness_seconds: int | None = None,
) -> FreshnessPolicy:
    return DomainPackFreshnessPolicyAdapter(
        domain,
        policy_id=policy_id,
        max_staleness_seconds=max_staleness_seconds,
        minimum_coverage=minimum_coverage,
        fresh_for_seconds=fresh_for_seconds,
        max_stale_for_seconds=max_stale_for_seconds,
        maximum_staleness_seconds=maximum_staleness_seconds,
    ).policy()


class InMemoryQueryFamilyRepository:
    """Deterministic repository fixture with PostgreSQL-equivalent semantics."""

    def __init__(self) -> None:
        self._exact: dict[str, QueryFamilyMatch] = {}
        self._aliases: list[QueryFamilyMatch] = []
        self._vectors: list[tuple[QueryFamilyMatch, tuple[float, ...]]] = []
        self._freshness: dict[str, FreshnessInput] = {}
        self._claims: dict[str, RefreshClaim] = {}
        self._current: dict[str, CurrentBundleRef] = {}
        self._lock = asyncio.Lock()

    def add_exact(self, match: QueryFamilyMatch) -> None:
        _ensure_layer(match, QueryMatchLayer.DETERMINISTIC)
        _validate_public_text(match.canonical_key, field_name="canonical_key")
        self._exact[match.canonical_key] = match

    def add_alias(self, match: QueryFamilyMatch) -> None:
        _ensure_layer(match, QueryMatchLayer.TRIGRAM)
        if match.matched_alias is None:
            raise ValueError("trigram matches require the matched alias")
        _validate_public_text(match.matched_alias, field_name="alias_text")
        self._aliases.append(match)

    def add_vector(
        self,
        match: QueryFamilyMatch,
        vector: tuple[float, ...],
        *,
        profile: EmbeddingProfile = BGE_M3_PROFILE_V1,
    ) -> None:
        _ensure_layer(match, QueryMatchLayer.VECTOR)
        if match.profile_id != profile.profile_id or match.profile_version != profile.model_version:
            raise ValueError("vector match metadata does not match the profile")
        validate_embedding_vector(profile, vector)
        self._vectors.append((match, vector))

    async def get_exact(self, canonical_key: str) -> QueryFamilyMatch | None:
        _validate_public_text(canonical_key, field_name="canonical_key")
        return self._exact.get(canonical_key)

    async def search_trigram(
        self, alias_text: str, *, limit: int = 5
    ) -> tuple[QueryFamilyMatch, ...]:
        _validate_public_text(alias_text, field_name="alias_text")
        _validate_limit(limit)
        scored = [
            (SequenceMatcher(None, alias_text.casefold(), item.matched_alias.casefold()).ratio(), item)
            for item in self._aliases
            if item.matched_alias is not None
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].family_id, pair[1].canonical_key))
        return tuple(
            item.model_copy(update={"confidence": confidence})
            for confidence, item in scored[:limit]
        )

    async def search_vector(
        self,
        vector: tuple[float, ...],
        profile: EmbeddingProfile,
        *,
        limit: int = 5,
    ) -> tuple[QueryFamilyMatch, ...]:
        _validate_limit(limit)
        validate_embedding_vector(profile, vector)
        scored = [
            (_cosine_similarity(vector, stored), item)
            for item, stored in self._vectors
            if item.profile_id == profile.profile_id
            and item.profile_version == profile.model_version
            and len(stored) == profile.dimensions
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].family_id, pair[1].canonical_key))
        return tuple(
            item.model_copy(update={"confidence": max(0.0, min(1.0, confidence))})
            for confidence, item in scored[:limit]
        )

    async def get_freshness(self, family_id: str) -> FreshnessInput | None:
        return self._freshness.get(family_id)

    async def save_freshness(self, state: FreshnessInput) -> None:
        self._freshness[state.family_id] = state

    async def claim_refresh(self, key: RefreshSingleFlightKey) -> RefreshClaim:
        claim_key = stable_refresh_claim_key(key)
        workflow_id = stable_refresh_workflow_id(key)
        async with self._lock:
            existing = self._claims.get(claim_key)
            if existing is not None:
                return existing.model_copy(update={"acquired": False})
            claim = RefreshClaim(claim_key=claim_key, workflow_id=workflow_id, acquired=True)
            self._claims[claim_key] = claim
            return claim

    async def update_refresh_status(self, claim_key: str, status: str) -> bool:
        if status not in {"active", "completed", "failed", "cancelled"}:
            raise ValueError("unsupported refresh claim status")
        async with self._lock:
            claim = self._claims.get(claim_key)
            if claim is None:
                return False
            if claim.status == status:
                return True
            if claim.status != "active":
                return False
            self._claims[claim_key] = claim.model_copy(update={"status": status})
            return True

    async def activate_bundle_if_current(
        self,
        family_id: str,
        expected_bundle_version: int | None,
        bundle_id: str,
        bundle_version: int,
    ) -> bool:
        async with self._lock:
            if bundle_version < 1:
                return False
            current = self._current.get(family_id)
            if expected_bundle_version is None:
                if current is None:
                    self._current[family_id] = CurrentBundleRef(
                        family_id=family_id,
                        bundle_id=bundle_id,
                        bundle_version=bundle_version,
                    )
                    return True
                return current.bundle_id == bundle_id and current.bundle_version == bundle_version
            if current is None or current.bundle_version != expected_bundle_version:
                return False
            if bundle_version < current.bundle_version:
                return False
            if bundle_version == current.bundle_version and current.bundle_id != bundle_id:
                return False
            self._current[family_id] = CurrentBundleRef(
                family_id=family_id,
                bundle_id=bundle_id,
                bundle_version=bundle_version,
            )
            return True

    async def get_current_bundle(self, family_id: str) -> CurrentBundleRef | None:
        return self._current.get(family_id)


_PRIVATE_TEXT_MARKERS = frozenset(
    {
        "user",
        "users",
        "userid",
        "session",
        "sessions",
        "sessionid",
        "subject",
        "subjects",
        "identity",
        "identities",
        "deviceid",
        "preference",
        "preferences",
        "memory",
        "favorite",
        "favorites",
        "cookie",
        "token",
        "credential",
        "credentials",
        "password",
        "secret",
        "account",
    }
)


def _validate_public_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    normalized = "".join(character for character in value.casefold() if character.isalnum())
    if any(marker in normalized for marker in _PRIVATE_TEXT_MARKERS):
        raise ValueError(f"{field_name} contains a private identity marker")


def _best_approved(
    matches: tuple[QueryFamilyMatch, ...], threshold: float
) -> QueryFamilyMatch | None:
    approved = [item for item in matches if item.confidence >= threshold]
    if not approved:
        return None
    return min(approved, key=lambda item: (-item.confidence, item.family_id, item.canonical_key))


def _validate_matches(
    matches: tuple[QueryFamilyMatch, ...],
    expected: QueryMatchLayer,
    request: QueryReuseRequest,
) -> tuple[QueryFamilyMatch, ...]:
    if not isinstance(matches, tuple):
        raise ValueError("repository matching results must be an immutable tuple")
    valid: list[QueryFamilyMatch] = []
    for match in matches:
        if not isinstance(match, QueryFamilyMatch):
            raise ValueError("repository returned an invalid Query Family match")
        _ensure_match(match, expected, request)
        if match.normalization_version == request.normalization_version:
            valid.append(match)
    return tuple(valid)


def _ensure_match(
    match: QueryFamilyMatch, expected: QueryMatchLayer, request: QueryReuseRequest
) -> None:
    _validate_public_text(match.canonical_key, field_name="canonical_key")
    if match.layer is not expected:
        raise ValueError(f"repository returned {match.layer.value} for {expected.value} tier")
    if expected is QueryMatchLayer.DETERMINISTIC and match.canonical_key != request.canonical_key:
        raise ValueError("deterministic repository match returned a different canonical key")
    if expected is QueryMatchLayer.VECTOR and (
        match.profile_id != request.embedding_profile.profile_id
        or match.profile_version != request.embedding_profile.model_version
    ):
        raise ValueError("vector repository match returned an incompatible profile")


def _ensure_layer(match: QueryFamilyMatch, expected: QueryMatchLayer) -> None:
    if match.layer is not expected:
        raise ValueError(f"repository returned {match.layer.value} for {expected.value} tier")


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("matching limit must be an integer between 1 and 100")


def _cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0
    return sum(left * right for left, right in zip(first, second, strict=True)) / (
        first_norm * second_norm
    )


__all__ = [
    "DomainPackFreshnessPolicyAdapter",
    "InMemoryQueryFamilyRepository",
    "QueryFamilyReuseService",
    "RefreshSingleFlightService",
    "freshness_policy_from_domain_pack",
]
