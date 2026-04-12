import { apiGet, apiDelete } from './client'

export async function getHistory(page = 1, pageSize = 20) {
  return apiGet<{ success: boolean; data: { history: unknown[]; total: number } }>(
    `/v1/history?page=${page}&pageSize=${pageSize}`
  )
}

export async function deleteHistoryItem(id: string) {
  return apiDelete<{ success: boolean }>(`/v1/history/${id}`)
}

export async function clearHistory() {
  return apiDelete<{ success: boolean }>('/v1/history')
}
