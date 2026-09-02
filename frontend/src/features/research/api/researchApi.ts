import { httpClient } from '../../../shared/api/httpClient'
import type { SearchAdmission, UnifiedSearchRequest } from '../../../shared/contracts'

export const researchApi = {
  startSearch: async (payload: UnifiedSearchRequest): Promise<SearchAdmission> => {
    return httpClient.post<SearchAdmission>('/v1/search/', payload)
  },
}
