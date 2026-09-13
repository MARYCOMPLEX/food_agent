# -*- coding: utf-8 -*-
"""Persistent database storage for modular MCP and account service configurations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, List, Optional

from loguru import logger

from food_agent.contracts.account_service import (
    AccountServiceConfig,
    AccountServiceProtocol,
    PlatformChannel,
)


class MCPServiceStorage:
    """SQLite-backed persistent store for MCP data source services.

    Provides asynchronous CRUD operations, safe transactional writes,
    and automatic seeding from ambient configuration (.env) on initial startup.
    """

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
                CREATE TABLE IF NOT EXISTS mcp_services (
                    service_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    mcp_url TEXT,
                    protocol TEXT NOT NULL DEFAULT 'http+mcp',
                    channels TEXT NOT NULL DEFAULT '[]',
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    auth_ref TEXT,
                    timeout_seconds REAL NOT NULL DEFAULT 30.0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    async def initialize(self, seed_json: Optional[str] = None) -> None:
        """Initialize the storage schema. Starts completely clean with no mock data."""
        await asyncio.to_thread(self._init_sync)
        self._initialized = True

    async def _seed_from_json(self, raw_json: str) -> None:
        try:
            items = json.loads(raw_json)
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict) or "service_id" not in item:
                    continue
                channels = item.get("channels", [])
                if isinstance(channels, (list, tuple)):
                    channel_list = [c if isinstance(c, str) else c.value for c in channels]
                else:
                    channel_list = [str(channels)]

                display_name = item.get("name") or item.get("service_id")
                await self.save_service(
                    {
                        "service_id": item["service_id"],
                        "name": display_name,
                        "base_url": str(item["base_url"]),
                        "mcp_url": str(item["mcp_url"]) if item.get("mcp_url") else None,
                        "protocol": item.get("protocol", "http+mcp"),
                        "channels": channel_list,
                        "capabilities": list(item.get("capabilities", [])),
                        "auth_ref": item.get("auth_ref"),
                        "timeout_seconds": float(item.get("timeout_seconds", 30.0)),
                        "enabled": bool(item.get("enabled", True)),
                    }
                )
            logger.info("Successfully seeded MCP services from ambient configuration")
        except Exception as exc:
            logger.warning(f"Failed to seed MCP services from ambient JSON: {exc}")

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["channels"] = json.loads(data["channels"])
        data["capabilities"] = json.loads(data["capabilities"])
        data["enabled"] = bool(data["enabled"])
        return data

    def _list_sync(self, enabled_only: bool) -> List[dict[str, Any]]:
        with self._get_connection() as conn:
            query = "SELECT * FROM mcp_services"
            params: list[Any] = []
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY created_at ASC"
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    async def list_services(self, enabled_only: bool = False) -> List[dict[str, Any]]:
        """List all MCP services, optionally filtering for only enabled services."""
        return await asyncio.to_thread(self._list_sync, enabled_only)

    def _get_sync(self, service_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM mcp_services WHERE service_id = ?", (service_id,)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None

    async def get_service(self, service_id: str) -> Optional[dict[str, Any]]:
        """Retrieve one MCP service configuration by service_id."""
        return await asyncio.to_thread(self._get_sync, service_id)

    def _save_sync(self, record: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        service_id = str(record["service_id"]).strip()
        name = str(record.get("name") or service_id).strip()
        base_url = str(record["base_url"]).strip()
        mcp_url = str(record["mcp_url"]).strip() if record.get("mcp_url") else None
        protocol = str(record.get("protocol") or "http+mcp").strip()
        channels = json.dumps(record.get("channels", []))
        capabilities = json.dumps(record.get("capabilities", []))
        auth_ref = str(record["auth_ref"]).strip() if record.get("auth_ref") else None
        timeout_seconds = float(record.get("timeout_seconds", 30.0))
        enabled = 1 if record.get("enabled", True) else 0

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT created_at FROM mcp_services WHERE service_id = ?", (service_id,)
            )
            existing = cursor.fetchone()
            if existing:
                created_at = existing["created_at"]
                conn.execute(
                    """
                    UPDATE mcp_services
                    SET name = ?, base_url = ?, mcp_url = ?, protocol = ?,
                        channels = ?, capabilities = ?, auth_ref = ?,
                        timeout_seconds = ?, enabled = ?, updated_at = ?
                    WHERE service_id = ?
                    """,
                    (
                        name,
                        base_url,
                        mcp_url,
                        protocol,
                        channels,
                        capabilities,
                        auth_ref,
                        timeout_seconds,
                        enabled,
                        now,
                        service_id,
                    ),
                )
            else:
                created_at = now
                conn.execute(
                    """
                    INSERT INTO mcp_services (
                        service_id, name, base_url, mcp_url, protocol,
                        channels, capabilities, auth_ref, timeout_seconds,
                        enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        service_id,
                        name,
                        base_url,
                        mcp_url,
                        protocol,
                        channels,
                        capabilities,
                        auth_ref,
                        timeout_seconds,
                        enabled,
                        created_at,
                        now,
                    ),
                )
            conn.commit()

        return {
            "service_id": service_id,
            "name": name,
            "base_url": base_url,
            "mcp_url": mcp_url,
            "protocol": protocol,
            "channels": json.loads(channels),
            "capabilities": json.loads(capabilities),
            "auth_ref": auth_ref,
            "timeout_seconds": timeout_seconds,
            "enabled": bool(enabled),
            "created_at": created_at,
            "updated_at": now,
        }

    async def save_service(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert or update an MCP service in persistent storage."""
        return await asyncio.to_thread(self._save_sync, record)

    def _delete_sync(self, service_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM mcp_services WHERE service_id = ?", (service_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def delete_service(self, service_id: str) -> bool:
        """Delete an MCP service from persistent storage."""
        return await asyncio.to_thread(self._delete_sync, service_id)

    def _set_enabled_sync(self, service_id: str, enabled: bool) -> Optional[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE mcp_services SET enabled = ?, updated_at = ? WHERE service_id = ?",
                (1 if enabled else 0, now, service_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            return self._get_sync(service_id)

    async def set_service_enabled(
        self, service_id: str, enabled: bool
    ) -> Optional[dict[str, Any]]:
        """Toggle the enabled status of an MCP service."""
        return await asyncio.to_thread(self._set_enabled_sync, service_id, enabled)

    @staticmethod
    def to_account_service_config(record: dict[str, Any]) -> AccountServiceConfig:
        """Convert a stored service dictionary to an immutable AccountServiceConfig model."""
        channels = tuple(PlatformChannel(c) for c in record.get("channels", []))
        protocol = AccountServiceProtocol(record.get("protocol", "http+mcp"))
        return AccountServiceConfig(
            service_id=record["service_id"],
            base_url=record["base_url"],
            mcp_url=record.get("mcp_url") or None,
            protocol=protocol,
            channels=channels,
            capabilities=tuple(record.get("capabilities", ())),
            timeout_seconds=float(record.get("timeout_seconds", 30.0)),
            auth_ref=record.get("auth_ref") or None,
        )
