import { httpClient } from '../../../shared/api/httpClient'
import type { HistoryItem } from '../../../shared/contracts'

export const historyApi = {
  getHistory: async (limit = 50, offset = 0): Promise<{ items: HistoryItem[], total: number }> => {
    return httpClient.get<{ items: HistoryItem[], total: number }>('/v1/history', { limit, offset })
  },

  deleteHistoryItem: async (historyId: string | number): Promise<{ success: boolean }> => {
    return httpClient.delete<{ success: boolean }>(`/v1/history/${historyId}`)
  },

  clearHistory: async (): Promise<{ success: boolean, message: string }> => {
    return httpClient.delete<{ success: boolean, message: string }>('/v1/history')
  },
}
