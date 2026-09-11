"""Database repository operations for restaurants, favorites, and search history."""
from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger

from .models import Favorite, Restaurant, SearchHistory, generate_restaurant_hash


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    """Read the first non-None alias without treating numeric zero as absent."""

    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _normalise_restaurant_name(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _normalise_provider_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalise_provider_ref(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


class RepositoryMixin:
    """Mixin: restaurant CRUD, favorites CRUD, and search history operations.

    Expects host to expose: _pool, _initialized,
    _row_to_restaurant, _row_to_history, _row_to_favorite_with_restaurant.
    """

    async def upsert_restaurant(self, restaurant_data: dict[str, Any]) -> Restaurant | None:
        """Insert or update a restaurant."""
        if not self._initialized or not self._pool:
            return None
        name = restaurant_data.get("name")
        if not name:
            logger.error("Restaurant name is required")
            return None
        tel = restaurant_data.get("tel")
        if isinstance(tel, list):
            tel = "; ".join(tel) if tel else None
        restaurant_id = restaurant_data.get("id") or generate_restaurant_hash(name, tel)
        trust_score = restaurant_data.get("trustScore") or restaurant_data.get("trust_score")
        if trust_score is not None:
            trust_score = round(float(trust_score), 1)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO restaurants (
                        id, name, alias, tel, address, city, district, region, business_area,
                        location, rating, cost, open_time, trust_score, one_liner,
                        tags, pros, cons, warning, must_try, black_list, stats, photos, source_notes,
                        provider_refs, profile_url, image_url, recommended_dishes, promotions,
                        profile_metadata, profile_gaps, source_payload, source_updated_at,
                        profile_fetched_at, profile_refresh_status, source_url, category,
                        review_count, average_price, latitude, longitude, coordinate_system,
                        geo, review_completeness
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                        $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26,
                        $27, $28, $29, $30, $31, $32, $33, $34, $35, $36, $37, $38,
                        $39, $40, $41, $42, $43, $44
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, alias = COALESCE(EXCLUDED.alias, restaurants.alias),
                        tel = COALESCE(EXCLUDED.tel, restaurants.tel),
                        address = COALESCE(EXCLUDED.address, restaurants.address),
                        city = COALESCE(EXCLUDED.city, restaurants.city),
                        district = COALESCE(EXCLUDED.district, restaurants.district),
                        region = COALESCE(EXCLUDED.region, restaurants.region),
                        business_area = COALESCE(EXCLUDED.business_area, restaurants.business_area),
                        location = COALESCE(EXCLUDED.location, restaurants.location),
                        rating = COALESCE(EXCLUDED.rating, restaurants.rating),
                        cost = COALESCE(EXCLUDED.cost, restaurants.cost),
                        open_time = COALESCE(EXCLUDED.open_time, restaurants.open_time),
                        trust_score = COALESCE(EXCLUDED.trust_score, restaurants.trust_score),
                        one_liner = COALESCE(EXCLUDED.one_liner, restaurants.one_liner),
                        tags = COALESCE(NULLIF(EXCLUDED.tags, '[]'::jsonb), restaurants.tags),
                        pros = COALESCE(NULLIF(EXCLUDED.pros, '[]'::jsonb), restaurants.pros),
                        cons = COALESCE(NULLIF(EXCLUDED.cons, '[]'::jsonb), restaurants.cons),
                        warning = COALESCE(EXCLUDED.warning, restaurants.warning),
                        must_try = COALESCE(NULLIF(EXCLUDED.must_try, '[]'::jsonb), restaurants.must_try),
                        black_list = COALESCE(NULLIF(EXCLUDED.black_list, '[]'::jsonb), restaurants.black_list),
                        stats = COALESCE(NULLIF(EXCLUDED.stats, '{}'::jsonb), restaurants.stats),
                        photos = COALESCE(NULLIF(EXCLUDED.photos, '[]'::jsonb), restaurants.photos),
                        source_notes = COALESCE(NULLIF(EXCLUDED.source_notes, '[]'::jsonb), restaurants.source_notes),
                        provider_refs = COALESCE(NULLIF(EXCLUDED.provider_refs, '{}'::jsonb), restaurants.provider_refs),
                        profile_url = COALESCE(EXCLUDED.profile_url, restaurants.profile_url),
                        image_url = COALESCE(EXCLUDED.image_url, restaurants.image_url),
                        recommended_dishes = COALESCE(NULLIF(EXCLUDED.recommended_dishes, '[]'::jsonb), restaurants.recommended_dishes),
                        promotions = COALESCE(NULLIF(EXCLUDED.promotions, '[]'::jsonb), restaurants.promotions),
                        profile_metadata = COALESCE(NULLIF(EXCLUDED.profile_metadata, '{}'::jsonb), restaurants.profile_metadata),
                        profile_gaps = COALESCE(NULLIF(EXCLUDED.profile_gaps, '[]'::jsonb), restaurants.profile_gaps),
                        source_payload = COALESCE(EXCLUDED.source_payload, restaurants.source_payload),
                        source_updated_at = COALESCE(EXCLUDED.source_updated_at, restaurants.source_updated_at),
                        profile_fetched_at = COALESCE(EXCLUDED.profile_fetched_at, restaurants.profile_fetched_at),
                        profile_refresh_status = COALESCE(EXCLUDED.profile_refresh_status, restaurants.profile_refresh_status),
                        source_url = COALESCE(EXCLUDED.source_url, restaurants.source_url),
                        category = COALESCE(EXCLUDED.category, restaurants.category),
                        review_count = COALESCE(EXCLUDED.review_count, restaurants.review_count),
                        average_price = COALESCE(EXCLUDED.average_price, restaurants.average_price),
                        latitude = COALESCE(EXCLUDED.latitude, restaurants.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, restaurants.longitude),
                        coordinate_system = COALESCE(EXCLUDED.coordinate_system, restaurants.coordinate_system),
                        geo = COALESCE(NULLIF(EXCLUDED.geo, '{}'::jsonb), restaurants.geo),
                        review_completeness = COALESCE(NULLIF(EXCLUDED.review_completeness, '{}'::jsonb), restaurants.review_completeness),
                        updated_at = NOW()
                    RETURNING *
                    """,
                    restaurant_id, name,
                    restaurant_data.get("chnName") or restaurant_data.get("alias"),
                    tel, restaurant_data.get("address"), restaurant_data.get("city"),
                    restaurant_data.get("district"),
                    restaurant_data.get("region"),
                    restaurant_data.get("businessArea") or restaurant_data.get("business_area"),
                    restaurant_data.get("location"), restaurant_data.get("rating"),
                    restaurant_data.get("cost"),
                    restaurant_data.get("openTime") or restaurant_data.get("open_time"),
                    trust_score,
                    restaurant_data.get("oneLiner") or restaurant_data.get("one_liner"),
                    json.dumps(restaurant_data.get("tags", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("pros", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("cons", []), ensure_ascii=False),
                    restaurant_data.get("warning"),
                    json.dumps(restaurant_data.get("mustTry") or restaurant_data.get("must_try", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("blackList") or restaurant_data.get("black_list", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("stats", {}), ensure_ascii=False),
                    json.dumps(restaurant_data.get("photos", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("sourceNotes") or restaurant_data.get("source_notes", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("providerRefs") or restaurant_data.get("provider_refs", {}), ensure_ascii=False),
                    restaurant_data.get("profileUrl") or restaurant_data.get("profile_url"),
                    restaurant_data.get("imageUrl") or restaurant_data.get("image_url"),
                    json.dumps(restaurant_data.get("recommendedDishes") or restaurant_data.get("recommended_dishes", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("promotions", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("profileMetadata") or restaurant_data.get("profile_metadata", {}), ensure_ascii=False),
                    json.dumps(restaurant_data.get("profileGaps") or restaurant_data.get("profile_gaps", []), ensure_ascii=False),
                    json.dumps(restaurant_data.get("sourcePayload") or restaurant_data.get("source_payload"), ensure_ascii=False, default=str) if restaurant_data.get("sourcePayload") is not None or restaurant_data.get("source_payload") is not None else None,
                    restaurant_data.get("sourceUpdatedAt") or restaurant_data.get("source_updated_at"),
                    restaurant_data.get("profileFetchedAt") or restaurant_data.get("profile_fetched_at"),
                    restaurant_data.get("profileRefreshStatus") or restaurant_data.get("profile_refresh_status"),
                    restaurant_data.get("sourceUrl") or restaurant_data.get("source_url"),
                    restaurant_data.get("category"),
                    _first_present(restaurant_data, "reviewCount", "review_count"),
                    _first_present(restaurant_data, "averagePrice", "average_price"),
                    restaurant_data.get("latitude"),
                    restaurant_data.get("longitude"),
                    restaurant_data.get("coordinateSystem") or restaurant_data.get("coordinate_system"),
                    json.dumps(restaurant_data.get("geo", {}), ensure_ascii=False, default=str),
                    json.dumps(restaurant_data.get("reviewCompleteness") or restaurant_data.get("review_completeness", {}), ensure_ascii=False, default=str),
                )
                return self._row_to_restaurant(row) if row else None
        except Exception as e:
            logger.error(f"upsert_restaurant failed: {e}")
            return None

    async def get_restaurant(self, restaurant_id: str) -> Restaurant | None:
        """Get a restaurant by ID."""
        if not self._initialized or not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM restaurants WHERE id = $1", restaurant_id)
                return self._row_to_restaurant(row) if row else None
        except Exception as e:
            logger.error(f"get_restaurant failed: {e}")
            return None

    async def get_cached_restaurant_by_name(self, name: str) -> dict[str, Any] | None:
        """Return the durable shop-profile projection without exposing the pool."""

        initialized = bool(getattr(self, "_initialized", False))
        pool = getattr(self, "_pool", None)
        if not initialized or pool is None:
            return None
        normalized_name = _normalise_restaurant_name(name)
        if not normalized_name:
            return None
        try:
            async with pool.acquire() as conn:
                query = """
                    SELECT * FROM restaurants
                    WHERE regexp_replace(lower(name), '[^[:alnum:]]', '', 'g') = $1
                    ORDER BY updated_at DESC NULLS LAST
                """
                fetch = getattr(conn, "fetch", None)
                if callable(fetch):
                    rows = await fetch(query, normalized_name)
                else:
                    row = await conn.fetchrow(f"{query} LIMIT 2", normalized_name)
                    rows = [row] if row is not None else []
                matches = [
                    row
                    for row in rows
                    if _normalise_restaurant_name(row.get("name")) == normalized_name
                ]
                return dict(matches[0]) if len(matches) == 1 else None
        except Exception as exc:
            logger.debug(f"get_cached_restaurant_by_name failed: {exc}")
            return None

    async def get_cached_restaurant_by_provider_ref(
        self,
        provider: str,
        provider_ref: str,
    ) -> dict[str, Any] | None:
        """Return one shop profile by its immutable provider identity.

        Provider references are stored as JSONB so a provider id remains the
        durable identity even when a shop changes its display name, phone, or
        address.  The query intentionally does not fall back to a fuzzy name
        match: a same-name branch must never be treated as the same shop.
        """

        initialized = bool(getattr(self, "_initialized", False))
        pool = getattr(self, "_pool", None)
        provider = _normalise_provider_name(provider)
        provider_ref = _normalise_provider_ref(provider_ref)
        if not initialized or pool is None or not provider or not provider_ref:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM restaurants
                    WHERE btrim(provider_refs ->> $1) = $2
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    provider,
                    provider_ref,
                )
                return dict(row) if row else None
        except Exception as exc:
            logger.debug(f"get_cached_restaurant_by_provider_ref failed: {exc}")
            return None

    async def get_favorites(self, user_id: str) -> list[Favorite]:
        """Get all favorites for a user with full restaurant details."""
        if not self._initialized or not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT f.id, f.user_id, f.restaurant_id, f.created_at,
                           r.name, r.alias, r.tel, r.address, r.city, r.district,
                           r.business_area, r.location, r.rating, r.cost, r.open_time,
                           r.trust_score, r.one_liner, r.tags, r.pros, r.cons,
                           r.warning, r.must_try, r.black_list, r.stats, r.photos, r.source_notes,
                           r.region, r.provider_refs, r.profile_url, r.source_url, r.image_url,
                           r.category, r.review_count, r.average_price, r.latitude, r.longitude,
                           r.coordinate_system, r.geo, r.recommended_dishes, r.promotions,
                           r.profile_metadata, r.review_completeness, r.profile_gaps,
                           r.source_payload, r.source_updated_at, r.profile_fetched_at,
                           r.profile_refresh_status
                    FROM favorites f LEFT JOIN restaurants r ON f.restaurant_id = r.id
                    WHERE f.user_id = $1 AND f.deleted_at IS NULL
                    ORDER BY f.created_at DESC
                    """, uuid.UUID(user_id),
                )
                return [self._row_to_favorite_with_restaurant(row) for row in rows]
        except Exception as e:
            logger.error(f"get_favorites failed: {e}")
            return []

    async def add_favorite(self, user_id: str, restaurant_id: str) -> Favorite | None:
        """Add a restaurant to favorites."""
        if not self._initialized or not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO favorites (user_id, restaurant_id) VALUES ($1, $2)
                    ON CONFLICT (user_id, restaurant_id) DO UPDATE SET
                        deleted_at = NULL, created_at = NOW()
                    WHERE favorites.deleted_at IS NOT NULL
                    RETURNING *
                    """, uuid.UUID(user_id), restaurant_id,
                )
                if row:
                    restaurant = await self.get_restaurant(restaurant_id)
                    return Favorite(
                        id=row["id"], user_id=str(row["user_id"]),
                        restaurant_id=row["restaurant_id"],
                        restaurant=restaurant.to_dict() if restaurant else None,
                        created_at=row["created_at"],
                    )
                return None
        except Exception as e:
            logger.error(f"add_favorite failed: {e}")
            return None

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool:
        """Soft delete a restaurant from favorites."""
        if not self._initialized or not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE favorites SET deleted_at = NOW() "
                    "WHERE user_id = $1 AND restaurant_id = $2 AND deleted_at IS NULL",
                    uuid.UUID(user_id), restaurant_id)
                return "UPDATE" in result
        except Exception as e:
            logger.error(f"remove_favorite failed: {e}")
            return False

    async def check_favorite(self, user_id: str, restaurant_id: str) -> bool:
        """Check if a restaurant is in favorites (not soft-deleted)."""
        if not self._initialized or not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM favorites "
                    "WHERE user_id = $1 AND restaurant_id = $2 AND deleted_at IS NULL)",
                    uuid.UUID(user_id), restaurant_id)
                return exists or False
        except Exception as e:
            logger.error(f"check_favorite failed: {e}")
            return False

    async def get_history(self, user_id: str, limit: int = 20, offset: int = 0) -> list[SearchHistory]:
        """Get search history for a user."""
        if not self._initialized or not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM search_history WHERE user_id = $1 "
                    "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                    uuid.UUID(user_id), limit, offset,
                )
                return [self._row_to_history(row) for row in rows]
        except Exception as e:
            logger.error(f"get_history failed: {e}")
            return []

    async def get_history_count(self, user_id: str) -> int:
        """Get total history count for a user."""
        if not self._initialized or not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM search_history WHERE user_id = $1",
                    uuid.UUID(user_id)) or 0
        except Exception as e:
            logger.error(f"get_history_count failed: {e}")
            return 0

    async def add_history(
        self, user_id: str, query: str, session_id: str | None = None,
        status: str = "loading", results_count: int = 0, location: str | None = None,
    ) -> SearchHistory | None:
        """Add a search to history."""
        if not self._initialized or not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO search_history (user_id, session_id, query, status, results_count, location) "
                    "VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
                    uuid.UUID(user_id), uuid.UUID(session_id) if session_id else None,
                    query, status, results_count, location,
                )
                return self._row_to_history(row) if row else None
        except Exception as e:
            logger.error(f"add_history failed: {e}")
            return None

    async def delete_history(self, user_id: str, history_id: int) -> bool:
        """Delete a single history item."""
        if not self._initialized or not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM search_history WHERE user_id = $1 AND id = $2",
                    uuid.UUID(user_id), history_id)
                return "DELETE" in result
        except Exception as e:
            logger.error(f"delete_history failed: {e}")
            return False

    async def clear_history(self, user_id: str) -> int:
        """Clear all history for a user."""
        if not self._initialized or not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM search_history WHERE user_id = $1", uuid.UUID(user_id))
                return int(result.split()[-1])
        except Exception as e:
            logger.error(f"clear_history failed: {e}")
            return 0

    async def update_history_status(
        self, session_id: str, status: str, results_count: int | None = None,
    ) -> bool:
        """Update search history status by session_id."""
        if not self._initialized or not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                if results_count is not None:
                    await conn.execute(
                        "UPDATE search_history SET status = $1, results_count = $2, "
                        "updated_at = NOW() WHERE session_id = $3",
                        status, results_count, uuid.UUID(session_id),
                    )
                else:
                    await conn.execute(
                        "UPDATE search_history SET status = $1, updated_at = NOW() "
                        "WHERE session_id = $2",
                        status, uuid.UUID(session_id),
                    )
                return True
        except Exception as e:
            logger.error(f"update_history_status failed: {e}")
            return False

    async def get_history_by_session(self, session_id: str) -> SearchHistory | None:
        """Get search history by session_id."""
        if not self._initialized or not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM search_history WHERE session_id = $1",
                    uuid.UUID(session_id),
                )
                return self._row_to_history(row) if row else None
        except Exception as e:
            logger.error(f"get_history_by_session failed: {e}")
            return None
