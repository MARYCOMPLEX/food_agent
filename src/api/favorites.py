"""
Favorites Routes - 收藏 API 路由.

Endpoints:
- GET /v1/favorites
- POST /v1/favorites
- DELETE /v1/favorites/{restaurantId}
- GET /v1/favorites/{restaurantId}/check
"""

import time
from typing import Dict, List, Any
from fastapi import APIRouter, Path, HTTPException

from api.schemas import FavoriteAddRequest, FavoriteResponse

router = APIRouter(prefix="/v1/favorites", tags=["favorites"])

# In-memory storage (TODO: replace with database)
# Structure: { user_id: [ {id, addedAt, restaurant: {...}} ] }
_user_favorites: Dict[str, List[Dict[str, Any]]] = {}


def _get_user_favorites(user_id: str = "default") -> List[Dict[str, Any]]:
    """Get user's favorites list."""
    if user_id not in _user_favorites:
        _user_favorites[user_id] = []
    return _user_favorites[user_id]


@router.get("")
async def get_favorites():
    """Get all user's favorites with full restaurant details."""
    favorites = _get_user_favorites()
    return {
        "success": True,
        "data": {
            "items": favorites,
            "total": len(favorites),
        }
    }


@router.post("", response_model=FavoriteResponse)
async def add_favorite(request: FavoriteAddRequest):
    """Add a restaurant to favorites."""
    favorites = _get_user_favorites()
    
    # Check if already exists
    for fav in favorites:
        if fav.get("id") == request.restaurantId:
            return FavoriteResponse(
                success=True,
                message="已在收藏中",
                isFavorite=True,
            )
    
    # Build favorite item with full restaurant data
    fav_item = {
        "id": request.restaurantId,
        "addedAt": time.time(),
    }
    
    # Include full restaurant object if provided
    if request.restaurant:
        fav_item["restaurant"] = request.restaurant.dict()
    
    favorites.append(fav_item)
    
    return FavoriteResponse(
        success=True,
        message="已添加到收藏",
        isFavorite=True,
    )


@router.delete("/{restaurantId}", response_model=FavoriteResponse)
async def remove_favorite(restaurantId: int = Path(..., description="店铺ID")):
    """Remove a restaurant from favorites."""
    favorites = _get_user_favorites()
    
    # Find and remove
    for i, fav in enumerate(favorites):
        if fav.get("id") == restaurantId:
            favorites.pop(i)
            return FavoriteResponse(
                success=True,
                message="已从收藏中移除",
                isFavorite=False,
            )
    
    # Not found, but return success anyway
    return FavoriteResponse(
        success=True,
        message="已从收藏中移除",
        isFavorite=False,
    )


@router.get("/{restaurantId}/check")
async def check_favorite(restaurantId: int = Path(..., description="店铺ID")):
    """Check if a restaurant is in favorites."""
    favorites = _get_user_favorites()
    
    is_favorite = any(fav.get("id") == restaurantId for fav in favorites)
    
    return {
        "success": True,
        "data": {
            "isFavorite": is_favorite,
        }
    }

