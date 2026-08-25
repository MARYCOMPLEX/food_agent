"""Compatibility tests for legacy asyncpg adapters under the release DSN."""

from __future__ import annotations

import pytest

from xhs_food.services.postgres_storage import PostgresStorage
from xhs_food.services.user_storage import UserStorageService

pytestmark = pytest.mark.unit


def test_asyncpg_adapters_normalize_the_sqlalchemy_driver_scheme() -> None:
    dsn = "postgresql+asyncpg://postgres:postgres@db:5432/xhs_food_agent"

    assert PostgresStorage(database_url=dsn)._database_url == (
        "postgresql://postgres:postgres@db:5432/xhs_food_agent"
    )
    assert UserStorageService(database_url=dsn)._database_url == (
        "postgresql://postgres:postgres@db:5432/xhs_food_agent"
    )
