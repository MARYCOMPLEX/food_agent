# -*- coding: utf-8 -*-
"""Database repository operations for restaurants, favorites, and search history."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from .models import Favorite, Restaurant, SearchHistory, generate_restaurant_hash


class RepositoryMixin:
    """Mixin: restaurant CRUD, favorites CRUD, and search history operations.

    Expects host to expose: _pool, _initialized,
    _row_to_restaurant, _row_to_history, _row_to_favorite_with_restaurant.
    """

    async def upsert_restaurant(self, restaurant_data: Dict[str, Any]) -> Optional[Restaurant]:
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
                        id, name, alias, tel, address, city, district, business_area,
                        location, rating, cost, open_time, trust_score, one_liner,
                        tags, pros, cons, warning, must_try, black_list, stats, photos, source_notes
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                        $15, $16, $17, $18, $19, $20, $21, $22, $23
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, alias = EXCLUDED.alias,
                        tel = COALESCE(EXCLUDED.tel, restaurants.tel),
                        address = COALESCE(EXCLUDED.address, restaurants.address),
                        city = COALESCE(EXCLUDED.city, restaurants.city),
                        district = COALESCE(EXCLUDED.district, restaurants.district),
                        business_area = COALESCE(EXCLUDED.business_area, restaurants.business_area),
                        location = COALESCE(EXCLUDED.location, restaurants.location),
                        rating = COALESCE(EXCLUDED.rating, restaurants.rating),
                        cost = COALESCE(EXCLUDED.cost, restaurants.cost),
                        open_time = COALESCE(EXCLUDED.open_time, restaurants.open_time),
                        trust_score = COALESCE(EXCLUDED.trust_score, restaurants.trust_score),
                        one_liner = COALESCE(EXCLUDED.one_liner, restaurants.one_liner),
                        tags = EXCLUDED.tags, pros = EXCLUDED.pros, cons = EXCLUDED.cons,
                        warning = EXCLUDED.warning, must_try = EXCLUDED.must_try,
                        black_list = EXCLUDED.black_list, stats = EXCLUDED.stats,
                        photos = EXCLUDED.photos, source_notes = EXCLUDED.source_notes,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    restaurant_id, name,
                    restaurant_data.get("chnName") or restaurant_data.get("alias"),
                    tel, restaurant_data.get("address"), restaurant_data.get("city"),
                    restaurant_data.get("district"),
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
                )
                return self._row_to_restaurant(row) if row else None
        except Exception as e:
            logger.error(f"upsert_restaurant failed: {e}")
            return None

    async def get_restaurant(self, restaurant_id: str) -> Optional[Restaurant]:
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
        """Return the legacy POI cache projection without exposing the pool."""

        initialized = bool(getattr(self, "_initialized", False))
        pool = getattr(self, "_pool", None)
        if not initialized or pool is None:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM restaurants WHERE name = $1 LIMIT 1",
                    name,
                )
                if row is None:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM restaurants
                        WHERE name ILIKE $1 OR name ILIKE $2
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT 1
                        """,
                        f"{name}%",
                        f"%{name}",
                    )
                return dict(row) if row else None
        except Exception as exc:
            logger.debug(f"get_cached_restaurant_by_name failed: {exc}")
            return None

    async def get_favorites(self, user_id: str) -> List[Favorite]:
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
                           r.warning, r.must_try, r.black_list, r.stats, r.photos, r.source_notes
                    FROM favorites f LEFT JOIN restaurants r ON f.restaurant_id = r.id
                    WHERE f.user_id = $1 AND f.deleted_at IS NULL
                    ORDER BY f.created_at DESC
                    """, uuid.UUID(user_id),
                )
                return [self._row_to_favorite_with_restaurant(row) for row in rows]
        except Exception as e:
            logger.error(f"get_favorites failed: {e}")
            return []

    async def add_favorite(self, user_id: str, restaurant_id: str) -> Optional[Favorite]:
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

    async def get_history(self, user_id: str, limit: int = 20, offset: int = 0) -> List[SearchHistory]:
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
        self, user_id: str, query: str, session_id: Optional[str] = None,
        status: str = "loading", results_count: int = 0, location: Optional[str] = None,
    ) -> Optional[SearchHistory]:
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
        self, session_id: str, status: str, results_count: Optional[int] = None,
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

    async def get_history_by_session(self, session_id: str) -> Optional[SearchHistory]:
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
