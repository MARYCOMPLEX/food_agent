# -*- coding: utf-8 -*-
"""
PostgresStorage - PostgreSQL long-term storage with pgvector.

Implements persistent storage for chat history with vector search capability.
Table: chat_history
"""

from __future__ import annotations

import asyncio
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
    logger.warning("asyncpg not installed, PostgresStorage will be disabled")


# SQL for table creation (without pgvector)
CREATE_TABLE_SQL_BASE = """
CREATE TABLE IF NOT EXISTS chat_history (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    user_id UUID,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_session_id ON chat_history(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_user_id ON chat_history(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_created_at ON chat_history(created_at DESC);
"""

# SQL to add embedding column (if pgvector is available)
# Dimension 4096 supports most common embedding models
ADD_EMBEDDING_COLUMN_SQL = """
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS embedding VECTOR(4096);
"""

# Enable pgvector extension
ENABLE_PGVECTOR_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"


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


class PostgresStorage:
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
        """Initialize database connection and create tables."""
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
                # Create base table first (no embedding column)
                await conn.execute(CREATE_TABLE_SQL_BASE)
                
                # Try to enable pgvector and add embedding column
                try:
                    await conn.execute(ENABLE_PGVECTOR_SQL)
                    await conn.execute(ADD_EMBEDDING_COLUMN_SQL)
                    self._pgvector_available = True
                    logger.info("pgvector enabled, embedding search available")
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
        """
        Save a message to persistent storage.
        
        Args:
            session_id: Session identifier
            role: "user" or "assistant"
            content: Message content
            user_id: Optional user identifier
            metadata: Optional metadata
            generate_embedding: Whether to generate embedding (async)
            
        Returns:
            Record ID if successful, None otherwise
        """
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
        """
        Get chat history for a session.
        
        Args:
            session_id: Session identifier
            limit: Max records to return
            offset: Offset for pagination
            
        Returns:
            List of ChatHistoryRecord, oldest first
        """
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
    
    async def search_similar(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> List[ChatHistoryRecord]:
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
