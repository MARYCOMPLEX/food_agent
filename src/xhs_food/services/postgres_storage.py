# -*- coding: utf-8 -*-
"""
PostgresStorage - PostgreSQL long-term storage with pgvector.

Implements persistent storage for chat history with vector search capability.
Table: chat_history
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from xhs_food.foundation.schema_authority import (
    SchemaNotReadyError,
    assert_postgres_schema_ready,
)
from xhs_food.services.postgres_vector import VectorSearchMixin

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logger.warning("asyncpg not installed, PostgresStorage will be disabled")


@dataclass
class ChatHistoryRecord:
    """Database record for chat history."""
    id: Optional[int] = None
    session_id: str = ""
    user_id: Optional[str] = None
    role: str = ""
    content: str = ""
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PostgresStorage(VectorSearchMixin):
    """
    PostgreSQL-based long-term storage for chat history.

    Features:
    - Persistent message storage
    - Vector similarity search (pgvector)
    - Session and user isolation

    Environment Variables:
        DATABASE_URL: Full PostgreSQL URL (takes precedence)
        OR individual settings:
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    """

    # Minimum content length for embedding (save costs)
    MIN_EMBEDDING_LENGTH = 10

    def __init__(
        self,
        database_url: Optional[str] = None,
        embedding_service=None,
    ):
        self._database_url = database_url
        self._embedding_service = embedding_service
        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False

        # Build database URL from environment if not provided
        if not self._database_url:
            self._database_url = self._build_database_url()
        if self._database_url:
            # The release manifest uses SQLAlchemy's async driver scheme;
            # asyncpg itself accepts the plain PostgreSQL URI scheme only.
            self._database_url = self._database_url.replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )

    def _build_database_url(self) -> Optional[str]:
        """Build database URL from environment variables."""
        # Try DATABASE_URL first
        url = os.getenv("DATABASE_URL")
        if url:
            return url

        # Build from individual env vars
        host = os.getenv("POSTGRES_HOST")
        if not host:
            return None

        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "postgres")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")

        if password:
            return f"postgresql://{user}:{password}@{host}:{port}/{db}"
        else:
            return f"postgresql://{user}@{host}:{port}/{db}"

    async def initialize(self) -> bool:
        """Initialize against the schema provisioned by Alembic."""
        if not ASYNCPG_AVAILABLE:
            logger.warning("asyncpg not available, PostgresStorage disabled")
            return False

        if not self._database_url:
            logger.warning("Database URL not configured, PostgresStorage disabled")
            return False

        try:
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=10,
            )

            self._pgvector_available = False

            async with self._pool.acquire() as conn:
                await assert_postgres_schema_ready(
                    conn,
                    {
                        "chat_history": (
                            "id",
                            "session_id",
                            "user_id",
                            "role",
                            "content",
                            "metadata",
                            "created_at",
                        )
                    },
                )

                # pgvector is optional for legacy reads, but its extension and
                # embedding column are still provisioned only by Alembic.
                try:
                    await assert_postgres_schema_ready(
                        conn,
                        {"chat_history": ("embedding",)},
                        extensions=("vector",),
                    )
                    self._pgvector_available = True
                    logger.info("pgvector enabled, embedding search available")
                except SchemaNotReadyError as e:
                    logger.warning(f"pgvector schema is not ready: {e}. Vector search disabled.")
                except Exception as e:
                    logger.warning(f"pgvector not available: {e}. Vector search disabled.")

            self._initialized = True
            logger.info("PostgresStorage initialized successfully")
            return True

        except Exception as e:
            logger.error(f"PostgresStorage initialization failed: {e}")
            return False

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        generate_embedding: bool = True,
    ) -> Optional[int]:
        """Save a message to persistent storage. Returns record ID or None."""
        if not self._initialized or not self._pool:
            return None

        try:
            # Generate embedding only if pgvector is available
            embedding = None
            if (generate_embedding and
                getattr(self, '_pgvector_available', False) and
                len(content) >= self.MIN_EMBEDDING_LENGTH):
                embedding = await self._generate_embedding(content)

            async with self._pool.acquire() as conn:
                if embedding:
                    record_id = await conn.fetchval(
                        """
                        INSERT INTO chat_history (session_id, user_id, role, content, embedding, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING id
                        """,
                        uuid.UUID(session_id),
                        uuid.UUID(user_id) if user_id else None,
                        role,
                        content,
                        str(embedding),  # pgvector expects string format
                        json.dumps(metadata or {}),
                    )
                else:
                    record_id = await conn.fetchval(
                        """
                        INSERT INTO chat_history (session_id, user_id, role, content, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                        """,
                        uuid.UUID(session_id),
                        uuid.UUID(user_id) if user_id else None,
                        role,
                        content,
                        json.dumps(metadata or {}),
                    )

                return record_id

        except Exception as e:
            logger.error(f"save_message failed: {e}")
            return None

    async def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ChatHistoryRecord]:
        """Get chat history for a session, oldest first."""
        if not self._initialized or not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, session_id, user_id, role, content, metadata, created_at
                    FROM chat_history
                    WHERE session_id = $1
                    ORDER BY created_at ASC
                    LIMIT $2 OFFSET $3
                    """,
                    uuid.UUID(session_id),
                    limit,
                    offset,
                )

                return [
                    ChatHistoryRecord(
                        id=row["id"],
                        session_id=str(row["session_id"]),
                        user_id=str(row["user_id"]) if row["user_id"] else None,
                        role=row["role"],
                        content=row["content"],
                        metadata=row["metadata"] or {},
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"get_session_history failed: {e}")
            return []

    async def delete_session(self, session_id: str) -> int:
        """Delete all messages for a session. Returns count of deleted records."""
        if not self._initialized or not self._pool:
            return 0

        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM chat_history WHERE session_id = $1",
                    uuid.UUID(session_id),
                )
                # Parse "DELETE N" result
                count = int(result.split()[-1])
                return count
        except Exception as e:
            logger.error(f"delete_session failed: {e}")
            return 0
