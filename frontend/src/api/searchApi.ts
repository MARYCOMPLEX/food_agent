import { apiGet, apiPost } from './client'

interface SearchStartResponse {
  success: boolean
  sessionId: string
  streamUrl: string
  message?: string
}

export async function startSearch(query: string, sessionId?: string): Promise<SearchStartResponse> {
  return apiPost('/v1/search/', {
    query,
    sessionId,
    // Comment evidence is always primary; the profile source is a secondary
    // enrichment pass for the same research turn.
    platforms: ['xhs_pc', 'dianping'],
  })
}

export async function getSearchStatus(sessionId: string) {
  return apiGet(`/v1/search/status/${sessionId}`)
}

export async function getSearchResults(sessionId: string) {
  return apiGet(`/v1/search/results/${sessionId}`)
}

export function createSSEConnection(sessionId: string, lastEventIndex = 0): EventSource {
  const url = `/v1/search/stream/${sessionId}${lastEventIndex > 0 ? `?lastEventIndex=${lastEventIndex}` : ''}`
  return new EventSource(url)
}
