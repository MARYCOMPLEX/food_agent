import { apiGet, apiPost, apiDelete } from './client'

export async function getFavorites() {
  return apiGet<{ success: boolean; data: { favorites: unknown[] } }>('/v1/favorites')
}

export async function addFavorite(restaurantId: string) {
  return apiPost<{ success: boolean }>('/v1/favorites', { restaurantId })
}

export async function removeFavorite(restaurantId: string) {
  return apiDelete<{ success: boolean }>(`/v1/favorites/${restaurantId}`)
}

export async function checkFavorite(restaurantId: string) {
  return apiGet<{ success: boolean; data: { isFavorite: boolean } }>(`/v1/favorites/${restaurantId}/check`)
}
