"""
Favorites Routes - 收藏 API 路由.

Endpoints:
- GET /v1/favorites
- POST /v1/favorites
- DELETE /v1/favorites/{restaurantId}
- GET /v1/favorites/{restaurantId}/check
"""

from fastapi import APIRouter, Path, Depends

from api.schemas import FavoriteAddRequest, FavoriteResponse
from api.deps import get_current_user_id, get_storage
from xhs_food.services.user_storage import UserStorageService

router = APIRouter(prefix="/v1/favorites", tags=["favorites"])


@router.get("")
async def get_favorites(
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Get all user's favorites with full restaurant details."""
    favorites = await storage.get_favorites(user_id)
    return {
        "success": True,
        "data": {
            "items": [f.to_dict() for f in favorites],
            "total": len(favorites),
        }
    }


@router.post("", response_model=FavoriteResponse)
async def add_favorite(
    request: FavoriteAddRequest,
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Add a restaurant to favorites.
    
    Requires the restaurant to exist in the restaurants table.
    """
    # Check if already exists
    if await storage.check_favorite(user_id, request.restaurantId):
        return FavoriteResponse(
            success=True,
            message="已在收藏中",
            isFavorite=True,
        )
    
    # Verify restaurant exists
    restaurant = await storage.get_restaurant(request.restaurantId)
    if not restaurant:
        return FavoriteResponse(
            success=False,
            message="餐厅不存在",
            isFavorite=False,
        )
    
    # Add to favorites (only needs restaurant_id now)
    await storage.add_favorite(user_id, request.restaurantId)
    
    return FavoriteResponse(
        success=True,
        message="已添加到收藏",
        isFavorite=True,
    )


@router.delete("/{restaurantId}", response_model=FavoriteResponse)
async def remove_favorite(
    restaurantId: str = Path(..., description="餐厅Hash ID (32字符)"),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Remove a restaurant from favorites."""
    await storage.remove_favorite(user_id, restaurantId)
    
    return FavoriteResponse(
        success=True,
        message="已从收藏中移除",
        isFavorite=False,
    )


@router.get("/{restaurantId}/check")
async def check_favorite(
    restaurantId: str = Path(..., description="餐厅Hash ID (32字符)"),
    user_id: str = Depends(get_current_user_id),
    storage: UserStorageService = Depends(get_storage),
):
    """Check if a restaurant is in favorites."""
    is_favorite = await storage.check_favorite(user_id, restaurantId)
    
    return {
        "success": True,
        "data": {
            "isFavorite": is_favorite,
        }
    }
