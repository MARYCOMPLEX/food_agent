# -*- coding: utf-8 -*-
"""Persistent database storage for dynamic LLM model and provider configurations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, List, Optional

from loguru import logger

from food_agent.config import settings


def mask_api_key(key: str | None) -> str:
    """Mask an API key for safe display in UI/logs, showing only first 7 and last 4 chars."""
    if not key:
        return "未设置"
    if len(key) <= 12:
        return "********"
    return f"{key[:7]}********{key[-4:]}"


class LLMConfigStorage:
    """SQLite-backed persistent store for LLM provider and model configurations.

    Allows dynamic addition, deletion, tuning, and default switching of models
    without editing environment variables or restarting the backend server.
    """

    _instance: Optional[LLMConfigStorage] = None

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> LLMConfigStorage:
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            default_dir = Path("data")
            default_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = str(default_dir / "mcp_services.db")
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db_path = db_path
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_sync(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_models (
                    model_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'OpenAI',
                    base_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    temperature REAL NOT NULL DEFAULT 0.2,
                    max_tokens INTEGER NOT NULL DEFAULT 1024,
                    reasoning_effort TEXT,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    is_user_selectable INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def initialize_sync(self) -> None:
        """Initialize table schema (synchronously). Starts completely clean with no mock data."""
        self._init_sync()
        self._initialized = True

    async def initialize(self) -> None:
        """Initialize table schema."""
        await asyncio.to_thread(self.initialize_sync)

    def _row_to_dict(self, row: sqlite3.Row, mask_key: bool = True) -> dict[str, Any]:
        data = dict(row)
        data["is_default"] = bool(data["is_default"])
        data["is_user_selectable"] = bool(data["is_user_selectable"])
        data["masked_api_key"] = mask_api_key(data.get("api_key"))
        if mask_key:
            data.pop("api_key", None)
        return data

    def _list_sync(self, user_selectable_only: bool, mask_key: bool) -> List[dict[str, Any]]:
        with self._get_connection() as conn:
            count_check = conn.execute("SELECT COUNT(*) FROM llm_models").fetchone()
            if count_check and count_check[0] > 0:
                def_check = conn.execute("SELECT COUNT(*) FROM llm_models WHERE is_default = 1").fetchone()
                if def_check and def_check[0] == 0:
                    conn.execute(
                        "UPDATE llm_models SET is_default = 1 WHERE model_id = (SELECT model_id FROM llm_models ORDER BY created_at ASC LIMIT 1)"
                    )
                    conn.commit()

            query = "SELECT * FROM llm_models"
            params: list[Any] = []
            if user_selectable_only:
                query += " WHERE is_user_selectable = 1"
            query += " ORDER BY is_default DESC, created_at ASC"
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row, mask_key=mask_key) for row in cursor.fetchall()]

    def list_models_sync(
        self, user_selectable_only: bool = False, mask_key: bool = True
    ) -> List[dict[str, Any]]:
        """List all configured LLM models synchronously."""
        if not self._initialized:
            self.initialize_sync()
        return self._list_sync(user_selectable_only, mask_key)

    async def list_models(
        self, user_selectable_only: bool = False, mask_key: bool = True
    ) -> List[dict[str, Any]]:
        """List all configured LLM models."""
        return await asyncio.to_thread(self._list_sync, user_selectable_only, mask_key)

    def _get_sync(self, identifier: str, mask_key: bool) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM llm_models WHERE model_id = ? OR model_name = ?",
                (identifier, identifier),
            )
            row = cursor.fetchone()
            return self._row_to_dict(row, mask_key=mask_key) if row else None

    def get_model_sync(self, identifier: str, mask_key: bool = False) -> Optional[dict[str, Any]]:
        """Get a single model synchronously by model_id or model_name."""
        if not self._initialized:
            self.initialize_sync()
        return self._get_sync(identifier, mask_key)

    async def get_model(self, identifier: str, mask_key: bool = False) -> Optional[dict[str, Any]]:
        """Get a single model by model_id or model_name."""
        return await asyncio.to_thread(self._get_sync, identifier, mask_key)

    def _get_default_sync(self, mask_key: bool) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM llm_models WHERE is_default = 1 ORDER BY updated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                # fallback to first available model if none marked default
                cursor = conn.execute("SELECT * FROM llm_models ORDER BY created_at ASC LIMIT 1")
                row = cursor.fetchone()
            return self._row_to_dict(row, mask_key=mask_key) if row else None

    def get_default_model_sync(self, mask_key: bool = False) -> Optional[dict[str, Any]]:
        """Get the currently active default model configuration synchronously."""
        if not self._initialized:
            self.initialize_sync()
        return self._get_default_sync(mask_key)

    async def get_default_model(self, mask_key: bool = False) -> Optional[dict[str, Any]]:
        """Get the currently active default model configuration."""
        return await asyncio.to_thread(self._get_default_sync, mask_key)

    def _save_sync(self, record: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        model_name = str(record["model_name"]).strip()
        model_id = str(record.get("model_id") or f"model_{model_name.replace('.', '_').replace('-', '_')}").strip()
        display_name = str(record.get("display_name") or model_name).strip()
        provider = str(record.get("provider") or "OpenAI").strip()
        base_url = str(record["base_url"]).strip()
        # Normalize base_url: strip trailing /chat/completions or /chat/completions/
        base_url = re.sub(r"/chat/completions/?$", "", base_url, flags=re.IGNORECASE).rstrip("/")
        if base_url:
            base_url = base_url + "/"
        api_key = str(record.get("api_key") or "").strip()
        temperature = float(record.get("temperature", 0.2))
        max_tokens = int(record.get("max_tokens", 1024))
        reasoning_effort = str(record["reasoning_effort"]).strip() if record.get("reasoning_effort") else None
        is_default = 1 if record.get("is_default", False) else 0
        is_user_selectable = 1 if record.get("is_user_selectable", True) else 0

        with self._get_connection() as conn:
            # If this record is set as default, clear default on other models
            if is_default:
                conn.execute("UPDATE llm_models SET is_default = 0")

            cursor = conn.execute("SELECT created_at, api_key FROM llm_models WHERE model_id = ?", (model_id,))
            existing = cursor.fetchone()
            if existing:
                created_at = existing["created_at"]
                # Keep existing api_key if not provided or masked
                if not api_key or "••••" in api_key or "****" in api_key:
                    api_key = existing["api_key"]

                conn.execute(
                    """
                    UPDATE llm_models
                    SET model_name = ?, display_name = ?, provider = ?,
                        base_url = ?, api_key = ?, temperature = ?,
                        max_tokens = ?, reasoning_effort = ?, is_default = ?,
                        is_user_selectable = ?, updated_at = ?
                    WHERE model_id = ?
                    """,
                    (
                        model_name,
                        display_name,
                        provider,
                        base_url,
                        api_key,
                        temperature,
                        max_tokens,
                        reasoning_effort,
                        is_default,
                        is_user_selectable,
                        now,
                        model_id,
                    ),
                )
            else:
                created_at = now
                conn.execute(
                    """
                    INSERT INTO llm_models (
                        model_id, model_name, display_name, provider,
                        base_url, api_key, temperature, max_tokens,
                        reasoning_effort, is_default, is_user_selectable,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_id,
                        model_name,
                        display_name,
                        provider,
                        base_url,
                        api_key,
                        temperature,
                        max_tokens,
                        reasoning_effort,
                        is_default,
                        is_user_selectable,
                        created_at,
                        now,
                    ),
                )
            conn.commit()

        try:
            from food_agent.services.llm_service import LLMService
            LLMService.clear_cache()
        except Exception:
            pass

        return {
            "model_id": model_id,
            "model_name": model_name,
            "display_name": display_name,
            "provider": provider,
            "base_url": base_url,
            "masked_api_key": mask_api_key(api_key),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "is_default": bool(is_default),
            "is_user_selectable": bool(is_user_selectable),
            "created_at": created_at,
            "updated_at": now,
        }

    async def save_model(self, record: dict[str, Any]) -> dict[str, Any]:
        """Save (create or update) an LLM model configuration."""
        return await asyncio.to_thread(self._save_sync, record)

    def _set_default_sync(self, model_id: str) -> Optional[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("UPDATE llm_models SET is_default = 0")
            cursor = conn.execute(
                "UPDATE llm_models SET is_default = 1, updated_at = ? WHERE model_id = ?",
                (now, model_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            result = self._get_sync(model_id, mask_key=True)

        try:
            from food_agent.services.llm_service import LLMService
            LLMService.clear_cache()
        except Exception:
            pass

        return result

    async def set_default_model(self, model_id: str) -> Optional[dict[str, Any]]:
        """Set a specified model as the system default."""
        return await asyncio.to_thread(self._set_default_sync, model_id)

    def _delete_sync(self, model_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM llm_models WHERE model_id = ?", (model_id,))
            conn.commit()
            success = cursor.rowcount > 0

        if success:
            try:
                from food_agent.services.llm_service import LLMService
                LLMService.clear_cache()
            except Exception:
                pass

        return success

    async def delete_model(self, model_id: str) -> bool:
        """Delete an LLM model configuration."""
        return await asyncio.to_thread(self._delete_sync, model_id)
