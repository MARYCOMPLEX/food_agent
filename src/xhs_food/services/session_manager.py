# -*- coding: utf-8 -*-
"""
SessionManager - Unified session and context management.

Orchestrates Redis (L1 cache) + PostgreSQL (persistent storage) hybrid memory.

Usage:
    manager = SessionManager()
    await manager.initialize()
    
    # Store messages
    await manager.add_user_message(session_id, "Hello")
    await manager.add_assistant_message(session_id, "Hi there!")
    
    # Get context for LLM
    context = await manager.get_context(session_id)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from xhs_food.services.redis_memory import RedisMemory, ChatMessage
from xhs_food.services.postgres_storage import PostgresStorage, ChatHistoryRecord


class SessionManager:
    """
    Unified session manager orchestrating Redis + PostgreSQL.
    
    Data Flow:
    1. Read: Redis first, fallback to PostgreSQL (cache warming)
    2. Write: Sync to Redis, async to PostgreSQL
    
    Features:
    - Multi-session support with session_id
    - Automatic cache warming from PostgreSQL
    - Background persistence with embeddings
    - Sliding window context management
    """
    
    # Configuration
    DEFAULT_CONTEXT_WINDOW = 10  # Messages to include in LLM context
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        database_url: Optional[str] = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
    ):
        self._redis_url = redis_url or os.getenv("REDIS_URL")
        self._database_url = database_url or os.getenv("DATABASE_URL")
        self._context_window = context_window
        
        # Initialize components
        self._redis = RedisMemory(
            redis_url=self._redis_url,
            window_size=self._context_window * 2,  # Store more than we show
        )
        self._postgres = PostgresStorage(
            database_url=self._database_url,
        )
        
        # Background task queue
        self._pending_saves: List[asyncio.Task] = []
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Initialize storage backends."""
        # Redis is initialized in constructor
        # PostgreSQL needs async initialization
        pg_ok = await self._postgres.initialize()
        
        if not pg_ok:
            logger.warning("PostgreSQL not available, using Redis-only mode")
        
        self._initialized = True
        return True
    
    async def close(self) -> None:
        """Close connections and wait for pending saves."""
        # Wait for pending background tasks
        if self._pending_saves:
            await asyncio.gather(*self._pending_saves, return_exceptions=True)
        
        await self._postgres.close()
        self._initialized = False
    
    def create_session(self) -> str:
        """Create a new session ID."""
        return str(uuid.uuid4())
    
    async def add_user_message(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a user message to the session."""
        await self._add_message(session_id, "user", content, user_id, metadata)
    
    async def add_assistant_message(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an assistant message to the session."""
        await self._add_message(session_id, "assistant", content, user_id, metadata)
    
    async def _add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a message to both Redis and PostgreSQL.
        
        - Redis: Synchronous (immediate)
        - PostgreSQL: Asynchronous (background)
        """
        # 1. Sync write to Redis (fast)
        self._redis.add_message(session_id, role, content, metadata)
        
        # 2. Async write to PostgreSQL (background)
        task = asyncio.create_task(
            self._postgres.save_message(
                session_id=session_id,
                role=role,
                content=content,
                user_id=user_id,
                metadata=metadata,
                generate_embedding=True,  # Uses EMBEDDING_* env vars
            )
        )
        self._pending_saves.append(task)
        
        # Clean up completed tasks
        self._pending_saves = [t for t in self._pending_saves if not t.done()]
    
    async def get_context(
        self,
        session_id: str,
        count: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Get conversation context for LLM.
        
        Implements cache warming: if Redis is empty, load from PostgreSQL.
        
        Args:
            session_id: Session identifier
            count: Number of messages (default: context_window)
            
        Returns:
            List of {"role": "user/assistant", "content": "..."} dicts
        """
        count = count or self._context_window
        
        # Try Redis first
        messages = self._redis.get_recent_messages(session_id, count)
        
        if messages:
            return [{"role": m.role, "content": m.content} for m in messages]
        
        # Cache warming: load from PostgreSQL
        logger.info(f"Cache miss for session {session_id}, warming from PostgreSQL")
        history = await self._postgres.get_session_history(session_id, limit=count)
        
        if history:
            # Populate Redis cache
            for record in history:
                self._redis.add_message(
                    session_id,
                    record.role,
                    record.content,
                    record.metadata,
                )
            
            return [{"role": r.role, "content": r.content} for r in history]
        
        return []
    
    async def get_full_history(
        self,
        session_id: str,
        limit: int = 100,
    ) -> List[ChatHistoryRecord]:
        """Get full chat history from PostgreSQL."""
        return await self._postgres.get_session_history(session_id, limit=limit)
    
    async def search_similar_context(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar messages in history (RAG support).
        
        Args:
            query: Query text
            session_id: Optional filter by session
            user_id: Optional filter by user
            limit: Max results
            
        Returns:
            List of similar messages with similarity scores
        """
        records = await self._postgres.search_similar(
            query=query,
            session_id=session_id,
            user_id=user_id,
            limit=limit,
        )
        
        return [r.to_dict() for r in records]
    
    async def clear_session(self, session_id: str) -> None:
        """Clear session from both Redis and PostgreSQL."""
        self._redis.clear_session(session_id)
        await self._postgres.delete_session(session_id)
        logger.info(f"Session {session_id} cleared")
    
    def session_exists(self, session_id: str) -> bool:
        """Check if session exists in Redis."""
        return self._redis.session_exists(session_id)
    
    def get_session_length(self, session_id: str) -> int:
        """Get number of messages in Redis cache."""
        return self._redis.get_session_length(session_id)


# Singleton instance
_session_manager: Optional[SessionManager] = None


async def get_session_manager() -> SessionManager:
    """Get or create singleton SessionManager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
        await _session_manager.initialize()
    return _session_manager
