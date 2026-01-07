"""
User Routes - 用户 API 路由.

Endpoints:
- GET /v1/user/profile
- PUT /v1/user/profile
- GET /v1/user/stats/{type}
- GET /v1/user/settings
- PUT /v1/user/settings
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Path, Depends
from pydantic import BaseModel

from api.deps import get_current_user_id, get_current_user, get_storage
from xhs_food.services.user_storage import UserStorageService, User

router = APIRouter(prefix="/v1/user", tags=["user"])


# =============================================================================
# Schemas
# =============================================================================

class UserProfileUpdateRequest(BaseModel):
    """PUT /v1/user/profile 请求体."""
    name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None


class UserSettingsUpdateRequest(BaseModel):
    """PUT /v1/user/settings 请求体."""
    notifications: Optional[Dict[str, Any]] = None
    privacy: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None


# =============================================================================
# Routes
# =============================================================================

@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Get current user profile with stats."""
    stats = await storage.get_user_stats(user_id)
    
    profile = user.to_dict()
    profile["stats"] = stats
    
    return {
        "success": True,
        "data": profile,
    }


@router.put("/profile")
async def update_profile(
    request: UserProfileUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Update user profile."""
    user = await storage.update_user(
        user_id=user_id,
        name=request.name,
        email=request.email,
        location=request.location,
    )
    
    if not user:
        return {
            "success": False,
            "message": "用户不存在",
        }
    
    stats = await storage.get_user_stats(user_id)
    profile = user.to_dict()
    profile["stats"] = stats
    
    return {
        "success": True,
        "data": profile,
    }


@router.get("/stats/{type}")
async def get_stats(
    type: str = Path(..., description="统计类型: saved, reviews, visited"),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Get detailed stats list."""
    if type not in ("saved", "reviews", "visited"):
        return {
            "success": False,
            "error": "invalid_type",
            "message": f"Invalid type: {type}. Must be 'saved', 'reviews', or 'visited'.",
        }
    
    items = []
    total = 0
    
    if type == "saved":
        favorites = await storage.get_favorites(user_id)
        items = [f.to_dict() for f in favorites]
        total = len(items)
    elif type == "visited":
        history = await storage.get_history(user_id, limit=50)
        items = [h.to_dict() for h in history]
        total = await storage.get_history_count(user_id)
    # reviews not implemented yet
    
    return {
        "success": True,
        "data": {
            "type": type,
            "items": items,
            "total": total,
        }
    }


@router.get("/settings")
async def get_settings(
    user: User = Depends(get_current_user),
):
    """Get user settings."""
    # Default settings structure
    default_settings = {
        "notifications": {
            "push": True,
            "email": False,
            "newRecommendations": True,
            "weeklyDigest": False,
        },
        "privacy": {
            "showLocation": True,
            "showActivity": False,
        },
        "preferences": {
            "language": "zh-CN",
            "theme": "system",
        }
    }
    
    # Merge with user settings
    settings = {**default_settings}
    if user.settings:
        for key in default_settings:
            if key in user.settings:
                settings[key] = {**default_settings[key], **user.settings[key]}
    
    return {
        "success": True,
        "data": settings,
    }


@router.put("/settings")
async def update_settings(
    request: UserSettingsUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    user: User = Depends(get_current_user),
    storage: UserStorageService = Depends(get_storage),
):
    """Update user settings."""
    # Merge with existing settings
    current_settings = user.settings or {}
    
    if request.notifications:
        current_settings["notifications"] = {
            **current_settings.get("notifications", {}),
            **request.notifications,
        }
    if request.privacy:
        current_settings["privacy"] = {
            **current_settings.get("privacy", {}),
            **request.privacy,
        }
    if request.preferences:
        current_settings["preferences"] = {
            **current_settings.get("preferences", {}),
            **request.preferences,
        }
    
    await storage.update_user(user_id, settings=current_settings)
    
    # Return updated settings
    return await get_settings(await get_current_user(
        x_user_id=user_id,
        x_device_id=None,
        storage=storage,
    ))
