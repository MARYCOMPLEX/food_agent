# -*- coding: utf-8 -*-
"""Main UserStorageService class and singleton."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logger.warning("asyncpg not installed, UserStorageService will be disabled")

from .converters import ConverterMixin
from .models import Favorite, SearchHistory, User
from .repository import RepositoryMixin
from .search_results import SearchResultsMixin
from .schema import (
    CREATE_FAVORITES_TABLE,
    CREATE_HISTORY_TABLE,
    CREATE_RESTAURANTS_TABLE,
    CREATE_SEARCH_RESULTS_TABLE,
    CREATE_USERS_TABLE,
    ENABLE_EXTENSIONS_SQL,
)


class UserStorageService(ConverterMixin, RepositoryMixin, SearchResultsMixin):
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
                # Migration: Add username if missing
                try:
                    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(50) UNIQUE")
                except Exception:
                    pass  # Column might exist or error is benign in dev

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
        username: Optional[str] = None,
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
                if username is not None:
                    updates.append(f"username = ${param_idx}")
                    params.append(username)
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

    async def create_search_history(
        self,
        *,
        session_id: str,
        query: str,
        status: str = "loading",
        user_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[SearchHistory]:
        """Compatibility façade used by the unified search API.

        The repository's canonical method is ``add_history``; keeping this
        adapter avoids coupling routes to the storage mixin implementation.
        """
        return await self.add_history(
            user_id=user_id or self.ANONYMOUS_USER_ID,
            query=query,
            session_id=session_id,
            status=status,
            location=location,
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
