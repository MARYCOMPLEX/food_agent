import { httpClient } from '../../../shared/api/httpClient'
import type {
  SearchAdmission,
  SearchResultsSnapshot,
  SearchStatusSnapshot,
} from '../../../shared/contracts'

export const sessionApi = {
  getStatus: async (sessionId: string): Promise<SearchStatusSnapshot> => {
    return httpClient.get<SearchStatusSnapshot>(`/v1/search/status/${sessionId}`)
  },

  getResults: async (sessionId: string): Promise<SearchResultsSnapshot> => {
    return httpClient.get<SearchResultsSnapshot>(`/v1/search/results/${sessionId}`)
  },

  refineQuery: async (sessionId: string, query: string): Promise<SearchAdmission> => {
    return httpClient.post<SearchAdmission>('/v1/search/', {
      sessionId,
      query,
    })
  },

  recoverSession: async (sessionId: string): Promise<any> => {
    return httpClient.post('/v1/search/', {
      sessionId,
    })
  },
}
