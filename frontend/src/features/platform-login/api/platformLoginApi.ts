import { httpClient } from '../../../shared/api/httpClient'
import type {
  PlatformLoginFlow,
  PlatformQrPresentation,
} from '../../../shared/contracts'

export const platformLoginApi = {
  startQrLogin: async (platform: string, accountRef: string): Promise<PlatformLoginFlow> => {
    return httpClient.post<PlatformLoginFlow>(
      `/v1/platform/accounts/${platform}/${accountRef}/login/qr`,
      { mode: 'qr' },
    )
  },

  getQrPresentation: async (flowId: string): Promise<PlatformQrPresentation> => {
    return httpClient.get<PlatformQrPresentation>(`/v1/platform/login/${flowId}/qr`)
  },

  pollLoginStatus: async (flowId: string): Promise<PlatformLoginFlow> => {
    return httpClient.post<PlatformLoginFlow>(`/v1/platform/login/${flowId}/poll`)
  },

  cancelLogin: async (flowId: string, reason?: string): Promise<{ success: boolean }> => {
    return httpClient.post<{ success: boolean }>(`/v1/platform/login/${flowId}/cancel`, {
      reason: reason || 'user_cancelled',
    })
  },

  getLoginStatus: async (flowId: string): Promise<PlatformLoginFlow> => {
    return httpClient.get<PlatformLoginFlow>(`/v1/platform/login/${flowId}/status`)
  },
}
