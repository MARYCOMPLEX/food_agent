# -*- coding: utf-8 -*-
"""Database repository operations for search results."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger


class SearchResultsMixin:
    """Mixin providing database CRUD operations for search results.

    Expects the host class to provide:
        _pool: asyncpg.Pool
        _initialized: bool
    """

    async def save_search_result(
        self, session_id: str, restaurants: List[Dict[str, Any]],
        summary: str = "", filtered_count: int = 0,
        query: str = "", turn_id: Optional[int] = None,
    ) -> bool:
        """Save search results for SSE recovery."""
        if not self._initialized or not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                if turn_id is None:
                    row = await conn.fetchrow(
                        "SELECT COALESCE(MAX(turn_id), 0) + 1 as next_turn "
                        "FROM search_results WHERE session_id = $1",
                        uuid.UUID(session_id),
                    )
                    turn_id = row["next_turn"] if row else 1
                await conn.execute(
                    "INSERT INTO search_results (session_id, turn_id, restaurants, summary, filtered_count, query) "
                    "VALUES ($1, $2, $3, $4, $5, $6) "
                    "ON CONFLICT (session_id, turn_id) DO UPDATE SET "
                    "restaurants = $3, summary = $4, filtered_count = $5, query = $6",
                    uuid.UUID(session_id), turn_id,
                    json.dumps(restaurants, ensure_ascii=False),
                    summary, filtered_count, query,
                )
                logger.debug(f"Saved search result: session={session_id}, turn={turn_id}, count={len(restaurants)}")
                return True
        except Exception as e:
            logger.error(f"save_search_result failed: {e}")
            return False

    def _parse_search_result_row(self, row) -> Dict[str, Any]:
        """Parse a search_results row into a dict."""
        restaurants = row["restaurants"]
        if isinstance(restaurants, str):
            restaurants = json.loads(restaurants)
        return {
            "session_id": str(row["session_id"]), "turn_id": row.get("turn_id", 1),
            "query": row.get("query", ""), "restaurants": restaurants,
            "summary": row["summary"], "filtered_count": row["filtered_count"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def get_search_result(self, session_id: str, turn_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get saved search results by session_id."""
        if not self._initialized or not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                if turn_id is not None:
                    row = await conn.fetchrow(
                        "SELECT * FROM search_results WHERE session_id = $1 AND turn_id = $2",
                        uuid.UUID(session_id), turn_id,
                    )
                else:
                    row = await conn.fetchrow(
                        "SELECT * FROM search_results WHERE session_id = $1 ORDER BY turn_id DESC LIMIT 1",
                        uuid.UUID(session_id),
                    )
                return self._parse_search_result_row(row) if row else None
        except Exception as e:
            logger.error(f"get_search_result failed: {e}")
            return None

    async def get_first_search_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the first (original) search result for a session."""
        return await self.get_search_result(session_id, turn_id=1)

    async def get_all_search_results(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all search results (all turns) for a session."""
        if not self._initialized or not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM search_results WHERE session_id = $1 ORDER BY turn_id ASC",
                    uuid.UUID(session_id),
                )
                return [self._parse_search_result_row(row) for row in rows]
        except Exception as e:
            logger.error(f"get_all_search_results failed: {e}")
            return []
