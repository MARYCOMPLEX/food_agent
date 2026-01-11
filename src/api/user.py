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

class Preferences(BaseModel):
    """用户偏好设置."""
    theme: Optional[str] = "system"  # light, dark, system
    language: Optional[str] = "zh-CN"
    accentColor: Optional[str] = None


class Notifications(BaseModel):
    """通知设置."""
    push: bool = True
    email: bool = False
    newRecommendations: bool = True
    weeklyDigest: bool = False


class Subscription(BaseModel):
    """订阅信息 (Read Only)."""
    plan: str = "Free"
    status: str = "active"
    expiresAt: Optional[str] = None


class UserProfileUpdateRequest(BaseModel):
    """PUT /v1/user/profile 请求体."""
    name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None


class UserSettingsUpdateRequest(BaseModel):
    """PUT /v1/user/settings 请求体 (批量更新)."""
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
    # Build args based on what's provided
    update_args = {"user_id": user_id}
    if request.name is not None:
        update_args["name"] = request.name
    if request.username is not None:
        update_args["username"] = request.username
    if request.email is not None:
        update_args["email"] = request.email
    if request.location is not None:
        update_args["location"] = request.location

    user = await storage.update_user(**update_args)
    
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
        total = len(items) # Estimate for now
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
    """Get complete user settings."""
    # Default settings
    defaults = {
        "preferences": {
            "theme": "system",
            "language": "zh-CN", 
            "accentColor": "default"
        },
        "notifications": {
            "push": True, 
            "email": False,
            "newRecommendations": True,
            "weeklyDigest": False
        },
        "subscription": {
            "plan": "Free",
            "status": "active"
        }
    }

    # Merge user settings
    user_settings = user.settings or {}
    
    # helper for deep merge (simple 1-level)
    def merge(default, current):
        return {**default, **(current or {})}

    response_data = user.to_dict() # Basics: id, name, email...
    
    # Attach settings
    response_data["preferences"] = merge(defaults["preferences"], user_settings.get("preferences"))
    response_data["notifications"] = merge(defaults["notifications"], user_settings.get("notifications"))
    response_data["subscription"] = merge(defaults["subscription"], user_settings.get("subscription"))

    return {
        "success": True,
        "data": response_data,
    }


@router.put("/settings")
async def update_settings_batch(
    request: UserSettingsUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    user: User = Depends(get_current_user),
    storage: UserStorageService = Depends(get_storage),
):
    """Batch update settings."""
    current_settings = user.settings or {}
    
    if request.notifications:
        current_settings["notifications"] = {
            **current_settings.get("notifications", {}),
            **request.notifications,
        }
    if request.preferences:
        current_settings["preferences"] = {
            **current_settings.get("preferences", {}),
            **request.preferences,
        }
        
    # Privacy is kept but not strictly typed yet, allows flexibility
    if request.privacy:
        current_settings["privacy"] = {
            **current_settings.get("privacy", {}),
            **request.privacy,
        }
    
    await storage.update_user(user_id, settings=current_settings)
    
    # Refetch to return full object
    updated_user = await storage.get_user(user_id)
    return await get_settings(updated_user)


@router.put("/preferences")
async def update_preferences(
    request: Dict[str, Any], # Allow flexible dict for now or specific model
    user_id: str = Depends(get_current_user_id),
    user: User = Depends(get_current_user),
    storage: UserStorageService = Depends(get_storage),
):
    """Update only preferences."""
    current_settings = user.settings or {}
    current_prefs = current_settings.get("preferences", {})
    
    # Merge updates
    new_prefs = {**current_prefs, **request}
    current_settings["preferences"] = new_prefs
    
    await storage.update_user(user_id, settings=current_settings)
    
    return {
        "success": True,
        "data": new_prefs
    }


@router.put("/notifications")
async def update_notifications(
    request: Dict[str, Any],
    user_id: str = Depends(get_current_user_id),
    user: User = Depends(get_current_user),
    storage: UserStorageService = Depends(get_storage),
):
    """Update only notification settings."""
    current_settings = user.settings or {}
    current_notifs = current_settings.get("notifications", {})
    
    new_notifs = {**current_notifs, **request}
    current_settings["notifications"] = new_notifs
    
    await storage.update_user(user_id, settings=current_settings)
    
    return {
        "success": True,
        "data": new_notifs
    }

