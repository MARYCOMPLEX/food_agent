# -*- coding: utf-8 -*-
"""
RedisMemory - Redis short-term context storage.

Implements L1 cache for conversation context using Redis List.
Key pattern: session:{session_id}:window
TTL: 24 hours by default
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis package not installed, RedisMemory will use in-memory fallback")


@dataclass
class ChatMessage:
    """Chat message structure."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata or {},
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata"),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ChatMessage":
        return cls.from_dict(json.loads(json_str))


class RedisMemory:
    """
    Redis-based short-term memory for conversation context.
    
    Implements sliding window pattern for recent messages.
    Falls back to in-memory dict if Redis is not available.
    
    Environment Variables:
        REDIS_URL: Full Redis URL (takes precedence)
        OR individual settings:
        REDIS_HOST, REDIS_PORT, REDIS_DATABASE, REDIS_USERNAME, REDIS_PASSWORD
    """
    
    # Configuration
    DEFAULT_TTL = 86400  # 24 hours
    DEFAULT_WINDOW_SIZE = 20  # Max messages in context window
    KEY_PREFIX = "session"
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl: int = DEFAULT_TTL,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ):
        import os
        
        self._ttl = ttl
        self._window_size = window_size
        self._redis: Optional[redis.Redis] = None
        self._fallback_store: Dict[str, List[str]] = {}
        
        # Build Redis URL from environment if not provided
        if not redis_url:
            redis_url = os.getenv("REDIS_URL")
        
        if not redis_url:
            # Try to build from individual env vars
            host = os.getenv("REDIS_HOST")
            if host:
                port = os.getenv("REDIS_PORT", "6379")
                db = os.getenv("REDIS_DATABASE", "0")
                username = os.getenv("REDIS_USERNAME", "")
                password = os.getenv("REDIS_PASSWORD", "")
                
                if username and password:
                    redis_url = f"redis://{username}:{password}@{host}:{port}/{db}"
                elif password:
                    redis_url = f"redis://:{password}@{host}:{port}/{db}"
                else:
                    redis_url = f"redis://{host}:{port}/{db}"
        
        if REDIS_AVAILABLE and redis_url:
            try:
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                # Mask password in log
                safe_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
                logger.info(f"Redis connected: {safe_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, using in-memory fallback")
                self._redis = None
    
    def _get_key(self, session_id: str) -> str:
        """Get Redis key for session."""
        return f"{self.KEY_PREFIX}:{session_id}:window"
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a message to the session context.
        
        Args:
            session_id: Session identifier
            role: "user" or "assistant"
            content: Message content
            metadata: Optional metadata
        """
        message = ChatMessage(
            role=role,
            content=content,
            timestamp=time.time(),
            metadata=metadata,
        )
        
        key = self._get_key(session_id)
        json_str = message.to_json()
        
        if self._redis:
            try:
                # RPUSH to add to the end of list
                self._redis.rpush(key, json_str)
                # Set TTL
                self._redis.expire(key, self._ttl)
                # Trim to window size (keep most recent)
                self._redis.ltrim(key, -self._window_size, -1)
            except Exception as e:
                logger.error(f"Redis add_message failed: {e}")
                self._fallback_add(key, json_str)
        else:
            self._fallback_add(key, json_str)
    
    def _fallback_add(self, key: str, json_str: str) -> None:
        """In-memory fallback for add_message."""
        if key not in self._fallback_store:
            self._fallback_store[key] = []
        self._fallback_store[key].append(json_str)
        # Trim
        if len(self._fallback_store[key]) > self._window_size:
            self._fallback_store[key] = self._fallback_store[key][-self._window_size:]
    
    def get_recent_messages(
        self,
        session_id: str,
        count: Optional[int] = None,
    ) -> List[ChatMessage]:
        """
        Get recent messages from session context.
        
        Args:
            session_id: Session identifier
            count: Number of messages to retrieve (default: all in window)
            
        Returns:
            List of ChatMessage objects, oldest first
        """
        key = self._get_key(session_id)
        count = count or self._window_size
        
        if self._redis:
            try:
                # LRANGE gets elements from start to end
                # -count to -1 gets the last `count` elements
                raw_messages = self._redis.lrange(key, -count, -1)
                return [ChatMessage.from_json(m) for m in raw_messages]
            except Exception as e:
                logger.error(f"Redis get_recent_messages failed: {e}")
                return self._fallback_get(key, count)
        else:
            return self._fallback_get(key, count)
    
    def _fallback_get(self, key: str, count: int) -> List[ChatMessage]:
        """In-memory fallback for get_recent_messages."""
        messages = self._fallback_store.get(key, [])
        raw = messages[-count:] if count else messages
        return [ChatMessage.from_json(m) for m in raw]
    
    def get_context_for_llm(
        self,
        session_id: str,
        count: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Get messages formatted for LLM context.
        
        Returns list of {"role": "user/assistant", "content": "..."}
        """
        messages = self.get_recent_messages(session_id, count)
        return [{"role": m.role, "content": m.content} for m in messages]
    
    def clear_session(self, session_id: str) -> None:
        """Clear all messages for a session."""
        key = self._get_key(session_id)
        
        if self._redis:
            try:
                self._redis.delete(key)
            except Exception as e:
                logger.error(f"Redis clear_session failed: {e}")
        
        if key in self._fallback_store:
            del self._fallback_store[key]
    
    def session_exists(self, session_id: str) -> bool:
        """Check if session has any messages."""
        key = self._get_key(session_id)
        
        if self._redis:
            try:
                return self._redis.exists(key) > 0
            except Exception as e:
                logger.error(f"Redis session_exists failed: {e}")
        
        return key in self._fallback_store and len(self._fallback_store[key]) > 0
    
    def get_session_length(self, session_id: str) -> int:
        """Get number of messages in session."""
        key = self._get_key(session_id)
        
        if self._redis:
            try:
                return self._redis.llen(key)
            except Exception as e:
                logger.error(f"Redis get_session_length failed: {e}")
        
        return len(self._fallback_store.get(key, []))
