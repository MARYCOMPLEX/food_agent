"""Compatibility helper for historical one-shot migration commands."""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def _database_url_from_legacy_env() -> str | None:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "xhs_food_agent")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    credentials = f"{user}:{password}" if password else user
    return f"postgresql+asyncpg://{credentials}@{host}:{port}/{database}"


def upgrade_head() -> None:
    """Run the single checked-in Alembic chain at its current head."""

    database_url = _database_url_from_legacy_env()
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")


__all__ = ["upgrade_head"]
