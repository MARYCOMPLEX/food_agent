# -*- coding: utf-8 -*-
"""
VectorSearchMixin - pgvector-based vector similarity search.

Provides embedding generation and similarity search capabilities
for PostgresStorage via mixin pattern.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger


class VectorSearchMixin:
    """
    Mixin providing vector similarity search via pgvector.

    Expects the host class to provide:
        self._pool: asyncpg connection pool
        self._initialized: bool
        self._pgvector_available: bool
        self._embedding_service: optional embedding service
    """

    async def search_similar(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> List[Any]:
        """
        Search for similar messages using vector similarity.

        Args:
            query: Query text
            session_id: Optional filter by session
            user_id: Optional filter by user
            limit: Max results
            min_similarity: Minimum cosine similarity threshold

        Returns:
            List of similar ChatHistoryRecord
        """
        if not self._initialized or not self._pool:
            return []

        # Generate query embedding
        query_embedding = await self._generate_embedding(query)
        if not query_embedding:
            return []

        try:
            # Import here to avoid circular imports
            from xhs_food.services.postgres_storage import ChatHistoryRecord

            async with self._pool.acquire() as conn:
                # Build query based on filters
                if session_id:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, role, content, metadata, created_at,
                               1 - (embedding <=> $1) as similarity
                        FROM chat_history
                        WHERE session_id = $2
                          AND embedding IS NOT NULL
                          AND 1 - (embedding <=> $1) >= $3
                        ORDER BY embedding <=> $1
                        LIMIT $4
                        """,
                        str(query_embedding),
                        uuid.UUID(session_id),
                        min_similarity,
                        limit,
                    )
                elif user_id:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, role, content, metadata, created_at,
                               1 - (embedding <=> $1) as similarity
                        FROM chat_history
                        WHERE user_id = $2
                          AND embedding IS NOT NULL
                          AND 1 - (embedding <=> $1) >= $3
                        ORDER BY embedding <=> $1
                        LIMIT $4
                        """,
                        str(query_embedding),
                        uuid.UUID(user_id),
                        min_similarity,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, role, content, metadata, created_at,
                               1 - (embedding <=> $1) as similarity
                        FROM chat_history
                        WHERE embedding IS NOT NULL
                          AND 1 - (embedding <=> $1) >= $2
                        ORDER BY embedding <=> $1
                        LIMIT $3
                        """,
                        str(query_embedding),
                        min_similarity,
                        limit,
                    )

                return [
                    ChatHistoryRecord(
                        id=row["id"],
                        session_id=str(row["session_id"]),
                        user_id=str(row["user_id"]) if row["user_id"] else None,
                        role=row["role"],
                        content=row["content"],
                        metadata={**(row["metadata"] or {}), "similarity": row["similarity"]},
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"search_similar failed: {e}")
            return []

    async def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for text.

        Uses environment variables:
            EMBEDDING_API_KEY: API key for embedding service
            EMBEDDING_API_BASE: Base URL for embedding API
            EMBEDDING_MODEL: Model name for embeddings
        """
        if self._embedding_service:
            return await self._embedding_service.embed(text)

        # Use environment variables for embedding
        api_key = os.getenv("EMBEDDING_API_KEY")
        api_base = os.getenv("EMBEDDING_API_BASE")
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

        if not api_key:
            logger.debug("EMBEDDING_API_KEY not set, skipping embedding")
            return None

        try:
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=model,
                openai_api_key=api_key,
                openai_api_base=api_base,
            )
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: embeddings.embed_query(text)
            )
            return result
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None
