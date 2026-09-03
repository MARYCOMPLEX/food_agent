# -*- coding: utf-8 -*-
"""Centralized typed application settings (pydantic-settings).

All ``os.getenv`` access in the codebase should be replaced by attribute
lookups on :data:`settings`. Adding a new configuration value is a
one-line change here plus an entry in ``.env.example``.
"""
from __future__ import annotations

from functools import lru_cache
import os
from typing import List, Literal, Optional

for _proxy_key in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_proxy_key)
    if _val and "::" in _val:
        os.environ[_proxy_key] = ",".join(p.strip() for p in _val.split(",") if "::" not in p and p.strip())

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment (.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- LLM ----------
    openai_api_key: Optional[str] = None
    openai_api_base: str = "https://api.siliconflow.cn/v1/"
    default_llm_model: str = "Qwen/Qwen3-8B"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024

    # ---------- Embedding (optional, falls back to LLM creds) ----------
    embedding_api_key: Optional[str] = None
    embedding_api_base: Optional[str] = None
    embedding_model: str = "text-embedding-3-small"

    # ---------- Search behavior ----------
    search_deep_mode: bool = False
    search_note_limit: int = 15
    search_notes_per_keyword: int = 4
    search_max_restaurants: int = 10

    # ---------- Concurrency ----------
    analyze_concurrency: int = 5
    poi_concurrency: int = 5

    # ---------- HTTP / SSE ----------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    sse_heartbeat_seconds: int = 30
    sse_timeout_seconds: int = 900
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_search: str = "10/minute"

    # ---------- Event bus ----------
    event_bus_backend: Literal["memory", "redis"] = "memory"
    event_stream_ttl_seconds: int = 3600
    event_stream_maxlen: int = 1000

    # ---------- Redis ----------
    redis_url: Optional[str] = None
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_database: int = 0
    redis_username: Optional[str] = None
    redis_password: Optional[str] = None

    # ---------- PostgreSQL ----------
    database_url: Optional[str] = None
    postgres_host: Optional[str] = None
    postgres_port: int = 5432
    postgres_db: str = "xhs_food_agent"
    postgres_user: str = "postgres"
    postgres_password: Optional[str] = None

    # ---------- Logging ----------
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # ---------- Derived helpers ----------
    def resolved_redis_url(self) -> Optional[str]:
        """Return a Redis URL, building one from host/port/auth when needed."""
        if self.redis_url:
            return self.redis_url
        if not self.redis_host:
            return None
        auth = ""
        if self.redis_username and self.redis_password:
            auth = f"{self.redis_username}:{self.redis_password}@"
        elif self.redis_password:
            auth = f":{self.redis_password}@"
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_database}"

    def resolved_database_url(self) -> Optional[str]:
        """Return a Postgres URL, building one from host/port/auth when needed."""
        if self.database_url:
            return self.database_url
        if not self.postgres_host:
            return None
        auth = f"{self.postgres_user}"
        if self.postgres_password:
            auth = f"{self.postgres_user}:{self.postgres_password}"
        return (
            f"postgresql://{auth}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached :class:`Settings` instance."""
    return Settings()


settings = get_settings()
