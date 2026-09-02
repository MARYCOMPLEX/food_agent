import { httpClient } from '../../../shared/api/httpClient'
import type { PlatformReadinessResponse } from '../../../shared/contracts'

export const opsApi = {
  getReadiness: async (): Promise<PlatformReadinessResponse> => {
    return httpClient.get<PlatformReadinessResponse>('/v1/platform/readiness')
  },
}
