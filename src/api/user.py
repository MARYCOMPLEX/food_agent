"""
User Routes - 用户 API 路由.

Endpoints:
- GET /v1/user/profile
- PUT /v1/user/profile
- GET /v1/user/stats/{type}
- GET /v1/user/settings
- PUT /v1/user/settings
"""

from typing import Dict, Any
from fastapi import APIRouter, Path

from api.schemas import UserProfileUpdateRequest

router = APIRouter(prefix="/v1/user", tags=["user"])

# Mock user data (TODO: replace with database)
_user_profile = {
    "id": "user_1",
    "name": "Guest User",
    "email": "guest@example.com",
    "avatar": None,
    "location": "Unknown",
    "memberSince": "2026-01-01",
    "stats": {
        "saved": 0,
        "reviews": 0,
        "visited": 0,
    }
}

_user_settings = {
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


@router.get("/profile")
async def get_profile():
    """Get current user profile."""
    return {
        "success": True,
        "data": _user_profile,
    }


@router.put("/profile")
async def update_profile(request: UserProfileUpdateRequest):
    """Update user profile."""
    if request.name:
        _user_profile["name"] = request.name
    if request.email:
        _user_profile["email"] = request.email
    if request.location:
        _user_profile["location"] = request.location
    
    return {
        "success": True,
        "data": _user_profile,
    }


@router.get("/stats/{type}")
async def get_stats(type: str = Path(..., description="统计类型: saved, reviews, visited")):
    """Get detailed stats list."""
    if type not in ("saved", "reviews", "visited"):
        return {
            "success": False,
            "error": "invalid_type",
            "message": f"Invalid type: {type}. Must be 'saved', 'reviews', or 'visited'.",
        }
    
    return {
        "success": True,
        "data": {
            "type": type,
            "items": [],
            "total": 0,
        }
    }


@router.get("/settings")
async def get_settings():
    """Get user settings."""
    return {
        "success": True,
        "data": _user_settings,
    }


@router.put("/settings")
async def update_settings(settings: Dict[str, Any]):
    """Update user settings."""
    if "notifications" in settings:
        _user_settings["notifications"].update(settings["notifications"])
    if "privacy" in settings:
        _user_settings["privacy"].update(settings["privacy"])
    if "preferences" in settings:
        _user_settings["preferences"].update(settings["preferences"])
    
    return {
        "success": True,
        "data": _user_settings,
    }
