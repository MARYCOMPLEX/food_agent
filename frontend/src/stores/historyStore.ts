import { create } from 'zustand'
import { getHistory, deleteHistoryItem, clearHistory as clearHistoryApi } from '../api/historyApi'
import type { HistoryItem } from '../types/user'

interface HistoryState {
  items: HistoryItem[]
  total: number
  page: number
  loading: boolean

  fetchHistory: (page?: number) => Promise<void>
  deleteItem: (id: string) => Promise<void>
  clearAll: () => Promise<void>
}

export const useHistoryStore = create<HistoryState>((set, get) => ({
  items: [],
  total: 0,
  page: 1,
  loading: false,

  fetchHistory: async (page = 1) => {
    set({ loading: true })
    try {
      const res = await getHistory(page)
      if (res.success && res.data) {
        set({
          items: (res.data.history ?? []) as HistoryItem[],
          total: res.data.total ?? 0,
          page,
        })
      }
    } catch {
      set({ items: [], total: 0 })
    }
    set({ loading: false })
  },

  deleteItem: async (id: string) => {
    try {
      await deleteHistoryItem(id)
      set({ items: get().items.filter(i => i.id !== id) })
    } catch { /* ignore */ }
  },

  clearAll: async () => {
    try {
      await clearHistoryApi()
      set({ items: [], total: 0 })
    } catch { /* ignore */ }
  },
}))
