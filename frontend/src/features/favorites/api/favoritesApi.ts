import { httpClient } from '../../../shared/api/httpClient'
import type { FavoriteResponse } from '../../../shared/contracts'

export const favoritesApi = {
  getFavorites: async (): Promise<{ items: any[], total: number }> => {
    return httpClient.get<{ items: any[], total: number }>('/v1/favorites')
  },

  addFavorite: async (restaurantId: string): Promise<FavoriteResponse> => {
    return httpClient.post<FavoriteResponse>('/v1/favorites', { restaurantId })
  },

  removeFavorite: async (restaurantId: string): Promise<FavoriteResponse> => {
    return httpClient.delete<FavoriteResponse>(`/v1/favorites/${restaurantId}`)
  },

  checkFavorite: async (restaurantId: string): Promise<{ isFavorite: boolean }> => {
    return httpClient.get<{ isFavorite: boolean }>(`/v1/favorites/${restaurantId}/check`)
  },
}
