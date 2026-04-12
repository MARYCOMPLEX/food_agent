import { apiGet, apiPost } from './client'

interface SearchStartResponse {
  success: boolean
  sessionId: string
  streamUrl: string
  message?: string
}

export async function startSearch(query: string, sessionId?: string): Promise<SearchStartResponse> {
  return apiPost('/v1/search/', { query, sessionId })
}

export async function refineSearch(sessionId: string, query: string): Promise<SearchStartResponse> {
  return apiPost('/v1/search/refine', { sessionId, query })
}

export async function getSearchStatus(sessionId: string) {
  return apiGet(`/v1/search/status/${sessionId}`)
}

export async function getSearchResults(sessionId: string) {
  return apiGet(`/v1/search/results/${sessionId}`)
}

export async function recoverSession(sessionId: string) {
  return apiGet(`/v1/search/recover/${sessionId}`)
}

export function createSSEConnection(sessionId: string, lastEventIndex = 0): EventSource {
  const url = `/v1/search/stream/${sessionId}${lastEventIndex > 0 ? `?lastEventIndex=${lastEventIndex}` : ''}`
  return new EventSource(url)
}
