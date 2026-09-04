"""Low-frequency shop-profile refresh coordination."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable, Sequence
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
        concurrency: int = 3,
    ) -> None:
        self._repository = repository
        self._policy = policy or ShopProfileRefreshPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._concurrency = max(1, int(concurrency))
        # Keep the bounds at service scope.  A semaphore created inside
        # ``plan``/``commit`` would only protect one call and could be
        # bypassed when two workflow turns refresh profiles concurrently.
        self._lookup_semaphore = asyncio.Semaphore(self._concurrency)
        self._upsert_semaphore = asyncio.Semaphore(self._concurrency)

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
        lookups = await self._lookup_many(names)
        for name, value in zip(names, lookups, strict=False):
            profile, error = value
            if error is not None:
                gaps.append(error)
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
        candidates = _unique_refresh_profiles(
            profile for profile in refreshed
        )
        persisted_values = await self._upsert_many(candidates)
        gaps: list[ResearchGap] = list(plan.gaps)
        for profile, (persisted, error) in zip(candidates, persisted_values, strict=False):
            if error is not None:
                gaps.append(error)
                continue
            if persisted is not None:
                _replace_profile(profiles, persisted)
            else:
                # A repository returning ``None`` violates the upsert
                # contract. Do not silently report a successful refresh that
                # was never made visible to the profile view.
                gaps.append(
                    ResearchGap(
                        source="shop_profile",
                        operation="profile.upsert",
                        code="profile_persistence_empty",
                        message="profile repository returned no persisted profile",
                        retryable=True,
                        details={"name": profile.name},
                    )
                )
        return ShopProfileSyncResult(
            profiles=tuple(_order_profiles(plan.candidates, profiles)),
            gaps=tuple(gaps),
        )

    async def _lookup_many(
        self, names: Sequence[str]
    ) -> tuple[tuple[ShopProfile | None, ResearchGap | None], ...]:
        """Read cache entries concurrently while preserving candidate order.

        Repositories may optionally expose a native ``find_many_by_name``
        method.  The fallback uses the same bounded service semaphore, so a
        legacy repository remains safe without forcing a protocol migration.
        """

        batch_lookup = getattr(self._repository, "find_many_by_name", None)
        if callable(batch_lookup):
            try:
                async with self._lookup_semaphore:
                    value = batch_lookup(tuple(names))
                    if inspect.isawaitable(value):
                        value = await value
                    normalised = _normalise_batch_profiles(names, value)
                    if normalised is not None:
                        return normalised
            except Exception as exc:
                # A broken optional batch implementation should degrade to
                # item-level reads rather than erase the cache view.
                _ = exc

        async def lookup(name: str) -> tuple[ShopProfile | None, ResearchGap | None]:
            async with self._lookup_semaphore:
                try:
                    return await self._repository.find_by_name(name), None
                except Exception as exc:
                    return None, ResearchGap(
                        source="shop_profile",
                        operation="cache.lookup",
                        code="profile_lookup_failed",
                        message=type(exc).__name__,
                        retryable=True,
                        details={"candidate": name},
                    )

        return tuple(await asyncio.gather(*(lookup(name) for name in names)))

    async def _upsert_many(
        self, profiles: Sequence[ShopProfile]
    ) -> tuple[tuple[ShopProfile | None, ResearchGap | None], ...]:
        """Persist profiles concurrently with per-item error isolation."""

        if not profiles:
            return ()
        batch_upsert = getattr(self._repository, "upsert_many", None)
        if callable(batch_upsert):
            try:
                async with self._upsert_semaphore:
                    value = batch_upsert(tuple(profiles))
                    if inspect.isawaitable(value):
                        value = await value
                    normalised = _normalise_batch_upserts(profiles, value)
                    if normalised is not None:
                        return normalised
            except Exception:
                # Fall through to isolated calls; the failed batch must not
                # discard profiles that can still be written individually.
                pass

        async def upsert(profile: ShopProfile) -> tuple[ShopProfile | None, ResearchGap | None]:
            async with self._upsert_semaphore:
                try:
                    return await self._repository.upsert(profile), None
                except Exception as exc:
                    return None, ResearchGap(
                        source="shop_profile",
                        operation="profile.upsert",
                        code="profile_persistence_failed",
                        message=type(exc).__name__,
                        retryable=True,
                        details={"name": profile.name},
                    )

        return tuple(await asyncio.gather(*(upsert(profile) for profile in profiles)))


def _unique_refresh_profiles(
    profiles: Iterable[ShopProfile],
) -> tuple[ShopProfile, ...]:
    """Keep one deterministic refresh per provider identity or normalized name."""

    output: list[ShopProfile] = []
    seen: set[str] = set()
    for profile in profiles:
        provider_ref = _provider_ref(profile)
        key = (
            f"dianping:{provider_ref}"
            if provider_ref
            else f"name:{_normalise_name(profile.name)}"
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(profile)
    return tuple(output)


def _normalise_batch_upserts(
    profiles: Sequence[ShopProfile],
    value: object,
) -> tuple[tuple[ShopProfile | None, ResearchGap | None], ...] | None:
    """Validate optional batch-upsert output before it reaches the reducer."""

    if not isinstance(value, (list, tuple)) or len(value) != len(profiles):
        return None
    output: list[tuple[ShopProfile | None, ResearchGap | None]] = []
    for item in value:
        if isinstance(item, ShopProfile):
            output.append((item, None))
            continue
        if isinstance(item, (list, tuple)) and len(item) == 2:
            persisted, error = item
            if (persisted is None or isinstance(persisted, ShopProfile)) and (
                error is None or isinstance(error, ResearchGap)
            ):
                output.append((persisted, error))
                continue
        if item is None:
            output.append((None, None))
            continue
        return None
    return tuple(output)


def _replace_profile(profiles: list[ShopProfile], incoming: ShopProfile) -> None:
    incoming_ref = _provider_ref(incoming)
    incoming_name = _normalise_name(incoming.name)
    if incoming_ref:
        # Provider ids are authoritative. A name match cannot merge two
        # provider identities, nor can it attach an identified profile to an
        # unidentified placeholder.
        for index, current in enumerate(profiles):
            current_ref = _provider_ref(current)
            if current_ref and incoming_ref == current_ref:
                profiles[index] = incoming
                return
        profiles.append(incoming)
        return

    # Name fallback is allowed only when both sides lack ids, and only when
    # there is one exact normalized candidate. Substring matches such as
    # ``老店`` versus ``老店春熙路店`` are different shops/branches.
    matches = [
        index
        for index, current in enumerate(profiles)
        if not _provider_ref(current)
        and incoming_name
        and incoming_name == _normalise_name(current.name)
    ]
    if len(matches) == 1:
        profiles[matches[0]] = incoming
        return
    profiles.append(incoming)


def _normalise_batch_profiles(
    names: Sequence[str], value: object
) -> tuple[tuple[ShopProfile | None, ResearchGap | None], ...] | None:
    """Normalize optional repository batch responses without guessing rows."""

    by_name: dict[str, ShopProfile] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, ShopProfile):
                by_name[_normalise_name(str(key))] = item
                by_name.setdefault(_normalise_name(item.name), item)
    elif isinstance(value, (list, tuple)):
        if len(value) == len(names):
            aligned: list[tuple[ShopProfile | None, ResearchGap | None]] = []
            for item in value:
                aligned.append((item if isinstance(item, ShopProfile) else None, None))
            return tuple(aligned)
        if not value:
            return tuple((None, None) for _ in names)
        for item in value:
            if isinstance(item, ShopProfile):
                by_name.setdefault(_normalise_name(item.name), item)
            else:
                return None
    else:
        return None
    return tuple((by_name.get(_normalise_name(name)), None) for name in names)


def _order_profiles(
    candidates: Sequence[str], profiles: Sequence[ShopProfile]
) -> list[ShopProfile]:
    output: list[ShopProfile] = []
    remaining = list(profiles)
    for candidate in candidates:
        normalized = _normalise_name(candidate)
        matches = [
            profile
            for profile in remaining
            if normalized and normalized == _normalise_name(profile.name)
        ]
        if len(matches) == 1:
            output.append(matches[0])
            remaining.remove(matches[0])
    output.extend(remaining)
    return output


def _normalise_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _provider_ref(profile: ShopProfile) -> str | None:
    value = profile.provider_refs.get("dianping")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _names_match(left: str, right: str) -> bool:
    return bool(left and right and left == right)


__all__ = [
    "ShopProfileRefreshPlan",
    "ShopProfileRefreshPolicy",
    "ShopProfileService",
    "ShopProfileSyncResult",
]
