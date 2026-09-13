import { httpClient } from '../../../shared/api/httpClient'
import { storage } from '../../../shared/utils/storage'
import type {
  PlatformAccount,
  PlatformAccountCreateRequest,
} from '../../../shared/contracts'

const ACCOUNTS_STORAGE_KEY = 'food_agent_saved_platform_accounts'

export const platformAccountsApi = {
  registerAccount: async (req: PlatformAccountCreateRequest): Promise<PlatformAccount> => {
    const acc = await httpClient.post<PlatformAccount>('/v1/platform/accounts', req)
    platformAccountsApi.saveAccountLocally(acc)
    return acc
  },

  getAccount: async (platform: string, accountRef: string): Promise<PlatformAccount> => {
    const acc = await httpClient.get<PlatformAccount>(`/v1/platform/accounts/${platform}/${accountRef}`)
    platformAccountsApi.saveAccountLocally(acc)
    return acc
  },

  getLocalAccounts: (): PlatformAccount[] => {
    const data = storage.get<PlatformAccount[] | null>(ACCOUNTS_STORAGE_KEY, null)
    if (data && Array.isArray(data))
      return data
    return []
  },

  saveAccountLocally: (acc: PlatformAccount) => {
    const current = platformAccountsApi.getLocalAccounts()
    const idx = current.findIndex(
      a => a.platform === acc.platform && a.account_ref === acc.account_ref,
    )
    if (idx >= 0) {
      current[idx] = { ...current[idx], ...acc }
    }
    else {
      current.push(acc)
    }
    storage.set(ACCOUNTS_STORAGE_KEY, current)
  },
}
