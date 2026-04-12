# -*- coding: utf-8 -*-
"""
UserStorageService - PostgreSQL storage for user data.

Handles persistence for:
- User profiles
- Favorites
- Search history

Follows the same patterns as PostgresStorage for consistency.
"""

from .models import (
    generate_restaurant_hash,
    User,
    Favorite,
    SearchHistory,
    Restaurant,
)
from .service import UserStorageService, get_user_storage_service

__all__ = [
    "UserStorageService",
    "get_user_storage_service",
    "generate_restaurant_hash",
    "User",
    "Favorite",
    "SearchHistory",
    "Restaurant",
]
