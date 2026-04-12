import { create } from 'zustand'
import { addFavorite, removeFavorite, getFavorites } from '../api/favoritesApi'
import type { Restaurant } from '../types/restaurant'

interface UserState {
  favorites: Map<string, Restaurant>
  favoriteIds: Set<string>

  fetchFavorites: () => Promise<void>
  toggleFavorite: (id: string, restaurant?: Restaurant) => Promise<void>
  isFavorite: (id: string) => boolean
}

export const useUserStore = create<UserState>((set, get) => ({
  favorites: new Map(),
  favoriteIds: new Set(),

  fetchFavorites: async () => {
    try {
      const res = await getFavorites()
      if (res.success && res.data?.favorites) {
        const map = new Map<string, Restaurant>()
        const ids = new Set<string>()
        for (const f of res.data.favorites as { restaurantId: string; restaurant?: Restaurant }[]) {
          if (f.restaurantId) {
            ids.add(f.restaurantId)
            if (f.restaurant) map.set(f.restaurantId, f.restaurant as Restaurant)
          }
        }
        set({ favorites: map, favoriteIds: ids })
      }
    } catch { /* ignore */ }
  },

  toggleFavorite: async (id: string, restaurant?: Restaurant) => {
    const isFav = get().favoriteIds.has(id)
    // Optimistic update
    const newIds = new Set(get().favoriteIds)
    const newFavs = new Map(get().favorites)
    if (isFav) {
      newIds.delete(id)
      newFavs.delete(id)
    } else {
      newIds.add(id)
      if (restaurant) newFavs.set(id, restaurant)
    }
    set({ favoriteIds: newIds, favorites: newFavs })

    try {
      if (isFav) await removeFavorite(id)
      else await addFavorite(id)
    } catch {
      // Rollback
      get().fetchFavorites()
    }
  },

  isFavorite: (id: string) => get().favoriteIds.has(id),
}))
