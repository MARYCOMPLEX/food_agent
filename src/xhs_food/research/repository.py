"""Shop profile repositories, kept separate from comment evidence storage."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from xhs_food.contracts import ResearchGap, ResearchOutcome, ShopProfile

StorageProvider = Callable[[], Awaitable[Any] | Any]
IdentityFactory = Callable[[str], str]


class InMemoryShopProfileRepository:
    """Reference implementation with non-destructive partial refresh semantics."""

    def __init__(self) -> None:
        self._profiles: dict[str, ShopProfile] = {}

    async def upsert(self, profile: ShopProfile) -> ShopProfile:
        key = _profile_key(profile)
        current = self._profiles.get(key)
        merged = profile if current is None else merge_profiles(current, profile)
        self._profiles[key] = merged
        return merged

    async def get(self, key: str) -> ShopProfile | None:
        return self._profiles.get(key)

    async def find_by_name(self, name: str) -> ShopProfile | None:
        target = _normalise_name(name)
        if not target:
            return None
        for profile in self._profiles.values():
            candidate = _normalise_name(profile.name)
            if candidate == target or candidate in target or target in candidate:
                return profile
        return None

    @property
    def profiles(self) -> tuple[ShopProfile, ...]:
        return tuple(self._profiles.values())


class UserStorageShopProfileRepository:
    """Adapt ShopProfile to the existing ``restaurants`` table owner API."""

    def __init__(
        self,
        storage_provider: StorageProvider,
        *,
        identity_factory: IdentityFactory | None = None,
    ) -> None:
        self._storage_provider = storage_provider
        self._identity_factory = identity_factory or _stable_storage_identity
        self._merge_cache = InMemoryShopProfileRepository()

    async def upsert(self, profile: ShopProfile) -> ShopProfile:
        storage = self._storage_provider()
        if inspect.isawaitable(storage):
            storage = await storage
        existing = await self._find_with_storage(storage, profile.name)
        merged = profile if existing is None else merge_profiles(existing, profile)
        merged = await self._merge_cache.upsert(merged)
        await storage.upsert_restaurant(
            profile_to_storage(merged, identity_factory=self._identity_factory)
        )
        return merged

    async def find_by_name(self, name: str) -> ShopProfile | None:
        cached = await self._merge_cache.find_by_name(name)
        if cached is not None:
            return cached
        storage = self._storage_provider()
        if inspect.isawaitable(storage):
            storage = await storage
        profile = await self._find_with_storage(storage, name)
        if profile is not None:
            await self._merge_cache.upsert(profile)
        return profile

    @staticmethod
    async def _find_with_storage(storage: Any, name: str) -> ShopProfile | None:
        lookup = getattr(storage, "get_cached_restaurant_by_name", None)
        if not callable(lookup):
            return None
        row = lookup(name)
        if inspect.isawaitable(row):
            row = await row
        return profile_from_storage(row) if isinstance(row, Mapping) else None


def merge_profiles(current: ShopProfile, incoming: ShopProfile) -> ShopProfile:
    """Merge a refresh without allowing missing/partial values to erase data."""

    update: dict[str, Any] = {}
    scalar_fields = (
        "name",
        "alias",
        "url",
        "image_url",
        "address",
        "city",
        "district",
        "region",
        "business_area",
        "location",
        "latitude",
        "longitude",
        "coordinate_system",
        "source_url",
        "phone",
        "rating",
        "review_count",
        "average_price",
        "category",
        "opening_hours",
        "source_updated_at",
        "fetched_at",
    )
    for name in scalar_fields:
        value = getattr(incoming, name)
        update[name] = value if value not in (None, "") else getattr(current, name)
    update["provider_refs"] = {**current.provider_refs, **incoming.provider_refs}
    update["geo"] = _merge_mapping(current.geo, incoming.geo)
    for name in ("images", "recommended_dishes", "promotions", "tags"):
        update[name] = _ordered_union(getattr(current, name), getattr(incoming, name))
    update["attributes"] = _merge_mapping(current.attributes, incoming.attributes)
    update["review_completeness"] = _merge_mapping(
        current.review_completeness, incoming.review_completeness
    )
    update["gaps"] = _ordered_union(current.gaps, incoming.gaps)
    update["source_payload"] = _merge_payload(current.source_payload, incoming.source_payload)
    update["outcome"] = incoming.outcome
    return current.model_copy(update=update)


def profile_to_storage(
    profile: ShopProfile,
    *,
    identity_factory: IdentityFactory | None = None,
) -> dict[str, Any]:
    shop_ref = profile.provider_refs.get("dianping")
    # A provider identity is the durable key. Contact details are mutable and
    # must never create a second restaurant row when a shop changes its phone.
    identifier = (identity_factory or _stable_storage_identity)(
        f"dianping:{shop_ref}" if shop_ref else profile.name
    )
    return {
        "id": identifier,
        "name": profile.name,
        "alias": profile.alias,
        "tel": profile.phone,
        "address": profile.address,
        "city": profile.city,
        "district": profile.district,
        "region": profile.region,
        "business_area": profile.business_area,
        "location": profile.location,
        "category": profile.category,
        "review_count": profile.review_count,
        "average_price": profile.average_price,
        "latitude": profile.latitude,
        "longitude": profile.longitude,
        "coordinate_system": profile.coordinate_system,
        "geo": dict(profile.geo),
        "rating": profile.rating,
        "cost": str(profile.average_price) if profile.average_price is not None else None,
        "open_time": profile.opening_hours,
        "tags": list(profile.tags),
        "must_try": [{"name": item, "reason": "大众点评高频推荐"} for item in profile.recommended_dishes],
        "photos": list(profile.images),
        "provider_refs": dict(profile.provider_refs),
        "profile_url": profile.url,
        "source_url": profile.source_url,
        "image_url": profile.image_url,
        "recommended_dishes": list(profile.recommended_dishes),
        "promotions": list(profile.promotions),
        "review_completeness": dict(profile.review_completeness),
        "profile_metadata": {
            "review_count": profile.review_count,
            "category": profile.category,
            "profile_outcome": profile.outcome.value,
            "attributes": profile.attributes,
            "review_completeness": profile.review_completeness,
            "source_url": profile.source_url,
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "coordinate_system": profile.coordinate_system,
            "geo": dict(profile.geo),
        },
        "profile_gaps": [gap.model_dump(mode="json") for gap in profile.gaps],
        "source_payload": profile.source_payload,
        "source_updated_at": profile.source_updated_at,
        "profile_fetched_at": profile.fetched_at,
        "profile_refresh_status": profile.outcome.value,
    }


def profile_from_storage(value: Mapping[str, Any]) -> ShopProfile | None:
    """Restore the durable shop projection used by the refresh policy."""

    name = _text(_first(value, "name", "shopName", "shop_name"))
    if not name:
        return None
    metadata = _json_mapping(_first(value, "profile_metadata", "profileMetadata"))
    raw_gaps = _json_sequence(_first(value, "profile_gaps", "profileGaps"))
    gaps: list[ResearchGap] = []
    for item in raw_gaps:
        if not isinstance(item, Mapping):
            continue
        try:
            gaps.append(ResearchGap.model_validate(item))
        except Exception:
            continue
    outcome_value = _text(
        _first(value, "profile_refresh_status", "profileRefreshStatus")
    )
    try:
        outcome = ResearchOutcome(outcome_value) if outcome_value else ResearchOutcome.COMPLETE
    except ValueError:
        outcome = ResearchOutcome.PARTIAL

    return ShopProfile(
        provider_refs={
            str(key): str(item)
            for key, item in _json_mapping(
                _first(value, "provider_refs", "providerRefs")
            ).items()
            if item not in (None, "")
        },
        name=name,
        alias=_optional_text(_first(value, "alias", "chnName")),
        url=_optional_text(_first(value, "profile_url", "profileUrl", "url")),
        source_url=_optional_text(_first(value, "source_url", "sourceUrl")),
        image_url=_optional_text(_first(value, "image_url", "imageUrl")),
        images=tuple(_json_sequence(_first(value, "photos", "images"))),
        address=_optional_text(value.get("address")),
        city=_optional_text(value.get("city")),
        district=_optional_text(value.get("district")),
        region=_optional_text(value.get("region")),
        business_area=_optional_text(
            _first(value, "business_area", "businessArea")
        ),
        location=_optional_text(value.get("location")),
        latitude=_optional_float(value.get("latitude")),
        longitude=_optional_float(value.get("longitude")),
        coordinate_system=_optional_text(
            _first(value, "coordinate_system", "coordinateSystem")
        ),
        geo=_json_mapping(value.get("geo")),
        phone=_optional_text(_first(value, "tel", "phone")),
        rating=_optional_float(value.get("rating")),
        review_count=_optional_int(_first(value, "review_count", "reviewCount")),
        average_price=_optional_float(
            _first(value, "average_price", "averagePrice")
        ),
        category=_optional_text(value.get("category")),
        opening_hours=_optional_text(_first(value, "open_time", "openingHours")),
        recommended_dishes=tuple(
            text
            for item in _json_sequence(
                _first(value, "recommended_dishes", "recommendedDishes")
            )
            if (text := _text(item))
        ),
        promotions=tuple(_json_sequence(value.get("promotions"))),
        tags=tuple(
            text
            for item in _json_sequence(value.get("tags"))
            if (text := _text(item))
        ),
        attributes=_json_mapping(metadata.get("attributes")),
        review_completeness=_json_mapping(
            _first(value, "review_completeness", "reviewCompleteness")
        ),
        source_payload=_json_value(_first(value, "source_payload", "sourcePayload")),
        source_updated_at=_optional_datetime(
            _first(value, "source_updated_at", "sourceUpdatedAt")
        ),
        fetched_at=_optional_datetime(
            _first(value, "profile_fetched_at", "profileFetchedAt")
        ),
        outcome=outcome,
        gaps=tuple(gaps),
    )


def _profile_key(profile: ShopProfile) -> str:
    provider_ref = profile.provider_refs.get("dianping")
    return f"dianping:{provider_ref}" if provider_ref else f"name:{profile.name.casefold()}"


def _ordered_union(left: tuple[Any, ...], right: tuple[Any, ...]) -> tuple[Any, ...]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in (*left, *right):
        marker = repr(value)
        if marker not in seen:
            seen.add(marker)
            output.append(value)
    return tuple(output)


def _merge_payload(current: Any, incoming: Any) -> Any:
    if incoming in (None, {}, [], ()):
        return current
    if current in (None, {}, [], ()) or current == incoming:
        return incoming
    if isinstance(current, Mapping) and "current" in current and "previous" in current:
        previous = list(current.get("previous") or [])
        previous.append(current.get("current"))
        return {"current": incoming, "previous": previous}
    return {"current": incoming, "previous": [current]}


def _merge_mapping(current: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        if value not in (None, "", [], {}, ()):
            merged[str(key)] = value
    return merged


def _stable_storage_identity(value: str) -> str:
    """Create the same deterministic restaurant key without importing storage internals."""

    normalized = value.strip()
    if not normalized:
        raise ValueError("restaurant identity must be non-empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _normalise_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _first(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate is not None:
            return candidate
    return None


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _json_mapping(value: Any) -> dict[str, Any]:
    parsed = _json_value(value)
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_sequence(value: Any) -> list[Any]:
    parsed = _json_value(value)
    if isinstance(parsed, (list, tuple)):
        return list(parsed)
    return []


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _optional_text(value: Any) -> str | None:
    output = _text(value)
    return output or None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = [
    "InMemoryShopProfileRepository",
    "UserStorageShopProfileRepository",
    "merge_profiles",
    "profile_from_storage",
    "profile_to_storage",
]
