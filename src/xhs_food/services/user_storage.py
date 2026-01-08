# -*- coding: utf-8 -*-
"""
UserStorageService - PostgreSQL storage for user data.

Handles persistence for:
- User profiles
- Favorites
- Search history

Follows the same patterns as PostgresStorage for consistency.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logger.warning("asyncpg not installed, UserStorageService will be disabled")


def generate_restaurant_hash(name: str, tel: Optional[str] = None) -> str:
    """
    Generate a unique hash ID for a restaurant.
    
    Uses SHA256(name + tel)[:32]. If tel is empty, uses name only.
    
    Args:
        name: Restaurant name (required)
        tel: Phone number (optional)
        
    Returns:
        32-character hex hash string
    """
    if not name:
        raise ValueError("Restaurant name is required for hash generation")
    
    # Normalize inputs
    name = name.strip()
    raw = name
    if tel and tel.strip():
        raw = f"{name}:{tel.strip()}"
    
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


# =============================================================================
# Database Schema
# =============================================================================

# Enable required extensions first
ENABLE_EXTENSIONS_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(255) UNIQUE,
    name VARCHAR(100) DEFAULT 'Guest',
    email VARCHAR(255),
    avatar TEXT,
    location VARCHAR(100),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_FAVORITES_TABLE = """
CREATE TABLE IF NOT EXISTS favorites (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL,
    UNIQUE(user_id, restaurant_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_restaurant ON favorites(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_favorites_deleted ON favorites(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS search_history (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID UNIQUE,
    query TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'loading',
    results_count INTEGER DEFAULT 0,
    location VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_user ON search_history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_created ON search_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_session ON search_history(session_id);
CREATE INDEX IF NOT EXISTS idx_history_deleted ON search_history(deleted_at) WHERE deleted_at IS NULL;
"""

CREATE_SEARCH_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS search_results (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID UNIQUE NOT NULL,
    restaurants JSONB NOT NULL DEFAULT '[]',
    summary TEXT,
    filtered_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_results_session ON search_results(session_id);
"""

CREATE_RESTAURANTS_TABLE = """
CREATE TABLE IF NOT EXISTS restaurants (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    alias VARCHAR(255),
    tel VARCHAR(50),
    address TEXT,
    city VARCHAR(100),
    district VARCHAR(100),
    business_area VARCHAR(100),
    location VARCHAR(50),
    rating REAL,
    cost VARCHAR(50),
    open_time VARCHAR(255),
    trust_score REAL,
    one_liner TEXT,
    tags JSONB DEFAULT '[]',
    pros JSONB DEFAULT '[]',
    cons JSONB DEFAULT '[]',
    warning TEXT,
    must_try JSONB DEFAULT '[]',
    black_list JSONB DEFAULT '[]',
    stats JSONB DEFAULT '{}',
    photos JSONB DEFAULT '[]',
    source_notes JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name);
CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city);
"""



# =============================================================================
# Data Models
# =============================================================================

@dataclass
class User:
    """User data model."""
    id: str
    device_id: Optional[str] = None
    name: str = "Guest"
    email: Optional[str] = None
    avatar: Optional[str] = None
    location: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "deviceId": self.device_id,
            "name": self.name,
            "email": self.email,
            "avatar": self.avatar,
            "location": self.location,
            "settings": self.settings,
            "memberSince": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Favorite:
    """Favorite data model."""
    id: int
    user_id: str
    restaurant_id: str  # Hash ID from restaurants table
    restaurant: Optional[Dict[str, Any]] = None  # Joined from restaurants table
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.restaurant_id,
            "addedAt": self.created_at.timestamp() if self.created_at else None,
            "restaurant": self.restaurant,
        }


@dataclass
class SearchHistory:
    """Search history data model."""
    id: int
    user_id: str
    query: str
    session_id: Optional[str] = None
    status: str = "loading"
    results_count: int = 0
    location: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": f"hist_{self.id}",
            "sessionId": self.session_id,
            "query": self.query,
            "status": self.status,
            "timestamp": self.created_at.timestamp() if self.created_at else None,
            "resultsCount": self.results_count,
            "location": self.location,
        }


@dataclass
class Restaurant:
    """Restaurant data model."""
    id: str  # Hash ID
    name: str
    alias: Optional[str] = None
    tel: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    business_area: Optional[str] = None
    location: Optional[str] = None  # lat,lng
    rating: Optional[float] = None
    cost: Optional[str] = None
    open_time: Optional[str] = None
    trust_score: Optional[float] = None
    one_liner: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    warning: Optional[str] = None
    must_try: List[Dict[str, str]] = field(default_factory=list)
    black_list: List[Dict[str, str]] = field(default_factory=list)
    stats: Dict[str, str] = field(default_factory=dict)
    photos: List[Dict[str, str]] = field(default_factory=list)
    source_notes: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "id": self.id,
            "name": self.name,
            "chnName": self.alias or self.name,
            "address": self.address,
            "location": self.location,
            "city": self.city,
            "district": self.district,
            "businessArea": self.business_area,
            "tel": self.tel,
            "rating": self.rating,
            "cost": self.cost,
            "openTime": self.open_time,
            "trustScore": round(self.trust_score, 1) if self.trust_score else None,
            "oneLiner": self.one_liner,
            "tags": self.tags,
            "pros": self.pros,
            "cons": self.cons,
            "warning": self.warning,
            "photos": self.photos,
            "sourceNotes": self.source_notes,
            "mustTry": self.must_try,
            "blackList": self.black_list,
            "stats": self.stats,
        }


# =============================================================================
# Storage Service
# =============================================================================

class UserStorageService:
    """
    PostgreSQL-based storage for user data.
    
    Features:
    - User profile management
    - Favorites CRUD
    - Search history CRUD
    - Multi-user isolation via user_id
    
    Environment Variables:
        DATABASE_URL: Full PostgreSQL URL (takes precedence)
        OR individual settings:
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    """

    # Anonymous user for backward compatibility
    ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"
    ANONYMOUS_DEVICE_ID = "anonymous"

    def __init__(self, database_url: Optional[str] = None):
        self._database_url = database_url or self._build_database_url()
        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    def _build_database_url(self) -> Optional[str]:
        """Build database URL from environment variables."""
        url = os.getenv("DATABASE_URL")
        if url:
            return url

        host = os.getenv("POSTGRES_HOST")
        if not host:
            return None

        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "postgres")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")

        if password:
            return f"postgresql://{user}:{password}@{host}:{port}/{db}"
        return f"postgresql://{user}@{host}:{port}/{db}"

    async def initialize(self) -> bool:
        """Initialize database connection and create tables."""
        if not ASYNCPG_AVAILABLE:
            logger.warning("asyncpg not available, UserStorageService disabled")
            return False

        if not self._database_url:
            logger.warning("Database URL not configured, UserStorageService disabled")
            return False

        try:
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=10,
            )

            async with self._pool.acquire() as conn:
                # Enable required extensions first
                try:
                    await conn.execute(ENABLE_EXTENSIONS_SQL)
                except Exception as ext_err:
                    logger.warning(f"Could not enable extensions: {ext_err}")
                
                await conn.execute(CREATE_USERS_TABLE)
                await conn.execute(CREATE_RESTAURANTS_TABLE)
                await conn.execute(CREATE_FAVORITES_TABLE)
                await conn.execute(CREATE_HISTORY_TABLE)
                await conn.execute(CREATE_SEARCH_RESULTS_TABLE)
                
                # Ensure anonymous user exists
                await self._ensure_anonymous_user(conn)

            self._initialized = True
            logger.info("UserStorageService initialized successfully")
            return True

        except Exception as e:
            logger.error(f"UserStorageService initialization failed: {e}")
            return False

    async def _ensure_anonymous_user(self, conn) -> None:
        """Ensure anonymous user exists for backward compatibility."""
        await conn.execute(
            """
            INSERT INTO users (id, device_id, name)
            VALUES ($1, $2, 'Anonymous')
            ON CONFLICT (id) DO NOTHING
            """,
            uuid.UUID(self.ANONYMOUS_USER_ID),
            self.ANONYMOUS_DEVICE_ID,
        )

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False

    # =========================================================================
    # User Management
    # =========================================================================

    async def get_or_create_user(self, device_id: str) -> User:
        """Get existing user by device_id or create new one."""
        if not self._initialized or not self._pool:
            return self._anonymous_user()

        try:
            async with self._pool.acquire() as conn:
                # Try to get existing user
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE device_id = $1",
                    device_id,
                )
                
                if row:
                    return self._row_to_user(row)
                
                # Create new user
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (device_id) VALUES ($1)
                    RETURNING *
                    """,
                    device_id,
                )
                return self._row_to_user(row)

        except Exception as e:
            logger.error(f"get_or_create_user failed: {e}")
            return self._anonymous_user()

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE id = $1",
                    uuid.UUID(user_id),
                )
                return self._row_to_user(row) if row else None

        except Exception as e:
            logger.error(f"get_user failed: {e}")
            return None

    async def update_user(
        self,
        user_id: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        location: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Optional[User]:
        """Update user profile."""
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                # Build dynamic update
                updates = []
                params = []
                param_idx = 1
                
                if name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(name)
                    param_idx += 1
                if email is not None:
                    updates.append(f"email = ${param_idx}")
                    params.append(email)
                    param_idx += 1
                if location is not None:
                    updates.append(f"location = ${param_idx}")
                    params.append(location)
                    param_idx += 1
                if settings is not None:
                    updates.append(f"settings = ${param_idx}")
                    params.append(json.dumps(settings))
                    param_idx += 1
                
                if not updates:
                    return await self.get_user(user_id)
                
                updates.append("updated_at = NOW()")
                params.append(uuid.UUID(user_id))
                
                query = f"""
                    UPDATE users SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                    RETURNING *
                """
                
                row = await conn.fetchrow(query, *params)
                return self._row_to_user(row) if row else None

        except Exception as e:
            logger.error(f"update_user failed: {e}")
            return None

    async def get_user_stats(self, user_id: str) -> Dict[str, int]:
        """Get user statistics."""
        if not self._initialized or not self._pool:
            return {"saved": 0, "reviews": 0, "visited": 0}

        try:
            async with self._pool.acquire() as conn:
                saved = await conn.fetchval(
                    "SELECT COUNT(*) FROM favorites WHERE user_id = $1",
                    uuid.UUID(user_id),
                )
                history = await conn.fetchval(
                    "SELECT COUNT(*) FROM search_history WHERE user_id = $1",
                    uuid.UUID(user_id),
                )
                return {
                    "saved": saved or 0,
                    "reviews": 0,  # Not implemented yet
                    "visited": history or 0,
                }
        except Exception as e:
            logger.error(f"get_user_stats failed: {e}")
            return {"saved": 0, "reviews": 0, "visited": 0}

    # =========================================================================
    # Favorites Management
    # =========================================================================

    async def get_favorites(self, user_id: str) -> List[Favorite]:
        """Get all favorites for a user with full restaurant details (excludes soft-deleted)."""
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
                    FROM favorites f
                    LEFT JOIN restaurants r ON f.restaurant_id = r.id
                    WHERE f.user_id = $1 AND f.deleted_at IS NULL
                    ORDER BY f.created_at DESC
                    """,
                    uuid.UUID(user_id),
                )
                return [self._row_to_favorite_with_restaurant(row) for row in rows]

        except Exception as e:
            logger.error(f"get_favorites failed: {e}")
            return []

    async def add_favorite(
        self,
        user_id: str,
        restaurant_id: str,
    ) -> Optional[Favorite]:
        """Add a restaurant to favorites.
        
        Args:
            user_id: User ID
            restaurant_id: Restaurant hash ID (32 chars)
        """
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                # Try to restore if soft-deleted, otherwise insert
                row = await conn.fetchrow(
                    """
                    INSERT INTO favorites (user_id, restaurant_id)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id, restaurant_id) DO UPDATE SET
                        deleted_at = NULL,
                        created_at = NOW()
                    WHERE favorites.deleted_at IS NOT NULL
                    RETURNING *
                    """,
                    uuid.UUID(user_id),
                    restaurant_id,
                )
                if row:
                    # Get full restaurant data
                    restaurant = await self.get_restaurant(restaurant_id)
                    return Favorite(
                        id=row["id"],
                        user_id=str(row["user_id"]),
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
                    """
                    UPDATE favorites 
                    SET deleted_at = NOW()
                    WHERE user_id = $1 AND restaurant_id = $2 AND deleted_at IS NULL
                    """,
                    uuid.UUID(user_id),
                    restaurant_id,
                )
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
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM favorites 
                        WHERE user_id = $1 AND restaurant_id = $2 AND deleted_at IS NULL
                    )
                    """,
                    uuid.UUID(user_id),
                    restaurant_id,
                )
                return exists or False

        except Exception as e:
            logger.error(f"check_favorite failed: {e}")
            return False

    # =========================================================================
    # Restaurant Management
    # =========================================================================

    async def upsert_restaurant(self, restaurant_data: Dict[str, Any]) -> Optional[Restaurant]:
        """Insert or update a restaurant.
        
        Args:
            restaurant_data: Dict with restaurant fields. Must include 'name'.
                If 'id' is provided, uses that; otherwise generates from name+tel.
        
        Returns:
            Restaurant object or None on failure
        """
        if not self._initialized or not self._pool:
            return None

        name = restaurant_data.get("name")
        if not name:
            logger.error("Restaurant name is required")
            return None

        # Generate or use provided ID
        tel = restaurant_data.get("tel")
        restaurant_id = restaurant_data.get("id") or generate_restaurant_hash(name, tel)
        
        # Round trust_score to 1 decimal
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
                        name = EXCLUDED.name,
                        alias = EXCLUDED.alias,
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
                        tags = EXCLUDED.tags,
                        pros = EXCLUDED.pros,
                        cons = EXCLUDED.cons,
                        warning = EXCLUDED.warning,
                        must_try = EXCLUDED.must_try,
                        black_list = EXCLUDED.black_list,
                        stats = EXCLUDED.stats,
                        photos = EXCLUDED.photos,
                        source_notes = EXCLUDED.source_notes,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    restaurant_id,
                    name,
                    restaurant_data.get("chnName") or restaurant_data.get("alias"),
                    tel,
                    restaurant_data.get("address"),
                    restaurant_data.get("city"),
                    restaurant_data.get("district"),
                    restaurant_data.get("businessArea") or restaurant_data.get("business_area"),
                    restaurant_data.get("location"),
                    restaurant_data.get("rating"),
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
        """Get a restaurant by ID.
        
        Args:
            restaurant_id: Restaurant hash ID (32 chars)
            
        Returns:
            Restaurant object or None
        """
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM restaurants WHERE id = $1",
                    restaurant_id,
                )
                return self._row_to_restaurant(row) if row else None

        except Exception as e:
            logger.error(f"get_restaurant failed: {e}")
            return None

    # =========================================================================
    # History Management
    # =========================================================================

    async def get_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[SearchHistory]:
        """Get search history for a user."""
        if not self._initialized or not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM search_history 
                    WHERE user_id = $1 
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    uuid.UUID(user_id),
                    limit,
                    offset,
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
                    uuid.UUID(user_id),
                ) or 0
        except Exception as e:
            logger.error(f"get_history_count failed: {e}")
            return 0

    async def add_history(
        self,
        user_id: str,
        query: str,
        session_id: Optional[str] = None,
        status: str = "loading",
        results_count: int = 0,
        location: Optional[str] = None,
    ) -> Optional[SearchHistory]:
        """Add a search to history.
        
        Args:
            user_id: User ID
            query: Search query
            session_id: Session ID for SSE recovery
            status: Search status (loading, completed, error)
            results_count: Number of results
            location: Search location
        """
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO search_history (user_id, session_id, query, status, results_count, location)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    uuid.UUID(user_id),
                    uuid.UUID(session_id) if session_id else None,
                    query,
                    status,
                    results_count,
                    location,
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
                    """
                    DELETE FROM search_history 
                    WHERE user_id = $1 AND id = $2
                    """,
                    uuid.UUID(user_id),
                    history_id,
                )
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
                    "DELETE FROM search_history WHERE user_id = $1",
                    uuid.UUID(user_id),
                )
                return int(result.split()[-1])

        except Exception as e:
            logger.error(f"clear_history failed: {e}")
            return 0

    async def update_history_status(
        self,
        session_id: str,
        status: str,
        results_count: Optional[int] = None,
    ) -> bool:
        """Update search history status by session_id.
        
        Args:
            session_id: Session ID
            status: New status (loading, completed, error)
            results_count: Optional updated results count
        """
        if not self._initialized or not self._pool:
            return False

        try:
            async with self._pool.acquire() as conn:
                if results_count is not None:
                    await conn.execute(
                        """
                        UPDATE search_history 
                        SET status = $1, results_count = $2, updated_at = NOW()
                        WHERE session_id = $3
                        """,
                        status,
                        results_count,
                        uuid.UUID(session_id),
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE search_history 
                        SET status = $1, updated_at = NOW()
                        WHERE session_id = $2
                        """,
                        status,
                        uuid.UUID(session_id),
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

    async def save_search_result(
        self,
        session_id: str,
        restaurants: List[Dict[str, Any]],
        summary: str = "",
        filtered_count: int = 0,
        query: str = "",
        turn_id: Optional[int] = None,
    ) -> bool:
        """Save search results for SSE recovery.
        
        Args:
            session_id: Session ID
            restaurants: List of restaurant data
            summary: Search summary
            filtered_count: Number of filtered restaurants
            query: Original query for this turn
            turn_id: Turn number (auto-increment if None)
        """
        if not self._initialized or not self._pool:
            return False

        try:
            async with self._pool.acquire() as conn:
                # 如果没有指定 turn_id，自动计算下一个
                if turn_id is None:
                    row = await conn.fetchrow(
                        """
                        SELECT COALESCE(MAX(turn_id), 0) + 1 as next_turn
                        FROM search_results WHERE session_id = $1
                        """,
                        uuid.UUID(session_id),
                    )
                    turn_id = row["next_turn"] if row else 1
                
                await conn.execute(
                    """
                    INSERT INTO search_results (session_id, turn_id, restaurants, summary, filtered_count, query)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (session_id, turn_id) DO UPDATE SET
                        restaurants = $3,
                        summary = $4,
                        filtered_count = $5,
                        query = $6
                    """,
                    uuid.UUID(session_id),
                    turn_id,
                    json.dumps(restaurants, ensure_ascii=False),
                    summary,
                    filtered_count,
                    query,
                )
                logger.debug(f"Saved search result: session={session_id}, turn={turn_id}, count={len(restaurants)}")
                return True

        except Exception as e:
            logger.error(f"save_search_result failed: {e}")
            return False

    async def get_search_result(
        self, 
        session_id: str, 
        turn_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get saved search results by session_id.
        
        Args:
            session_id: Session ID
            turn_id: Specific turn (None = latest turn)
        
        Returns:
            Dict with restaurants, summary, filtered_count, turn_id or None
        """
        if not self._initialized or not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                if turn_id is not None:
                    # 获取指定轮次
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM search_results 
                        WHERE session_id = $1 AND turn_id = $2
                        """,
                        uuid.UUID(session_id),
                        turn_id,
                    )
                else:
                    # 获取最新轮次（turn_id = 1 是首次搜索）
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM search_results 
                        WHERE session_id = $1
                        ORDER BY turn_id DESC
                        LIMIT 1
                        """,
                        uuid.UUID(session_id),
                    )
                
                if row:
                    restaurants = row["restaurants"]
                    if isinstance(restaurants, str):
                        restaurants = json.loads(restaurants)
                    return {
                        "session_id": str(row["session_id"]),
                        "turn_id": row.get("turn_id", 1),
                        "query": row.get("query", ""),
                        "restaurants": restaurants,
                        "summary": row["summary"],
                        "filtered_count": row["filtered_count"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    }
                return None

        except Exception as e:
            logger.error(f"get_search_result failed: {e}")
            return None
    
    async def get_first_search_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the first (original) search result for a session.
        
        This is useful for refine to restore the original recommendations.
        """
        return await self.get_search_result(session_id, turn_id=1)
    
    async def get_all_search_results(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all search results (all turns) for a session."""
        if not self._initialized or not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM search_results 
                    WHERE session_id = $1
                    ORDER BY turn_id ASC
                    """,
                    uuid.UUID(session_id),
                )
                
                results = []
                for row in rows:
                    restaurants = row["restaurants"]
                    if isinstance(restaurants, str):
                        restaurants = json.loads(restaurants)
                    results.append({
                        "session_id": str(row["session_id"]),
                        "turn_id": row.get("turn_id", 1),
                        "query": row.get("query", ""),
                        "restaurants": restaurants,
                        "summary": row["summary"],
                        "filtered_count": row["filtered_count"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    })
                return results

        except Exception as e:
            logger.error(f"get_all_search_results failed: {e}")
            return []

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _anonymous_user(self) -> User:
        """Create anonymous user for fallback."""
        return User(
            id=self.ANONYMOUS_USER_ID,
            device_id=self.ANONYMOUS_DEVICE_ID,
            name="Anonymous",
        )

    def _row_to_user(self, row) -> User:
        """Convert database row to User."""
        return User(
            id=str(row["id"]),
            device_id=row["device_id"],
            name=row["name"] or "Guest",
            email=row["email"],
            avatar=row["avatar"],
            location=row["location"],
            settings=row["settings"] or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_favorite(self, row) -> Favorite:
        """Convert database row to Favorite (basic, no join)."""
        return Favorite(
            id=row["id"],
            user_id=str(row["user_id"]),
            restaurant_id=row["restaurant_id"],
            restaurant=None,
            created_at=row["created_at"],
        )

    def _row_to_favorite_with_restaurant(self, row) -> Favorite:
        """Convert joined database row to Favorite with restaurant data."""
        # Build restaurant dict from joined columns
        restaurant_data = None
        if row.get("name"):
            # Parse JSONB fields
            tags = row.get("tags", [])
            if isinstance(tags, str):
                tags = json.loads(tags)
            pros = row.get("pros", [])
            if isinstance(pros, str):
                pros = json.loads(pros)
            cons = row.get("cons", [])
            if isinstance(cons, str):
                cons = json.loads(cons)
            must_try = row.get("must_try", [])
            if isinstance(must_try, str):
                must_try = json.loads(must_try)
            black_list = row.get("black_list", [])
            if isinstance(black_list, str):
                black_list = json.loads(black_list)
            stats = row.get("stats", {})
            if isinstance(stats, str):
                stats = json.loads(stats)
            photos = row.get("photos", [])
            if isinstance(photos, str):
                photos = json.loads(photos)
            source_notes = row.get("source_notes", [])
            if isinstance(source_notes, str):
                source_notes = json.loads(source_notes)

            trust_score = row.get("trust_score")
            restaurant_data = {
                "id": row["restaurant_id"],
                "name": row["name"],
                "chnName": row.get("alias") or row["name"],
                "address": row.get("address"),
                "location": row.get("location"),
                "city": row.get("city"),
                "district": row.get("district"),
                "businessArea": row.get("business_area"),
                "tel": row.get("tel"),
                "rating": row.get("rating"),
                "cost": row.get("cost"),
                "openTime": row.get("open_time"),
                "trustScore": round(trust_score, 1) if trust_score else None,
                "oneLiner": row.get("one_liner"),
                "tags": tags,
                "pros": pros,
                "cons": cons,
                "warning": row.get("warning"),
                "photos": photos,
                "sourceNotes": source_notes,
                "mustTry": must_try,
                "blackList": black_list,
                "stats": stats,
            }

        return Favorite(
            id=row["id"],
            user_id=str(row["user_id"]),
            restaurant_id=row["restaurant_id"],
            restaurant=restaurant_data,
            created_at=row["created_at"],
        )

    def _row_to_restaurant(self, row) -> Restaurant:
        """Convert database row to Restaurant."""
        # Parse JSONB fields
        tags = row.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)
        pros = row.get("pros", [])
        if isinstance(pros, str):
            pros = json.loads(pros)
        cons = row.get("cons", [])
        if isinstance(cons, str):
            cons = json.loads(cons)
        must_try = row.get("must_try", [])
        if isinstance(must_try, str):
            must_try = json.loads(must_try)
        black_list = row.get("black_list", [])
        if isinstance(black_list, str):
            black_list = json.loads(black_list)
        stats = row.get("stats", {})
        if isinstance(stats, str):
            stats = json.loads(stats)
        photos = row.get("photos", [])
        if isinstance(photos, str):
            photos = json.loads(photos)
        source_notes = row.get("source_notes", [])
        if isinstance(source_notes, str):
            source_notes = json.loads(source_notes)

        return Restaurant(
            id=row["id"],
            name=row["name"],
            alias=row.get("alias"),
            tel=row.get("tel"),
            address=row.get("address"),
            city=row.get("city"),
            district=row.get("district"),
            business_area=row.get("business_area"),
            location=row.get("location"),
            rating=row.get("rating"),
            cost=row.get("cost"),
            open_time=row.get("open_time"),
            trust_score=row.get("trust_score"),
            one_liner=row.get("one_liner"),
            tags=tags,
            pros=pros,
            cons=cons,
            warning=row.get("warning"),
            must_try=must_try,
            black_list=black_list,
            stats=stats,
            photos=photos,
            source_notes=source_notes,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_history(self, row) -> SearchHistory:
        """Convert database row to SearchHistory."""
        return SearchHistory(
            id=row["id"],
            user_id=str(row["user_id"]),
            query=row["query"],
            session_id=str(row["session_id"]) if row.get("session_id") else None,
            status=row.get("status", "loading"),
            results_count=row["results_count"] or 0,
            location=row.get("location"),
            created_at=row["created_at"],
            updated_at=row.get("updated_at"),
        )


# =============================================================================
# Singleton Instance
# =============================================================================

_user_storage_service: Optional[UserStorageService] = None


async def get_user_storage_service() -> UserStorageService:
    """Get or create singleton UserStorageService."""
    global _user_storage_service
    if _user_storage_service is None:
        _user_storage_service = UserStorageService()
        await _user_storage_service.initialize()
    return _user_storage_service
