"""
API Dependencies - FastAPI 依赖注入.

提供用户认证和存储服务的依赖注入。
"""

from typing import Optional

from fastapi import Header, Depends
from loguru import logger

from xhs_food.services.user_storage import (
    UserStorageService,
    get_user_storage_service,
    User,
)


# =============================================================================
# Storage Service Dependency
# =============================================================================

# Cached storage service instance
_storage_service: Optional[UserStorageService] = None


async def get_storage() -> UserStorageService:
    """
    Get UserStorageService instance.
    
    Usage:
        @router.get("/")
        async def handler(storage: UserStorageService = Depends(get_storage)):
            ...
    """
    global _storage_service
    if _storage_service is None:
        _storage_service = await get_user_storage_service()
    return _storage_service


# =============================================================================
# User Authentication Dependencies
# =============================================================================

async def get_current_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    storage: UserStorageService = Depends(get_storage),
) -> str:
    """
    Get current user ID from headers.
    
    Priority:
    1. X-User-Id header (explicit user ID)
    2. X-Device-Id header (auto-create user by device)
    3. Anonymous user (backward compatible)
    
    Usage:
        @router.get("/")
        async def handler(user_id: str = Depends(get_current_user_id)):
            ...
    """
    # Explicit user ID
    if x_user_id:
        return x_user_id
    
    # Device-based user
    if x_device_id:
        user = await storage.get_or_create_user(x_device_id)
        return user.id
    
    # Anonymous fallback
    return UserStorageService.ANONYMOUS_USER_ID


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    storage: UserStorageService = Depends(get_storage),
) -> User:
    """
    Get current user object.
    
    Usage:
        @router.get("/profile")
        async def handler(user: User = Depends(get_current_user)):
            return user.to_dict()
    """
    if x_user_id:
        user = await storage.get_user(x_user_id)
        if user:
            return user
    
    if x_device_id:
        return await storage.get_or_create_user(x_device_id)
    
    # Anonymous user
    return storage._anonymous_user()
