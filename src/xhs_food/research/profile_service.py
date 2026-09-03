"""Low-frequency shop-profile refresh coordination."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from xhs_food.contracts import (
    ResearchGap,
    ResearchOutcome,
    ShopProfile,
    ShopProfileRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class ShopProfileRefreshPolicy:
    """Decide when durable Dianping facts should be fetched again."""

    refresh_after: timedelta = timedelta(days=7)
    partial_retry_after: timedelta = timedelta(hours=12)

    def requires_refresh(self, profile: ShopProfile, *, now: datetime) -> bool:
        observed_at = profile.fetched_at or profile.source_updated_at
        if observed_at is None:
            return True
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        retry_after = (
            self.refresh_after
            if profile.outcome is ResearchOutcome.COMPLETE
            else self.partial_retry_after
        )
        return now - observed_at >= retry_after


@dataclass(frozen=True, slots=True)
class ShopProfileRefreshPlan:
    candidates: tuple[str, ...]
    cached_profiles: tuple[ShopProfile, ...]
    refresh_candidates: tuple[str, ...]
    fresh_cache_hits: tuple[str, ...]
    gaps: tuple[ResearchGap, ...] = ()


@dataclass(frozen=True, slots=True)
class ShopProfileSyncResult:
    profiles: tuple[ShopProfile, ...]
    gaps: tuple[ResearchGap, ...] = ()


class ShopProfileService:
    """Own profile cache decisions and non-destructive persistence."""

    def __init__(
        self,
        repository: ShopProfileRepositoryPort,
        *,
        policy: ShopProfileRefreshPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or ShopProfileRefreshPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def repository(self) -> ShopProfileRepositoryPort:
        return self._repository

    async def plan(self, candidates: Sequence[str]) -> ShopProfileRefreshPlan:
        names = tuple(
            dict.fromkeys(str(name).strip() for name in candidates if str(name).strip())
        )
        cached: list[ShopProfile] = []
        refresh: list[str] = []
        hits: list[str] = []
        gaps: list[ResearchGap] = []
        now = self._clock()
        for name in names:
            try:
                profile = await self._repository.find_by_name(name)
            except Exception as exc:
                profile = None
                gaps.append(
                    ResearchGap(
                        source="shop_profile",
                        operation="cache.lookup",
                        code="profile_lookup_failed",
                        message=type(exc).__name__,
                        retryable=True,
                        details={"candidate": name},
                    )
                )
            if profile is None:
                refresh.append(name)
                continue
            cached.append(profile)
            if self._policy.requires_refresh(profile, now=now):
                refresh.append(name)
            else:
                hits.append(name)
        return ShopProfileRefreshPlan(
            candidates=names,
            cached_profiles=tuple(cached),
            refresh_candidates=tuple(refresh),
            fresh_cache_hits=tuple(hits),
            gaps=tuple(gaps),
        )

    async def commit(
        self,
        plan: ShopProfileRefreshPlan,
        refreshed: Sequence[ShopProfile],
    ) -> ShopProfileSyncResult:
        profiles = list(plan.cached_profiles)
        gaps: list[ResearchGap] = []
        for profile in refreshed:
            if not profile.provider_refs:
                continue
            try:
                persisted = await self._repository.upsert(profile)
            except Exception as exc:
                gaps.append(
                    ResearchGap(
                        source="shop_profile",
                        operation="profile.upsert",
                        code="profile_persistence_failed",
                        message=type(exc).__name__,
                        retryable=True,
                        details={"name": profile.name},
                    )
                )
                continue
            _replace_profile(profiles, persisted)
        return ShopProfileSyncResult(
            profiles=tuple(_order_profiles(plan.candidates, profiles)),
            gaps=tuple(gaps),
        )


def _replace_profile(profiles: list[ShopProfile], incoming: ShopProfile) -> None:
    incoming_ref = incoming.provider_refs.get("dianping")
    incoming_name = _normalise_name(incoming.name)
    for index, current in enumerate(profiles):
        current_ref = current.provider_refs.get("dianping")
        current_name = _normalise_name(current.name)
        if (incoming_ref and incoming_ref == current_ref) or _names_match(
            incoming_name, current_name
        ):
            profiles[index] = incoming
            return
    profiles.append(incoming)


def _order_profiles(
    candidates: Sequence[str], profiles: Sequence[ShopProfile]
) -> list[ShopProfile]:
    output: list[ShopProfile] = []
    remaining = list(profiles)
    for candidate in candidates:
        normalized = _normalise_name(candidate)
        for profile in tuple(remaining):
            if _names_match(normalized, _normalise_name(profile.name)):
                output.append(profile)
                remaining.remove(profile)
                break
    output.extend(remaining)
    return output


def _normalise_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _names_match(left: str, right: str) -> bool:
    return bool(left and right and (left == right or left in right or right in left))


__all__ = [
    "ShopProfileRefreshPlan",
    "ShopProfileRefreshPolicy",
    "ShopProfileService",
    "ShopProfileSyncResult",
]
