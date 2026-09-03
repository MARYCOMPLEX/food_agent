"""Read-only legacy table contracts owned by Alembic.

The old ``CREATE_*`` names remain as non-executable references for import
compatibility. Passing one to an asyncpg ``execute`` call is intentionally no
longer supported; deployment must run ``alembic upgrade head`` first.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSchemaReference:
    table_name: str
    required_columns: tuple[str, ...]


REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": (
        "id",
        "device_id",
        "name",
        "username",
        "settings",
        "created_at",
        "updated_at",
        "deleted_at",
    ),
    "restaurants": (
        "id",
        "name",
        "created_at",
        "updated_at",
        "region",
        "provider_refs",
        "profile_url",
        "source_url",
        "image_url",
        "category",
        "review_count",
        "average_price",
        "latitude",
        "longitude",
        "coordinate_system",
        "geo",
        "recommended_dishes",
        "promotions",
        "profile_metadata",
        "review_completeness",
        "profile_gaps",
        "source_payload",
        "source_updated_at",
        "profile_fetched_at",
        "profile_refresh_status",
    ),
    "favorites": ("id", "user_id", "restaurant_id", "created_at", "deleted_at"),
    "search_history": (
        "id",
        "user_id",
        "session_id",
        "query",
        "status",
        "created_at",
        "updated_at",
        "deleted_at",
    ),
    "search_results": (
        "id",
        "session_id",
        "restaurants",
        "created_at",
        "turn_id",
        "query",
    ),
}

# Deprecated names kept as import-level references, never as executable SQL.
CREATE_USERS_TABLE = TableSchemaReference("users", REQUIRED_COLUMNS["users"])
CREATE_RESTAURANTS_TABLE = TableSchemaReference("restaurants", REQUIRED_COLUMNS["restaurants"])
CREATE_FAVORITES_TABLE = TableSchemaReference("favorites", REQUIRED_COLUMNS["favorites"])
CREATE_HISTORY_TABLE = TableSchemaReference("search_history", REQUIRED_COLUMNS["search_history"])
CREATE_SEARCH_RESULTS_TABLE = TableSchemaReference(
    "search_results", REQUIRED_COLUMNS["search_results"]
)
ENABLE_EXTENSIONS_SQL = ("pgcrypto", "uuid-ossp")

__all__ = [
    "CREATE_FAVORITES_TABLE",
    "CREATE_HISTORY_TABLE",
    "CREATE_RESTAURANTS_TABLE",
    "CREATE_SEARCH_RESULTS_TABLE",
    "CREATE_USERS_TABLE",
    "ENABLE_EXTENSIONS_SQL",
    "REQUIRED_COLUMNS",
    "TableSchemaReference",
]
